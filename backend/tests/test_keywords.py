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


# ---------------------------------------------------------------
# 泛词单字禁用（短语保留）与指标缩写禁用（方向名保留）
# ---------------------------------------------------------------
def test_泛词单字禁用但短语保留(app, db):
    _seed(db, "Deep Learning for Image Segmentation",
          "Deep learning and self-supervised learning drive image "
          "segmentation research. Our diffusion model improves image "
          "segmentation quality across benchmarks. Self-supervised learning "
          "pretraining boosts the diffusion model further. The system uses "
          "text signals and task specific features for segmentation.")

    with app.app_context():
        keywords.rebuild_keywords()
    names = _names(db, db.execute("SELECT id FROM paper").fetchone()["id"])

    # 泛词不再以独立关键词出现
    for banned in ("model", "image", "feature", "task", "text",
                   "system", "signal"):
        assert banned not in names, f"泛词 {banned!r} 不该成为关键词"
    # 含泛词的有效短语照常保留
    for phrase in ("deep learning", "self-supervised learning",
                   "image segmentation", "diffusion model"):
        assert phrase in names, f"有效短语 {phrase!r} 应保留"


def test_指标缩写禁用_方向名保留(app, db):
    _seed(db, "CLIP Guided Neural Rendering",
          "We evaluate with mse psnr lpips frossl metrics. CLIP features "
          "guide neural rendering. MSE and PSNR are reported per dataset. "
          "NeRF baselines are compared with our CLIP guided pipeline.")
    _seed(db, "3DGS Compression",
          "3dgs renders scenes with mse psnr metrics. 3dgs compression "
          "saves storage for streaming.")
    # nerf 单独一篇反复提及，避免「tf=1 被 Top 8 挤掉」的排序性缺席
    _seed(db, "NeRF Revisited",
          "NeRF improves neural rendering. NeRF baselines and NeRF "
          "variants are compared across scenes.")

    with app.app_context():
        keywords.rebuild_keywords()

    for banned in ("mse", "psnr", "lpips", "frossl"):
        row = db.execute("SELECT COUNT(*) AS c FROM keyword WHERE name_key = ?",
                         (banned,)).fetchone()["c"]
        assert row == 0, f"指标缩写 {banned!r} 不该成为关键词"
    nerf_paper = db.execute(
        "SELECT id FROM paper WHERE title = 'NeRF Revisited'").fetchone()["id"]
    assert "nerf" in _names(db, nerf_paper)
    clip_paper = db.execute(
        "SELECT id FROM paper WHERE title = 'CLIP Guided Neural Rendering'"
    ).fetchone()["id"]
    assert "clip" in _names(db, clip_paper)
    gs_paper = db.execute(
        "SELECT id FROM paper WHERE title = '3DGS Compression'").fetchone()["id"]
    assert "3dgs" in _names(db, gs_paper)


# ---------------------------------------------------------------
# 词形折叠
# ---------------------------------------------------------------
def test_词形折叠_detect归并到detection(app, db):
    _seed(db, "We Detect Salient Objects",
          "Our network detects objects and we detect boundaries in images.")
    _seed(db, "Salient Object Detection Survey",
          "Salient object detection methods are surveyed. Detection "
          "networks are grouped by supervision.")

    with app.app_context():
        keywords.rebuild_keywords()

    detect_rows = db.execute(
        "SELECT COUNT(*) AS c FROM keyword WHERE name_key IN ('detect', 'detected')"
    ).fetchone()["c"]
    assert detect_rows == 0                       # 变体不单独成词
    detection = db.execute(
        "SELECT COUNT(*) AS c FROM keyword WHERE name_key = 'detection'"
    ).fetchone()["c"]
    assert detection == 1                         # 归并为一行
    names = [_names(db, p) for p in
             [r["id"] for r in db.execute("SELECT id FROM paper")]]
    assert all("detection" in ns for ns in names)  # 两篇都指向规范词


