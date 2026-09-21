"""论文接口：/api/v1/papers/* —— 功能2「论文列表管理」（原型③）。

    GET    /papers                列表（精确/模糊检索 + 关键词/会议/年份筛选 + 分页）
    GET    /papers/<id>           详情（含关键词列表）
    POST   /papers                手工新增（source='manual'）
    PUT    /papers/<id>           编辑（改题目会重算 title_key）
    DELETE /papers/<id>           软删除（status='deleted'，可恢复）
    POST   /papers/<id>/restore   恢复

「联网爬取兜底」不在本模块做隐式副作用：列表查不到时，前端空态给出
[🌐 联网爬取并返回] 按钮，显式调用功能1 的 POST /papers/crawl
（auto_commit=true），返回体本来就带摘要/关键词/原文链接 —— GET 上做
"查不到就顺手去爬" 的副作用既违反语义，也可能被轮询/预取放大成流量事故。

编辑与删除走 4xx：和任务接口同一个取舍 —— 参数错/不存在/状态冲突是
真正的客户端错误；「查无此文」类业务结果只出现在搜索结果里。
"""
from flask import Blueprint, request

from crawl.textutil import normalize_title
from crawl.units import CONFERENCE_CODES
from db import execute, execute_many, query_all, query_one
from utils.pagination import paginated, parse_pagination
from utils.response import fail, ok

bp = Blueprint("papers", __name__)

# 列表项统一走这个 SELECT，避免各处字段不一致。
# 关键词用 GROUP_CONCAT 一次带出，列表页不用为每行再发一次请求。
BASE_SELECT = """
    SELECT p.id,
           p.title,
           p.year,
           p.abstract,
           p.url,
           p.source,
           p.enrich_status,
           (SELECT GROUP_CONCAT(k.name, ',')
              FROM paper_keyword pk
              JOIN keyword k ON k.id = pk.keyword_id
             WHERE pk.paper_id = p.id) AS keywords_csv,
           c.code AS conference_code,
           c.name AS conference_name
      FROM paper p
      LEFT JOIN conference c ON c.id = p.conference_id
"""

# 手工新增/编辑允许改动的字段（白名单防意外写库）
_EDITABLE = ("title", "authors", "year", "abstract", "url", "pdf_url", "doi")


def _keywords(csv_value):
    return csv_value.split(",") if csv_value else []


def _build_filters(args):
    """把 query 参数翻译成 WHERE 子句。

    检索模式（对应列表页 [精确 ▾] 切换）：
      exact —— 仅在题目中匹配（按完整题目的子串）
      fuzzy —— 题目 + 关键词（默认）
    """
    where = ["p.status = 'active'"]
    params = []

    q = (args.get("q") or "").strip()
    mode = (args.get("mode") or "fuzzy").strip()

    if q:
        if mode == "exact":
            where.append("p.title LIKE ?")
            params.append(f"%{q}%")
        else:
            where.append("""(
                p.title LIKE ?
                OR EXISTS (
                    SELECT 1 FROM paper_keyword pk
                      JOIN keyword k ON k.id = pk.keyword_id
                     WHERE pk.paper_id = p.id AND k.name LIKE ?
                )
            )""")
            params += [f"%{q}%", f"%{q}%"]

    # 首页 Top10 / 详情页关键词标签跳转过来时带的关键词过滤
    keyword = (args.get("keyword") or "").strip()
    if keyword:
        where.append("""EXISTS (
            SELECT 1 FROM paper_keyword pk
              JOIN keyword k ON k.id = pk.keyword_id
             WHERE pk.paper_id = p.id AND k.name = ?
        )""")
        params.append(keyword)

    conferences = [c for c in args.getlist("conference") if c]
    if conferences:
        where.append(f"c.code IN ({','.join('?' * len(conferences))})")
        params += conferences

    years = [y for y in args.getlist("year", type=int) if y]
    if years:
        where.append(f"p.year IN ({','.join('?' * len(years))})")
        params += years

    return " WHERE " + " AND ".join(where), params


