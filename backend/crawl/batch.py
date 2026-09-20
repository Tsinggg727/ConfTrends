"""批量导入的异步执行 —— 设计文档 §6.1 步骤 3（titles）与步骤 4（bibtex / unit）。

**为什么是「线程 + 数据库」而不是 Celery**：单进程课程项目，为了异步引一个
broker 是纯粹的负担。但异步任务的**状态不能只放内存** —— Flask debug 模式一
热重载就全丢，2,700 篇的断点也跟着没了。所以进度、断点、失败一律落在
crawl_task / crawl_task_item 里；内存里那份注册表只放「现在正在跑哪道题」
这种天然易失、丢了也不影响正确性的信息。

**线程模型**：一个任务一个线程，线程里自己 `with app.app_context()`，于是
`db.get_db()` 通过 flask.g 给这个线程一份独立连接（sqlite3 连接不能跨线程），
`teardown_appcontext` 在 with 退出时关掉它。请求上下文从头到尾没被碰过。

**单条和批量共用** `service.resolve_title()`：检索顺序、匹配阈值、失败降级
只有一份实现，不会出现「单条能匹配上、批量匹配不上」这种鬼故事。
"""
import csv
import io
import os
import re
import threading
import time

from flask import current_app

from db import transaction

from . import service, storage
from .fail_reason import CrawlError, InvalidParam
from .parsers.common import clean_text
from .textutil import normalize_title
from .units import units_for

# 输入上限（设计文档 §4.1 ② 的校验与拒绝）
MAX_TITLES = 5000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = (".txt", ".csv")
MAX_TITLE_LEN = 500                       # 与 paper.title / crawl_task_item.input_title 一致

# 停手原因码。存 crawl_task.pause_reason，也是 /resume 的前提说明。
PAUSE_BREAKER = "BREAKER_TRIPPED"
PAUSE_FAILURES = "TOO_MANY_FAILURES"
PAUSE_INTERNAL = "INTERNAL_ERROR"
PAUSE_INTERRUPTED = "INTERRUPTED"
PAUSE_USER = "USER_PAUSED"
PAUSE_REASON_LABELS = {
    PAUSE_BREAKER: "站点拒绝服务（403/429），已按合规要求停手",
    PAUSE_FAILURES: "连续多条抓取失败，疑似站点改版或限流，已停手待确认",
    PAUSE_INTERNAL: "后台处理遇到未预期错误，已暂停（可从断点续跑）",
    PAUSE_INTERRUPTED: "上次运行中断（进程退出/崩溃），可从断点续跑",
    PAUSE_USER: "用户手动暂停，可随时从断点继续",
}


def pause_label(reason):
    return PAUSE_REASON_LABELS.get(reason, reason or "")


# ---------------------------------------------------------------
# 输入解析（纯函数，不碰 HTTP —— 上传那点 HTTP 细节留在 api 层）
# ---------------------------------------------------------------
# CSV 导出常见的表头，出现在第一行就丢掉
_TITLE_HEADERS = {"title", "titles", "paper", "paper title",
                  "题目", "标题", "论文题目", "论文标题"}


def _decode(raw):
    """UTF-8 优先，退回 GBK。

    Excel 存的 CSV 在中文 Windows 上是 GBK，直接 utf-8 解会抛异常；
    而 utf-8-sig 顺带把 BOM 去掉，省得第一行题目带着 \\ufeff 进库。
    """
    for enc in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _first_column(text):
    """CSV 只取第一列 —— 用户导出时往往还带着作者/年份那几列。"""
    rows = []
    for row in csv.reader(io.StringIO(text)):
        rows.append(row[0] if row else "")
    return "\n".join(rows)


