"""单条题目爬取链路测试 —— 设计文档 §6.1 步骤 2 的验收标准。

    「单条题目能从抓取一路走到 crawl_task_item 落库」

链路：匹配题目 → 抓详情页取摘要 → 写 crawl_task_item →（auto_commit 时）写 paper。
全部跑在本地 fixture 上，不联网。
"""
import json

import pytest

from conftest import fixture
from crawl import service
from crawl.fail_reason import CrawlError, InvalidParam
from crawl.units import list_units
from fakes import FakeFetcher

CVF_INDEX = fixture("cvf_index.html")
CVF_DETAIL_HTML = fixture("cvf_detail.html")
ECVA_LIST = fixture("ecva_list.html")
ECVA_DETAIL_HTML = fixture("ecva_detail.html")

TITLE = "Neural Radiance Fields for Scene Reconstruction"
CVF_LIST_URL = "https://openaccess.thecvf.com/CVPR2024?day=all"
CVF_DETAIL_URL = ("https://openaccess.thecvf.com/content/CVPR2024/html/"
                  "Zeng_Neural_Radiance_2024_CVPR_paper.html")
ECVA_LIST_URL = "https://www.ecva.net/papers.php"
ECVA_TITLE = "Selective Distillation for Open Vocabulary Segmentation"
ECVA_DETAIL_URL = ("https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/"
                   "4_ECCV_2024_paper.php")

EMPTY_PAGE = "<html><body><dl></dl></body></html>"


def cvf_fetcher(pages=None, **kwargs):
    mapping = {CVF_LIST_URL: CVF_INDEX, CVF_DETAIL_URL: CVF_DETAIL_HTML}
    mapping.update(pages or {})
    return FakeFetcher(mapping, **kwargs)


def ecva_fetcher(pages=None, **kwargs):
    mapping = {ECVA_LIST_URL: ECVA_LIST, ECVA_DETAIL_URL: ECVA_DETAIL_HTML}
    mapping.update(pages or {})
    return FakeFetcher(mapping, **kwargs)


def all_units_fetcher(pages=None):
    """所有单元的索引页都返回空，只有指定页有内容 —— 用来验证跨单元检索。"""
    mapping = {u.index_url: EMPTY_PAGE for u in list_units()}
    mapping.update(pages or {})
    return FakeFetcher(mapping)


# ---------------------------------------------------------------
# 核心验收：单条题目一路走到落库
# ---------------------------------------------------------------
def test_单条爬取写入任务与明细(app, db):
    with app.app_context():
        data = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                    fetcher=cvf_fetcher())

    assert data["status"] == "success"
    assert data["matched_unit"] == "CVPR 2024"
    assert data["match_reason"] == "exact"

    # --- crawl_task_item 落库 ---
    item = db.execute(
        "SELECT * FROM crawl_task_item WHERE id = ?", (data["item_id"],)
    ).fetchone()
    assert item is not None
    assert item["input_title"] == TITLE
    assert item["status"] == "success"
    assert item["fail_reason"] is None
    assert item["detail_url"] == CVF_DETAIL_URL
    assert item["pdf_url"].endswith("Zeng_Neural_Radiance_2024_CVPR_paper.pdf")

    parsed = json.loads(item["parsed_json"])
    assert parsed["matched_unit"] == "CVPR 2024"
    assert parsed["paper"]["abstract"]
    assert parsed["paper"]["title"] == TITLE

    # --- crawl_task 落库 ---
    task = db.execute(
        "SELECT * FROM crawl_task WHERE task_id = ?", (data["task_id"],)
    ).fetchone()
    assert task["type"] == "single"
    assert task["conference_code"] == "CVPR"
    assert task["year"] == 2024
    assert (task["status"], task["total"], task["finished"],
            task["success"], task["failed"]) == ("done", 1, 1, 1, 0)
    assert task["cursor"] == 1
    # 明细挂在任务上（外键指向 crawl_task.id）
    assert item["task_id"] == task["id"]


