"""关键词图谱（功能4）—— 节点准入、共现边、scope 隔离、相关论文分页。

语料直接落库构造。DF 门槛（GRAPH_KEYWORD_MIN_DF）按测试需要临时调低
到 4，专门覆盖「DF=4 的词卡在默认 5 之下、调阈值后准入」的边界。
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


@pytest.fixture()
def graph_db(app, db):
    """6 篇 CVPR 2024：p1–p4 alpha+beta（共现 4 次），p5–p6 只有 alpha；
    另有 gamma 只在 p6（DF=1，必被门槛挡掉）。"""
    ids = [_paper(db, "CVPR", 2024) for _ in range(6)]
    for pid in ids[:4]:
        _link(db, pid, "alpha")
        _link(db, pid, "beta")
    for pid in ids[4:]:
        _link(db, pid, "alpha")
    _link(db, ids[5], "gamma")
    with app.app_context():
        rebuild_hot_stats()
    return app


def test_节点按热度排序_DF门槛生效(graph_db, client):
    graph_db.config["GRAPH_KEYWORD_MIN_DF"] = 4     # alpha(6) 过、beta(4) 过、gamma(1) 挡
    data = client.get("/api/v1/graph/keywords",
                      query_string={"year": 2024, "conference": "CVPR"}) \
        .get_json()["data"]
    names = [n["name"] for n in data["nodes"]]
    assert names == ["alpha", "beta"]               # 按热度降序（alpha 频次更高）
    assert all(n["df"] >= 4 for n in data["nodes"])
    assert data["nodes"][0]["heat_norm"] == 100.0


def test_共现边_权重是同篇论文数(graph_db, db, client):
    graph_db.config["GRAPH_KEYWORD_MIN_DF"] = 4
    data = client.get("/api/v1/graph/keywords",
                      query_string={"year": 2024, "conference": "CVPR"}) \
        .get_json()["data"]
    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert {edge["source"], edge["target"]} == {
        db.execute("SELECT id FROM keyword WHERE name='alpha'").fetchone()["id"],
        db.execute("SELECT id FROM keyword WHERE name='beta'").fetchone()["id"]}
    assert edge["weight"] == 4                      # p1–p4 四篇同现


def test_默认门槛5_把DF4的词挡在图谱外(graph_db, client):
    data = client.get("/api/v1/graph/keywords",
                      query_string={"year": 2024, "conference": "CVPR"}) \
        .get_json()["data"]
    assert [n["name"] for n in data["nodes"]] == ["alpha"]   # beta DF=4 < 5
    assert data["edges"] == []                               # 单节点无边


def test_n限制与scope隔离(graph_db, client):
    graph_db.config["GRAPH_KEYWORD_MIN_DF"] = 4
    data = client.get("/api/v1/graph/keywords",
                      query_string={"year": 2024, "conference": "CVPR", "n": 1}) \
        .get_json()["data"]
    assert [n["name"] for n in data["nodes"]] == ["alpha"]
    assert data["edges"] == []                       # beta 被 n 截掉，无边
    # 2023 scope 无任何统计 → 空节点
    empty = client.get("/api/v1/graph/keywords",
                       query_string={"year": 2023, "conference": "CVPR"}) \
        .get_json()["data"]
    assert empty["nodes"] == []
    assert client.get("/api/v1/graph/keywords",
                      query_string={"conference": "NIPS"}).status_code == 400


def test_相关论文分页与404(graph_db, db, client):
    alpha_id = db.execute("SELECT id FROM keyword WHERE name='alpha'") \
        .fetchone()["id"]
    data = client.get(f"/api/v1/graph/keywords/{alpha_id}/papers",
                      query_string={"page": 1, "page_size": 4}).get_json()["data"]
    assert data["total"] == 6
    assert len(data["list"]) == 4
    assert data["list"][0]["year"] == 2024

    page2 = client.get(f"/api/v1/graph/keywords/{alpha_id}/papers",
                       query_string={"page": 2, "page_size": 4}) \
        .get_json()["data"]
    assert len(page2["list"]) == 2

    assert client.get("/api/v1/graph/keywords/999999/papers").status_code == 404
