"""爬取接口 —— 设计文档 §4.1（主接口）与 §4.2（配套接口）。

    POST /api/v1/papers/crawl             单个题目爬取（同步）
    POST /api/v1/papers/import            批量导入（异步，立即返回 task_id）
    GET  /api/v1/tasks                    任务列表（历史任务面板）
    GET  /api/v1/tasks/<task_id>          任务进度查询（前端每 2s 轮询）
    GET  /api/v1/tasks/<task_id>/items    结果行分页（支持状态筛选 / 增量）
    POST /api/v1/tasks/<task_id>/commit   暂存模式的「全部入库」
    POST /api/v1/tasks/<task_id>/pause    用户手动暂停（§5.3 的 [⏸ 暂停]）
    POST /api/v1/tasks/<task_id>/resume   从断点续跑
    POST /api/v1/tasks/<task_id>/cancel   取消任务（已完成部分保留）

`POST /papers/import` 的 `type` 支持 `titles`（步骤 3）/ `bibtex` / `unit`
（步骤 4）。三种输入共用一条调度链：解析输入 → 建任务与明细 → 后台线程边爬边写，
进度查 `GET /tasks/<task_id>`。

**响应约定**：业务失败（题目没找到、摘要为空）返回 HTTP 200 +
`data.status = "failed"`，只有参数本身不合法才用 4xx ——
否则前端拦截器会把「没找到」也弹成红色 toast，与原型④「失败行内展示原因」的
表现冲突（§4.1 的设计取舍）。批量任务同理：单条失败不进 HTTP 状态码，
它是任务结果的一部分，通过 `recent_failures` 与结果列表呈现。
"""
from flask import Blueprint, current_app, request

from crawl import batch, service, storage
from crawl.fail_reason import CrawlError, InvalidParam, describe, is_retryable
from crawl.units import CONFERENCE_CODES, held_in, units_for
from db import query_one
from utils.pagination import paginated, parse_pagination
from utils.response import fail, ok

bp = Blueprint("crawl", __name__)

# 进度条上方的阶段文案，让用户知道卡在哪一步而不只是看到百分比
STAGE_LABELS = {
    "discover": "检索论文清单",
    "enrich": "抓取详情页摘要",
    "s2": "Semantic Scholar 补全",
    "extract": "关键词抽取",
    "commit": "写入数据库",
}

# §4.1 ③：recent_failures 只带最近若干条，完整失败列表另走分页接口
RECENT_FAILURES = 10


