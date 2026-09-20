"""单条题目爬取链路 —— 设计文档 §6.1 步骤 2。

流程（对应 §1.1 的阶段一到阶段六，本步骤只走单条路径）：

    解析会议/年份 → 抓列表页 → 匹配题目 → 抓详情页取摘要 → 写 crawl_task_item
                                                          （auto_commit 时再写 paper）

几个刻意的设计取舍，都写在代码里了，这里先列一遍：

1. **业务失败不抛到 HTTP 层**。题目没找到是正常业务结果，返回
   `data.status = "failed"` + fail_reason，HTTP 仍是 200 —— 见 §4.1 的设计取舍。
   只有参数本身不合法（会议年份不存在）才用 InvalidParam 变成 4xx。

2. **索引页带缓存**。一届的索引页 5–7 MB、要 4–15 秒；缓存后连续爬多篇题目
   只拉一次。这不只是快，更是礼貌 —— 少发几 MB 的重复请求。

3. **摘要抓不到不算失败**。论文的标题/作者/会议/年份/链接都已经拿到了，
   因为详情页没打开就整条判失败不划算。摘要缺失记 `enrich_status='partial'`
   和具体失败码，item 仍算成功 —— 与 §1.2 「ABSTRACT_MISSING 是警告级」一致。
"""
import threading
import time

from flask import current_app

from . import storage
from .fail_reason import CrawlError, InvalidParam
from .fetcher import Fetcher
from .parsers import get_parser, parse_detail
from .textutil import build_index, match_title, normalize_title
from .units import (CONFERENCE_CODES, CONFERENCE_UNITS, VENUE_LABELS, held_in,
                    list_units, units_for)

# 索引页缓存上限（个单元）。一届的解析结果约 2–3 MB，别让它无限涨。
_INDEX_CACHE_MAX_UNITS = 3

_index_cache = {}          # (source, tag) -> (过期时刻, entries, {title_key: entry})
_index_lock = threading.Lock()

_fetcher = None
_fetcher_lock = threading.Lock()


# ---------------------------------------------------------------
# 配件
# ---------------------------------------------------------------
def get_fetcher():
    """全进程共用一个限速器 —— 限速必须是全局的，否则多来源会各限各的。"""
    global _fetcher
    if _fetcher is None:
        with _fetcher_lock:
            if _fetcher is None:
                cfg = current_app.config
                _fetcher = Fetcher(
                    user_agent=cfg["CRAWL_USER_AGENT"],
                    min_interval=cfg["CRAWL_MIN_INTERVAL"],
                    max_interval=cfg["CRAWL_MAX_INTERVAL"],
                    concurrency=cfg["CRAWL_CONCURRENCY"],
                    list_timeout=cfg["CRAWL_LIST_TIMEOUT"],
                    detail_timeout=cfg["CRAWL_DETAIL_TIMEOUT"],
                    max_retries=cfg["CRAWL_MAX_RETRIES"],
                    respect_robots=cfg["CRAWL_RESPECT_ROBOTS"],
                )
    return _fetcher


def reset_fetcher():
    """测试用：丢掉缓存的 fetcher，让下一次调用按新配置重建。"""
    global _fetcher
    with _fetcher_lock:
        _fetcher = None


def clear_index_cache():
    with _index_lock:
        _index_cache.clear()


def load_index(unit, fetcher):
    """取某个单元的论文清单，返回 (entries, title_key 索引, 是否命中缓存)。

    缓存的是**解析后的结果**而不是 HTML —— 5–7 MB 的原始页面留着没用，
    解析一次 4 秒才是真正要省的开销。
    """
    key = (unit.source, unit.tag)
    ttl = current_app.config["CRAWL_INDEX_CACHE_TTL"]
    now = time.monotonic()

    with _index_lock:
        hit = _index_cache.get(key)
        if hit and hit[0] > now:
            return hit[1], hit[2], True

    html = fetcher.get_list(unit.index_url)
    parser = get_parser(unit.source)
    entries = parser.parse_list(html, unit.tag)
    index = build_index(entries)
    del html                                  # 及时放手，别让 7 MB 挂到函数结束

    with _index_lock:
        if len(_index_cache) >= _INDEX_CACHE_MAX_UNITS:
            oldest = min(_index_cache, key=lambda k: _index_cache[k][0])
            _index_cache.pop(oldest, None)
        _index_cache[key] = (time.monotonic() + ttl, entries, index)

    return entries, index, False


# ---------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------
def _calendar_hint(conference_code, year):
    """把「会议年份不存在」讲清楚，别让用户对着一个空列表猜。"""
    if conference_code and year:
        years = CONFERENCE_UNITS.get(conference_code, {}).get("years", ())
        return (f"{conference_code} 在 {year} 年没有举办；"
                f"可抓年份为 {', '.join(str(y) for y in years)}")
    return "没有匹配的会议-年份组合"


