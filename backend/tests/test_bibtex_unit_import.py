"""BibTeX / unit 导入 + 边爬边入库 —— 设计文档 §6.1 步骤 4。

验收标准（§7 验收表）：「跑完 CVPR2024 一届不崩、可中断续跑」。

核心验证五件事：
  1. .bib → 题目列表（花括号/引号两种取值、缺 title 跳过、归一化去重）；
  2. unit 模式阶段一拉整届清单（索引页只抓一次，阶段二从缓存取）；
  3. auto_commit=true 边爬边入库：逐条直接写 paper，明细不再暂存 paper 到 parsed_json；
  4. 断点续爬 / 熔断停手对 bibtex / unit 与 titles 同一条调度链；
  5. 校验与拒绝：文件类型、大小、conference_code、同届重复任务 → 4xx/409。

全部跑在本地 fixture 上，不联网（fetcher 用 FakeFetcher）。
"""
import io
import json
import time

import pytest
from werkzeug.datastructures import FileStorage

from conftest import fixture
from crawl import batch, service, storage
from crawl.fail_reason import InvalidParam
from crawl.units import units_for
from fakes import FakeFetcher

CVF_DETAIL_HTML = fixture("cvf_detail.html")
CVF_LIST_URL = "https://openaccess.thecvf.com/CVPR2024?day=all"

TITLE = "Neural Radiance Fields for Scene Reconstruction"
TITLE_DETAIL = ("https://openaccess.thecvf.com/content/CVPR2024/html/"
                "Zeng_Neural_Radiance_2024_CVPR_paper.html")
SPARSE = "Sparse Views Make Strong Baselines"
SPARSE_DETAIL = ("https://openaccess.thecvf.com/content/CVPR2024/html/"
                 "Chen_Sparse_Views_2024_CVPR_paper.html")
_SPARSE_HTML = "<html><body><div id='abstract'>Sparse views abstract.</div></body></html>"

# 精简的整届清单：两篇（一篇带 BibTeX、一篇不带），用于 unit 模式的可控用例
UNIT_INDEX = """<!DOCTYPE HTML><html><body><div id="content"><dl>
<dt class="ptitle"><br><a href="/content/CVPR2024/html/Zeng_Neural_Radiance_2024_CVPR_paper.html">Neural Radiance Fields for Scene Reconstruction</a></dt>
<dd><form class="authsearch"><input type="hidden" name="query_author" value="Haijin Zeng"><a href="#">Haijin Zeng</a>,</form></dd>
<dd>[<a href="/content/CVPR2024/papers/Zeng_Neural_Radiance_2024_CVPR_paper.pdf">pdf</a>]<div class="link2">[<a class="fakelink">bibtex</a>]<div class="bibref pre-white-space">@InProceedings{Zeng_2024_CVPR,
    title = {Neural Radiance Fields for Scene Reconstruction},
    booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)},
    year = {2024}}</div></div></dd>
<dt class="ptitle"><br><a href="/content/CVPR2024/html/Chen_Sparse_Views_2024_CVPR_paper.html">Sparse Views Make Strong Baselines</a></dt>
<dd><form class="authsearch"><input type="hidden" name="query_author" value="Lin Chen"><a href="#">Lin Chen</a>,</form></dd>
<dd>[<a href="/content/CVPR2024/papers/Chen_Sparse_Views_2024_CVPR_paper.pdf">pdf</a>]</dd>
</dl></div></body></html>"""

BIB = """@InProceedings{Zeng_2024_CVPR,
    author    = {Zeng, Haijin and Li, Wei},
    title     = {Neural Radiance Fields for Scene Reconstruction},
    booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)},
    year      = {2024}
}

@InProceedings{Chen_2024_CVPR,
    author    = {Chen, Lin},
    title     = {Sparse Views Make Strong Baselines},
    booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)},
    year      = {2024}
}

@Article{NoTitle_2024,
    author = {Nobody, N},
    year   = {2024}
}"""


def cvf_fetcher(pages=None, errors=None, blocked_hosts=None):
    mapping = {
        CVF_LIST_URL: UNIT_INDEX,
        TITLE_DETAIL: CVF_DETAIL_HTML,
        SPARSE_DETAIL: _SPARSE_HTML,
    }
    mapping.update(pages or {})
    return FakeFetcher(mapping, errors=errors, blocked_hosts=blocked_hosts)


def make_task(app, titles, task_type, auto_commit=True,
              conference_code="CVPR", year=2024):
    with app.app_context():
        task = storage.create_task(task_type, conference_code, year, auto_commit,
                                   total=len(titles))
        storage.create_items(task["id"], titles)
        return task


