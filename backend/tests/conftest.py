"""pytest 公共装置。

测试默认**不联网**：抓取器被替换成读本地 fixture 的假实现，
所以用例是确定性的、秒级的。真实站点的冒烟测试见 test_live_crawl.py，
它默认跳过，需要显式开 CRAWL_LIVE=1。
"""
import os
import sqlite3
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

from app import create_app            # noqa: E402
from config import Config             # noqa: E402
from crawl import service             # noqa: E402


def fixture(name):
    """读一个 HTML 样例文件。"""
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class TestConfig(Config):
    TESTING = True
    # 测试不等待真实的 0.5–1s 间隔；限速本身在 test_fetcher 里单独验证
    CRAWL_MIN_INTERVAL = 0.0
    CRAWL_MAX_INTERVAL = 0.0
    CRAWL_INDEX_CACHE_TTL = 300


@pytest.fixture()
def app(tmp_path):
    """每个用例一个全新的库，避免用例之间互相污染。"""
    db_path = str(tmp_path / "test.db")
    TestConfig.DB_PATH = db_path

    with open(Config.SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    application = create_app(TestConfig)
    service.reset_fetcher()
    service.clear_index_cache()
    yield application
    service.reset_fetcher()
    service.clear_index_cache()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    """直连测试库，用来断言落库结果。"""
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