@bp.get("/papers")
def list_papers():
    page, page_size = parse_pagination(request.args)
    where_sql, params = _build_filters(request.args)

    total = query_one(
        f"""SELECT COUNT(*) AS c FROM paper p
              LEFT JOIN conference c ON c.id = p.conference_id
            {where_sql}""",
        params,
    )["c"]

    rows = query_all(
        f"""{BASE_SELECT}
            {where_sql}
            ORDER BY p.year DESC, p.id DESC
            LIMIT ? OFFSET ?""",
        params + [page_size, (page - 1) * page_size],
    )

    items = []
    for r in rows:
        item = dict(r)
        item["conference"] = {
            "code": r["conference_code"],
            "name": r["conference_name"],
        }
        item.pop("conference_code")
        item.pop("conference_name")
        item["keywords"] = _keywords(item.pop("keywords_csv"))
        items.append(item)

    return ok(paginated(items, total, page, page_size))


# ---------------------------------------------------------------
# 详情 / 新增 / 编辑 / 软删除 / 恢复
# ---------------------------------------------------------------
@bp.get("/papers/<int:paper_id>")
def get_paper(paper_id):
    row = query_one(f"{BASE_SELECT} WHERE p.id = ? AND p.status = 'active'",
                    (paper_id,))
    if row is None:
        return fail(404, "论文不存在"), 404

    paper = dict(row)
    paper["conference"] = {"code": row["conference_code"],
                           "name": row["conference_name"]}
    paper.pop("conference_code")
    paper.pop("conference_name")
    paper["keywords"] = _keywords(paper.pop("keywords_csv"))
    return ok(paper)


def _resolve_conference(payload):
    """conference_code → conference_id；给了不存在的 code 是参数错误。
    返回 id，或 (response, 400) 由调用方直接 return。"""
    code = (payload.get("conference_code") or "").strip().upper()
    if not code:
        return None
    row = query_one("SELECT id FROM conference WHERE code = ?", (code,))
    if row is None:
        return fail(400, f"会议 {code} 不在系统内（CVPR / ICCV / ECCV）"), 400
    return row["id"]


def _validate_year(value):
    from flask import current_app
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return fail(400, "year 必须是整数"), 400
    cfg = current_app.config
    if not (cfg["YEAR_MIN"] <= year <= cfg["YEAR_MAX"]):
        return fail(400, f"year 必须在 {cfg['YEAR_MIN']}–{cfg['YEAR_MAX']} 之间"), 400
    return year


@bp.post("/papers")
def create_paper():
    """手工新增（source='manual'）—— 列表页「新增」弹窗的后端。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return fail(400, "请求体必须是 JSON 对象"), 400

    title = (payload.get("title") or "").strip()
    if not title:
        return fail(400, "title 不能为空"), 400
    if len(title) > 500:
        return fail(400, "title 过长（上限 500 字符）"), 400

    year = _validate_year(payload.get("year"))
    if isinstance(year, tuple):
        return year
    conference_id = _resolve_conference(payload)
    if isinstance(conference_id, tuple):
        return conference_id

    title_key = normalize_title(title)
    if query_one("SELECT id FROM paper WHERE title_key = ?", (title_key,)):
        return fail(409, "已存在同题论文（按归一化题目判重）"), 409

    paper_id = execute(
        """INSERT INTO paper
             (title, title_key, conference_id, year, abstract, authors,
              url, pdf_url, doi, source, status, enrich_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', 'active', 'pending')""",
        (title, title_key, conference_id, year,
         (payload.get("abstract") or "").strip() or None,
         (payload.get("authors") or "").strip() or None,
         (payload.get("url") or "").strip() or None,
         (payload.get("pdf_url") or "").strip() or None,
         (payload.get("doi") or "").strip() or None),
    )
    return ok({"id": paper_id}, message="已新增论文"), 200


