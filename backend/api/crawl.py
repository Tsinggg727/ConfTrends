"""爬取接口 —— 设计文档 §4.1。

    POST /api/v1/papers/crawl      单个题目爬取（同步）
    GET  /api/v1/tasks/<task_id>   任务进度查询（读取 crawl_task）

批量导入 `POST /papers/import`（§4.1 ②）属设计文档 §6.1 步骤 3，不在本次范围。

**响应约定**：业务失败（题目没找到、摘要为空）返回 HTTP 200 +
`data.status = "failed"`，只有参数本身不合法才用 4xx ——
否则前端拦截器会把「没找到」也弹成红色 toast，与原型④「失败行内展示原因」
的表现冲突（§4.1 的设计取舍）。
"""
from flask import Blueprint, request

from crawl import service
from crawl.fail_reason import InvalidParam
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
    都不给则按「新→旧」依次检索 10 个单元，最坏到分钟级。
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


@bp.get("/tasks/<task_id>")
def get_task(task_id):
    """任务进度查询。

    单条爬取是同步的，这个接口主要给「手动验证任务行落库」和后续批量任务用。
    `qps` / `eta_sec` / `current_title` 是批量任务才有的字段（§4.1 ③），
    本步骤不返回 —— 与其填假值，不如等批量导入时一起补上。
    """
    row = query_one("SELECT * FROM crawl_task WHERE task_id = ?", (task_id,))
    if row is None:
        return fail(404, "任务不存在"), 404

    task = dict(row)
    total = task["total"] or 0
    finished = task["finished"] or 0
    elapsed = query_one(
        """SELECT CAST((julianday(COALESCE(finished_at, CURRENT_TIMESTAMP))
                        - julianday(started_at)) * 86400 AS INTEGER) AS s
             FROM crawl_task WHERE task_id = ?""",
        (task_id,),
    )["s"]

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
        "cursor": task["cursor"],
        "elapsed_sec": max(elapsed or 0, 0),
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        # 限速器计数：requests / retries / blocked / blocked_hosts
        "fetcher": service.get_fetcher().stats(),
    })