def test_词形折叠_3dg与3dgs归并(app, db):
    _seed(db, "3DGS Rendering Pipeline", "The 3dgs pipeline renders fast.")
    _seed(db, "3DG Avatar Animation", "The 3dg avatar animates faces.")

    with app.app_context():
        keywords.rebuild_keywords()

    rows = db.execute(
        "SELECT name, name_key FROM keyword WHERE name_key IN ('3dgs', '3dg')"
    ).fetchall()
    assert [(r["name"], r["name_key"]) for r in rows] == [("3dgs", "3dgs")]
    for pid in [r["id"] for r in db.execute("SELECT id FROM paper")]:
        assert "3dgs" in _names(db, pid)


def test_单复数与modeling折叠不留变体行(app, db):
    _seed(db, "Generative Models", "Generative modeling of images.")
    _seed(db, "World Modeling", "A world model for agents.")

    with app.app_context():
        keywords.rebuild_keywords()

    for stale in ("models", "modeling"):
        assert db.execute("SELECT COUNT(*) AS c FROM keyword WHERE name_key = ?",
                          (stale,)).fetchone()["c"] == 0
    # 两个变体写法都归到同一规范词
    assert db.execute(
        "SELECT COUNT(*) AS c FROM keyword WHERE name_key = 'generative model'"
    ).fetchone()["c"] == 1


def test_所有格撇号不产生幽灵关键词(app, db):
    # 回归：model's → _singular 剥 s 会暴露尾部撇号成 model'，绕过泛词禁用，
    # 再经 link_keywords 的 normalize_title 洗成 "model" 混进关键词表
    _seed(db, "TEA: Test-time Energy Adaptation",
          "Our model's reliance on pre-trained model weights hurts the "
          "model's calibration. LLMs' features guide the model alignment.")
    _seed(db, "Vision Survey", "Vision transformers advance vision research "
                               "across many vision benchmarks and tasks.")

    with app.app_context():
        keywords.rebuild_keywords()

    for stale in ("model", "models", "llms"):
        assert db.execute("SELECT COUNT(*) AS c FROM keyword WHERE name_key = ?",
                          (stale,)).fetchone()["c"] == 0, f"{stale!r} 是幽灵关键词"
    # llms' 折叠成 llm 后是否成行取决于排序（小语料 tf=1 排不进 Top 8），
    # 这里只断言幽灵行不存在


# ---------------------------------------------------------------
# 方案C：缩写假词门槛 + 弱实词边界表（规则实现，本次不重建真实库）
# ---------------------------------------------------------------
def test_缩写假词门槛_白名单豁免(app, db):
    # ttt / ed：低频短字母缩写 → 应被门槛挡掉
    _seed(db, "TTT and ED Ablations for Segmentation",
          "TTT improves segmentation. ED is an ablation on segmentation. "
          "Segmentation results compare ttt and ed variants on benchmarks.")
    # clip：同样低频，但在方向名白名单里 → 必须幸存（门槛误杀的直接检验）
    _seed(db, "CLIP for Zero-Shot Classification",
          "CLIP enables zero shot classification. CLIP visual encoder "
          "aligns images with text for classification.")

    with app.app_context():
        keywords.rebuild_keywords()

    for banned in ("ttt", "ed"):
        assert db.execute("SELECT COUNT(*) AS c FROM keyword WHERE name_key = ?",
                          (banned,)).fetchone()["c"] == 0
    clip_paper = db.execute(
        "SELECT id FROM paper WHERE title LIKE 'CLIP%'").fetchone()["id"]
    assert "clip" in _names(db, clip_paper)


def test_缩写假词门槛_双缩写bigram一并丢弃(app, db):
    # 评估报告里的 bo sd：两个缩写拼成的假 bigram，单个缩写都过不了门槛，
    # 组合体也必须消失（门槛在 bigram 上的传播规则）
    _seed(db, "Bayesian Optimization Distillation Study",
          "We call our method BO SD for short. BO SD tunes the pipeline. "
          "The method bayesian optimization distillation works well on tasks.")

    with app.app_context():
        keywords.rebuild_keywords()

    assert db.execute("SELECT COUNT(*) AS c FROM keyword WHERE name_key = 'bo sd'"
                      ).fetchone()["c"] == 0