def test_成功行返回原型要求的三字段(app):
    with app.app_context():
        data = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                    fetcher=cvf_fetcher())

    paper = data["paper"]
    # 摘要 / 关键词 / 原文链接 —— 原型④「成功行三字段」
    assert len(paper["abstract"]) > 100
    assert paper["keywords"] == [] and paper["keywords_status"] == "pending"
    assert paper["url"] == CVF_DETAIL_URL

    # 其余字段
    assert paper["title_key"] == "neural radiance fields for scene reconstruction"
    assert paper["authors"] == "Zeng, Haijin, Li, Wei"        # 取自 BibTeX 的 and 分隔
    assert paper["year"] == 2024
    assert paper["conference_code"] == "CVPR"
    assert paper["source"] == "cvf"
    assert paper["pdf_url"].endswith("_paper.pdf")
    assert paper["doi"] == "10.1109/CVPR52688.2024.00000"     # 来自详情页 citation_doi
    assert paper["pages"] == "1234-1243"
    assert paper["bibtex_key"] == "Zeng_2024_CVPR"
    assert "Conference on Computer Vision and Pattern Recognition" in paper["venue_raw"]
    assert paper["enrich_status"] == "enriched"
    assert paper["fail_reason"] is None
    assert paper["id"] is None                                # 未 auto_commit，还没入库


def test_按题目模糊匹配也能找到(app):
    """用户少打一个词：靠包含匹配命中，但评分低于精确命中。"""
    with app.app_context():
        data = service.crawl_single("Neural Radiance Fields for Scene Reconstruction (CVPR)",
                                    conference_code="CVPR", year=2024,
                                    fetcher=cvf_fetcher())
    assert data["status"] == "success"
    assert data["match_reason"] == "contains"
    assert 0.90 <= data["match_score"] < 1.0


def test_拉取顺序是先列表页后详情页(app):
    fake = cvf_fetcher()
    with app.app_context():
        service.crawl_single(TITLE, conference_code="CVPR", year=2024, fetcher=fake)
    assert fake.urls() == [CVF_LIST_URL, CVF_DETAIL_URL]
    assert fake.kinds() == ["list", "detail"]


def test_索引页缓存_第二篇题目不重复拉列表页(app):
    second = "Sparse Views Make Strong Baselines"
    second_detail = ("https://openaccess.thecvf.com/content/CVPR2024/html/"
                     "Chen_Sparse_Views_2024_CVPR_paper.html")
    fake = cvf_fetcher(pages={second_detail: "<html><body>"
                              "<div id='abstract'>Another abstract.</div></body></html>"})
    with app.app_context():
        service.crawl_single(TITLE, conference_code="CVPR", year=2024, fetcher=fake)
        service.crawl_single(second, conference_code="CVPR", year=2024, fetcher=fake)
    # 列表页只抓了一次，详情页两次
    assert fake.urls().count(CVF_LIST_URL) == 1
    assert fake.kinds() == ["list", "detail", "detail"]


# ---------------------------------------------------------------
# 失败路径
# ---------------------------------------------------------------
def test_题目未找到_记为失败并保留检索范围(app, db):
    with app.app_context():
        data = service.crawl_single("A Paper That Does Not Exist Anywhere In CVPR",
                                    conference_code="CVPR", year=2024,
                                    fetcher=cvf_fetcher())

    assert data["status"] == "failed"
    assert data["fail_reason"] == "NOT_FOUND_CVF"
    assert data["retryable"] is False
    assert "CVPR 2024" in data["fail_message"]

    item = db.execute("SELECT * FROM crawl_task_item WHERE id = ?",
                      (data["item_id"],)).fetchone()
    assert item["status"] == "failed"
    assert item["fail_reason"] == "NOT_FOUND_CVF"
    assert item["paper_id"] is None

    task = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                      (data["task_id"],)).fetchone()
    # 任务本身跑完了（不是中断），只是这一条失败了
    assert (task["status"], task["finished"], task["failed"]) == ("done", 1, 1)


