"""会议接口 —— GET /conferences、GET /conferences/{code}（系统设计 §3.2）。"""
import sqlite3

import pytest


@pytest.fixture()
def db(app):
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_返回三大会议_字段齐全(app, client):
    data = client.get("/api/v1/conferences").get_json()["data"]
    assert [r["code"] for r in data] == ["CVPR", "ICCV", "ECCV"]
    for r in data:
        # 关于页卡片依赖的文案字段全部非空 —— 空了页面会开天窗
        assert r["name"] and r["full_name"] and r["intro"]
        assert r["cycle"] and r["scale"] and r["official_url"]


def test_单个会议与404(client):
    row = client.get("/api/v1/conferences/CVPR").get_json()["data"]
    assert row["code"] == "CVPR" and row["full_name"]
    assert client.get("/api/v1/conferences/nips").status_code == 404