def read_upload(file_storage):
    """把上传的 .txt/.csv 读成题目文本。参数不合法抛 InvalidParam（→ 4xx）。"""
    name = (file_storage.filename or "").strip()
    suffix = os.path.splitext(name)[1].lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise InvalidParam(
            f"只支持 {' / '.join(ALLOWED_SUFFIXES)} 文件，收到的是「{name or '无文件名'}」")

    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)      # 多读 1 字节即可判断超限
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidParam(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限")

    text = _decode(raw)
    return _first_column(text) if suffix == ".csv" else text


def read_bib_upload(file_storage):
    """读上传的 .bib 文件。参数不合法抛 InvalidParam（→ 4xx）。"""
    name = (file_storage.filename or "").strip()
    suffix = os.path.splitext(name)[1].lower()
    if suffix != ".bib":
        raise InvalidParam(f"BibTeX 只支持 .bib 文件，收到的是「{name or '无文件名'}」")

    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)      # 多读 1 字节即可判断超限
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidParam(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限")
    return _decode(raw)


def parse_titles(text):
    """一段文本 → 题目列表，返回 `(titles, warnings)`。

    每行一个题目，顺带做四件小事：
      · 去掉空行、首尾空白、整行包裹的引号（CSV 导出会带）；
      · 第一行若是 title/题目 这类表头就丢掉；
      · 按**归一化题目**去重 —— 同一篇论文没必要爬两遍，白耗配额；
      · 超过 500 字符的行跳过（多半是整段粘进来了），记一条警告。
    """
    titles, warnings = [], []
    seen = set()
    duplicates = 0
    too_long = 0
    first_line = True

    for raw in (text or "").splitlines():
        line = raw.strip()
        if len(line) >= 2 and line[0] == line[-1] and line[0] in "\"'":
            line = line[1:-1].strip()
        if not line:
            continue
        if first_line:
            first_line = False
            if line.lower() in _TITLE_HEADERS:
                continue
        if len(line) > MAX_TITLE_LEN:
            too_long += 1
            continue

        key = normalize_title(line)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        titles.append(line)

    if duplicates:
        warnings.append(f"{duplicates} 行与前面的题目重复（按归一化题目去重），已合并")
    if too_long:
        warnings.append(f"{too_long} 行超过 {MAX_TITLE_LEN} 字符，已跳过")
    return titles, warnings


# BibTeX 记录以 @type{ 开头，整个记录是一个花括号配对块（title 里带花括号很常见）
_ENTRY_RE = re.compile(r"@\w+\s*\{")


def _split_bib_entries(text):
    """把 .bib 文本切成一条条记录（顶层 @type{...} 块，花括号配对）。"""
    entries, i, n = [], 0, len(text or "")
    while i < n:
        m = _ENTRY_RE.search(text, i)
        if not m:
            break
        start, open_pos = m.start(), m.end() - 1      # open_pos 指向 '{'
        depth, j = 0, open_pos
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        entries.append(text[start:j + 1])
        i = j + 1
    return entries


# title 的取值可以是 {...} 或 "..." 两种，值定界符在 = 号之后
_TITLE_RE = re.compile(r"\btitle\s*=\s*([{\"])", re.IGNORECASE)


def _bib_title(entry):
    """取一条 BibTeX 记录的 title 字段，兼容 {...} 与 "..." 两种取值。"""
    m = _TITLE_RE.search(entry)
    if not m:
        return ""
    if m.group(1) == "{":
        # 花括号配对扫描 —— 标题里带花括号很常见（title = {A {3D} Approach}）
        i, depth, start = m.end(), 1, m.end()
        while i < len(entry) and depth > 0:
            if entry[i] == "{":
                depth += 1
            elif entry[i] == "}":
                depth -= 1
            i += 1
        return clean_text(entry[start:i - 1])
    end = entry.find('"', m.end())
    return clean_text(entry[m.end():end]) if end != -1 else ""


def parse_bibtex(text):
    """一段 .bib 文本 → 题目列表，返回 `(titles, warnings)`。

    从每个 @...{...} 记录里取 `title` 字段，再复刻 parse_titles 的去重/超长检查。
    LaTeX 转义留在题目原文里 —— normalize_title 在匹配阶段会剥掉它，这里不提前破坏。
    """
    titles, warnings = [], []
    seen, no_title, duplicates, too_long = set(), 0, 0, 0
    entries = _split_bib_entries(text)

    for entry in entries:
        title = _bib_title(entry)
        if not title:
            no_title += 1
            continue
        if len(title) > MAX_TITLE_LEN:
            too_long += 1
            continue
        key = normalize_title(title)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        titles.append(title)

    if not entries:
        warnings.append("没有解析出任何 BibTeX 记录（@type{...}）")
    if no_title:
        warnings.append(f"{no_title} 条记录缺 title 字段，已跳过")
    if duplicates:
        warnings.append(f"{duplicates} 条记录的题目重复（按归一化题目去重），已合并")
    if too_long:
        warnings.append(f"{too_long} 条题目超过 {MAX_TITLE_LEN} 字符，已跳过")
    return titles, warnings


def titles_from_entries(entries):
    """整届清单 → 去重后的题目列表（unit 模式阶段一用）。

    与 build_index 同一条去重口径：同一届里归一化题目相同的只保留先出现的。
    """
    titles, seen = [], set()
    for e in entries:
        key = normalize_title(e["title"])
        if key and key not in seen:
            seen.add(key)
            titles.append(e["title"])
    return titles


# ---------------------------------------------------------------
# 任务注册表（进程内的易失状态）
# ---------------------------------------------------------------
# task_id -> {"current_title": str|None, "pause_reason": str|None}
#
# ⚠️ 这里**不是**权威来源：pause_reason 同时写在 crawl_task 表里，
# 进程重启后只有数据库那份还在。current_title 没法持久化（它每秒钟都在变），
# 所以它天生只活在内存里 —— 查不到就当 None，前端显示成「—」即可。
_live = {}
_threads = {}                       # task_id -> Thread
_live_lock = threading.Lock()


def _set_live(task_id, **fields):
    with _live_lock:
        _live.setdefault(task_id, {}).update(fields)


def live_state(task_id):
    with _live_lock:
        return dict(_live.get(task_id) or {})


def is_running(task_id):
    with _live_lock:
        thread = _threads.get(task_id)
    return bool(thread and thread.is_alive())


def forget(task_id):
    with _live_lock:
        _live.pop(task_id, None)
        _threads.pop(task_id, None)


def request_pause(task_id):
    """请求暂停（§5.3 的 [⏸ 暂停]）。

    只设标志不动库：正在跑的线程在下一条明细**开始前**看到它就停手，
    当前这条让它处理完 —— 明细的原子性不受影响，状态由 run() 自己落。
    """
    _set_live(task_id, pause_requested=True)


def request_cancel(task_id):
    """请求取消（§4.2 的 /cancel）。与 request_pause 同一套协作机制。"""
    _set_live(task_id, cancel_requested=True)


def recover_stale_tasks(app):
    """进程启动时，把上次「跑着跑着进程死了」的任务标成 paused。

    新进程没有任何运行中的线程，可 DB 里还留着 status='running' 的行 ——
    不处理的话前端会一直轮询它，find_active_task 也会一直被它占着，
    新任务在同一个会议-年份上永远建不起来。

    只在服务真正启动时调（app.py 的 __main__），不在 create_app 里 ——
    否则测试进程 import 时会把正在跑的开发服务器任务误标成 paused。
    返回恢复的任务数。
    """
    import sqlite3

    if not os.path.exists(app.config["DB_PATH"]):
        return 0
    conn = sqlite3.connect(app.config["DB_PATH"])
    try:
        cur = conn.execute(
            "UPDATE crawl_task SET status = 'paused', pause_reason = ? "
            "WHERE status = 'running'", (PAUSE_INTERRUPTED,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ---------------------------------------------------------------
# 起任务 / 跑任务
# ---------------------------------------------------------------
def start(app, task_id, fetcher=None):
    """起一个后台线程跑任务并立刻返回。

    已经在跑的任务不重复起 —— 重复点「续跑」不该把同一批题目跑两遍。
    daemon=True：Flask 退出时不必等它跑完（剩下的题目还在 pending，下次续跑）。
    """
    if is_running(task_id):
        return None

    thread = threading.Thread(
        target=run, args=(app, task_id), kwargs={"fetcher": fetcher},
        name=f"crawl-task-{str(task_id)[:8]}", daemon=True,
    )
    with _live_lock:
        _threads[task_id] = thread
        _live.setdefault(task_id, {})
    thread.start()
    return thread


def run(app, task_id, fetcher=None):
    """跑一个批量任务，直到跑完或触发停手规则。

    **同步执行**：线程只是它的壳。测试直接调这个函数，不必和线程调度赛跑；
    接口层通过 start() 调它。

    titles / bibtex 两种走「给题目去索引页找」；unit 走「整届清单直接逐条抓」。
    除此之外的调度（断点续爬、熔断停手、计数）三者完全一致。
    """
    with app.app_context():
        task = storage.get_task(task_id)
        if task is None:
            raise ValueError(f"任务不存在：{task_id}")

        cfg = current_app.config
        fetcher = fetcher or service.get_fetcher()
        units = units_for(task["conference_code"], task["year"])
        auto_commit = bool(task["auto_commit"])
        max_consecutive = cfg["CRAWL_BATCH_MAX_CONSECUTIVE_FAILURES"]

        # 上一轮留下的暂停/取消标志必须清掉：resume 起的线程沿用同一个
        # 注册表条目，不清的话新线程一进来就「看到取消」直接退出。
        _set_live(task_id, current_title=None, pause_reason=None,
                  pause_requested=False, cancel_requested=False)
        # 进度条上的阶段：每道题内部都会走一遍「检索 → 详情页」，
        # 但索引页有缓存，跑起来之后耗时几乎全在详情页，所以统一显示 enrich。
        storage.update_task(task_id, stage="enrich")

        consecutive_failures = 0
        pause_reason = None
        cancelled = False
        try:
            # 按任务类型选「处理一条明细」的方式。unit 的整届清单通常已在
            # 阶段一装进索引缓存，这里再取一次是命中；但续跑时缓存可能已过期
            # （TTL 30 分钟），要重拉 5–7 MB 的索引页，可能失败 —— 所以放进
            # try：拉不下来就暂停任务记 pause_reason，而不是让异常穿透 ——
            # 那样任务永远停在未完成状态，既不能续跑，前端也只能一直轮询。
            if task["type"] == "unit":
                unit = units[0]
                entries, _index, _cached = service.load_index(unit, fetcher)
                entry_by_key = {normalize_title(e["title"]): e for e in entries}

                def process(item):
                    return _process_unit_item(item, unit, entry_by_key, fetcher,
                                              auto_commit)
            else:
                item_deadline = cfg["CRAWL_SINGLE_DEADLINE_SEC"] or None

                def process(item):
                    return _process_item(item, units, fetcher, item_deadline,
                                         auto_commit)

            # 只取 pending：断点续爬就是把上次没跑到的接着跑，成功的绝不重来
            for item in storage.pending_items(task["id"]):
                # 用户点了暂停/取消：把当前这条处理完、下一条开始前停手
                live = live_state(task_id)
                if live.get("cancel_requested"):
                    cancelled = True
                    break
                if live.get("pause_requested"):
                    pause_reason = PAUSE_USER
                    break

                _set_live(task_id, current_title=item["input_title"])
                ok, fetch_failed = process(item)

                if ok:
                    storage.bump_task(task_id, cursor=item["seq"],
                                      finished=1, success=1)
                    consecutive_failures = 0
                else:
                    storage.bump_task(task_id, cursor=item["seq"],
                                      finished=1, failed=1)
                    # 「没找到这篇」很正常（用户可能记错题目），不累计；
                    # 只有抓取层面的失败连着来才说明站点那边有问题。
                    consecutive_failures = consecutive_failures + 1 if fetch_failed else 0

                stats = fetcher.stats()
                if stats.get("blocked_hosts"):
                    # 站点已经明确拒绝服务：按 §1.3 立刻停手，剩下的题目
                    # 原样留在 pending，等熔断期过去再续跑 —— 不硬闯。
                    pause_reason = PAUSE_BREAKER
                    break
                if consecutive_failures >= max_consecutive:
                    pause_reason = PAUSE_FAILURES
                    break
        except CrawlError:
            # 抓取层失败：整届清单在续跑时缓存已过期、重拉又被熔断/网络错误
            # 挡住，或会议表缺种子数据 —— 一条都处理不了。落成 paused 才能
            # 续跑；熔断（403/429）用 BREAKER 的说法，与循环内的检查同一口径。
            reason = PAUSE_BREAKER if fetcher.stats().get("blocked_hosts") \
                else PAUSE_INTERNAL
            storage.pause_task(task_id, reason)
            _set_live(task_id, pause_reason=reason)
            raise
        except Exception:
            # 崩了也要留个能续跑的状态，否则前端会一直轮询一条永远 running 的任务。
            # 用 paused 而不是 failed —— 崩溃不该堵死「从断点续跑」这条路。
            storage.pause_task(task_id, PAUSE_INTERNAL)
            _set_live(task_id, pause_reason=PAUSE_INTERNAL)
            raise
        finally:
            _set_live(task_id, current_title=None)

        if cancelled:
            # 取消：已完成的保留，剩下的留在 pending，cursor 保留供续跑（§4.2）
            storage.mark_status(task_id, "cancelled")
        elif pause_reason:
            _set_live(task_id, pause_reason=pause_reason)
            storage.pause_task(task_id, pause_reason)
        else:
            # 计数是 bump_task 一路累加的，这里只改状态和时间
            storage.mark_status(task_id, "done",
                                stage="commit" if auto_commit else "enrich")

        return storage.get_task(task_id)


def _process_item(item, units, fetcher, deadline_sec, auto_commit):
    """处理一条「按题目检索」的明细（titles / bibtex）。

    返回 `(是否成功, 失败是否属于抓取层面)`。
    """
    title = (item["input_title"] or "").strip()
    deadline = time.monotonic() + deadline_sec if deadline_sec else None
    res = service.resolve_title(title, units, fetcher, deadline=deadline)

    if not res.found:
        storage.finish_item(
            item["id"], "failed",
            fail_reason=res.error.code,
            parsed={"input_title": title, "searched_units": res.searched,
                    "candidates": service.top_candidates(res.candidates)},
        )
        return False, res.fetch_failed

    return _succeed(item, res.paper, res.unit.label, res.warnings, auto_commit)


def _process_unit_item(item, unit, entry_by_key, fetcher, auto_commit):
    """处理一条「整届清单」的明细（unit 模式）：条目直接来自索引页，无需标题匹配。"""
    title = (item["input_title"] or "").strip()
    entry = entry_by_key.get(normalize_title(title))
    if entry is None:
        storage.finish_item(item["id"], "failed", fail_reason="NOT_FOUND_CVF",
                            parsed={"input_title": title})
        return False, False

    paper, warnings = service.build_paper(unit, entry, fetcher)
    paper["match_score"] = 1.0          # 条目直接来自列表页，匹配无歧义
    paper["match_reason"] = "exact"
    return _succeed(item, paper, unit.label, warnings, auto_commit)


def _succeed(item, paper, unit_label, warnings, auto_commit):
    """一条明细成功落定。

    auto_commit=true 直接写库（明细指回 paper_id）；false 则把 paper 暂存进
    parsed_json，等「全部入库」再写。两种模式下 paper 都不会丢，只是时点不同。
    """
    paper_id = None
    if auto_commit:
        paper_id, _ = _store_paper(item["id"], paper)

    parsed = {
        "input_title": (item["input_title"] or "").strip(),
        "matched_unit": unit_label,
        "match_score": paper.get("match_score"),
        "match_reason": paper.get("match_reason"),
        "warnings": warnings,
    }
    if not auto_commit:
        # 暂存模式：parsed_json 里的 paper 是「全部入库」唯一的数据来源，必须写全
        parsed["paper"] = paper

    storage.finish_item(item["id"], "success", paper_id=paper_id,
                        fail_reason=paper.get("fail_reason"),
                        detail_url=paper.get("url"),
                        pdf_url=paper.get("pdf_url"),
                        parsed=parsed)
    return True, False


def _store_paper(item_id, paper):
    """auto_commit=true：把一篇论文直接写 paper 表 + 关键词关联。

    与 commit_staged 的差别是**逐条入库**（边爬边写，不经 parsed_json 暂存）——
    崩溃时已经写完的那部分不丢，剩下的留在 pending 从断点续跑。
    """
    paper = dict(paper)
    paper["conference_id"] = _conference_id(paper)
    # 单条一个事务（§1.1 阶段六）：paper + 明细指回 + 关键词关联要么全成
    # 要么全不成 —— 中途崩溃不留下「paper 在、关联不在」的半成品。
    with transaction():
        paper_id, action = storage.upsert_paper(paper, commit=False)
        storage.attach_paper(item_id, paper_id, commit=False)
        storage.link_keywords(paper_id, paper.get("keywords") or [], commit=False)
    return paper_id, action


def _conference_id(paper):
    code = paper.get("conference_code")
    conf = storage.conference_info(code)
    if conf is None:
        raise CrawlError(
            "CONFERENCE_UNKNOWN",
            f"会议表里没有 {code}，请先执行 python scripts/init_db.py",
        )
    return conf["id"]


# ---------------------------------------------------------------
# 全部入库
# ---------------------------------------------------------------
def commit_staged(task_id):
    """把暂存模式下的解析结果写进 paper 表（§4.2 的「全部入库」）。

    可重复调用：按 title_key 去重，第二次调用只会得到 skipped_dup。
    整个循环包在**一个事务**里 —— 2,700 篇逐条提交就是 2,700 次落盘。
    """
    task = storage.get_task(task_id)
    counts = {"inserted": 0, "updated": 0, "skipped_dup": 0}

    with transaction():
        for item in storage.success_items(task["id"]):
            paper = (item.get("parsed") or {}).get("paper")
            if not paper:
                continue              # 早期任务可能没把 parsed_json 写全，跳过而不是崩

            paper = dict(paper)               # 不改动 parsed_json 里那份
            paper["conference_id"] = _conference_id(paper)
            paper_id, action = storage.upsert_paper(paper, commit=False)
            storage.attach_paper(item["id"], paper_id, commit=False)
            counts["skipped_dup" if action == "skipped" else action] += 1

    storage.update_task(task_id, stage="commit")
    return counts
