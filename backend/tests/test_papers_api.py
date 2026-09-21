"""论文列表管理接口 —— 功能2（原型③）。

验证列表检索（精确/模糊/关键词/分页）、详情、手工新增、编辑（title_key
重算与判重）、软删除与恢复。数据直接落库构造，不经过爬取链路 ——
论文从哪来是功能1的事，功能2只管管好库里已有的。
"""
import sqlite3

import pytest

from conftest import fixture


@pytest.fixture()
def db(app):
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed_paper(db, title, code="CVPR", year=2024, **extra):
    """插一篇论文，返回 id。title_key 用小写凑合 —— 判重口径由 API 层负责。"""
    cur = db.execute(
        """INSERT INTO paper
             (title, title_key, conference_id, year, abstract, authors,
              url, source, status, enrich_status)
           VALUES (?, ?, (SELECT id FROM conference WHERE code = ?),
                   ?, ?, ?, ?, 'cvf', 'active', 'enriched')""",
        (title, extra.get("title_key", title.lower()), code, year,
         extra.get("abstract", f"{title} 的摘要。"),
         extra.get("authors", "A. Author"),
         extra.get("url", f"https://example.com/{abs(hash(title))}")),
    )
    db.commit()
    return cur.lastrowid


def _seed_keyword(db, paper_id, name):
    db.execute("INSERT INTO keyword (name, name_key) VALUES (?, ?)",
               (name, name.lower()))
    db.execute(
        """INSERT INTO paper_keyword (paper_id, keyword_id, weight, rank)
           VALUES (?, (SELECT id FROM keyword WHERE name_key = ?), 1.0, 1)""",
        (paper_id, name.lower()))
    db.commit()


# ---------------------------------------------------------------
# 列表
# ---------------------------------------------------------------
def test_列表_默认分页与字段(app, client, db):
    _seed_paper(db, "Neural Radiance Fields")
    _seed_paper(db, "Diffusion Models Beat GANs", code="ICCV", year=2023)

    data = client.get("/api/v1/papers").get_json()["data"]
    assert data["total"] == 2 and data["page"] == 1
    row = data["list"][0]
    assert row["title"] == "Neural Radiance Fields"     # 同年按 id 倒序
    assert row["conference"]["code"] in ("CVPR", "ICCV")
    assert row["keywords"] == []


def test_列表_精确模式只搜题目(app, client, db):
    pid = _seed_paper(db, "Neural Radiance Fields")
    _seed_keyword(db, pid, "NeRF")                       # 关键词里含 NeRF

    exact = client.get("/api/v1/papers",
                       query_string={"q": "NeRF", "mode": "exact"}).get_json()["data"]
    assert exact["total"] == 0                           # 题目里没有 NeRF

    fuzzy = client.get("/api/v1/papers",
                       query_string={"q": "NeRF", "mode": "fuzzy"}).get_json()["data"]
    assert fuzzy["total"] == 1                           # 关键词命中


def test_列表_按编号检索(app, client, db):
    pid = _seed_paper(db, "Diffusion Models Beat GANs")
    data = client.get("/api/v1/papers",
                      query_string={"q": str(pid)}).get_json()["data"]
    assert data["total"] == 1


def test_列表_关键词与会议年份筛选(app, client, db):
    p1 = _seed_paper(db, "Paper One")
    _seed_keyword(db, p1, "Diffusion Model")
    _seed_paper(db, "Paper Two", code="ECCV", year=2022)

    hit = client.get("/api/v1/papers",
                     query_string={"keyword": "Diffusion Model"}).get_json()["data"]
    assert hit["total"] == 1 and hit["list"][0]["title"] == "Paper One"

    conf = client.get("/api/v1/papers",
                      query_string={"conference": "ECCV", "year": 2022}) \
        .get_json()["data"]
    assert conf["total"] == 1 and conf["list"][0]["title"] == "Paper Two"


def test_列表_软删除的不出现(app, client, db):
    _seed_paper(db, "Visible Paper")
    gone = _seed_paper(db, "Deleted Paper")
    db.execute("UPDATE paper SET status = 'deleted' WHERE id = ?", (gone,))
    db.commit()

    data = client.get("/api/v1/papers").get_json()["data"]
    assert data["total"] == 1


# ---------------------------------------------------------------
# 详情
# ---------------------------------------------------------------
def test_详情_含关键词列表(app, client, db):
    pid = _seed_paper(db, "Neural Radiance Fields")
    _seed_keyword(db, pid, "NeRF")
    _seed_keyword(db, pid, "3DGS")

    row = client.get(f"/api/v1/papers/{pid}").get_json()["data"]
    assert row["title"] == "Neural Radiance Fields"
    assert sorted(row["keywords"]) == ["3DGS", "NeRF"]
    assert row["abstract"]

    assert client.get("/api/v1/papers/999999").status_code == 404


# ---------------------------------------------------------------
# 新增 / 编辑
# ---------------------------------------------------------------
def test_新增_手工论文(app, client, db):
    resp = client.post("/api/v1/papers", json={
        "title": "Manually Added Paper", "conference_code": "CVPR",
        "year": 2024, "authors": "H. Human", "abstract": "手打的摘要",
    })
    assert resp.status_code == 200
    pid = resp.get_json()["data"]["id"]

    row = client.get(f"/api/v1/papers/{pid}").get_json()["data"]
    assert row["source"] == "manual"
    assert row["conference"]["code"] == "CVPR"
    assert db.execute("SELECT title_key FROM paper WHERE id = ?",
                      (pid,)).fetchone()["title_key"] == "manually added paper"