def _validate(title, conference_code, year):
    if not title:
        raise InvalidParam("title 不能为空")
    if len(title) > 500:
        raise InvalidParam("title 过长（上限 500 字符）")
    if conference_code and conference_code not in CONFERENCE_CODES:
        raise InvalidParam(
            f"conference_code 必须是 {' / '.join(CONFERENCE_CODES)} 之一")
    if year is not None and not isinstance(year, int):
        raise InvalidParam("year 必须是整数")
    if conference_code and year is not None and not held_in(conference_code, year):
        raise InvalidParam(_calendar_hint(conference_code, year))

    units = units_for(conference_code, year)
    if not units:
        raise InvalidParam(_calendar_hint(conference_code, year))
    return units


# ---------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------
def crawl_single(title, conference_code=None, year=None, auto_commit=False,
                 fetcher=None):
    """爬取单篇论文。

    同步执行：给定会议+年份时约 5–20 秒（一次索引页 + 一次详情页）；
    不限定会议年份时按「新→旧」依次检索 10 个单元，最坏可能到分钟级，
    所以有个总时限 CRAWL_SINGLE_DEADLINE_SEC 兜底。

    返回的就是给前端的 `data`，成功与否都返回，不抛异常（参数错除外）。
    """
    title = (title or "").strip()
    units = _validate(title, conference_code, year)

    fetcher = fetcher or get_fetcher()
    task = storage.create_task("single", conference_code, year, auto_commit, total=1)
    item_id = storage.create_item(task["id"], seq=1, input_title=title)

    deadline = time.monotonic() + current_app.config["CRAWL_SINGLE_DEADLINE_SEC"]
    started = time.monotonic()

    # --- 阶段一/二：依次检索各单元的索引页，找到题目 ---
    matched = match = unit = None
    searched, candidates, truncated = [], [], False

    try:
        for u in units:
            if time.monotonic() > deadline:
                truncated = True
                break
            entries, index, cached = load_index(u, fetcher)
            searched.append({"unit": u.label, "candidates": len(entries),
                             "cached": cached})
            if not index:
                continue
            m = match_title(title, index)
            if m.matched:
                matched, match, unit = m.entry, m, u
                break
            for c in m.candidates:
                c["unit"] = u.label
                candidates.append(c)

        if matched is None:
            return _fail(task, item_id, title, CrawlError(
                "NOT_FOUND_CVF",
                _not_found_message(title, searched, truncated),
            ), searched, _top_candidates(candidates), started, fetcher)

        # 找到了，进入补全阶段
        storage.update_task(task["task_id"], stage="enrich")
        paper, warnings = _build_paper(unit, matched, fetcher)
        paper["match_score"] = match.score
        paper["match_reason"] = match.reason

    except CrawlError as err:
        # 抓取过程中的失败：索引页拉不下来 / 被熔断 / 网络错误
        return _fail(task, item_id, title, err, searched,
                     _top_candidates(candidates), started, fetcher)
    except Exception:
        # 没预料到的异常：先把任务标成 failed 再往上抛，
        # 否则会留下一条永远 running 的任务，前端会一直轮询它
        storage.finish_task(task["task_id"], status="failed", failed=1)
        raise

    # --- 阶段六：入库（仅 auto_commit） ---
    commit = None
    if auto_commit:
        conf = storage.conference_info(unit.conference_code)
        if conf is None:
            raise CrawlError(
                "CONFERENCE_UNKNOWN",
                f"会议表里没有 {unit.conference_code}，请先执行 python scripts/init_db.py",
            )
        paper["conference_id"] = conf["id"]
        paper_id, action = storage.upsert_paper(paper)
        paper["id"] = paper_id
        commit = {"action": action, "paper_id": paper_id}
        storage.update_task(task["task_id"], stage="commit")

    storage.finish_item(
        item_id, "success",
        paper_id=paper.get("id"),
        fail_reason=paper.get("fail_reason"),
        detail_url=paper.get("url"),
        pdf_url=paper.get("pdf_url"),
        parsed={"input_title": title, "matched_unit": unit.label,
                "match_score": match.score, "match_reason": match.reason,
                "paper": paper, "warnings": warnings},
    )
    storage.finish_task(
        task["task_id"],
        success=1,
        stage="commit" if auto_commit else "enrich",
    )

    return {
        "status": "success",
        "task_id": task["task_id"],
        "item_id": item_id,
        "input_title": title,
        "matched_unit": unit.label,
        "match_score": match.score,
        "match_reason": match.reason,
        "searched_units": searched,
        "warnings": warnings,
        "auto_commit": bool(auto_commit),
        "commit": commit,
        "elapsed_sec": round(time.monotonic() - started, 2),
        "fetcher": fetcher.stats(),
        "paper": paper,
    }


