"""关键词图谱接口 —— 功能4（原型① 的图谱区）。

    GET /api/v1/graph/keywords?year=&conference=&n=50   节点 + 共现边
        （year=total 为跨年总计口径；响应带 years 供年份下拉）
    GET /api/v1/graph/keywords/<id>/papers?page=        该词下的相关论文（分页）

口径：
    节点 = (year, conference) scope 内有热度的关键词，且全局 DF ≥
    GRAPH_KEYWORD_MIN_DF（等价于 keywords.graph_keywords(min_df=5) 的
    准入集合，这里直接调它建 DF 映射），按热度取前 n。
    边 = 两个节点关键词出现在**同一篇论文**（共现），权重 = 共现论文数，
    且只在 scope 内的论文上统计。

共现边是「同一篇论文同时出现」，不代表语义相关 —— 前端以细线低透明度
呈现，节点大小（热度）才是主视觉。
"""
from flask import Blueprint, current_app, request

from crawl import keywords as kw
from crawl.units import CONFERENCE_CODES
from db import query_all, query_one
from utils.pagination import paginated, parse_pagination
from utils.response import fail, ok

bp = Blueprint("graph", __name__)

DEFAULT_GRAPH_N = 50
MAX_GRAPH_N = 200


def _resolve_scope(args):
    """解析 year / conference：year = 具体年份或 'total'（跨年总计）；
    缺省 = 统计表最新一年。conference 缺省 = 汇总（conference_id NULL）。
    返回 (year, conference_id, conf_code, years)。
    参数不合法抛 None（由调用方转 400）。"""
    years = [r["year"] for r in query_all(
        "SELECT DISTINCT year FROM hot_keyword_stat ORDER BY year DESC")]

    raw_year = (args.get("year") or "").strip()
    if raw_year and raw_year != "total" and not raw_year.isdigit():
        return None
    if raw_year == "total":
        year = "total"
    elif raw_year.isdigit():
        year = int(raw_year)
    else:
        year = years[0] if years else None

    conf_code = (args.get("conference") or "").strip().upper()
    if conf_code and conf_code not in CONFERENCE_CODES:
        return None
    conference_id = None
    if conf_code:
        row = query_one("SELECT id FROM conference WHERE code = ?", (conf_code,))
        conference_id = row["id"] if row else None

    return year, conference_id, conf_code or None, years


