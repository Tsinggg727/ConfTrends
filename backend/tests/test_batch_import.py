"""批量导入（titles）+ 进度查询 + commit + resume —— 设计文档 §6.1 步骤 3。

验收标准（§7 验收表）：「50 条题目跑通，进度条与计数正确」。

核心验证四件事：
  1. 异步任务逐条跑，每条落 crawl_task_item 状态 + crawl_task.cursor；
  2. 暂存模式不写 paper，点「全部入库」才写，且按 title_key 去重；
  3. 断点续爬只跑 status='pending' 的题目，成功的不重来；
  4. 进度查询返回 current_title / qps / eta_sec / recent_failures。

全部跑在本地 fixture 上，不联网（fetcher 用 FakeFetcher，间隔 0）。
异步路径：接口层起线程，测试里等它跑完；核心逻辑直接同步调 batch.run。
"""
import io
import json
import time

import pytest
from werkzeug.datastructures import FileStorage

from conftest import fixture
from crawl import batch, service, storage
from crawl.fail_reason import InvalidParam
from fakes import FakeFetcher

CVF_INDEX = fixture("cvf_index.html")
CVF_DETAIL_HTML = fixture("cvf_detail.html")
CVF_LIST_URL = "https://openaccess.thecvf.com/CVPR2024?day=all"

TITLE = "Neural Radiance Fields for Scene Reconstruction"
TITLE_DETAIL = ("https://openaccess.thecvf.com/content/CVPR2024/html/"
                "Zeng_Neural_Radiance_2024_CVPR_paper.html")
SPARSE = "Sparse Views Make Strong Baselines"
SPARSE_DETAIL = ("https://openaccess.thecvf.com/content/CVPR2024/html/"
                 "Chen_Sparse_Views_2024_CVPR_paper.html")
MISSING = "A Paper That Does Not Exist Anywhere In CVPR"
_SPARSE_HTML = "<html><body><div id='abstract'>Sparse views abstract.</div></body></html>"


def cvf_fetcher(pages=None, errors=None):
    mapping = {
        CVF_LIST_URL: CVF_INDEX,
        TITLE_DETAIL: CVF_DETAIL_HTML,
        SPARSE_DETAIL: _SPARSE_HTML,
    }
    mapping.update(pages or {})
    return FakeFetcher(mapping, errors=errors)


def make_task(app, titles, conference_code="CVPR", year=2024):
    with app.app_context():
        task = storage.create_task("titles", conference_code, year, False,
                                   total=len(titles))
        storage.create_items(task["id"], titles)
        return task