def wait_finished(app, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with app.app_context():
            task = storage.get_task(task_id)
        if task and task["status"] not in ("queued", "running"):
            return task
        time.sleep(0.01)
    raise AssertionError(f"任务 {task_id} 在 {timeout}s 内没跑完")


# ---------------------------------------------------------------
# .bib 解析（纯函数）
# ---------------------------------------------------------------
def test_parse_bibtex_取title并跳过缺title():
    titles, warnings = batch.parse_bibtex(BIB)
    assert titles == [TITLE, SPARSE]
    assert any("缺 title" in w for w in warnings)


def test_parse_bibtex_归一化去重():
    dup = BIB + ("\n@InProceedings{Dup_2024,"
                 " title = {Neural Radiance Fields  for  Scene Reconstruction},"
                 " year = {2024}}")
    titles, warnings = batch.parse_bibtex(dup)
    assert titles == [TITLE, SPARSE]
    assert any("重复" in w for w in warnings)


def test_parse_bibtex_花括号嵌套title():
    text = "@Article{X, title = {A {3D} Approach to {NeRF}}, year={2024}}"
    titles, _ = batch.parse_bibtex(text)
    assert titles == ["A {3D} Approach to {NeRF}"]


def test_parse_bibtex_引号取值title():
    text = '@InProceedings{X, title = "Quoted Title Here", year={2024}}'
    titles, _ = batch.parse_bibtex(text)
    assert titles == ["Quoted Title Here"]


def test_parse_bibtex_空文本给警告():
    titles, warnings = batch.parse_bibtex("")
    assert titles == []
    assert any("没有解析出" in w for w in warnings)


# ---------------------------------------------------------------
# .bib 文件上传
# ---------------------------------------------------------------
def test_bib_upload_扩展名不符报参数错():
    fs = FileStorage(stream=io.BytesIO(b"x"), filename="papers.txt")
    with pytest.raises(InvalidParam):
        batch.read_bib_upload(fs)


def test_bib_upload_超过大小上限报参数错():
    big = io.BytesIO(b"x" * (batch.MAX_UPLOAD_BYTES + 1))
    fs = FileStorage(stream=big, filename="papers.bib")
    with pytest.raises(InvalidParam):
        batch.read_bib_upload(fs)


def test_bib_upload_正常读取():
    fs = FileStorage(stream=io.BytesIO(BIB.encode()), filename="papers.bib")
    assert "Zeng_2024_CVPR" in batch.read_bib_upload(fs)


# ---------------------------------------------------------------
# unit 模式：整届清单 → 边爬边入库
# ---------------------------------------------------------------
def test_unit_边爬边入库直接写paper(app, db):
    task = make_task(app, [TITLE, SPARSE], "unit")
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert (row["status"], row["finished"], row["success"]) == ("done", 2, 2)
    assert row["stage"] == "commit"               # auto_commit 停在 commit

    papers = db.execute("SELECT title, source FROM paper ORDER BY id").fetchall()
    assert [p["title"] for p in papers] == [TITLE, SPARSE]
    assert all(p["source"] == "cvf" for p in papers)

    # 明细指回 paper，且 parsed_json 里不再暂存整份 paper（边爬边入库）
    items = db.execute(
        "SELECT paper_id, parsed_json FROM crawl_task_item ORDER BY seq").fetchall()
    assert all(i["paper_id"] is not None for i in items)
    for i in items:
        parsed = json.loads(i["parsed_json"])
        assert "paper" not in parsed
        assert parsed["matched_unit"] == "CVPR 2024"
        assert parsed["match_reason"] == "exact"


def test_unit_索引页只抓一次(app):
    fake = cvf_fetcher()
    with app.app_context():
        unit = units_for("CVPR", 2024)[0]
        service.load_index(unit, fake)                       # 阶段一
        task = make_task(app, [TITLE, SPARSE], "unit")
        batch.run(app, task["task_id"], fetcher=fake)        # 阶段二：缓存命中
    assert fake.urls().count(CVF_LIST_URL) == 1
    assert fake.kinds() == ["list", "detail", "detail"]


def test_unit_resume只跑pending(app, db):
    task = make_task(app, [TITLE, SPARSE], "unit")
    with app.app_context():
        items = storage.list_items(task["id"])
        storage.finish_item(items[0]["id"], "success", parsed={"input_title": TITLE})
        storage.bump_task(task["task_id"], cursor=1, finished=1, success=1)
        storage.pause_task(task["task_id"], batch.PAUSE_BREAKER)

    fake = cvf_fetcher()
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=fake)

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert (row["status"], row["finished"], row["success"]) == ("done", 2, 2)
    assert TITLE_DETAIL not in fake.urls()         # 成功的不重来
    assert SPARSE_DETAIL in fake.urls()


def test_unit_熔断触发则暂停并保留pending(app, db):
    task = make_task(app, [TITLE, SPARSE], "unit")
    fake = cvf_fetcher(blocked_hosts=["openaccess.thecvf.com"])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=fake)

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert row["status"] == "paused"
    assert row["pause_reason"] == batch.PAUSE_BREAKER
    items = db.execute(
        "SELECT input_title, status FROM crawl_task_item "
        "WHERE task_id = ? ORDER BY seq", (row["id"],)).fetchall()
    assert [(i["input_title"], i["status"]) for i in items] == \
        [(TITLE, "success"), (SPARSE, "pending")]


