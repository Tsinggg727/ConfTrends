"""抓取任务的持久化 —— crawl_task / crawl_task_item / paper。

独立成一层的原因：这三个表的读写散在流程里会把编排逻辑淹掉，
而且任务进度、断点、失败重试都依赖它们的字段语义稳定。

所有函数都要求调用方已经在 Flask app context 里（db.py 用 flask.g 持有连接）。
"""
import json
import uuid

from db import execute, query_all, query_one


def _now():
    # 统一走 SQLite 的 CURRENT_TIMESTAMP，避免 Python 本地时区混进库
    return query_one("SELECT CURRENT_TIMESTAMP AS t")["t"]


# ---------------------------------------------------------------
# conference
# ---------------------------------------------------------------
def conference_info(code):
    """取会议的 id / code / name；会议表没种子数据时返回 None。"""
    row = query_one("SELECT id, code, name FROM conference WHERE code = ?", (code,))
    return dict(row) if row else None


# ---------------------------------------------------------------
# crawl_task
# ---------------------------------------------------------------
_TASK_FIELDS = {
    "status", "stage", "total", "finished", "success", "failed",
    "skipped", "cursor", "started_at", "finished_at",
}


def create_task(task_type, conference_code, year, auto_commit, total):
    tid = str(uuid.uuid4())
    execute(
        """INSERT INTO crawl_task
             (task_id, type, conference_code, year, auto_commit, status, stage,
              total, finished, success, failed, skipped, cursor, started_at)
           VALUES (?, ?, ?, ?, ?, 'running', 'discover', ?, 0, 0, 0, 0, 0, CURRENT_TIMESTAMP)""",
        (tid, task_type, conference_code, year, 1 if auto_commit else 0, total),
    )
    row = query_one("SELECT * FROM crawl_task WHERE task_id = ?", (tid,))
    return dict(row)


def update_task(task_id, **fields):
    """按字段名白名单更新任务，避免拼出意外的 SQL。"""
    bad = set(fields) - _TASK_FIELDS
    if bad:
        raise ValueError(f"crawl_task 没有这些字段：{sorted(bad)}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    execute(
        f"UPDATE crawl_task SET {sets} WHERE task_id = ?",
        list(fields.values()) + [task_id],
    )


def get_task(task_id):
    row = query_one("SELECT * FROM crawl_task WHERE task_id = ?", (task_id,))
    return dict(row) if row else None


def finish_task(task_id, *, status="done", stage=None, success=0, failed=0,
                skipped=0, finished=1, cursor=None):
    update_task(
        task_id,
        status=status,
        stage=stage or "commit",
        total=finished,
        finished=finished,
        success=success,
        failed=failed,
        skipped=skipped,
        cursor=finished if cursor is None else cursor,
        finished_at=_now(),
    )


# ---------------------------------------------------------------
# crawl_task_item
# ---------------------------------------------------------------
def create_item(task_row_id, seq, input_title):
    return execute(
        """INSERT INTO crawl_task_item
             (task_id, seq, input_title, status, retry_count, created_at)
           VALUES (?, ?, ?, 'pending', 0, CURRENT_TIMESTAMP)""",
        (task_row_id, seq, input_title),
    )


def finish_item(item_id, status, *, paper_id=None, fail_reason=None,
                detail_url=None, pdf_url=None, parsed=None):
    """落定一条明细。

    parsed 会序列化成 parsed_json —— 暂存模式（auto_commit=false）下
    它是「用户点全部入库」时唯一的数据来源，所以必须写全。
    """
    execute(
        """UPDATE crawl_task_item
              SET status = ?, paper_id = ?, fail_reason = ?,
                  detail_url = COALESCE(?, detail_url),
                  pdf_url    = COALESCE(?, pdf_url),
                  parsed_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?""",
        (
            status,
            paper_id,
            fail_reason,
            detail_url,
            pdf_url,
            json.dumps(parsed, ensure_ascii=False) if parsed is not None else None,
            item_id,
        ),
    )


def get_item(item_id):
    row = query_one("SELECT * FROM crawl_task_item WHERE id = ?", (item_id,))
    if not row:
        return None
    d = dict(row)
    if d.get("parsed_json"):
        try:
            d["parsed"] = json.loads(d["parsed_json"])
        except (ValueError, TypeError):
            d["parsed"] = None
    return d


def list_items(task_row_id):
    return [dict(r) for r in query_all(
        "SELECT * FROM crawl_task_item WHERE task_id = ? ORDER BY seq", (task_row_id,)
    )]


# ---------------------------------------------------------------
# paper
# ---------------------------------------------------------------
def upsert_paper(p):
    """按 title_key 入库，返回 (paper_id, action)。

    对应设计文档 §1.4 阶段六的两种结果：
      inserted —— 新论文
      updated  —— 已存在，但本次补全到了新字段（摘要 / DOI / PDF）
      skipped  —— 已存在且没有新东西
    """
    row = query_one(
        "SELECT id, abstract, doi, pdf_url, authors FROM paper WHERE title_key = ?",
        (p["title_key"],),
    )

    if row is None:
        pid = execute(
            """INSERT INTO paper
                 (title, title_key, conference_id, year, abstract, authors, url,
                  pdf_url, doi, s2_paper_id, bibtex_key, venue_raw, pages,
                  source, status, enrich_status, match_score, fail_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (
                p["title"], p["title_key"], p["conference_id"], p["year"],
                p.get("abstract") or None, p.get("authors") or None,
                p.get("url") or None, p.get("pdf_url") or None, p.get("doi") or None,
                p.get("s2_paper_id") or None, p.get("bibtex_key") or None,
                p.get("venue_raw") or None, p.get("pages") or None,
                p.get("source") or "manual", p.get("enrich_status") or "pending",
                p.get("match_score"), p.get("fail_reason") or None,
            ),
        )
        return pid, "inserted"

    # 已存在：只在「真的补到了新内容」时更新，避免无意义地刷 updated_at
    patches = {}
    if p.get("abstract") and not row["abstract"]:
        patches["abstract"] = p["abstract"]
    if p.get("doi") and not row["doi"]:
        patches["doi"] = p["doi"]
    if p.get("pdf_url") and not row["pdf_url"]:
        patches["pdf_url"] = p["pdf_url"]
    if p.get("authors") and not row["authors"]:
        patches["authors"] = p["authors"]

    if not patches:
        return row["id"], "skipped"

    patches["enrich_status"] = p.get("enrich_status") or "enriched"
    patches["fail_reason"] = p.get("fail_reason")
    sets = ", ".join(f"{k} = ?" for k in patches)
    execute(
        f"UPDATE paper SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        list(patches.values()) + [row["id"]],
    )
    return row["id"], "updated"
