"""论文接口：/api/v1/papers/*

骨架阶段只实现列表查询，用来验证「前端 → 代理 → Flask → SQLite」整条链路。
create / update / delete / related 随列表页开发补齐（见系统设计 §3.3）。
"""
from flask import Blueprint, request

from db import query_all, query_one
from utils.pagination import paginated, parse_pagination
from utils.response import ok

bp = Blueprint("papers", __name__)

# 列表项统一走这个 SELECT，避免各处字段不一致
BASE_SELECT = """
    SELECT p.id,
           p.title,
           p.year,
           p.url,
           p.source,
           c.code AS conference_code,
           c.name AS conference_name
      FROM paper p
      LEFT JOIN conference c ON c.id = p.conference_id
"""


def _build_filters(args):
    """把 query 参数翻译成 WHERE 子句。

    检索模式（对应列表页 [精确 ▾] 切换）：
      exact —— 仅在题目中匹配
      fuzzy —— 题目 + 关键词 + 论文编号（默认）
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
                OR CAST(p.id AS TEXT) = ?
                OR EXISTS (
                    SELECT 1 FROM paper_keyword pk
                      JOIN keyword k ON k.id = pk.keyword_id
                     WHERE pk.paper_id = p.id AND k.name LIKE ?
                )
            )""")
            params += [f"%{q}%", q, f"%{q}%"]

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
        items.append(item)

    return ok(paginated(items, total, page, page_size))
