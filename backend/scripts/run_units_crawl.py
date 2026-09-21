"""串行爬取三个单元（CVPR2024 / ICCV2023 / ECCV2024）—— 只调 HTTP 接口。

用法：
    cd backend
    .venv/Scripts/python.exe scripts/run_units_crawl.py

职责与边界：
    · 串行提交 POST /papers/import（type=unit, auto_commit=true）——
      后端对同一 (conference_code, year) 本来就只允许一个活跃任务（409），
      串行是为了让三届共享同一个全局限速器时互不抢配额；
    · 每 5s 轮询 GET /tasks/{task_id}，直到终态；paused 视原因自动续跑
      （熔断等冷却期过后 resume，INTERNAL / TOO_MANY_FAILURES 停手报告）；
    · 每届跑完用 sqlite3 **只读**连接验证：paper 数、摘要非空数、失败码分布
      （失败码分布没有现成接口，直接读库是最省事且无副作用的方式）；
    · 不 import 后端任何模块、不写库 —— 只当自己是第三个客户端。
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:5000/api/v1"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conftrends.db"
LOG_PATH = Path(__file__).resolve().parent.parent / "crawl_units.log"

UNITS = [("CVPR", 2024), ("ICCV", 2023), ("ECCV", 2024)]
POLL_SEC = 5
RESUME_MAX = 30                     # 熔断冷却 5 分钟一次，最多容忍 30 次（2.5 小时）
TERMINAL = {"done", "cancelled", "failed"}

# 可自动续跑的暂停原因：
#   BREAKER_TRIPPED —— 站点 403/429，等冷却期过去再敲门（§1.3 合规语义）
#   INTERRUPTED     —— 有别的进程启动过 app.py 把 running 任务标了 paused
#                      （实测：debug 模式下第二次启动同一服务即如此），
#                      那个进程多半因端口占用已退出，等 30s 再续跑是安全的
AUTO_RESUME = {"BREAKER_TRIPPED": 310, "INTERRUPTED": 30}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def api(method, path, **kwargs):
    """调接口：非 2xx 时把 body 带出来，报错信息里别只有状态码。"""
    resp = requests.request(method, f"{BASE}{path}", timeout=300, **kwargs)
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:300]}
    if resp.status_code >= 400:
        raise RuntimeError(f"{method} {path} → HTTP {resp.status_code}: {body}")
    return body


def wait_terminal(task_id):
    """轮询到终态；可自动续跑的暂停（熔断/被外部启动打断）等一等再 resume。"""
    resumes = 0
    while True:
        task = api("GET", f"/tasks/{task_id}")["data"]
        status = task["status"]
        if status in TERMINAL:
            return task
        if status == "paused":
            reason = task.get("pause_reason") or ""
            if reason in AUTO_RESUME and resumes < RESUME_MAX:
                resumes += 1
                wait = AUTO_RESUME[reason]
                log(f"  暂停（{reason}，第 {resumes} 次），{wait}s 后自动续跑…")
                time.sleep(wait)
                api("POST", f"/tasks/{task_id}/resume")
                continue
            log(f"  ⚠ 暂停且不自动续跑：{reason}（{task.get('pause_label')}），"
                f"手动 resume：POST /tasks/{task_id}/resume")
            return task
        # 未到终态：每 30s 报一次进度，别把日志刷成瀑布
        if task["finished"] and task["finished"] % 30 == 0:
            log(f"  {task['finished']}/{task['total']} "
                f"成功 {task['success']} 失败 {task['failed']} "
                f"{task.get('qps', 0)} 篇/秒 · {task.get('current_title') or ''}")
        time.sleep(POLL_SEC)


def verify(conference_code, year, task):
    """只读验证一届的落库结果，返回报告 dict。"""
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conf = conn.execute("SELECT id FROM conference WHERE code = ?",
                            (conference_code,)).fetchone()
        if conf is None:
            return {"error": f"conference 表没有 {conference_code}"}
        conf_id = conf["id"]
        papers, with_abstract = conn.execute(
            """SELECT COUNT(*) AS papers,
                      SUM(CASE WHEN abstract IS NOT NULL AND abstract != ''
                               THEN 1 ELSE 0 END) AS with_abstract
                 FROM paper WHERE conference_id = ? AND year = ?""",
            (conf_id, year)).fetchone()
        item_stats = conn.execute(
            """SELECT i.status, i.fail_reason, COUNT(*) AS c
                 FROM crawl_task_item i
                 JOIN crawl_task t ON t.id = i.task_id
                WHERE t.task_id = ?
                GROUP BY i.status, i.fail_reason
                ORDER BY c DESC""",
            (task_id := task["task_id"],)).fetchall()
        staged_abstract = conn.execute(
            """SELECT SUM(CASE WHEN json_extract(i.parsed_json, '$.paper.abstract')
                                   IS NOT NULL
                                  AND json_extract(i.parsed_json, '$.paper.abstract') != ''
                               THEN 1 ELSE 0 END) AS c
                 FROM crawl_task_item i JOIN crawl_task t ON t.id = i.task_id
                WHERE t.task_id = ? AND i.status = 'success'""",
            (task_id,)).fetchone()
    finally:
        conn.close()

    fail_dist = {r["status"] + (":" + (r["fail_reason"] or "-")): r["c"]
                 for r in item_stats}
    return {
        "task_id": task_id,
        "task_status": task["status"],
        "task_counters": {k: task[k] for k in ("total", "finished", "success",
                                               "failed", "skipped")},
        "papers": papers or 0,
        "papers_with_abstract_db": with_abstract or 0,
        "papers_with_abstract_staged": staged_abstract["c"] if staged_abstract else 0,
        "item_status_distribution": fail_dist,
    }


def main():
    # 0. 日历核对：三个单元都必须在 /crawl/units 里
    calendar = api("GET", "/crawl/units")["data"]
    available = {(u["conference_code"], u["year"]): u for u in calendar["units"]}
    for unit in UNITS:
        if unit not in available:
            raise SystemExit(f"{unit} 不在 /crawl/units 日历里，中止")

    # 历史任务：该届已有跑完的任务就不再重爬（重复 import 会开新任务）
    done_units = set()
    for t in api("GET", "/tasks?page=1&page_size=100")["data"]["list"]:
        if t["status"] == "done":
            done_units.add((t["conference_code"], t["year"]))

    results = {}
    for code, year in UNITS:
        info = available[(code, year)]
        scale = (f"实测 {info['expected_papers']} 篇" if info["papers_measured"]
                 else f"估 {info['est_papers_min']}–{info['est_papers_max']} 篇")
        log(f"=== 处理 {code} {year}（{scale}）===")

        if (code, year) in done_units:
            log("  该届已有跑完的任务，跳过（避免重复爬取）")
            continue

        started = time.time()
        task = _submit_or_adopt(code, year)
        log(f"  task_id={task['task_id']}（status={task['status']}），开始轮询")

        task = wait_terminal(task["task_id"])
        mins = round((time.time() - started) / 60, 1)
        log(f"=== {code} {year} 结束：{task['status']}，"
            f"成功 {task['success']} / 失败 {task['failed']}，用时 {mins} 分钟 ===")

        report = verify(code, year, task)
        results[f"{code} {year}"] = report
        log("  验证：" + json.dumps(report, ensure_ascii=False))

    log("=== 全部完成，汇总 ===")
    log(json.dumps(results, ensure_ascii=False, indent=2))


def _submit_or_adopt(code, year):
    """提交该届导入；409（已有活跃任务占着同一届）则收养那个任务。

    收养的场景：上次运行留下的 paused 任务（继续跑，不重复消耗配额），
    或别的客户端刚提交的 running 任务（接上轮询即可，串行由它继续保证）。
    """
    try:
        return api("POST", "/papers/import", json={
            "type": "unit", "conference_code": code, "year": year,
            "auto_commit": True,
        })["data"]
    except RuntimeError as exc:
        message = str(exc)
        if "409" not in message:
            raise
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                      message)
        if not m:
            raise
        task_id = m.group(0)
        task = api("GET", f"/tasks/{task_id}")["data"]
        if task["status"] == "paused":
            log(f"  收养 paused 任务 {task_id}，续跑剩余 "
                f"{task['total'] - task['finished']} 条")
            api("POST", f"/tasks/{task_id}/resume")
        else:
            log(f"  收养已在跑的任务 {task_id}（status={task['status']}）")
        return task


if __name__ == "__main__":
    sys.exit(main())