# ---------------------------------------------------------------
# bibtex 模式：题目 → 检索 → 边爬边入库
# ---------------------------------------------------------------
def test_bibtex_边爬边入库写paper(app, db):
    task = make_task(app, [TITLE, SPARSE], "bibtex")
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert (row["status"], row["finished"], row["success"]) == ("done", 2, 2)
    papers = db.execute("SELECT title FROM paper ORDER BY id").fetchall()
    assert [p["title"] for p in papers] == [TITLE, SPARSE]


# ---------------------------------------------------------------
# 索引缓存 TTL
# ---------------------------------------------------------------
def test_索引缓存TTL过期后重新拉取(app):
    fake = cvf_fetcher()
    with app.app_context():
        # 过期时刻在存入时就折算成绝对时间（store + 当时的 TTL），
        # 事后改配置不会追溯已缓存的条目 —— 要验证「过期重拉」，
        # 必须在第一次 load 之前就把 TTL 设为 0，让条目生来即过期。
        app.config["CRAWL_INDEX_CACHE_TTL"] = 0
        unit = units_for("CVPR", 2024)[0]
        service.load_index(unit, fake)
        service.load_index(unit, fake)
    assert fake.urls().count(CVF_LIST_URL) == 2


# ---------------------------------------------------------------
# 关键词关联写路径（阶段五产出关键词后即插即用，本步骤无抽取）
# ---------------------------------------------------------------
def test_link_keywords写入keyword与paper_keyword(app, db):
    with app.app_context():
        conf_id = storage.conference_info("CVPR")["id"]
        paper_id, _ = storage.upsert_paper({
            "title": "Keyword Link Test", "title_key": "keyword link test",
            "conference_id": conf_id, "year": 2024, "source": "cvf",
        })
        storage.link_keywords(paper_id, [
            {"name": "Diffusion Model", "weight": 0.8, "rank": 1},
            {"name": "3D", "weight": 0.5, "rank": 2},
        ])

    rows = db.execute(
        "SELECT k.name, pk.weight, pk.rank FROM paper_keyword pk "
        "JOIN keyword k ON k.id = pk.keyword_id WHERE pk.paper_id = ? "
        "ORDER BY pk.rank", (paper_id,)).fetchall()
    assert [(r["name"], r["weight"], r["rank"]) for r in rows] == [
        ("Diffusion Model", 0.8, 1), ("3D", 0.5, 2),
    ]


# ---------------------------------------------------------------
# HTTP 接口层
# ---------------------------------------------------------------
def test_API_bibtex上传_边爬边入库(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", data={
        "type": "bibtex", "conference_code": "CVPR", "year": "2024",
        "file": (io.BytesIO(BIB.encode()), "papers.bib"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["type"] == "bibtex"
    assert data["total"] == 2
    assert data["auto_commit"] is True
    task = wait_finished(app, data["task_id"])
    assert task["success"] == 2


def test_API_unit整届导入_边爬边入库(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", json={
        "type": "unit", "conference_code": "CVPR", "year": 2024,
    })

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["type"] == "unit"
    assert data["total"] == 2
    assert data["auto_commit"] is True
    task = wait_finished(app, data["task_id"])
    assert task["success"] == 2


def test_API_commit对auto_commit任务返回409(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", json={
        "type": "unit", "conference_code": "CVPR", "year": 2024,
    })
    task_id = resp.get_json()["data"]["task_id"]
    wait_finished(app, task_id)

    commit = client.post(f"/api/v1/tasks/{task_id}/commit")
    assert commit.status_code == 409


def test_API_bibtex缺会议年份返回400(app, client):
    resp = client.post("/api/v1/papers/import", json={"type": "bibtex", "text": "x"})
    assert resp.status_code == 400
    assert "conference_code" in resp.get_json()["message"]


def test_API_unit缺年份返回400(app, client):
    resp = client.post("/api/v1/papers/import",
                       json={"type": "unit", "conference_code": "CVPR"})
    assert resp.status_code == 400
    assert "year" in resp.get_json()["message"]


def test_API_bibtex文件类型不符返回400(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", data={
        "type": "bibtex", "conference_code": "CVPR", "year": "2024",
        "file": (io.BytesIO(b"x"), "papers.txt"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert ".bib" in resp.get_json()["message"]


def test_API_unit不需要文件返回400(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", data={
        "type": "unit", "conference_code": "CVPR", "year": "2024",
        "file": (io.BytesIO(b"x"), "papers.bib"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_API_conference_code不在三大顶会返回400(app, client):
    resp = client.post("/api/v1/papers/import",
                       json={"type": "unit", "conference_code": "NIPS", "year": 2024})
    assert resp.status_code == 400
