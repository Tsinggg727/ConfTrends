"""爬取接口 —— 设计文档 §4.1（主接口）与 §4.2（配套接口）。

    POST /api/v1/papers/crawl             单个题目爬取（同步）
    POST /api/v1/papers/import            批量导入（异步，立即返回 task_id）
    GET  /api/v1/tasks/<task_id>          任务进度查询（前端每 2s 轮询）
    POST /api/v1/tasks/<task_id>/commit   暂存模式的「全部入库」
    POST /api/v1/tasks/<task_id>/resume   从断点续跑

`POST /papers/import` 的 `type` 目前只实现 `titles`；`bibtex` / `unit` 属
设计文档 §6.1 步骤 4 及以后，接口先按「参数不认识」明确拒绝，不假装能用。

**响应约定**：业务失败（题目没找到、摘要为空）返回 HTTP 200 +
`data.status = "failed"`，只有参数本身不合法才用 4xx ——
否则前端拦截器会把「没找到」也弹成红色 toast，与原型④「失败行内展示原因」
的表现冲突（§4.1 的设计取舍）。批量任务同理：单条失败不进 HTTP 状态码，
它是任务结果的一部分，通过 `recent_failures` 与结果列表呈现。
"""
from flask import Blueprint, current_app, request

from crawl import batch, service, storage
from crawl.fail_reason import CrawlError, InvalidParam, describe
from crawl.units import CONFERENCE_CODES, held_in, units_for
from db import query_one
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
    """批量导入（§4.1 ②）。

    请求体二选一，参数相同：

        application/json      {"type": "titles",
                               "text": "题目一\\n题目二",
                               "conference_code": "CVPR", "year": 2024,
                               "auto_commit": false}
        multipart/form-data   把 text 换成 file（.txt / .csv，CSV 只取第一列）

    `titles` 默认 `auto_commit=false`：先暂存，用户看过匹配结果再走
    `POST /tasks/<id>/commit` 一次入库 —— 50 条里有 3 条匹配错了，
    不该在用户看见之前就已经写进 paper 表。

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
    if not task_type:
        return fail(400, "缺少 type 参数（本步骤支持 titles）"), 400
    if task_type != "titles":
        return fail(400, f"type={task_type} 尚未实现，本步骤只支持 titles"), 400

    try:
        text = batch.read_upload(upload) if upload is not None else (payload.get("text") or "")
        conference_code, year = _target(payload)
    except InvalidParam as exc:
        return fail(exc.code, exc.message), exc.code

    if not text.strip():
        return fail(400, "没有收到内容：给 text 字段，或用 file 上传 .txt / .csv"), 400

    titles, warnings = batch.parse_titles(text)
    if not titles:
        return fail(400, "没有从内容里解析出任何题目"), 400
    if len(titles) > batch.MAX_TITLES:
        return fail(400, f"题目行数 {len(titles)} 超过上限 {batch.MAX_TITLES}"), 400

    # 同一 (会议, 年份) 上已有没跑完的任务：别重复消耗同一批配额（§4.1 ②）
    existing = storage.find_active_task(conference_code, year)
    if existing:
        return fail(409, f"{_target_label(existing)} 上已有未跑完的任务 "
                         f"{existing['task_id']}（{existing['status']}），"
                         f"请先续跑它或等它跑完"), 409

    warnings += _slow_batch_warnings(conference_code, year)

    # titles 类型本步骤只走「暂存 + 全部入库」，不做边爬边入库。
    # 强制 false，免得用户传了 true 得到一个「跑完却不写 paper、
    # 又不能走 commit」的死任务。auto_commit=true 留给 bibtex/unit（步骤 4+）。
    auto_commit = False
    # 库里的 type 用 §3.3 的枚举 batch_titles（区别于 API 输入参数 titles），
    # 与 crawl_single 的 single 对应：一个是「单条」，一个是「批量题目」。
    task = storage.create_task("batch_titles", conference_code, year, auto_commit,
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
    }, message=f"识别到 {len(titles)} 条题目，已开始抓取")


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

    return ok({
        "task_id": task["task_id"],
        "type": task["type"],
        "status": task["status"],
        "stage": task["stage"],
        "stage_label": STAGE_LABELS.get(task["stage"], task["stage"]),
        "conference_code": task["conference_code"],
        "year": task["year"],
        "auto_commit": bool(task["auto_commit"]),
        "total": total,
        "finished": finished,
        "percent": round(finished / total * 100, 1) if total else 0.0,
        "success": task["success"],
        "failed": task["failed"],
        "skipped": task["skipped"],
        "current_title": live.get("current_title"),
        "elapsed_sec": max(int(elapsed), 0),
        "eta_sec": _eta_sec(task, total, finished, elapsed),
        "qps": _qps(finished, elapsed),
        "cursor": task["cursor"],
        "pause_reason": pause_reason,
        "pause_label": batch.pause_label(pause_reason),
        "recent_failures": _recent_failures(task["id"]),
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        # 限速器计数：requests / retries / blocked / blocked_hosts
        "fetcher": service.get_fetcher().stats(),
    })


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