# ---------------------------------------------------------------
# 单个题目（同步）
# ---------------------------------------------------------------
@bp.post("/papers/crawl")
def crawl_paper():
    """单个题目爬取。

    请求体：
        {
          "title": "完整题目",            # 必填
          "conference_code": "CVPR",     # 可选：CVPR / ICCV / ECCV
          "year": 2024,                  # 可选
          "auto_commit": false           # 可选，默认 false = 只暂存不写 paper 表
        }

    限定会议+年份能显著加速（只拉那一届索引页，约 5–20 秒）；
    都不给则按「新→旧」依次检索 9 个单元，最坏到分钟级。
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return fail(400, "请求体必须是 JSON"), 400
    if not isinstance(payload, dict):
        return fail(400, "请求体必须是 JSON 对象"), 400

    title = (payload.get("title") or "").strip()
    conference_code = (payload.get("conference_code") or "").strip().upper() or None
    year = payload.get("year")
    auto_commit = bool(payload.get("auto_commit", False))

    try:
        data = service.crawl_single(
            title,
            conference_code=conference_code,
            year=year,
            auto_commit=auto_commit,
        )
    except InvalidParam as exc:
        return fail(exc.code, exc.message), exc.code

    return ok(data)


# ---------------------------------------------------------------
# 批量导入（异步）
# ---------------------------------------------------------------
@bp.post("/papers/import")
def import_papers():
    """批量导入（§4.1 ②）—— titles / bibtex / unit 三种输入的统一下单口。

      titles   给 text 或 file(.txt/.csv)，默认暂存（auto_commit=false）；
      bibtex   给 file(.bib)，conference_code + year 必填，默认边爬边入库；
      unit     不给内容，只给 conference_code + year，平台自己拉整届清单，
               默认边爬边入库。

    `titles` 默认 `auto_commit=false`：先暂存，用户看过匹配结果再走
    `POST /tasks/<id>/commit` 一次入库 —— 50 条里有 3 条匹配错了，
    不该在用户看见之前就已经写进 paper 表。bibtex / unit 动辄几千条，
    默认边爬边入库，崩溃时已完成的部分不丢。

    解析完立刻返回 `task_id` 和「识别到 N 条」，抓取在后台线程里跑，
    进度查 `GET /tasks/<task_id>`。
    """
    if (request.content_type or "").startswith("multipart/"):
        payload = request.form.to_dict()
        upload = request.files.get("file")
    else:
        upload = None
        payload = request.get_json(silent=True)
        if payload is None:
            return fail(400, "请求体必须是 JSON，或用 multipart/form-data 上传文件"), 400
        if not isinstance(payload, dict):
            return fail(400, "请求体必须是 JSON 对象"), 400

    task_type = (payload.get("type") or "").strip().lower()
    if task_type not in ("titles", "bibtex", "unit"):
        return fail(400, f"type={task_type or '空'} 不支持，"
                         f"可选 titles / bibtex / unit"), 400

    # bibtex / unit 必须明确会议 + 年份；titles 两个都可以不给（依次找 9 个单元）
    try:
        conference_code, year = _target_required(payload) \
            if task_type in ("bibtex", "unit") else _target(payload)
    except InvalidParam as exc:
        return fail(exc.code, exc.message), exc.code

    # 同一 (会议, 年份) 上已有没跑完的任务：别重复消耗同一批配额（§4.1 ②）
    existing = storage.find_active_task(conference_code, year)
    if existing:
        return fail(409, f"{_target_label(existing)} 上已有未跑完的任务 "
                         f"{existing['task_id']}（{existing['status']}），"
                         f"请先续跑它或等它跑完"), 409

    # titles 只走「暂存 + 全部入库」，强制 false —— 免得用户传 true 得到
    # 一个「跑完却不写 paper、又不能走 commit」的死任务。bibtex/unit 默认 true。
    auto_commit = _auto_commit(payload, default=True) \
        if task_type in ("bibtex", "unit") else False

    try:
        titles, warnings = _extract_titles(task_type, payload, upload,
                                           conference_code, year)
    except InvalidParam as exc:
        return fail(exc.code, exc.message), exc.code
    except CrawlError as exc:
        # unit 阶段一拉整届清单失败（网络/429 熔断）：这是上游不可用，不是参数错
        return fail(503, f"拉取整届清单失败：{exc.message}，请稍后重试"), 503

    if len(titles) > batch.MAX_TITLES:
        return fail(400, f"论文数 {len(titles)} 超过上限 {batch.MAX_TITLES}"), 400

    warnings += _slow_batch_warnings(conference_code, year)

    # 库里的 type 用 §3.3 的枚举：API 的 titles 存成 batch_titles，
    # bibtex / unit 与输入同名，和 crawl_single 的 single 对应。
    stored_type = "batch_titles" if task_type == "titles" else task_type
    task = storage.create_task(stored_type, conference_code, year, auto_commit,
                               total=len(titles))
    storage.create_items(task["id"], titles)

    batch.start(current_app._get_current_object(), task["task_id"])

    return ok({
        "task_id": task["task_id"],
        "type": task["type"],
        "total": len(titles),
        "auto_commit": bool(auto_commit),
        "status": task["status"],
        "poll_url": f"/api/v1/tasks/{task['task_id']}",
        "warnings": warnings,
    }, message=f"识别到 {len(titles)} 条，已开始抓取")


def _target(payload):
    """解析会议/年份。titles 类型两个都可以不给（那就是 9 个单元依次找）。"""
    code = (payload.get("conference_code") or "").strip().upper() or None
    year = payload.get("year")
    if year in ("", None):
        year = None
    elif isinstance(year, str) and year.strip().isdigit():
        year = int(year)                      # multipart 表单里什么都是字符串

    if code and code not in CONFERENCE_CODES:
        raise InvalidParam(f"conference_code 必须是 {' / '.join(CONFERENCE_CODES)} 之一")
    # bool 也是 int，别让 year=true 变成 1 年
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
        raise InvalidParam("year 必须是整数")
    if code and year is not None and not held_in(code, year):
        raise InvalidParam(f"{code} 在 {year} 年没有举办")
    if not units_for(code, year):
        raise InvalidParam("没有匹配的会议-年份组合")
    return code, year


def _target_required(payload):
    """bibtex / unit 必须明确会议 + 年份。"""
    code, year = _target(payload)
    if not code:
        raise InvalidParam("bibtex / unit 类型必须给 conference_code")
    if year is None:
        raise InvalidParam("bibtex / unit 类型必须给 year")
    return code, year


def _auto_commit(payload, default=False):
    """取 auto_commit：没传用默认值；multipart 表单里它是个字符串，得显式解析。"""
    value = payload.get("auto_commit")
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _extract_titles(task_type, payload, upload, conference_code, year):
    """按 type 把输入变成去重后的题目列表，返回 `(titles, warnings)`。

    参数不合法抛 InvalidParam（→ 4xx）；unit 阶段一拉整届清单失败抛 CrawlError
    （由调用方转成 503）。
    """
    if task_type == "titles":
        text = batch.read_upload(upload) if upload is not None \
            else (payload.get("text") or "")
        if not text.strip():
            raise InvalidParam("没有收到内容：给 text 字段，或用 file 上传 .txt / .csv")
        titles, warnings = batch.parse_titles(text)
        if not titles:
            raise InvalidParam("没有从内容里解析出任何题目")
        return titles, warnings

    if task_type == "bibtex":
        if upload is None:
            raise InvalidParam("bibtex 类型必须用 file 上传 .bib 文件")
        text = batch.read_bib_upload(upload)
        titles, warnings = batch.parse_bibtex(text)
        if not titles:
            raise InvalidParam("没有从 .bib 里解析出任何论文")
        return titles, warnings

    # unit：平台自己去列表页拉整届清单（阶段一，结果进索引缓存供阶段二复用）
    if upload is not None:
        raise InvalidParam("unit 类型不需要上传文件，只给 conference_code + year")
    unit = units_for(conference_code, year)[0]
    # load_index 的形参是 (unit, fetcher)：两个都是对象，传反了要到运行时才暴露
    entries, _index, _cached = service.load_index(unit, service.get_fetcher())
    titles = batch.titles_from_entries(entries)
    if not titles:
        raise InvalidParam(f"{unit.label} 的列表页没有解析出任何论文")
    return titles, []


def _target_label(task):
    return f"{task['conference_code']} {task['year']}" if task["year"] \
        else str(task["conference_code"])


def _slow_batch_warnings(conference_code, year):
    """跑之前先把「这批会很慢」讲清楚，别让用户对着不动的进度条猜。"""
    units = units_for(conference_code, year)
    cap = current_app.config["CRAWL_INDEX_CACHE_MAX_UNITS"]
    if len(units) <= cap:
        return []
    return [
        f"未限定会议年份：每道题都要依次检索 {len(units)} 个单元的索引页，"
        f"而索引缓存只留 {cap} 个单元，会反复重拉 5–7 MB 的页面。"
        f"建议传 conference_code + year，或把 CRAWL_INDEX_CACHE_MAX_UNITS 调到 {len(units)}"
    ]


# ---------------------------------------------------------------
# 进度查询
# ---------------------------------------------------------------
@bp.get("/tasks/<task_id>")
def get_task(task_id):
    """任务进度查询（§4.1 ③）—— 前端每 2s 轮询它驱动进度条。

    单条爬取是同步的，查出来就是个已经跑完的单条任务；`current_title` /
    `eta_sec` / `recent_failures` 这些字段是批量任务才有意义的。

    `current_title` 取自进程内的注册表，进程重启后就是 None（它每秒钟都在变，
    没法持久化）；`pause_reason` 反之以数据库为准。
    """
    row = query_one("SELECT * FROM crawl_task WHERE task_id = ?", (task_id,))
    if row is None:
        return fail(404, "任务不存在"), 404

    task = dict(row)
    total = task["total"] or 0
    finished = task["finished"] or 0
    elapsed = _elapsed_sec(task_id)
    live = batch.live_state(task_id)
    pause_reason = task["pause_reason"] or live.get("pause_reason")

    # 共享字段（列表 / 进度查询同一口径）+ 进度查询独有的实时字段
    data = _task_summary(task)
    data.update({
        "pause_reason": pause_reason,
        "pause_label": batch.pause_label(pause_reason),
        "current_title": live.get("current_title"),
        "started_at": task["started_at"],
        "elapsed_sec": max(int(elapsed), 0),
        "eta_sec": _eta_sec(task, total, finished, elapsed),
        "qps": _qps(finished, elapsed),
        "recent_failures": _recent_failures(task["id"]),
        # 限速器计数：requests / retries / blocked / blocked_hosts
        "fetcher": service.get_fetcher().stats(),
    })
    return ok(data)


def _elapsed_sec(task_id):
    """已跑秒数（带小数，qps 需要精度）。没开始的按 0 算。"""
    row = query_one(
        """SELECT (julianday(COALESCE(finished_at, CURRENT_TIMESTAMP))
                   - julianday(COALESCE(started_at, created_at))) * 86400.0 AS s
             FROM crawl_task WHERE task_id = ?""",
        (task_id,),
    )
    return (row["s"] or 0.0) if row else 0.0


def _qps(finished, elapsed):
    """任务全程的平均速率（§4.1 ③ 的示例就是 finished/elapsed）。

    速率掉到 0 而 `status` 还是 running，说明卡住了 —— 这个判断留给前端。
    """
    if not finished or elapsed <= 0:
        return 0.0
    return round(finished / elapsed, 2)


def _eta_sec(task, total, finished, elapsed):
    """剩余秒数。跑完是 0；暂停或还没跑出速率就是 None —— 不编数字。"""
    if finished >= total:
        return 0
    if task["status"] != "running":
        return None
    rate = _qps(finished, elapsed)
    return int((total - finished) / rate) if rate > 0 else None


def _recent_failures(task_row_id):
    """最近若干条失败（§4.1 ③），带上人话文案。"""
    return [
        {"item_id": r["id"], "seq": r["seq"], "input_title": r["input_title"],
         "fail_reason": r["fail_reason"], "fail_message": describe(r["fail_reason"])}
        for r in storage.recent_failures(task_row_id, RECENT_FAILURES)
    ]


# ---------------------------------------------------------------
# 全部入库 / 断点续跑
# ---------------------------------------------------------------
@bp.post("/tasks/<task_id>/commit")
def commit_task(task_id):
    """暂存模式的「全部入库」（§4.2）。

    把成功明细里的 `parsed_json.paper` 写进 paper 表，按 title_key 去重。
    可重复调用：第二次只会得到 `skipped_dup`。
    """
    task = storage.get_task(task_id)
    if task is None:
        return fail(404, "任务不存在"), 404
    if task["auto_commit"]:
        return fail(409, "这个任务是边爬边入库（auto_commit=true），无需再入库"), 409
    if task["status"] == "running":
        return fail(409, "任务还在跑，等它跑完再入库"), 409

    try:
        counts = batch.commit_staged(task_id)
    except CrawlError as exc:
        # 走到这里基本是会议表没种子数据 —— 服务端环境问题，不是用户的参数问题
        return fail(500, exc.message), 500

    return ok(counts, message=(f"入库完成：新增 {counts['inserted']} 篇、"
                               f"补全 {counts['updated']} 篇、"
                               f"已存在跳过 {counts['skipped_dup']} 篇"))


@bp.post("/tasks/<task_id>/resume")
def resume_task(task_id):
    """从断点续跑（§4.2）。

    只跑 `status='pending'` 的题目，已经成功的绝不重来 ——
    不为已经拿到的结果再花一次配额。`cursor` 保留为对外的高水位。
    """
    task = storage.get_task(task_id)
    if task is None:
        return fail(404, "任务不存在"), 404
    if batch.is_running(task_id):
        return fail(409, "任务已经在跑了"), 409
    if task["status"] not in ("paused", "cancelled"):
        return fail(409, f"任务状态是 {task['status']}，"
                         f"只有 paused / cancelled 能续跑"), 409

    pending = len(storage.pending_items(task["id"]))
    if not pending:
        # 上一轮正好停在最后一条之后：没有待跑的，直接收尾
        storage.mark_status(task_id, "done",
                            stage="commit" if task["auto_commit"] else "enrich")
        return ok({"task_id": task_id, "status": "done", "pending": 0,
                   "resumed": False}, message="没有待处理的题目，任务已收尾")

    storage.resume_task(task_id)
    batch.start(current_app._get_current_object(), task_id)

    return ok({
        "task_id": task_id,
        "status": "running",
        "resumed": True,
        "pending": pending,
        "cursor": task["cursor"],
        "poll_url": f"/api/v1/tasks/{task_id}",
    }, message=f"已从断点续跑，剩余 {pending} 条")


# ---------------------------------------------------------------
# 任务列表 / 结果行 / 暂停 / 取消
# ---------------------------------------------------------------
@bp.get("/tasks")
def list_tasks():
    """任务列表（§4.2）—— 历史任务面板与「刷新后找回任务」的数据源。"""
    page, page_size = parse_pagination(request.args)
    rows, total = storage.list_tasks(page, page_size)
    return ok(paginated([_task_summary(r) for r in rows],
                        total, page, page_size))


@bp.get("/tasks/<task_id>/items")
def list_task_items(task_id):
    """结果行分页（§4.2）：`status=all|success|failed|skipped|pending`。

    `after_seq` 是增量参数：只返回 seq 更大的行，供前端轮询时把
    新完成的行插进列表顶部，不整页重拉（§5.3 的增量刷新）。
    """
    task = storage.get_task(task_id)
    if task is None:
        return fail(404, "任务不存在"), 404

    status = (request.args.get("status") or "all").strip().lower()
    if status not in storage.ITEM_FILTERS:
        return fail(400, f"status 只能是 {' / '.join(storage.ITEM_FILTERS)}"), 400

    page, page_size = parse_pagination(request.args)
    after_seq = request.args.get("after_seq", 0, type=int) or 0

    rows, total = storage.page_items(task["id"], status, after_seq,
                                     page, page_size)
    for r in rows:
        # 失败码翻译成人话 + 可重试标记：前端据此决定行尾给 [重试] 还是 [忽略]
        r["fail_message"] = describe(r["fail_reason"]) if r["fail_reason"] else ""
        r["retryable"] = is_retryable(r["fail_reason"]) if r["fail_reason"] else None

    return ok(paginated(rows, total, page, page_size))


@bp.post("/tasks/<task_id>/pause")
def pause_task(task_id):
    """手动暂停（§5.3 的 [⏸ 暂停]）。已完成的保留，可从断点继续。"""
    task = storage.get_task(task_id)
    if task is None:
        return fail(404, "任务不存在"), 404

    if batch.is_running(task_id):
        # 只设标志：正在处理的那条让它跑完，状态由线程自己落
        batch.request_pause(task_id)
        return ok({"task_id": task_id, "status": "pausing"},
                  message="已请求暂停，正在收尾当前这一篇")
    if task["status"] == "paused":
        return ok({"task_id": task_id, "status": "paused"}, message="任务已是暂停状态")
    if task["status"] != "running":
        # done / cancelled / failed / queued：queued 没线程在跑，直接落库
        if task["status"] == "queued":
            storage.pause_task(task_id, batch.PAUSE_USER)
            return ok({"task_id": task_id, "status": "paused"}, message="任务已暂停")
        return fail(409, f"任务状态是 {task['status']}，不能暂停"), 409

    # 库里是 running 但线程已经不在（进程重启等）：直接落库
    storage.pause_task(task_id, batch.PAUSE_USER)
    return ok({"task_id": task_id, "status": "paused"}, message="任务已暂停")


@bp.post("/tasks/<task_id>/cancel")
def cancel_task(task_id):
    """取消任务（§4.2）：已完成的保留，剩下的留在 pending，cursor 保留供续跑。"""
    task = storage.get_task(task_id)
    if task is None:
        return fail(404, "任务不存在"), 404
    if task["status"] in ("done", "failed", "cancelled"):
        return fail(409, f"任务已是终态（{task['status']}），无需取消"), 409

    if batch.is_running(task_id):
        batch.request_cancel(task_id)
        return ok({"task_id": task_id, "status": "cancelling"},
                  message="已请求取消，正在收尾当前这一篇")

    storage.mark_status(task_id, "cancelled")
    return ok({"task_id": task_id, "status": "cancelled"},
              message=f"任务已取消，已完成的 {task['finished']} 条保留，"
                      f"剩余 {task['total'] - task['finished']} 条未处理")


def _task_summary(row):
    """列表行与进度查询共用一套字段口径，前端两种入口读到的形状一致。"""
    total = row["total"] or 0
    finished = row["finished"] or 0
    pause_reason = row["pause_reason"]
    return {
        "task_id": row["task_id"],
        "type": row["type"],
        "status": row["status"],
        "stage": row["stage"],
        "stage_label": STAGE_LABELS.get(row["stage"], row["stage"]),
        "conference_code": row["conference_code"],
        "year": row["year"],
        "auto_commit": bool(row["auto_commit"]),
        "total": total,
        "finished": finished,
        "percent": round(finished / total * 100, 1) if total else 0.0,
        "success": row["success"],
        "failed": row["failed"],
        "skipped": row["skipped"],
        "cursor": row["cursor"],
        "pause_reason": pause_reason,
        "pause_label": batch.pause_label(pause_reason),
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }
