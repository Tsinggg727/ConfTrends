"""标题归一化与匹配的测试。

这是防「张冠李戴」的闸门，所以用例里反向的（**不该**匹配上）比正向的更重要。
"""
from crawl.textutil import (MIN_FUZZY_LEN, build_index, match_title,
                            normalize_authors, normalize_pages,
                            normalize_title, similarity)


# ---------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------
def test_归一化转小写并去标点():
    assert normalize_title("Neural Radiance Fields: A Survey!") == \
        "neural radiance fields a survey"


def test_归一化还原latex转义():
    assert normalize_title(r"R{\'e}sum{\'e} of {3D} Splatting") == "resume of 3d splatting"
    assert normalize_title(r"Mart{\'i}n") == "martin"


def test_归一化解html实体():
    assert normalize_title("Fast &amp; Accurate Tracking") == "fast accurate tracking"


def test_归一化合并重音符号():
    assert normalize_title("Résumé") == normalize_title("Resume") == "resume"
    assert normalize_title("Über") == "uber"


def test_归一化去掉行内公式():
    assert normalize_title("A $O(n^2)$ Algorithm") == "a algorithm"


def test_归一化压缩空白():
    assert normalize_title("  Two   Spaces \n and newline ") == "two spaces and newline"


def test_归一化空输入():
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


def test_作者与页码归一化():
    assert normalize_authors("Zeng, Haijin and Li, Wei") == "Zeng, Haijin, Li, Wei"
    assert normalize_authors("Solo Author") == "Solo Author"
    assert normalize_authors("") == ""
    assert normalize_pages("1234--1243") == "1234-1243"
    assert normalize_pages(" 12 - 14 ") == "12-14"
    assert normalize_pages("") == ""


# ---------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------
PAPERS = [
    {"title": "Diffusion Models Beat GANs on Image Synthesis",
     "detail_url": "https://example.com/a"},
    {"title": "Neural Radiance Fields for Scene Reconstruction",
     "detail_url": "https://example.com/b"},
    {"title": "Segment Anything", "detail_url": "https://example.com/c"},
]
INDEX = build_index(PAPERS)


def test_精确命中():
    m = match_title("Diffusion Models Beat GANs on Image Synthesis", INDEX)
    assert m.matched and m.reason == "exact" and m.score == 1.0
    assert m.entry["detail_url"] == "https://example.com/a"


def test_大小写与标点不影响命中():
    m = match_title("diffusion models beat gans on image synthesis!", INDEX)
    assert m.matched and m.reason == "exact"


def test_半截题目走包含匹配():
    m = match_title("Diffusion Models Beat GANs", INDEX)
    assert m.matched and m.reason == "contains" and m.score >= 0.90


def test_混入多余词也能命中():
    m = match_title("Neural Radiance Fields for Scene Reconstruction (CVPR 2024)", INDEX)
    assert m.matched and m.reason == "contains"


def test_错字在阈值内仍可命中():
    m = match_title("Neural Radience Fields for Scene Reconstruction", INDEX)
    assert m.matched and m.reason in ("fuzzy", "contains")
    assert m.score >= 0.90


def test_不相干题目判失败而不是乱匹配():
    m = match_title("A Completely Different Paper About Cooking", INDEX)
    assert not m.matched
    assert m.reason == "none"


def test_短题目不做模糊匹配():
    """短查询做包含匹配会命中一大片，是错配的主要来源。"""
    assert len(normalize_title("GANs")) < MIN_FUZZY_LEN
    m = match_title("GANs", INDEX)
    assert not m.matched


def test_未命中时带近似候选供人工确认():
    m = match_title("Neural Radiance Field for Scene Reconstruction", INDEX)
    if not m.matched:
        assert m.candidates and m.candidates[0]["score"] >= 0.60


def test_共享前缀但不达阈值时给出候选():
    m = match_title("Diffusion Models Beat GANs on Image Generatio", INDEX)
    # 差一个词：要么命中（fuzzy），要么给出候选，二者必有其一
    assert m.matched or m.candidates


def test_相似度函数():
    assert similarity("abc", "abc") == 1.0
    assert similarity("", "abc") == 0.0
    assert 0 < similarity("abc", "abd") < 1


def test_索引去重保留首个():
    index = build_index([
        {"title": "Same Title", "detail_url": "first"},
        {"title": "same  title!", "detail_url": "second"},
    ])
    assert len(index) == 1
    assert index["same title"]["detail_url"] == "first"