def test_弱实词边界表_单字与碎片一并消失(app, db):
    # single blurry / size kernel / third kind 是评估报告点名的碎片；
    # 弱实词进 STOPWORDS 后，旁边真正的概念（blurry image）应能浮现
    _seed(db, "Detection in the Third Kind",
          "We study single blurry image detection with a size kernel "
          "design. The blurry image results and kernel design are strong. "
          "Additional growth exit analysis follows the kind of tasks.")

    with app.app_context():
        keywords.rebuild_keywords()

    names = _names(db, db.execute("SELECT id FROM paper").fetchone()["id"])
    joined = " ".join(names)
    for banned in ("kind", "growth", "exit", "additional",
                   "single", "size", "third",
                   "single blurry", "size kernel", "third kind",
                   "additional growth", "additional label"):
        assert banned not in names, f"{banned!r} 应被边界表挡住"
    assert "blurry image" in joined             # 真概念从碎片旁浮现


# ---------------------------------------------------------------
# 方案A：统计口径查询的 DF 过滤
# ---------------------------------------------------------------
def _seed_n(db, title, abstract, n):
    """同一关键词语料灌 n 篇（DF=n 的来源）。"""
    for i in range(n):
        _seed(db, f"{title} Study {i}", f"{abstract} Case {i}.")


def test_Top10口径_DF门槛生效(app, db):
    # alpha 出现在全部 8 篇（DF=8，含跨篇复用）、beta 2 篇、gamma 1 篇
    _seed_n(db, "Alpha", "alpha method with beta hints and gamma notes.", 5)
    _seed_n(db, "Beta", "beta model with alpha context and gamma trace.", 2)
    _seed_n(db, "Gamma", "gamma field with alpha context.", 1)

    with app.app_context():
        counts = keywords.rebuild_keywords()
        top = keywords.top_keywords(min_df=3, limit=10)
        full = keywords.top_keywords(min_df=1, limit=100)

    assert counts["with_keywords"] == 8              # 语料确实抽取成功
    names = [r["name"] for r in top]
    assert names[0] == "alpha"                       # DF 最高的居首
    assert all(r["df"] >= 3 for r in top)            # 口径硬约束
    assert "beta" not in names and "gamma" not in names   # DF=2/1 被挡
    assert {"beta", "gamma"} & {r["name"] for r in full}  # 不过滤时它们在


def test_图谱口径_节点数显著缩减(app, db):
    _seed_n(db, "Alpha", "alpha method with beta hints and gamma notes.", 5)
    _seed_n(db, "Beta", "beta model with alpha context and gamma trace.", 2)
    _seed_n(db, "Gamma", "gamma field with alpha context.", 1)

    with app.app_context():
        counts = keywords.rebuild_keywords()
        all_nodes = keywords.graph_keywords(min_df=1)
        graph_nodes = keywords.graph_keywords(min_df=5)

    assert counts["keywords"] >= 5
    # 图谱口径（DF≥5）把长尾挡在门外：节点显著缩减且只留 DF 达标者
    assert len(graph_nodes) < len(all_nodes) / 2
    assert all(r["df"] >= 5 for r in graph_nodes)
    names = {r["name"] for r in graph_nodes}
    assert "alpha" in names
    assert "beta" not in names and "gamma" not in names   # DF=2/1 不进图谱


def test_统计口径阈值在config且可回滚(app):
    from flask import current_app
    with app.app_context():
        assert current_app.config["STATS_KEYWORD_MIN_DF"] == 3
        assert current_app.config["GRAPH_KEYWORD_MIN_DF"] == 5
    # 回滚语义：阈值改成 1 等价于不过滤
    with app.app_context():
        rows = keywords.top_keywords(min_df=1, limit=100)
    assert all(r["df"] >= 1 for r in rows)