def test_详情页抓取失败仍算成功但摘要留空(app, db):
    """标题/作者/会议/年份/链接都已到手，不该因为详情页打不开就整条丢弃。"""
    fake = cvf_fetcher(errors={CVF_DETAIL_URL: CrawlError("PAGE_FETCH_FAILED", "超时")})
    with app.app_context():
        data = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                    fetcher=fake)

    assert data["status"] == "success"
    assert data["paper"]["abstract"] == ""
    assert data["paper"]["enrich_status"] == "partial"
    assert data["paper"]["fail_reason"] == "PAGE_FETCH_FAILED"
    assert any("详情页抓取失败" in w for w in data["warnings"])

    item = db.execute("SELECT * FROM crawl_task_item WHERE id = ?",
                      (data["item_id"],)).fetchone()
    assert item["status"] == "success"
    assert item["fail_reason"] == "PAGE_FETCH_FAILED"     # 留着，供「重试补全」用


def test_详情页没有摘要记摘要缺失(app):
    blank = "<html><body><div id='papertitle'>T</div></body></html>"
    fake = cvf_fetcher(pages={CVF_LIST_URL: CVF_INDEX, CVF_DETAIL_URL: blank})
    with app.app_context():
        data = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                    fetcher=fake)
    assert data["status"] == "success"
    assert data["paper"]["fail_reason"] == "ABSTRACT_MISSING"
    assert data["paper"]["enrich_status"] == "partial"


def test_索引页整体抓不到时记为抓取失败(app):
    fake = FakeFetcher(errors={CVF_LIST_URL: CrawlError("NETWORK_ERROR", "断网")})
    with app.app_context():
        data = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                    fetcher=fake)
    assert data["status"] == "failed"
    assert data["fail_reason"] == "NETWORK_ERROR"


# ---------------------------------------------------------------
# auto_commit 入库
# ---------------------------------------------------------------
def test_auto_commit写入paper表(app, db):
    with app.app_context():
        data = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                    auto_commit=True, fetcher=cvf_fetcher())

    assert data["commit"]["action"] == "inserted"
    paper_id = data["commit"]["paper_id"]
    assert data["paper"]["id"] == paper_id

    row = db.execute("SELECT * FROM paper WHERE id = ?", (paper_id,)).fetchone()
    assert row["title"] == TITLE
    assert row["title_key"] == "neural radiance fields for scene reconstruction"
    assert row["year"] == 2024
    assert row["abstract"]
    assert row["doi"] == "10.1109/CVPR52688.2024.00000"
    assert row["source"] == "cvf"
    assert row["enrich_status"] == "enriched"
    assert row["pages"] == "1234-1243"
    # 会议外键指向 conference 表，而不是存一个字符串
    conf = db.execute("SELECT code FROM conference WHERE id = ?",
                      (row["conference_id"],)).fetchone()
    assert conf["code"] == "CVPR"

    item = db.execute("SELECT paper_id FROM crawl_task_item WHERE id = ?",
                      (data["item_id"],)).fetchone()
    assert item["paper_id"] == paper_id       # 明细能指回论文，供结果行「查看」


def test_重复爬取同一篇不产生重复论文(app, db):
    with app.app_context():
        service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                             auto_commit=True, fetcher=cvf_fetcher())
        second = service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                                      auto_commit=True, fetcher=cvf_fetcher())

    assert second["commit"]["action"] == "skipped"      # 没有新字段可补
    count = db.execute("SELECT COUNT(*) AS c FROM paper").fetchone()["c"]
    assert count == 1


