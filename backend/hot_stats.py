"""热词统计 —— 功能3「Top10 热门方向」的数据底座（系统设计 §2.5）。

口径（与原型页脚「热度 = 词频 × 年份增长率」一致，公式取自系统设计 §2.5）：

    freq        = COUNT(DISTINCT paper)，按 (keyword, conference, year) 聚合
    prev_freq   = 同口径上一年（year-1）的 freq，查不到记 0
    growth_rate = (freq - prev) / max(prev, 1)；prev=0（首年/新词/双年会
                  的空档年）时按「无前值」记 0，避免 heat 被除零伪影放大
    heat        = freq × (1 + growth_rate)
    heat_norm   = heat / 同 (conference, year) 内最大 heat × 100
    rank        = 同 (conference, year) 内按 heat 降序，1 = Top1

conference_id = NULL 的行是「三大会议汇总」口径（该年全部论文），
非 NULL 是单会议口径；两套都算，榜单按查询参数二选一。

全量重算（DELETE + INSERT 一个事务）：统计行是纯派生数据，来源只有
paper_keyword，重算永远安全且幂等 —— 设计 §2.5 的「增量重算」等有
性能压力再做成按 (year, conference) 分区。
"""
import time

from db import execute, execute_many, query_all, transaction


def rebuild_hot_stats():
    """全量重算 hot_keyword_stat。返回统计 dict（接口与 CLI 共用）。"""
    started = time.time()

    # 词频聚合：单会议口径只统计挂了会议的论文；汇总口径（conference_id
    # 为 NULL 的统计行）覆盖该年全部论文，包括手工新增的未挂会议论文
    freq_rows = query_all(
        """SELECT pk.keyword_id, p.conference_id, p.year,
                  COUNT(DISTINCT pk.paper_id) AS freq
             FROM paper_keyword pk JOIN paper p ON p.id = pk.paper_id
            GROUP BY pk.keyword_id, p.conference_id, p.year""")
    per_conf = {(r["keyword_id"], r["conference_id"], r["year"]): r["freq"]
                for r in freq_rows}
    total = {}
    for r in freq_rows:
        key = (r["keyword_id"], None, r["year"])
        total[key] = total.get(key, 0) + r["freq"]
    all_freq = {**per_conf, **total}

    # 先算 heat，再按 (conference, year) scope 归一化、排名
    computed = []
    for (kid, conf, year), freq in all_freq.items():
        prev = all_freq.get((kid, conf, year - 1), 0)
        growth = (freq - prev) / max(prev, 1) if prev > 0 else 0.0
        computed.append({
            "keyword_id": kid, "conference_id": conf, "year": year,
            "freq": freq, "prev_freq": prev,
            "growth_rate": round(growth, 4),
            "heat": round(freq * (1 + growth), 4),
        })

    scopes = {}
    for row in computed:
        scopes.setdefault((row["conference_id"], row["year"]), []).append(row)
    for rows in scopes.values():
        rows.sort(key=lambda r: (-r["heat"], -r["freq"], r["keyword_id"]))
        max_heat = rows[0]["heat"] or 1.0
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
            row["heat_norm"] = round(row["heat"] / max_heat * 100, 2)

    params = [
        (r["keyword_id"], r["conference_id"], r["year"], r["freq"],
         r["prev_freq"], r["growth_rate"], r["heat"], r["heat_norm"],
         r["rank"])
        for rows in scopes.values() for r in rows
    ]
    with transaction():
        execute("DELETE FROM hot_keyword_stat", commit=False)
        execute_many(
            """INSERT INTO hot_keyword_stat
                 (keyword_id, conference_id, year, freq, prev_freq,
                  growth_rate, heat, heat_norm, rank)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            params, commit=False)

    years = sorted({r["year"] for r in computed}, reverse=True)
    return {
        "rows": len(params),
        "scopes": len(scopes),
        "years": years,
        "keywords_with_stats": len({r["keyword_id"] for r in computed}),
        "elapsed_sec": round(time.time() - started, 2),
    }
