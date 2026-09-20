"""真实站点冒烟测试 —— 默认跳过。

    cd backend
    CRAWL_LIVE=1 ./.venv/Scripts/python.exe -m pytest tests/test_live_crawl.py -v -s

为什么默认跳过：
  · 会真的访问 openaccess.thecvf.com 与 www.ecva.net（索引页 5–7 MB）；
  · 站点改版或限流时它会红，但那时是**站点变了**，不是代码坏了 ——
    这类信号不该污染日常的测试结果。

它验证的是本地 fixture 验证不了的那一半：真实页面结构是否还和假设一致。
用例里的题目是实测存在的真实论文，不是编的。
"""
import os
import sqlite3

import pytest

from app import create_app
from config import Config
from conftest import TestConfig
from crawl import service

pytestmark = pytest.mark.skipif(
    os.environ.get("CRAWL_LIVE") != "1",
    reason="真实站点冒烟测试，默认跳过；设 CRAWL_LIVE=1 开启",
)

# 实测取自 CVPR2024 / ECCV2024 的索引页（2026-09-20）
CVPR_TITLE = "DPMesh: Exploiting Diffusion Prior for Occluded Human Mesh Recovery"
CVPR_PARTIAL = "DPMesh: Exploiting Diffusion Prior"
ECCV_TITLE = "FunQA: Towards Surprising Video Comprehension"


class LiveConfig(TestConfig):
    """真实抓取要按设计文档 §1.3 的礼貌参数走，不能像本地用例那样把间隔调成 0。"""

    CRAWL_MIN_INTERVAL = 0.5
    CRAWL_MAX_INTERVAL = 1.0
    CRAWL_INDEX_CACHE_TTL = 600


@pytest.fixture(scope="module", autouse=True)
def _fresh_caches():
    """索引缓存跨用例保留 —— 每个用例重抓一遍 7 MB 的索引页正是设计文档不允许的事。

    整个模块前后各清一次：进来的假设是冷启动，出去的假设是不留残留。
    """
    service.reset_fetcher()
    service.clear_index_cache()
    yield
    service.reset_fetcher()
    service.clear_index_cache()


@pytest.fixture()
def app(tmp_path):
    """覆盖 conftest 里的 app —— 唯一区别是恢复真实请求间隔。"""
    config = type("LiveConfig", (LiveConfig,), {"DB_PATH": str(tmp_path / "live.db")})

    with open(Config.SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(schema)
    conn.commit()
    conn.close()

    # 每个用例换一个抓取器，统计数字才干净（索引缓存不归它管，见上面的 _fresh_caches）
    service.reset_fetcher()
    return create_app(config)


def test_真实抓取_CVPR2024(app):
    with app.app_context():
        data = service.crawl_single(CVPR_TITLE, conference_code="CVPR", year=2024)

    assert data["status"] == "success", data.get("fail_message")
    paper = data["paper"]
    assert paper["title"] == CVPR_TITLE
    assert paper["source"] == "cvf"
    assert len(paper["abstract"]) > 200, "CVF 详情页的摘要没抓到"
    assert paper["pdf_url"].endswith(".pdf")
    assert paper["bibtex_key"]                      # BibTeX 来自列表页
    assert paper["authors"]
    assert paper["venue_raw"]
    assert paper["enrich_status"] == "enriched"

    print(f"\n[CVPR] {paper['title']}")
    print(f"       作者：{paper['authors'][:70]}")
    print(f"       摘要：{paper['abstract'][:120]}...")
    print(f"       原文：{paper['url']}")
    print(f"       PDF ：{paper['pdf_url']}")
    print(f"       匹配：{data['match_reason']} {data['match_score']}")
    print(f"       耗时：{data['elapsed_sec']}s  抓取计数：{data['fetcher']}")


def test_真实抓取_半截题目也能命中(app):
    with app.app_context():
        data = service.crawl_single(CVPR_PARTIAL, conference_code="CVPR", year=2024)
    assert data["status"] == "success"
    assert data["paper"]["title"] == CVPR_TITLE
    print(f"\n[半截题目] {CVPR_PARTIAL!r} → {data['match_reason']} "
          f"{data['match_score']}")


def test_真实抓取_ECCV2024经ECVA(app):
    with app.app_context():
        data = service.crawl_single(ECCV_TITLE, conference_code="ECCV", year=2024)

    assert data["status"] == "success", data.get("fail_message")
    paper = data["paper"]
    assert paper["source"] == "ecva"
    assert len(paper["abstract"]) > 200, "ECVA 详情页的摘要没抓到"
    assert paper["doi"].startswith("10.1007/")      # 列表页的 Springer 链接
    assert paper["pdf_url"].endswith(".pdf")
    assert paper["bibtex_key"] == ""                # ECVA 没有 BibTeX
    assert "European Conference on Computer Vision" in paper["venue_raw"]

    print(f"\n[ECCV] {paper['title']}")
    print(f"       作者：{paper['authors'][:70]}")
    print(f"       摘要：{paper['abstract'][:120]}...")
    print(f"       DOI ：{paper['doi']}")
    print(f"       PDF ：{paper['pdf_url']}")
    print(f"       耗时：{data['elapsed_sec']}s  抓取计数：{data['fetcher']}")


def test_真实抓取_不存在的题目判失败(app):
    """索引页已被上面的用例缓存，所以这次只花一次匹配的时间。"""
    with app.app_context():
        data = service.crawl_single("A Paper Title That Certainly Does Not Exist In CVPR 2024",
                                    conference_code="CVPR", year=2024)
    assert data["status"] == "failed"
    assert data["fail_reason"] == "NOT_FOUND_CVF"
    print(f"\n[未找到] {data['fail_message']}")


def test_真实抓取_auto_commit_入库(app):
    with app.app_context():
        data = service.crawl_single(CVPR_TITLE, conference_code="CVPR", year=2024,
                                    auto_commit=True)
    assert data["status"] == "success"
    assert data["commit"]["action"] in ("inserted", "updated")

    with sqlite3.connect(app.config["DB_PATH"]) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM paper WHERE id = ?",
                           (data["commit"]["paper_id"],)).fetchone()
    assert row["title"] == CVPR_TITLE
    assert row["abstract"]
    assert row["enrich_status"] == "enriched"
    print(f"\n[入库] paper.id={row['id']} action={data['commit']['action']} "
          f"abstract={len(row['abstract'])} 字符")
