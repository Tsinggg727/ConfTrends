"""热词统计（功能3）—— rebuild 口径 + GET /stats/top。

语料直接落库构造（paper / keyword / paper_keyword），验证系统设计 §2.5
的五条公式：freq 聚合、prev/growth、heat、heat_norm、rank，以及汇总
（conference_id NULL）与单会议两套口径、DF≥3 上榜门槛。
"""
import sqlite3

import pytest

from hot_stats import rebuild_hot_stats


@pytest.fixture()
def db(app):
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _paper(db, conf, year):
    conf_id = db.execute("SELECT id FROM conference WHERE code = ?",
                         (conf,)).fetchone()["id"] if conf else None
    n = db.execute("SELECT COUNT(*) AS c FROM paper").fetchone()["c"]
    title = f"paper {conf} {year} #{n + 1}"
    cur = db.execute(
        """INSERT INTO paper (title, title_key, conference_id, year,
                              source, status)
             VALUES (?, ?, ?, ?, 'cvf', 'active')""",
        (title, title.lower(), conf_id, year))
    db.commit()
    return cur.lastrowid


def _link(db, paper_id, name):
    db.execute(
        """INSERT INTO keyword (name, name_key) VALUES (?, ?)
           ON CONFLICT(name_key) DO NOTHING""", (name, name))
    db.execute(
        """INSERT INTO paper_keyword (paper_id, keyword_id, weight, rank)
             VALUES (?, (SELECT id FROM keyword WHERE name_key = ?), 1.0, 1)""",
        (paper_id, name))
    db.commit()


def _stat(db, name, conf, year):
    """查一行统计（conf=None 查汇总口径）。"""
    conf_id = None
    if conf is not None:
        conf_id = db.execute("SELECT id FROM conference WHERE code = ?",
                             (conf,)).fetchone()["id"]
    sql = """SELECT s.freq, s.prev_freq, s.growth_rate, s.heat, s.heat_norm,
                    s.rank, s.year, c.code AS conf
               FROM hot_keyword_stat s
               JOIN keyword k ON k.id = s.keyword_id
               LEFT JOIN conference c ON c.id = s.conference_id
              WHERE k.name_key = ? AND s.year = ? AND s.conference_id """
    sql += "IS NULL" if conf is None else "= ?"
    params = [name, year] if conf is None else [name, year, conf_id]
    row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def test_rebuild_词频_增长_热度公式(app, db):
    # diffusion：CVPR 2023 两篇（freq=2），CVPR 2024 六篇（freq=6）
    # → 2024 growth = (6-2)/2 = 2.0，heat = 6×3 = 18；2023 无前值 → heat = 2
    for _ in range(2):
        _link(db, _paper(db, "CVPR", 2023), "diffusion")
    for _ in range(6):
        _link(db, _paper(db, "CVPR", 2024), "diffusion")

    with app.app_context():
        counts = rebuild_hot_stats()
    assert counts["rows"] >= 4                      # 两套口径 × 两个年份

    s23 = _stat(db, "diffusion", "CVPR", 2023)
    s24 = _stat(db, "diffusion", "CVPR", 2024)
    assert (s23["freq"], s23["prev_freq"], s23["growth_rate"], s23["heat"]) == \
        (2, 0, 0, 2.0)
    assert (s24["freq"], s24["prev_freq"], s24["growth_rate"], s24["heat"]) == \
        (6, 2, 2.0, 18.0)


def test_rebuild_汇总口径是各会议之和(app, db):
    # nerf：CVPR 2024 两篇 + ECCV 2024 三篇 → 汇总 freq=5；单会议各自独立
    for _ in range(2):
        _link(db, _paper(db, "CVPR", 2024), "nerf")
    for _ in range(3):
        _link(db, _paper(db, "ECCV", 2024), "nerf")

    with app.app_context():
        rebuild_hot_stats()

    assert _stat(db, "nerf", "CVPR", 2024)["freq"] == 2
    assert _stat(db, "nerf", "ECCV", 2024)["freq"] == 3
    total = _stat(db, "nerf", None, 2024)
    assert total["freq"] == 5 and total["conf"] is None


def test_rebuild_heat_norm与rank按scope独立(app, db):
    # CVPR 2024 scope：diffusion heat=18 居首 → norm=100 rank=1；
    # nerf heat=2（2 篇无前值）→ norm = 2/18×100
    for _ in range(2):
        _link(db, _paper(db, "CVPR", 2023), "diffusion")
    for _ in range(6):
        _link(db, _paper(db, "CVPR", 2024), "diffusion")
    for _ in range(2):
        _link(db, _paper(db, "CVPR", 2024), "nerf")

    with app.app_context():
        rebuild_hot_stats()

    top = _stat(db, "diffusion", "CVPR", 2024)
    second = _stat(db, "nerf", "CVPR", 2024)
    assert top["rank"] == 1 and top["heat_norm"] == 100.0
    assert second["rank"] == 2
    assert second["heat_norm"] == pytest.approx(2 / 18 * 100, abs=0.01)
    # 独立 scope：CVPR 2023 里 diffusion 是唯一词 → rank 1 norm 100
    s23 = _stat(db, "diffusion", "CVPR", 2023)
    assert s23["rank"] == 1 and s23["heat_norm"] == 100.0


def test_rebuild_幂等(app, db):
    for _ in range(3):
        _link(db, _paper(db, "CVPR", 2024), "diffusion")
    with app.app_context():
        first = rebuild_hot_stats()
        second = rebuild_hot_stats()
    assert first["rows"] == second["rows"]
    assert db.execute("SELECT COUNT(*) AS c FROM hot_keyword_stat") \
        .fetchone()["c"] == first["rows"]


# ---------------------------------------------------------------
# GET /stats/top
# ---------------------------------------------------------------
@pytest.fixture()
def ranked(app, db, client):
    """造一个可控榜单：hotkw（DF=4，CVPR 2024 热度最高）、lonely（DF=1，
    热度再高也不得上榜——DF 门槛的检验点）。"""
    for _ in range(4):
        _link(db, _paper(db, "CVPR", 2024), "hotkw")
    for _ in range(2):
        _link(db, _paper(db, "CVPR", 2023), "hotkw")          # DF=6，跨年
    for _ in range(6):
        _link(db, _paper(db, "CVPR", 2024), "rare")
    _link(db, _paper(db, "CVPR", 2024), "lonely")
    for _ in range(3):
        # DF=3 恰好过门槛：检验汇总 / 单会议 scope 的隔离，而不是 DF 门槛
        _link(db, _paper(db, "ECCV", 2024), "eccvonly")
    with app.app_context():
        rebuild_hot_stats()
    return client


def test_API_top_DF门槛与排序(app, ranked):
    data = ranked.get("/api/v1/stats/top",
                      query_string={"year": 2024, "conference": "CVPR"}) \
        .get_json()["data"]
    names = [r["name"] for r in data["list"]]
    # lonely DF=1 < 3：哪怕在榜单 scope 里也无资格上榜；
    # hotkw 跨年增长（4 vs 2 → heat=8）压过无前值的 rare（heat=6）
    assert "lonely" not in names
    assert names[0] == "hotkw" and names[1] == "rare"
    assert data["list"][0]["growth_rate"] == 1.0
    assert {"name", "freq", "heat", "rank", "heat_norm"} <= set(data["list"][0])


def test_API_top_年缺省取最新_汇总缺省NULL(app, ranked):
    data = ranked.get("/api/v1/stats/top").get_json()["data"]
    assert data["year"] == 2024                        # 表里最新一年
    assert data["conference"] is None                  # 缺省 = 汇总口径
    # 汇总口径能看到 ECCV 2024 的词（单会议 CVPR 口径看不到）
    eccv = ranked.get("/api/v1/stats/top",
                      query_string={"year": 2024, "conference": "ECCV"}) \
        .get_json()["data"]
    assert any(r["name"] == "eccvonly" for r in eccv["list"])


def test_API_top_n限制与参数校验(app, ranked):
    data = ranked.get("/api/v1/stats/top",
                      query_string={"year": 2024, "n": 1}).get_json()["data"]
    assert len(data["list"]) == 1
    assert ranked.get("/api/v1/stats/top",
                      query_string={"conference": "NIPS"}).status_code == 400
    assert ranked.get("/api/v1/stats/top",
                      query_string={"year": "abcd"}).status_code == 400
    assert ranked.get("/api/v1/stats/top",
                      query_string={"year": 2019}).get_json()["data"]["list"] == []


def test_API_rebuild触发重算(app, ranked):
    before = ranked.get("/api/v1/stats/top",
                        query_string={"year": 2024}).get_json()["data"]
    resp = ranked.post("/api/v1/stats/rebuild")
    assert resp.status_code == 200
    after = ranked.get("/api/v1/stats/top",
                       query_string={"year": 2024}).get_json()["data"]
    assert [r["name"] for r in after["list"]] == \
        [r["name"] for r in before["list"]]            # 幂等：重算结果一致