@bp.get("/graph/keywords")
def keyword_graph():
    args = request.args
    scope = _resolve_scope(args)
    if scope is None:
        return fail(400, "year 必须是整数或 total；conference 必须是 "
                         f"{' / '.join(CONFERENCE_CODES)} 之一"), 400
    year, conference_id, conf_code, years = scope

    raw_n = (args.get("n") or "").strip()
    if raw_n and not raw_n.isdigit():
        return fail(400, "n 必须是整数"), 400
    n = min(max(int(raw_n), 1), MAX_GRAPH_N) if raw_n else DEFAULT_GRAPH_N

    if year is None:
        return ok({"year": None, "conference": conf_code, "n": n, "years": years,
                   "nodes": [], "edges": []})

    # DF 门槛（方案A）：全局 DF ≥ 图谱阈值才准入；DF 从 graph_keywords 的
    # 准入集合里带出，节点行里一并返回
    min_df = current_app.config["GRAPH_KEYWORD_MIN_DF"]
    df_map = {r["id"]: r["df"]
              for r in kw.graph_keywords(min_df=min_df)}

    if year == "total":
        # 跨年总计口径：各年热度加总（论文按年天然不重叠，freq 相加即总数），
        # heat_norm 在选出的节点内重新归一化
        rows = query_all(
            """SELECT s.keyword_id AS id, k.name,
                      SUM(s.freq) AS freq, SUM(s.heat) AS heat
                 FROM hot_keyword_stat s JOIN keyword k ON k.id = s.keyword_id
                WHERE s.conference_id IS ?
                GROUP BY s.keyword_id""",
            (conference_id,))
        picked = sorted((r for r in rows if r["id"] in df_map),
                        key=lambda r: (-r["heat"], -r["freq"], r["id"]))[:n]
        max_heat = (picked[0]["heat"] if picked else 0) or 1.0
        nodes = [{"id": r["id"], "name": r["name"], "df": df_map[r["id"]],
                  "freq": r["freq"], "heat": r["heat"],
                  "heat_norm": round(r["heat"] / max_heat * 100, 2)}
                 for r in picked]
    else:
        scope_rows = query_all(
            """SELECT s.keyword_id AS id, k.name, s.freq, s.heat, s.heat_norm
                 FROM hot_keyword_stat s JOIN keyword k ON k.id = s.keyword_id
                WHERE s.year = ? AND s.conference_id IS ?
                ORDER BY s.heat DESC""",
            (year, conference_id))
        nodes = [{"id": r["id"], "name": r["name"], "df": df_map[r["id"]],
                  "freq": r["freq"], "heat": r["heat"], "heat_norm": r["heat_norm"]}
                 for r in scope_rows if r["id"] in df_map][:n]

    if len(nodes) < 2:
        return ok({"year": year, "conference": conf_code, "n": n, "years": years,
                   "nodes": nodes, "edges": []})

    # 共现边：同论文同现的两个节点词；只在 scope 内的论文上统计
    ids = [nd["id"] for nd in nodes]
    marks = ",".join("?" * len(ids))
    paper_where = []
    edge_params = []
    if year != "total":                    # 总计口径不按年过滤，跨全部年份
        paper_where.append("p2.year = ?")
        edge_params.append(year)
    if conference_id is not None:
        paper_where.append("p2.conference_id = ?")
        edge_params.append(conference_id)
    paper_filter = f" WHERE {' AND '.join(paper_where)}" if paper_where else ""
    rows = query_all(
        f"""SELECT pk1.keyword_id AS source, pk2.keyword_id AS target,
                   COUNT(DISTINCT pk1.paper_id) AS weight
              FROM paper_keyword pk1
              JOIN paper_keyword pk2
                ON pk2.paper_id = pk1.paper_id AND pk2.keyword_id > pk1.keyword_id
             WHERE pk1.paper_id IN (SELECT p2.id FROM paper p2{paper_filter})
               AND pk1.keyword_id IN ({marks})
               AND pk2.keyword_id IN ({marks})
             GROUP BY pk1.keyword_id, pk2.keyword_id""",
        edge_params + ids + ids)
    # count 与 weight 同值：前端 tooltip 以 count ?? weight 兜底展示
    edges = [dict(r, count=r["weight"]) for r in rows]

    return ok({"year": year, "conference": conf_code, "n": n, "years": years,
               "nodes": nodes, "edges": edges})


@bp.get("/graph/keywords/<int:keyword_id>/papers")
def keyword_papers(keyword_id):
    """某关键词下的相关论文（分页）—— 图谱节点点击的落地数据。"""
    kw_row = query_one("SELECT id, name FROM keyword WHERE id = ?", (keyword_id,))
    if kw_row is None:
        return fail(404, "关键词不存在"), 404

    page, page_size = parse_pagination(request.args)
    where = "pk.keyword_id = ? AND p.status = 'active'"
    total = query_one(
        f"""SELECT COUNT(DISTINCT p.id) AS c
              FROM paper_keyword pk JOIN paper p ON p.id = pk.paper_id
             WHERE {where}""",
        (keyword_id,),
    )["c"]
    rows = query_all(
        f"""SELECT p.id, p.title, p.year, p.abstract, p.url, c.code AS conf
              FROM paper_keyword pk
              JOIN paper p ON p.id = pk.paper_id
              LEFT JOIN conference c ON c.id = p.conference_id
             WHERE {where}
             ORDER BY p.year DESC, p.id DESC
             LIMIT ? OFFSET ?""",
        (keyword_id, page_size, (page - 1) * page_size),
    )
    return ok(paginated([dict(r) for r in rows], total, page, page_size))
