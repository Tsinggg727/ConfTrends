"""热词统计接口 —— 功能3「Top10 热门方向」与功能5「热度走势对比」。

    GET  /api/v1/stats/top?year=&conference=&n=     Top N 热词榜（热度降序）
    GET  /api/v1/stats/trend?keywords=&from=&to=&conferences=
                                                    热词逐年热度（走势页数据源）
    POST /api/v1/stats/rebuild                      全量重算 hot_keyword_stat

`/stats/top` 的 DF 门槛：与 keywords.top_keywords(min_df=STATS_KEYWORD_MIN_DF)
同一口径 —— 只有全局 DF≥3 的关键词有上榜资格（评估报告方案A），用子查询
实现，避免把几千个 id 拼进 IN 列表。conference 缺省 = 三大会议汇总
（hot_keyword_stat.conference_id IS NULL）。

`/stats/trend` 的 data 保留 conference 维度（§4：tooltip 要显示
「年份 / 会议 / 热词 / 热度」），同一关键词一年的多个会议数据由前端
聚合画线。
"""
from flask import Blueprint, current_app, request

from crawl.units import CONFERENCE_CODES
from db import query_all, query_one
from hot_stats import rebuild_hot_stats
from utils.response import fail, ok

bp = Blueprint("stats", __name__)

DEFAULT_TOP_N = 10
MAX_TOP_N = 50


@bp.get("/stats/top")
def stats_top():
    """Top N 热词榜：热度 = 词频 × 年份增长率（系统设计 §2.5）。

    参数：
        year        统计年份，缺省 = 表里最新一年
        conference  CVPR / ICCV / ECCV，缺省 = 三大会议汇总
        n           榜单长度，缺省 10，上限 50
    """
    years = [r["year"] for r in query_all(
        "SELECT DISTINCT year FROM hot_keyword_stat ORDER BY year DESC")]

    raw_year = (request.args.get("year") or "").strip()
    if raw_year and not raw_year.isdigit():
        return fail(400, "year 必须是整数"), 400
    year = int(raw_year) if raw_year else (years[0] if years else None)

    conf_code = (request.args.get("conference") or "").strip().upper()
    if conf_code and conf_code not in CONFERENCE_CODES:
        return fail(400, f"conference 必须是 {' / '.join(CONFERENCE_CODES)} 之一"), 400

    raw_n = (request.args.get("n") or "").strip()
    if raw_n and not raw_n.isdigit():
        return fail(400, "n 必须是整数"), 400
    n = min(max(int(raw_n), 1), MAX_TOP_N) if raw_n else DEFAULT_TOP_N

    if year is None:
        # 统计表还是空的（没跑过 /stats/rebuild）：给前端明确的空态信号
        return ok({"year": None, "conference": conf_code or None, "n": n,
                   "years": [], "list": []})

    min_df = current_app.config["STATS_KEYWORD_MIN_DF"]
    # conference 参数是 code，统计行存的是 conference_id —— 先换算
    conference_id = None
    if conf_code:
        row = query_one("SELECT id FROM conference WHERE code = ?", (conf_code,))
        conference_id = row["id"] if row else None
    rows = query_all(
        """SELECT s.keyword_id, k.name, s.freq, s.prev_freq, s.growth_rate,
                  s.heat, s.heat_norm, s.rank
             FROM hot_keyword_stat s JOIN keyword k ON k.id = s.keyword_id
            WHERE s.year = ?
              AND s.conference_id IS ?
              AND s.keyword_id IN (
                    SELECT keyword_id FROM paper_keyword
                    GROUP BY keyword_id HAVING COUNT(*) >= ?)
            ORDER BY s.rank
            LIMIT ?""",
        (year, conference_id, min_df, n),
    )

    return ok({
        "year": year,
        "conference": conf_code or None,
        "n": n,
        "years": years,
        "list": [dict(r) for r in rows],
    })


@bp.post("/stats/rebuild")
def stats_rebuild():
    """全量重算 hot_keyword_stat（系统设计 §4：论文入库/删除后调用）。

    同步执行：全库 58k 条关联的聚合 + 重写在 1–2s 量级，不值得为它起线程。
    """
    counts = rebuild_hot_stats()
    return ok(counts, message=(
        f"热词统计已重算：{counts['rows']} 行、{counts['scopes']} 个口径分区、"
        f"{counts['keywords_with_stats']} 个关键词，耗时 {counts['elapsed_sec']}s"))


