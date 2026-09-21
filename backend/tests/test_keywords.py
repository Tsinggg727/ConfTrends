"""关键词抽取（阶段五）—— 设计文档 §1.1。

覆盖四条验收线：
  1. 抽取结果非空且结构正确（rank 从 1 连续、weight ∈ (0,1] 随 rank 递减）；
  2. 归一化生效（停用词剔除、单复数合并、同义词短语归并 3dgs）；
  3. IDF 是全量语料口径（全库共现的词 IDF 低于特异词，直接影响排序）；
  4. 重建幂等（重跑不产生重复行、计数不变）。

语料直接落库构造，不经过爬取链路 —— 抽取只认 paper 表的 title/abstract。
"""
import sqlite3

import pytest

from crawl import keywords


@pytest.fixture()
def db(app):
    conn = sqlite3.connect(app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _seed(db, title, abstract=""):
    cur = db.execute(
        """INSERT INTO paper (title, title_key, year, abstract, source, status)
             VALUES (?, ?, 2024, ?, 'cvf', 'active')""",
        (title, title.lower(), abstract))
    db.commit()
    return cur.lastrowid


def _links(db, paper_id):
    return db.execute(
        """SELECT k.name, k.name_key, pk.weight, pk.rank
             FROM paper_keyword pk JOIN keyword k ON k.id = pk.keyword_id
            WHERE pk.paper_id = ? ORDER BY pk.rank""", (paper_id,)).fetchall()


def _names(db, paper_id):
    return [r["name"] for r in _links(db, paper_id)]


# ---------------------------------------------------------------
# 结构：非空、Top 5–8、rank/weight 合理
# ---------------------------------------------------------------
def test_抽取结果非空且结构合理(app, db):
    _seed(db, "Neural Radiance Fields for Scene Reconstruction",
          "We present neural radiance fields that reconstruct scenes from "
          "sparse views. Radiance fields optimize volume rendering with "
          "positional encoding and achieve state of the art novel view "
          "synthesis quality on benchmark datasets.")
    _seed(db, "Diffusion Models Beat GANs on Image Synthesis",
          "Diffusion models achieve superior image sample quality. "
          "Classifer guidance improves diffusion model sampling and "
          "image synthesis diversity compared with GAN baselines.")

    with app.app_context():
        counts = keywords.rebuild_keywords()
    assert counts["with_keywords"] == 2

    for row in db.execute("SELECT id FROM paper").fetchall():
        links = _links(db, row["id"])
        assert keywords.TOP_FLOOR <= len(links) <= keywords.TOP_CEIL
        weights = [r["weight"] for r in links]
        ranks = [r["rank"] for r in links]
        assert ranks == list(range(1, len(links) + 1))     # rank 从 1 连续
        assert all(0 < w <= 1.0 for w in weights)          # weight 归一化
        assert weights == sorted(weights, reverse=True)    # 随 rank 递减
    assert counts["links"] == sum(
        len(_links(db, r["id"])) for r in db.execute("SELECT id FROM paper"))
    assert counts["keywords"] >= 10


def test_摘要为空退化为仅题目(app, db):
    _seed(db, "Zero-Shot Semantic Segmentation via Vision-Language Alignment")
    with app.app_context():
        counts = keywords.rebuild_keywords()
    assert counts["with_keywords"] == 1
    names = _names(db, db.execute("SELECT id FROM paper").fetchone()["id"])
    assert 1 <= len(names) <= keywords.TOP_CEIL
    assert any("segmentation" in n for n in names)


# ---------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------
def test_停用词与学术套话不进关键词(app, db):
    _seed(db, "A Novel Benchmark for Point Cloud Registration",
          "In this paper, we propose a method and show results on several "
          "datasets. The proposed approach outperforms existing baselines "
          "and the experiments demonstrate that our point cloud registration "
          "network generalizes across benchmarks with strong performance.")
    with app.app_context():
        keywords.rebuild_keywords()
    names = _names(db, db.execute("SELECT id FROM paper").fetchone()["id"])
    joined = " ".join(names)
    for banned in ("paper", "method", "approach", "propose", "proposed",
                   "result", "show", "the", "we", "and", "of"):
        assert banned not in names, f"{banned!r} 不该出现在关键词里"
    assert "point cloud" in joined


def test_单复数合并(app, db):
    _seed(db, "Diffusion Models Beat GANs", "Diffusion models generate images.")
    _seed(db, "Conditional Diffusion Model", "A diffusion model for text to image.")
    with app.app_context():
        keywords.rebuild_keywords()

    keys = db.execute("SELECT id, name_key FROM keyword").fetchall()
    diffusion = [k for k in keys if k["name_key"] == "diffusion model"]
    assert len(diffusion) == 1                        # 两种写法归并成一行
    name = db.execute("SELECT name FROM keyword WHERE name_key = 'diffusion model'") \
        .fetchone()["name"]
    assert name == "diffusion model"                  # 单数形态作为展示名


def test_同义词归并_3dgs(app, db):
    _seed(db, "3D Gaussian Splatting for Real-Time Radiance Field Rendering",
          "3D Gaussian Splatting achieves real-time rendering. Our gaussian "
          "splatting pipeline outperforms Mip-NeRF on novel view synthesis.")
    _seed(db, "Sparse View 3D Gaussian Splatting",
          "We compress gaussian splatting scenes for few shot reconstruction.")
    with app.app_context():
        keywords.rebuild_keywords()

    rows = db.execute(
        "SELECT name, name_key FROM keyword WHERE name_key = '3dgs'").fetchall()
    assert len(rows) == 1                             # 全称/简写/单复数都归到 3dgs
    for paper in db.execute("SELECT id FROM paper").fetchall():
        assert "3dgs" in _names(db, paper["id"])


# ---------------------------------------------------------------
# IDF 全量语料口径
# ---------------------------------------------------------------
def test_IDF_全库共现词低于特异词(app, db):
    def doc_set(title, abstract):
        return {t for sent in keywords.tokenize(f"{title} {abstract}") for t in sent}

    docs = [doc_set(f"Vision Transformer Survey {i}",
                    "Vision transformers are widely used in vision tasks and "
                    "vision benchmarks across the vision community.")
            for i in range(5)]
    idf = keywords.compute_idf(docs)

    unique = doc_set("Neural Radiance Fields",
                     "Neural radiance fields reconstruct scenes from sparse views.")
    idf_u = keywords.compute_idf(docs + [unique])

    # vision 出现在全部 5 篇 → IDF 应显著低于只出现 1 篇的 radiance
    assert idf["vision"] < idf_u["radiance"]
    assert idf["vision"] == pytest.approx(1.0)        # N==df 时平滑式退化为 1


def test_全库共现词排序被IDF压制(app, db):
    # 4 篇都含 vision，只有 1 篇特异含 radiance field：该篇里特异词应排前
    for i in range(4):
        _seed(db, f"Vision Survey Part {i}",
              "Vision transformers advance vision understanding in vision "
              "research across many vision datasets and vision tasks.")
    pid = _seed(db, "Neural Radiance Fields for Scenes",
                "Neural radiance fields render scenes. Radiance fields "
                "improve novel view synthesis for real scenes with vision.")

    with app.app_context():
        keywords.rebuild_keywords()
    names = _names(db, pid)
    radiance = next(n for n in names if "radiance" in n)
    assert names.index(radiance) <= 2                  # 特异词进入最前
    if "vision" in names:                              # 全库共现词不该反超
        assert names.index(radiance) < names.index("vision")


# ---------------------------------------------------------------
# 幂等与写库
# ---------------------------------------------------------------
def test_重建幂等_不产生重复(app, db):
    _seed(db, "Point Cloud Completion", "Point cloud completion networks.")

    with app.app_context():
        first = keywords.rebuild_keywords()
        second = keywords.rebuild_keywords()

    assert first["links"] == second["links"]
    assert first["keywords"] == second["keywords"]
    assert db.execute("SELECT COUNT(*) AS c FROM paper_keyword").fetchone()["c"] \
        == first["links"]


def test_重建不影响手工关联(app, db):
    _seed(db, "Manual Keyword Paper", "Some abstract about matching.")
    db.execute("INSERT INTO keyword (name, name_key) VALUES ('Manual Tag', 'manual tag')")
    db.execute(
        """INSERT INTO paper_keyword (paper_id, keyword_id, weight, rank, source)
             VALUES (1, (SELECT id FROM keyword WHERE name_key = 'manual tag'),
                     1.0, 1, 'manual')""")
    db.commit()

    with app.app_context():
        keywords.rebuild_keywords()

    manual = db.execute(
        """SELECT COUNT(*) AS c FROM paper_keyword WHERE source = 'manual'"""
    ).fetchone()["c"]
    assert manual == 1                                # source='manual' 幸存


# ---------------------------------------------------------------
# API 入口
# ---------------------------------------------------------------
def test_API_rebuild触发抽取_列表页随之有词(app, client, db):
    _seed(db, "Neural Radiance Fields", "Radiance fields for view synthesis.")
    resp = client.post("/api/v1/keywords/rebuild")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["with_keywords"] == 1 and data["links"] >= 1

    # 功能2 的列表接口 JOIN paper_keyword，抽取后关键词直接可见
    papers = client.get("/api/v1/papers").get_json()["data"]["list"]
    assert papers[0]["keywords"]