@bp.put("/papers/<int:paper_id>")
def update_paper(paper_id):
    row = query_one("SELECT id, title, title_key FROM paper WHERE id = ?",
                    (paper_id,))
    if row is None:
        return fail(404, "论文不存在"), 404
    if query_one("SELECT status FROM paper WHERE id = ? AND status = 'deleted'",
                 (paper_id,)):
        return fail(409, "论文已删除，请先恢复再编辑"), 409

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return fail(400, "请求体必须是 JSON 对象"), 400

    sets, params = [], []

    if "title" in payload:
        title = (payload.get("title") or "").strip()
        if not title:
            return fail(400, "title 不能为空"), 400
        if len(title) > 500:
            return fail(400, "title 过长（上限 500 字符）"), 400
        if title != row["title"]:
            title_key = normalize_title(title)
            clash = query_one(
                "SELECT id FROM paper WHERE title_key = ? AND id != ?",
                (title_key, paper_id))
            if clash:
                return fail(409, "已存在同题论文（按归一化题目判重）"), 409
            sets += ["title = ?", "title_key = ?"]
            params += [title, title_key]

    if "year" in payload:
        year = _validate_year(payload.get("year"))
        if isinstance(year, tuple):
            return year
        sets.append("year = ?")
        params.append(year)

    if "conference_code" in payload:
        conference_id = _resolve_conference(payload)
        if isinstance(conference_id, tuple):
            return conference_id
        sets.append("conference_id = ?")
        params.append(conference_id)

    for field in ("authors", "abstract", "url", "pdf_url", "doi"):
        if field in payload:
            sets.append(f"{field} = ?")
            params.append((payload.get(field) or "").strip() or None)

    if sets:
        sets.append("updated_at = CURRENT_TIMESTAMP")
        execute(f"UPDATE paper SET {', '.join(sets)} WHERE id = ?",
                params + [paper_id])

    return ok({"id": paper_id}, message="已保存"), 200


@bp.delete("/papers/<int:paper_id>")
def delete_paper(paper_id):
    """软删除：热词统计、历史任务里的引用都还在，恢复即可找回。"""
    row = query_one("SELECT status FROM paper WHERE id = ?", (paper_id,))
    if row is None:
        return fail(404, "论文不存在"), 404
    if row["status"] == "deleted":
        return fail(409, "论文已经在回收站里，无需重复删除"), 409

    execute("UPDATE paper SET status = 'deleted', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ?", (paper_id,))
    return ok({"id": paper_id, "status": "deleted"}, message="已删除（可恢复）"), 200


@bp.post("/papers/<int:paper_id>/restore")
def restore_paper(paper_id):
    row = query_one("SELECT status FROM paper WHERE id = ?", (paper_id,))
    if row is None:
        return fail(404, "论文不存在"), 404
    if row["status"] == "active":
        return fail(409, "论文未删除，无需恢复"), 409

    execute("UPDATE paper SET status = 'active', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ?", (paper_id,))
    return ok({"id": paper_id, "status": "active"}, message="已恢复"), 200


@bp.post("/papers/batch-delete")
def batch_delete_papers():
    """按会议 / 年份批量软删除（status='deleted'，可逐篇恢复）。

    至少指定 conference_code 或 year 之一，防止全表误删；
    只作用于 status='active' 的论文，返回删除数量。
    """
    payload = request.get_json(silent=True) or {}
    code = (payload.get("conference_code") or "").strip().upper()
    raw_year = payload.get("year")

    year = None
    if raw_year not in (None, ""):
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            return fail(400, "year 必须是整数"), 400
    if not code and year is None:
        return fail(400, "至少指定 conference_code 或 year 之一"), 400
    if code and code not in CONFERENCE_CODES:
        return fail(400, f"conference_code 必须是 {' / '.join(CONFERENCE_CODES)} 之一"), 400

    where = ["p.status = 'active'"]
    params = []
    if code:
        where.append("c.code = ?")
        params.append(code)
    if year is not None:
        where.append("p.year = ?")
        params.append(year)
    clause = " AND ".join(where)

    n = query_one(
        f"""SELECT COUNT(*) AS c FROM paper p
              LEFT JOIN conference c ON c.id = p.conference_id
             WHERE {clause}""",
        params,
    )["c"]
    if n == 0:
        return fail(404, "没有符合条件的论文"), 404

    ids = [r["id"] for r in query_all(
        f"""SELECT p.id FROM paper p
              LEFT JOIN conference c ON c.id = p.conference_id
             WHERE {clause}""",
        params,
    )]
    execute_many(
        "UPDATE paper SET status = 'deleted', updated_at = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        [(i,) for i in ids],
    )
    return ok({"deleted": n}, message=f"已批量软删除 {n} 篇论文（可逐篇恢复）")