def _not_found_message(title, searched, truncated):
    units = "、".join(s["unit"] for s in searched) or "（无）"
    msg = f"未在以下单元中找到「{title}」：{units}。请改用官网完整标题"
    if truncated:
        msg += "（检索因超时提前结束，可用 conference_code/year 限定范围加速）"
    return msg


def _top_candidates(candidates):
    return sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)[:3]


def _fail(task, item_id, title, err, searched, candidates, started, fetcher):
    """统一构造失败返回：HTTP 仍是 200，业务状态是 failed（§4.1）。"""
    storage.finish_item(item_id, "failed", fail_reason=err.code,
                        parsed={"input_title": title,
                                "searched_units": searched,
                                "candidates": candidates})
    storage.finish_task(task["task_id"], failed=1, stage="enrich")

    data = {
        "status": "failed",
        "task_id": task["task_id"],
        "item_id": item_id,
        "input_title": title,
        "searched_units": searched,
        "candidates": candidates,
        "elapsed_sec": round(time.monotonic() - started, 2),
        "fetcher": fetcher.stats(),
    }
    data.update(err.to_dict())
    return data


# ---------------------------------------------------------------
# 组装论文对象
# ---------------------------------------------------------------
def _build_paper(unit, entry, fetcher):
    """把「列表页条目 + 详情页摘要 + BibTeX」合成一条论文。

    权威值优先取列表页（一次带回整届，不依赖详情页是否改版），
    BibTeX 用来补齐 DOI/页码/venue 与做交叉校验。
    """
    parser = get_parser(unit.source)
    warnings = []

    # --- 详情页：唯一目的是摘要 ---
    detail, abstract, fail_reason = {}, "", None
    if entry.get("detail_url"):
        try:
            detail = parse_detail(fetcher.get_detail(entry["detail_url"]))
            abstract = detail.get("abstract") or ""
            if not abstract:
                fail_reason = "ABSTRACT_MISSING"
                warnings.append("摘要为空（ABSTRACT_MISSING）——关键词抽取将退化为仅用题目")
            elif detail.get("abstract_truncated"):
                warnings.append("摘要超长已截断至 4000 字符")
        except CrawlError as exc:
            fail_reason = exc.code
            warnings.append(
                f"详情页抓取失败（{exc.code}）：{exc.message}；"
                "已保留列表页元数据，摘要留空")
    else:
        fail_reason = "ABSTRACT_MISSING"
        warnings.append("列表页未给出详情页链接，无法取摘要")

    # --- BibTeX（只有 CVF 有） ---
    bib = {}
    if entry.get("bibtex"):
        parse_bib = getattr(parser, "parse_bibtex", None)
        if parse_bib:
            bib = parse_bib(entry["bibtex"]) or {}
            if not bib.get("bibtex_key"):
                # 不硬失败：标题/作者/年份/链接都已在手，BibTeX 只是加分项
                warnings.append("BibTeX 解析不出关键字段（BIBTEX_PARSE_FAILED），已忽略")

    title = entry["title"]
    if bib.get("bibtex_title") and normalize_title(bib["bibtex_title"]) != normalize_title(title):
        warnings.append("BibTeX 标题与列表页标题不一致，已以列表页为准")

    authors = bib.get("authors") or entry.get("authors") or ""

    # 年份：BibTeX 优先，但它和单元年份冲突时以单元为准
    # —— 单元年份来自 URL（/CVPR2024），不可能解析错。
    year = unit.year
    bib_year = str(bib.get("year", "")).strip()
    if bib_year.isdigit() and int(bib_year) != unit.year:
        warnings.append(f"BibTeX 年份 {bib_year} 与单元年份 {unit.year} 不一致，已以单元为准")

    pdf_url = entry.get("pdf_url") or detail.get("pdf_url") or ""
    doi = entry.get("doi") or detail.get("doi") or ""

    paper = {
        "id": None,                       # auto_commit 后才有
        "title": title,
        "title_key": normalize_title(title),
        "authors": authors,
        "conference": {"code": unit.conference_code, "name": unit.conference_code},
        "conference_code": unit.conference_code,
        "year": year,
        "abstract": abstract,
        "abstract_truncated": bool(detail.get("abstract_truncated")),
        # 关键词抽取是阶段五（本步骤范围外），先如实返回空列表
        "keywords": [],
        "keywords_status": "pending",
        "url": entry.get("detail_url", ""),
        "pdf_url": pdf_url,
        "doi": doi,
        "pages": bib.get("pages", ""),
        "bibtex_key": bib.get("bibtex_key", ""),
        "venue_raw": bib.get("venue_raw") or VENUE_LABELS.get(unit.conference_code, ""),
        "source": unit.source,
        "match_score": None,              # 由调用方填（match.score）
        "enrich_status": "enriched" if abstract else "partial",
        "fail_reason": fail_reason,
    }
    return paper, warnings