def test_暂存模式不写paper表(app, db):
    with app.app_context():
        service.crawl_single(TITLE, conference_code="CVPR", year=2024,
                             fetcher=cvf_fetcher())
    count = db.execute("SELECT COUNT(*) AS c FROM paper").fetchone()["c"]
    assert count == 0
    # 但解析结果落在 parsed_json 里，点「全部入库」时不会丢
    item = db.execute("SELECT parsed_json FROM crawl_task_item").fetchone()
    assert json.loads(item["parsed_json"])["paper"]["abstract"]


# ---------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------
def test_会议年份不存在时报参数错且不建任务(app, db):
    with app.app_context():
        with pytest.raises(InvalidParam) as exc:
            service.crawl_single(TITLE, conference_code="ICCV", year=2024)
    assert "ICCV" in str(exc.value) and "2024" in str(exc.value)
    # 参数错误在建任务之前就挡住了，不该留下垃圾任务行
    assert db.execute("SELECT COUNT(*) AS c FROM crawl_task").fetchone()["c"] == 0


def test_题目为空报参数错(app):
    with app.app_context():
        with pytest.raises(InvalidParam):
            service.crawl_single("   ", conference_code="CVPR", year=2024)


def test_会议代号不合法报参数错(app):
    with app.app_context():
        with pytest.raises(InvalidParam):
            service.crawl_single(TITLE, conference_code="NIPS", year=2024)


# ---------------------------------------------------------------
# 跨单元检索（不限定会议 / 年份）
# ---------------------------------------------------------------
def test_不限定会议年份时依次检索并命中(app):
    fake = all_units_fetcher({CVF_LIST_URL: CVF_INDEX, CVF_DETAIL_URL: CVF_DETAIL_HTML})
    with app.app_context():
        data = service.crawl_single(TITLE, fetcher=fake)

    assert data["status"] == "success"
    assert data["matched_unit"] == "CVPR 2024"
    # 按「新 → 旧、CVPR → ICCV → ECCV」排，CVPR2024 排在第 4 个
    assert [s["unit"] for s in data["searched_units"]] == \
        ["CVPR 2026", "CVPR 2025", "ICCV 2025", "CVPR 2024"]


def test_不限定会议年份时全部落空(app):
    with app.app_context():
        data = service.crawl_single("No Such Paper Anywhere", fetcher=all_units_fetcher())
    assert data["status"] == "failed"
    assert data["fail_reason"] == "NOT_FOUND_CVF"
    # 全部单元都试过。CVPR 5 届 + ICCV 2 届 + ECCV 2 届 = 9
    assert len(data["searched_units"]) == len(list_units()) == 9
    assert "超时" not in data["fail_message"]          # 没超时，是确实没有


def test_可抓单元日历():
    """三大顶会节奏不同：CVPR 每年、ICCV/ECCV 两年一届，ECCV 2026 尚未发布。"""
    units = {(u.conference_code, u.year) for u in list_units()}
    assert units == {
        ("CVPR", 2022), ("CVPR", 2023), ("CVPR", 2024), ("CVPR", 2025), ("CVPR", 2026),
        ("ICCV", 2023), ("ICCV", 2025),
        ("ECCV", 2022), ("ECCV", 2024),
    }
    assert len(units) == 9
    # CVPR/ICCV 走 CVF，ECCV 走 ECVA
    assert {u.source for u in list_units() if u.conference_code == "ECCV"} == {"ecva"}
    assert {u.source for u in list_units() if u.conference_code == "CVPR"} == {"cvf"}


# ---------------------------------------------------------------
# ECVA（ECCV）链路
# ---------------------------------------------------------------
def test_ECCV链路走ECVA解析器(app, db):
    with app.app_context():
        data = service.crawl_single(ECVA_TITLE, conference_code="ECCV", year=2024,
                                    fetcher=ecva_fetcher())

    assert data["status"] == "success"
    assert data["matched_unit"] == "ECCV 2024"
    paper = data["paper"]
    assert paper["source"] == "ecva"
    assert paper["abstract"].count(",") >= 3           # ECVA 的摘要标点完整
    assert paper["pdf_url"].endswith("/papers/00004.pdf")
    assert paper["doi"] == "10.1007/978-3-031-73232-4_1"
    assert paper["bibtex_key"] == ""                   # ECVA 侧没有 BibTeX
    assert paper["pages"] == ""
    assert "European Conference on Computer Vision" in paper["venue_raw"]

    item = db.execute("SELECT * FROM crawl_task_item WHERE id = ?",
                      (data["item_id"],)).fetchone()
    assert item["status"] == "success"