def test_新增_参数校验(app, client, db):
    cases = [
        ({"title": ""}, 400),                                   # 空题目
        ({"title": "x" * 501}, 400),                            # 超长
        ({"title": "No Year", "year": 1999}, 400),              # 年份越界
        ({"title": "Bad Conf", "conference_code": "NIPS"}, 400),  # 会议不存在
        ({"title": "Neural Radiance Fields", "year": "abc"}, 400),
    ]
    for payload, code in cases:
        assert client.post("/api/v1/papers", json=payload).status_code == code, payload


def test_新增_同题判重409(app, client, db):
    _seed_paper(db, "Neural Radiance Fields",
                title_key="neural radiance fields")
    resp = client.post("/api/v1/papers",
                       json={"title": "Neural  Radiance  Fields"})  # 多空格同题
    assert resp.status_code == 409


def test_编辑_改题目重算title_key(app, client, db):
    pid = _seed_paper(db, "Old Title Here")

    resp = client.put(f"/api/v1/papers/{pid}", json={
        "title": "New  Title  Here", "year": 2023, "abstract": "更新过的摘要"})
    assert resp.status_code == 200

    row = client.get(f"/api/v1/papers/{pid}").get_json()["data"]
    assert row["title"] == "New  Title  Here"           # 展示值保留原样
    assert db.execute("SELECT title_key FROM paper WHERE id = ?",
                      (pid,)).fetchone()["title_key"] == "new title here"
    assert row["year"] == 2023


def test_编辑_改成已存在的同题返回409(app, client, db):
    _seed_paper(db, "Taken Title", title_key="taken title")
    pid = _seed_paper(db, "Editable Paper")

    resp = client.put(f"/api/v1/papers/{pid}", json={"title": "Taken  Title"})
    assert resp.status_code == 409


def test_编辑_不存在404_已删除409(app, client, db):
    assert client.put("/api/v1/papers/999999",
                      json={"title": "x"}).status_code == 404

    pid = _seed_paper(db, "Deleted Paper")
    db.execute("UPDATE paper SET status = 'deleted' WHERE id = ?", (pid,))
    db.commit()
    assert client.put(f"/api/v1/papers/{pid}",
                      json={"title": "x"}).status_code == 409


# ---------------------------------------------------------------
# 软删除 / 恢复
# ---------------------------------------------------------------
def test_删除与恢复(app, client, db):
    pid = _seed_paper(db, "Recyclable Paper")

    resp = client.delete(f"/api/v1/papers/{pid}")
    assert resp.status_code == 200
    status = db.execute("SELECT status FROM paper WHERE id = ?",
                        (pid,)).fetchone()["status"]
    assert status == "deleted"                           # 软删除，行还在
    assert client.get(f"/api/v1/papers/{pid}").status_code == 404

    # 列表不出现；重复删除 409；恢复后回来
    assert client.get("/api/v1/papers").get_json()["data"]["total"] == 0
    assert client.delete(f"/api/v1/papers/{pid}").status_code == 409

    assert client.post(f"/api/v1/papers/{pid}/restore").status_code == 200
    assert client.get(f"/api/v1/papers/{pid}").status_code == 200
    assert client.post(f"/api/v1/papers/{pid}/restore").status_code == 409


def test_删除与恢复_不存在404(client):
    assert client.delete("/api/v1/papers/999999").status_code == 404
    assert client.post("/api/v1/papers/999999/restore").status_code == 404


# ---------------------------------------------------------------
# 批量删除（按会议 / 年份）
# ---------------------------------------------------------------
def _seed_conf_year(client, title, code, year):
    resp = client.post("/api/v1/papers", json={
        "title": title, "conference_code": code, "year": year})
    assert resp.status_code == 200
    return resp.get_json()["data"]["id"]


def test_批量删除_按会议年份(app, client, db):
    for i in range(3):
        _seed_conf_year(client, f"CVPR Paper {i}", "CVPR", 2024)
    for i in range(2):
        _seed_conf_year(client, f"ICCV Paper {i}", "ICCV", 2023)

    resp = client.post("/api/v1/papers/batch-delete",
                       json={"conference_code": "CVPR", "year": 2024})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["deleted"] == 3

    # CVPR 2024 全部软删除；ICCV 2023 不受影响
    left = client.get("/api/v1/papers",
                      query_string={"conference": "CVPR", "year": 2024}) \
        .get_json()["data"]["total"]
    assert left == 0
    assert client.get("/api/v1/papers",
                      query_string={"conference": "ICCV",
                                    "year": 2023}).get_json()["data"]["total"] == 2

    # 删除的论文可逐篇恢复
    pid = db.execute("SELECT id FROM paper WHERE status='deleted' LIMIT 1") \
        .fetchone()["id"]
    assert client.post(f"/api/v1/papers/{pid}/restore").status_code == 200


def test_批量删除_条件不全返回400(app, client):
    resp = client.post("/api/v1/papers/batch-delete", json={})
    assert resp.status_code == 400
    assert "至少指定" in resp.get_json()["message"]

    resp = client.post("/api/v1/papers/batch-delete",
                       json={"conference_code": "NIPS"})
    assert resp.status_code == 400


def test_批量删除_无匹配返回404(app, client):
    resp = client.post("/api/v1/papers/batch-delete",
                       json={"conference_code": "CVPR", "year": 2026})
    assert resp.status_code == 404
