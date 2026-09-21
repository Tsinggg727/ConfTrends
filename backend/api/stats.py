"""热词统计接口 —— 功能3「Top10 热门方向」（原型①）。

    GET  /api/v1/stats/top?year=&conference=&n=   Top N 热词榜（热度降序）
    POST /api/v1/stats/rebuild                    全量重算 hot_keyword_stat

`/stats/top` 的 DF 门槛：与 keywords.top_keywords(min_df=STATS_KEYWORD_MIN_DF)
同一口径 —— 只有全局 DF≥3 的关键词有上榜资格（评估报告方案A），用子查询
实现，避免把几千个 id 拼进 IN 列表。conference 缺省 = 三大会议汇总
（hot_keyword_stat.conference_id IS NULL）。
"""
from flask import Blueprint, current_app, request

from crawl.units import CONFERENCE_CODES
from db import query_one, query_all
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