def test_ECCV上一届的论文不会被当年份收录(app):
    """papers.php 一个页面混着所有年份，年份过滤必须生效。"""
    fake = ecva_fetcher()
    with app.app_context():
        data = service.crawl_single("Old Paper From The Previous Edition",
                                    conference_code="ECCV", year=2024, fetcher=fake)
    assert data["status"] == "failed"
    assert data["fail_reason"] == "NOT_FOUND_CVF"


# ---------------------------------------------------------------
# HTTP 接口层
# ---------------------------------------------------------------
def patch_fetcher(monkeypatch, fake):
    """让 service 复用同一个假抓取器实例 —— 否则每次 get_fetcher() 都是新的，
    stats() 之类的断言会莫名其妙地变成 0。"""
    monkeypatch.setattr(service, "get_fetcher", lambda: fake)
    return fake


def test_API_单个题目爬取(client, app, monkeypatch):
    patch_fetcher(monkeypatch, cvf_fetcher())
    resp = client.post("/api/v1/papers/crawl", json={
        "title": TITLE, "conference_code": "CVPR", "year": 2024,
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    data = body["data"]
    assert data["status"] == "success"
    assert data["paper"]["title"] == TITLE
    assert data["paper"]["abstract"]
    assert data["task_id"] and data["item_id"]


def test_API_会议代号小写也接受(client, app, monkeypatch):
    patch_fetcher(monkeypatch, cvf_fetcher())
    resp = client.post("/api/v1/papers/crawl",
                       json={"title": TITLE, "conference_code": "cvpr", "year": 2024})
    assert resp.get_json()["data"]["status"] == "success"


def test_API_业务失败仍返回200(client, app, monkeypatch):
    """题目没找到是正常业务结果，不该变成 4xx —— 否则前端会弹红 toast。"""
    patch_fetcher(monkeypatch, cvf_fetcher())
    resp = client.post("/api/v1/papers/crawl",
                       json={"title": "Nothing Like This Exists", "conference_code": "CVPR",
                             "year": 2024})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert body["data"]["status"] == "failed"
    assert body["data"]["fail_reason"] == "NOT_FOUND_CVF"


def test_API_参数错误返回400(client, app):
    resp = client.post("/api/v1/papers/crawl",
                       json={"title": TITLE, "conference_code": "ICCV", "year": 2024})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == 400


def test_API_缺title返回400(client, app):
    resp = client.post("/api/v1/papers/crawl", json={"conference_code": "CVPR"})
    assert resp.status_code == 400
    assert "title" in resp.get_json()["message"]


def test_API_请求体不是JSON返回400(client, app):
    resp = client.post("/api/v1/papers/crawl", data="not json",
                       content_type="text/plain")
    assert resp.status_code == 400


def test_API_任务进度查询(client, app, monkeypatch):
    fake = patch_fetcher(monkeypatch, cvf_fetcher())
    task_id = client.post("/api/v1/papers/crawl", json={
        "title": TITLE, "conference_code": "CVPR", "year": 2024,
    }).get_json()["data"]["task_id"]

    resp = client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "done"
    assert data["stage"] == "enrich"                      # 未 auto_commit
    assert data["stage_label"] == "抓取详情页摘要"
    assert data["total"] == 1 and data["finished"] == 1
    assert data["percent"] == 100.0
    assert data["success"] == 1 and data["failed"] == 0
    assert data["fetcher"]["requests"] == len(fake.calls) == 2


def test_API_任务不存在返回404(client, app):
    resp = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