def wait_finished(app, task_id, timeout=5.0):
    """等后台线程跑完，返回最终的任务行。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with app.app_context():
            task = storage.get_task(task_id)
        if task and task["status"] not in ("queued", "running"):
            return task
        time.sleep(0.01)
    raise AssertionError(f"任务 {task_id} 在 {timeout}s 内没跑完")


# ---------------------------------------------------------------
# 输入解析（纯函数）
# ---------------------------------------------------------------
def test_parse_每行一个题目去空行去首尾空白():
    titles, warnings = batch.parse_titles("  A  \n\nB\n   \nC  ")
    assert titles == ["A", "B", "C"]
    assert warnings == []


def test_parse_表头行被跳过():
    titles, _ = batch.parse_titles("title\nFoo Bar\nBaz Qux")
    assert titles == ["Foo Bar", "Baz Qux"]
    titles_cn, _ = batch.parse_titles("论文题目\nFoo Bar")
    assert titles_cn == ["Foo Bar"]


def test_parse_归一化去重():
    titles, warnings = batch.parse_titles("Diffusion Models Beat GANs\n"
                                          "Diffusion Models  Beat  GANs")
    assert titles == ["Diffusion Models Beat GANs"]
    assert any("重复" in w for w in warnings)


def test_parse_超长行跳过并警告():
    long = "x" * 501
    titles, warnings = batch.parse_titles(f"ok title\n{long}")
    assert titles == ["ok title"]
    assert any("跳过" in w for w in warnings)


def test_parse_引号包裹被剥掉():
    titles, _ = batch.parse_titles('"Quoted Title"\n\'Another One\'')
    assert titles == ["Quoted Title", "Another One"]


# ---------------------------------------------------------------
# 文件上传
# ---------------------------------------------------------------
def test_upload_txt():
    fs = FileStorage(stream=io.BytesIO("A\nB\n".encode()), filename="titles.txt")
    assert batch.read_upload(fs) == "A\nB\n"


def test_upload_csv只取第一列():
    body = io.BytesIO("title,authors\nalpha,One\nbeta,Two\n".encode())
    fs = FileStorage(stream=body, filename="list.csv")
    text = batch.read_upload(fs)
    assert text == "title\nalpha\nbeta"        # 只取第一列，表头还留着
    titles, _ = batch.parse_titles(text)       # 表头在这一层跳过
    assert titles == ["alpha", "beta"]


def test_upload_扩展名不符报参数错():
    fs = FileStorage(stream=io.BytesIO(b"x"), filename="titles.bib")
    with pytest.raises(InvalidParam):
        batch.read_upload(fs)


def test_upload_超过大小上限报参数错():
    big = io.BytesIO(b"x" * (batch.MAX_UPLOAD_BYTES + 1))
    fs = FileStorage(stream=big, filename="titles.txt")
    with pytest.raises(InvalidParam):
        batch.read_upload(fs)


# ---------------------------------------------------------------
# 核心：批量跑通 + 计数 + 暂存
# ---------------------------------------------------------------
def test_批量跑通_任务与明细计数正确(app, db):
    task = make_task(app, [TITLE, SPARSE, MISSING])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert (row["status"], row["finished"], row["success"], row["failed"]) == \
        ("done", 3, 2, 1)
    assert row["cursor"] == 3                        # 高水位 = 处理到的最后一条
    assert row["stage"] == "enrich"                  # 暂存模式停在 enrich

    items = db.execute(
        "SELECT seq, input_title, status FROM crawl_task_item "
        "WHERE task_id = ? ORDER BY seq", (row["id"],)).fetchall()
    assert [(i["input_title"], i["status"]) for i in items] == [
        (TITLE, "success"), (SPARSE, "success"), (MISSING, "failed"),
    ]


def test_批量逐条更新cursor_失败在中间也不断(app, db):
    task = make_task(app, [MISSING, TITLE, SPARSE])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert (row["finished"], row["success"], row["failed"], row["cursor"]) == \
        (3, 2, 1, 3)


def test_批量暂存不写paper但解析结果落parsed_json(app, db):
    task = make_task(app, [TITLE, SPARSE])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())

    assert db.execute("SELECT COUNT(*) AS c FROM paper").fetchone()["c"] == 0
    item = db.execute(
        "SELECT parsed_json FROM crawl_task_item WHERE input_title = ?",
        (TITLE,)).fetchone()
    parsed = json.loads(item["parsed_json"])
    assert parsed["paper"]["abstract"]
    assert parsed["paper"]["title"] == TITLE
    assert parsed["matched_unit"] == "CVPR 2024"


def test_批量复用索引缓存_列表页只抓一次(app):
    task = make_task(app, [TITLE, SPARSE, MISSING])
    fake = cvf_fetcher()
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=fake)
    assert fake.urls().count(CVF_LIST_URL) == 1
    assert fake.kinds() == ["list", "detail", "detail"]


def test_批量_不存在题目判失败且继续后续(app, db):
    task = make_task(app, [MISSING, TITLE])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())
    item = db.execute(
        "SELECT fail_reason FROM crawl_task_item WHERE input_title = ?",
        (MISSING,)).fetchone()
    assert item["fail_reason"] == "NOT_FOUND_CVF"


# ---------------------------------------------------------------
# 停手规则
# ---------------------------------------------------------------
def test_进程重启后running任务被恢复为paused(app, db):
    task = make_task(app, [TITLE, SPARSE])
    # 模拟「上次进程死掉时这任务还在 running」：没有线程，只有库里的 running 行
    with app.app_context():
        storage.update_task(task["task_id"], status="running")

    recovered = batch.recover_stale_tasks(app)
    assert recovered == 1

    row = db.execute("SELECT status, pause_reason FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert row["status"] == "paused"
    assert row["pause_reason"] == batch.PAUSE_INTERRUPTED
def test_熔断触发则暂停并保留pending(app, db):
    # 站点 429：fetcher 的 blocked_hosts 非空 → 跑完当前这条就停手
    task = make_task(app, [TITLE, SPARSE])
    fake = FakeFetcher({CVF_LIST_URL: CVF_INDEX, TITLE_DETAIL: CVF_DETAIL_HTML,
                        SPARSE_DETAIL: _SPARSE_HTML},
                       blocked_hosts=["openaccess.thecvf.com"])

    with app.app_context():
        batch.run(app, task["task_id"], fetcher=fake)

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert row["status"] == "paused"
    assert row["pause_reason"] == batch.PAUSE_BREAKER
    # 第一条已成功，剩下的留在 pending，等续跑
    items = db.execute(
        "SELECT input_title, status FROM crawl_task_item "
        "WHERE task_id = ? ORDER BY seq", (row["id"],)).fetchall()
    assert [(i["input_title"], i["status"]) for i in items] == \
        [(TITLE, "success"), (SPARSE, "pending")]


# ---------------------------------------------------------------
# 全部入库
# ---------------------------------------------------------------
def test_commit写paper并返回计数(app, db):
    task = make_task(app, [TITLE, SPARSE])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())
        counts = batch.commit_staged(task["task_id"])

    assert counts == {"inserted": 2, "updated": 0, "skipped_dup": 0}
    papers = db.execute("SELECT title, source FROM paper ORDER BY id").fetchall()
    assert [p["title"] for p in papers] == [TITLE, SPARSE]
    assert all(p["source"] == "cvf" for p in papers)
    # 明细指回 paper
    linked = db.execute(
        "SELECT COUNT(*) AS c FROM crawl_task_item WHERE paper_id IS NOT NULL"
    ).fetchone()["c"]
    assert linked == 2


def test_commit可重复调用_第二次全skipped(app, db):
    task = make_task(app, [TITLE])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())
        batch.commit_staged(task["task_id"])
        again = batch.commit_staged(task["task_id"])
    assert again == {"inserted": 0, "updated": 0, "skipped_dup": 1}
    assert db.execute("SELECT COUNT(*) AS c FROM paper").fetchone()["c"] == 1


def test_commit只入库成功的题目(app, db):
    task = make_task(app, [TITLE, MISSING])
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=cvf_fetcher())
        counts = batch.commit_staged(task["task_id"])
    assert counts["inserted"] == 1
    assert db.execute("SELECT COUNT(*) AS c FROM paper").fetchone()["c"] == 1


# ---------------------------------------------------------------
# 断点续爬
# ---------------------------------------------------------------
def test_resume只跑pending_成功的不重来(app, db):
    task = make_task(app, [TITLE, SPARSE])
    # 模拟「TITLE 已成功、SPARSE 未跑」就停了
    with app.app_context():
        items = storage.list_items(task["id"])
        storage.finish_item(items[0]["id"], "success",
                            parsed={"input_title": TITLE})
        storage.bump_task(task["task_id"], cursor=1, finished=1, success=1)
        storage.pause_task(task["task_id"], batch.PAUSE_BREAKER)

    fake = cvf_fetcher()
    with app.app_context():
        batch.run(app, task["task_id"], fetcher=fake)

    row = db.execute("SELECT * FROM crawl_task WHERE task_id = ?",
                     (task["task_id"],)).fetchone()
    assert (row["status"], row["finished"], row["success"]) == ("done", 2, 2)
    # TITLE 的详情页没再被抓，只有 SPARSE 的
    assert TITLE_DETAIL not in fake.urls()
    assert SPARSE_DETAIL in fake.urls()


# ---------------------------------------------------------------
# HTTP 接口层
# ---------------------------------------------------------------
def _post_import(client, app, fetcher, **payload):
    service.set_fetcher(fetcher)
    return client.post("/api/v1/papers/import", json=payload)


def test_API_批量导入JSON_返回task_id并识别N条(app, client):
    text = f"{TITLE}\n{SPARSE}\n{MISSING}"
    resp = _post_import(client, app, cvf_fetcher(), type="titles", text=text,
                        conference_code="CVPR", year=2024)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["code"] == 0
    assert "识别到 3 条" in body["message"]
    data = body["data"]
    assert data["total"] == 3 and data["type"] == "batch_titles"
    assert data["auto_commit"] is False
    assert data["poll_url"].endswith(data["task_id"])

    task = wait_finished(app, data["task_id"])
    assert (task["status"], task["success"], task["failed"]) == ("done", 2, 1)


def test_API_批量导入file上传txt(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", data={
        "type": "titles", "conference_code": "CVPR", "year": "2024",
        "file": (io.BytesIO(f"{TITLE}\n{SPARSE}\n".encode()), "titles.txt"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total"] == 2
    task = wait_finished(app, data["task_id"])
    assert task["success"] == 2


def test_API_批量导入csv跳过表头(app, client):
    service.set_fetcher(cvf_fetcher())
    resp = client.post("/api/v1/papers/import", data={
        "type": "titles", "conference_code": "CVPR", "year": "2024",
        "file": (io.BytesIO(f"title,authors\n{TITLE}\n".encode()), "l.csv"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 200
    assert resp.get_json()["data"]["total"] == 1


def test_API_进度查询含批量字段(app, client):
    text = f"{TITLE}\n{MISSING}"
    resp = _post_import(client, app, cvf_fetcher(), type="titles", text=text,
                        conference_code="CVPR", year=2024)
    task_id = resp.get_json()["data"]["task_id"]
    wait_finished(app, task_id)

    body = client.get(f"/api/v1/tasks/{task_id}").get_json()["data"]
    assert body["status"] == "done"
    assert body["finished"] == 2 and body["percent"] == 100.0
    # §4.1 ③ 的批量字段都在
    for key in ("current_title", "elapsed_sec", "eta_sec", "qps", "cursor",
                "recent_failures"):
        assert key in body
    assert body["eta_sec"] == 0                        # 跑完了，剩余 0
    assert len(body["recent_failures"]) == 1
    assert body["recent_failures"][0]["fail_reason"] == "NOT_FOUND_CVF"
    assert "item_id" in body["recent_failures"][0]


def test_API_commit_全部入库(app, client):
    resp = _post_import(client, app, cvf_fetcher(), type="titles",
                        text=f"{TITLE}\n{SPARSE}", conference_code="CVPR",
                        year=2024)
    task_id = resp.get_json()["data"]["task_id"]
    wait_finished(app, task_id)

    commit = client.post(f"/api/v1/tasks/{task_id}/commit").get_json()
    assert commit["data"] == {"inserted": 2, "updated": 0, "skipped_dup": 0}


def test_API_resume_从断点续跑(app, client):
    task = make_task(app, [TITLE, SPARSE])
    with app.app_context():
        items = storage.list_items(task["id"])
        storage.finish_item(items[0]["id"], "success",
                            parsed={"input_title": TITLE})
        storage.bump_task(task["task_id"], cursor=1, finished=1, success=1)
        storage.pause_task(task["task_id"], batch.PAUSE_BREAKER)
    service.set_fetcher(cvf_fetcher())

    resp = client.post(f"/api/v1/tasks/{task['task_id']}/resume")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["resumed"] is True and data["pending"] == 1
    assert wait_finished(app, task["task_id"])["success"] == 2


def test_API_resume_已跑完返回409(app, client):
    resp = _post_import(client, app, cvf_fetcher(), type="titles",
                        text=TITLE, conference_code="CVPR", year=2024)
    task_id = resp.get_json()["data"]["task_id"]
    wait_finished(app, task_id)
    assert client.post(f"/api/v1/tasks/{task_id}/resume").status_code == 409


def test_API_type未实现返回400(app, client):
    resp = client.post("/api/v1/papers/import", json={"type": "ris",
                                                      "text": "x"})
    assert resp.status_code == 400
    assert "不支持" in resp.get_json()["message"]


def test_API_空内容返回400(app, client):
    resp = client.post("/api/v1/papers/import", json={"type": "titles",
                                                      "text": "  \n  "})
    assert resp.status_code == 400


def test_API_会议年份不存在返回400(app, client):
    resp = client.post("/api/v1/papers/import",
                       json={"type": "titles", "text": TITLE,
                             "conference_code": "ICCV", "year": 2024})
    assert resp.status_code == 400


def test_API_同会议年份已有任务返回409(app, client):
    # 前置任务直接落库（queued / running / paused 都算「没跑完」），不起真线程：
    # 真任务在零间隔 FakeFetcher 下毫秒级跑完，和下一个请求赛跑的结果不稳定。
    # find_active_task 只认库里的状态，这样构造的前置条件和真跑一等价。
    make_task(app, [TITLE], conference_code="CVPR", year=2024)

    text = f"{TITLE}\n{SPARSE}"
    second = client.post("/api/v1/papers/import",
                         json={"type": "titles", "text": text,
                               "conference_code": "CVPR", "year": 2024})
    assert second.status_code == 409
    assert "任务" in second.get_json()["message"]


def test_API_任务不存在返回404(client):
    assert client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000").status_code == 404