# ---------------------------------------------------------------
# 热度走势（功能5）
# ---------------------------------------------------------------
DEFAULT_TREND_N = 10
MAX_TREND_N = 30
TREND_PALETTE_MAX = 10                     # 前端调色板容量，默认选中词数与之对齐


@bp.get("/stats/trend")
def stats_trend():
    """热词逐年热度（走势页数据源，系统设计 §4 /stats/trend）。

    参数：
        keywords     逗号分隔的 keyword id；缺省 = 范围内总热度最高的
                     top_n 个词（单会议 + 汇总口径合并计）
        from / to    年份窗口，缺省 = 表里最小 / 最大年
        conferences  逗号分隔的会议 code，缺省 = 三大会议全部
        top_n        缺省选词数，上限 30

    data 保留 conference 维度：同一关键词一年可能有多行（每会议一行），
    前端画线时按年聚合、tooltip 展示会议明细。
    """
    years = sorted({r["year"] for r in query_all(
        "SELECT DISTINCT year FROM hot_keyword_stat")})

    def _parse_int_list(raw, what):
        if not (raw or "").strip():
            return None
        items = []
        for part in raw.split(","):
            part = part.strip()
            if not part.isdigit():
                return False               # 参数错哨兵
            items.append(int(part))
        return items

    keywords_param = _parse_int_list(request.args.get("keywords"), "keywords")
    if keywords_param is False:
        return fail(400, "keywords 必须是逗号分隔的整数"), 400

    conferences = [c.strip().upper()
                   for c in (request.args.get("conferences") or "").split(",")
                   if c.strip()]
    bad = [c for c in conferences if c not in CONFERENCE_CODES]
    if bad:
        return fail(400, f"conference 只能是 {' / '.join(CONFERENCE_CODES)}"), 400

    if not years:
        return ok({"from": None, "to": None, "conferences": conferences,
                   "years": [], "series": []})

    year_from = request.args.get("from", type=int)
    year_to = request.args.get("to", type=int)
    year_from = year_from or years[0]
    year_to = year_to or years[-1]
    if year_from > year_to:
        return fail(400, "from 不能大于 to"), 400
    window = [y for y in years if year_from <= y <= year_to]
    if not window:
        return ok({"from": year_from, "to": year_to,
                   "conferences": conferences, "years": [], "series": []})

    top_n = request.args.get("top_n", type=int) or DEFAULT_TREND_N
    top_n = min(max(top_n, 1), MAX_TREND_N)

    # scope：单会议口径（conference_id NOT NULL），conferences 过滤在 SQL
    # 里做，缺省三大会议全量
    scope_where = ["s.conference_id IS NOT NULL",
                   "s.year BETWEEN ? AND ?"]
    scope_params = [year_from, year_to]
    if conferences:
        scope_where.append(f"c.code IN ({','.join('?' * len(conferences))})")
        scope_params += conferences

    # 选词：缺省取范围内总热度最高的 top_n 个（单会议+汇总合并计热度）
    if keywords_param is not None:
        selected = keywords_param
    else:
        selected = [r["keyword_id"] for r in query_all(
            f"""SELECT s.keyword_id, SUM(s.heat) AS total_heat
                  FROM hot_keyword_stat s JOIN conference c ON c.id = s.conference_id
                 WHERE {' AND '.join(scope_where)}
                 GROUP BY s.keyword_id
                 ORDER BY total_heat DESC
                 LIMIT ?""",
            scope_params + [top_n],
        )]
    if not selected:
        return ok({"from": year_from, "to": year_to,
                   "conferences": conferences, "years": window, "series": []})

    marks = ",".join("?" * len(selected))
    rows = query_all(
        f"""SELECT s.keyword_id, k.name, s.year, c.code AS conference,
                   s.freq, s.heat, s.heat_norm
              FROM hot_keyword_stat s
              JOIN keyword k ON k.id = s.keyword_id
              JOIN conference c ON c.id = s.conference_id
             WHERE {' AND '.join(scope_where)}
               AND s.keyword_id IN ({marks})
             ORDER BY s.year""",
        scope_params + selected,
    )

    series_map = {}
    for r in rows:
        entry = series_map.setdefault(r["keyword_id"],
                                      {"keyword_id": r["keyword_id"],
                                       "name": r["name"], "data": []})
        entry["data"].append({"year": r["year"], "conference": r["conference"],
                              "freq": r["freq"], "heat": r["heat"],
                              "heat_norm": r["heat_norm"]})

    return ok({
        "from": year_from,
        "to": year_to,
        "conferences": conferences or list(CONFERENCE_CODES),
        "years": window,
        "series": list(series_map.values()),
    })
