"""解析器单元测试 —— 全部跑在本地 fixture 上，不联网。

fixture 是按实测的真实 HTML 结构裁剪出来的（见 scripts/verify_cvf.py /
verify_ecva.py 的注释），所以这些用例同时也在守护「站点结构假设」：
哪天站点改版，改掉的不只是代码，还有这里的样例。
"""
from conftest import fixture
from crawl.parsers import cvf, ecva, parse_detail
from crawl.parsers.common import (bib_field, bibtex_key, clean_abstract,
                                  doi_from_url, meta_content, make_soup)
from crawl.textutil import normalize_title

CVF_INDEX = fixture("cvf_index.html")
CVF_DETAIL = fixture("cvf_detail.html")
ECVA_LIST = fixture("ecva_list.html")
ECVA_DETAIL = fixture("ecva_detail.html")


# ---------------------------------------------------------------
# CVF 列表页
# ---------------------------------------------------------------
def test_cvf_跳过非论文条目():
    """`dt` 里只有 class=ptitle 且带 <a> 的才是论文。"""
    entries = cvf.parse_list(CVF_INDEX)
    assert len(entries) == 4
    titles = [e["title"] for e in entries]
    assert "Session 3A: Reconstruction" not in titles
    assert "Broken entry without a link" not in titles


def test_cvf_条目字段齐全():
    first = cvf.parse_list(CVF_INDEX)[0]
    assert first["title"] == "Neural Radiance Fields for Scene Reconstruction"
    assert first["authors"] == "Haijin Zeng, Wei Li"
    assert first["detail_url"] == (
        "https://openaccess.thecvf.com/content/CVPR2024/html/"
        "Zeng_Neural_Radiance_2024_CVPR_paper.html")
    assert first["bibtex"].startswith("@InProceedings{Zeng_2024_CVPR,")


def test_cvf_正文pdf不被补充材料顶替():
    entries = cvf.parse_list(CVF_INDEX)
    assert entries[0]["pdf_url"].endswith("Zeng_Neural_Radiance_2024_CVPR_paper.pdf")
    assert "_supp" not in entries[0]["pdf_url"].lower()


def test_cvf_只有补充材料时pdf留空():
    only_supp = cvf.parse_list(CVF_INDEX)[3]
    assert only_supp["title"] == "Only Supplement Available"
    assert only_supp["pdf_url"] == ""


def test_cvf_缺bibtex的条目仍可解析():
    entry = cvf.parse_list(CVF_INDEX)[2]
    assert entry["bibtex"] == ""
    assert entry["pdf_url"].endswith("Chen_Sparse_Views_2024_CVPR_paper.pdf")
    assert cvf.parse_bibtex(entry["bibtex"]) == {}


def test_cvf_bibtex字段解析():
    bib = cvf.parse_list(CVF_INDEX)[0]["bibtex"]
    assert bibtex_key(bib) == "Zeng_2024_CVPR"
    assert bib_field(bib, "title") == "Neural Radiance Fields for Scene Reconstruction"
    assert bib_field(bib, "author") == "Zeng, Haijin and Li, Wei"
    assert bib_field(bib, "year") == "2024"
    assert bib_field(bib, "pages") == "1234-1243"
    assert "Conference on Computer Vision and Pattern Recognition" in bib_field(bib, "booktitle")


def test_cvf_bibtex标题里的嵌套花括号不被截断():
    """`title = {R{\\'e}sum{\\'e} of {3D} ...}` —— 非贪婪正则会在这里截断。"""
    bib = cvf.parse_list(CVF_INDEX)[1]["bibtex"]
    assert bib_field(bib, "title") == r"R{\'e}sum{\'e} of {3D} Gaussian Splatting"


def test_cvf_bibtex转成入库字段():
    """作者用 and 分隔 → 逗号；页码 5678--5689 → 5678-5689。"""
    parsed = cvf.parse_bibtex(cvf.parse_list(CVF_INDEX)[1]["bibtex"])
    assert parsed["authors"] == "Martín, Ana"
    assert parsed["pages"] == "5678-5689"
    assert parsed["year"] == "2024"


def test_cvf_bibtex标题与列表页标题归一化后一致():
    """列表页的 Résumé 与 BibTeX 的 R{\\'e}sum{\\'e} 应当归一成同一个 key。"""
    entries = cvf.parse_list(CVF_INDEX)
    list_title = entries[1]["title"]
    bib_title = bib_field(entries[1]["bibtex"], "title")
    assert list_title != bib_title                      # 字面不同
    assert normalize_title(list_title) == normalize_title(bib_title)  # 归一后相同
    assert normalize_title(list_title) == "resume of 3d gaussian splatting"


# ---------------------------------------------------------------
# ECVA 列表页
# ---------------------------------------------------------------
def test_ecva_按年份过滤():
    """papers.php 一个页面混着所有年份，必须只留目标届。"""
    entries = ecva.parse_list(ECVA_LIST, "eccv_2024")
    assert len(entries) == 2
    assert all("eccv_2024" in e["detail_url"] for e in entries)
    assert all("ECCV 2022" not in e["title"] for e in entries)


def test_ecva_上一届被排除():
    assert ecva.parse_list(ECVA_LIST, "eccv_2022")[0]["title"] == \
        "Old Paper From The Previous Edition"


def test_ecva_无引号href补成绝对链接():
    first = ecva.parse_list(ECVA_LIST, "eccv_2024")[0]
    assert first["detail_url"] == (
        "https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php")


def test_ecva_条目字段齐全():
    first = ecva.parse_list(ECVA_LIST, "eccv_2024")[0]
    assert first["title"] == "Selective Distillation for Open Vocabulary Segmentation"
    assert first["authors"] == "Zheng Li, Marco Rossi, Anne Dubois"
    assert first["pdf_url"] == (
        "https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/00004.pdf")
    assert first["bibtex"] == ""            # ECVA 列表页没有 BibTeX


def test_ecva_补充材料被排除():
    first = ecva.parse_list(ECVA_LIST, "eccv_2024")[0]
    assert "-supp" not in first["pdf_url"]


def test_ecva_doi从springer链接提取():
    entries = ecva.parse_list(ECVA_LIST, "eccv_2024")
    assert entries[0]["doi"] == "10.1007/978-3-031-73232-4_1"
    assert entries[1]["doi"] == "10.1007/978-3-031-73232-4_2"


# ---------------------------------------------------------------
# 详情页（两站共用）
# ---------------------------------------------------------------
def test_两站详情页共用同一份解析():
    cvf_paper = parse_detail(CVF_DETAIL)
    ecva_paper = parse_detail(ECVA_DETAIL)

    for paper, expected in (
        (cvf_paper, "Neural Radiance Fields for Scene Reconstruction"),
        (ecva_paper, "Selective Distillation for Open Vocabulary Segmentation"),
    ):
        assert paper["title"] == expected
        assert paper["authors"]
        assert len(paper["abstract"]) > 100
        assert not paper["abstract_truncated"]


def test_cvf详情页的citation_doi分支():
    """⚠️ 这个 DOI 是 fixture 里造的，**真实 CVF 页面并没有 citation_doi**。

    2026-09-20 实测：CVF 详情页只有 citation_title / citation_author，
    索引页的 doi 也为空 —— CVF 侧确实完全没有 DOI（与设计文档 §0.3 一致）。

    保留这个用例，是因为详情解析器读 citation_doi 是一条零成本的分支：
    哪天 CVF 补上 DOI，不用改代码就能接住。但它**不能**用来断言
    「CVF 论文有 DOI」——真实数据里 doi 就是空串。
    """
    assert parse_detail(CVF_DETAIL)["doi"] == "10.1109/CVPR52688.2024.00000"


def test_真实CVF详情页没有doi时字段为空串():
    """剥离掉 DOI 后的同一份 fixture —— 对应站点当前的实际情况。"""
    import re
    html = re.sub(r'<meta[^>]*citation_doi[^>]*>', "", CVF_DETAIL)
    assert parse_detail(html)["doi"] == ""


def test_ecva详情页摘要标点完整():
    """ECVA 的摘要保留逗号（CVF 那一侧被站点剥掉了，见设计文档 §0.2）。"""
    abstract = parse_detail(ECVA_DETAIL)["abstract"]
    assert abstract.count(",") >= 3


def test_详情页meta标签兜底():
    """三个 div 都读不到时退回 citation_* meta —— 站点改版时不至于全瞎。"""
    html = """<html><head>
        <meta name="citation_title" content="Fallback Title">
        <meta name="citation_author" content="A. One">
        <meta name="citation_author" content="B. Two">
        <meta name="citation_abstract" content="An abstract from meta.">
      </head><body></body></html>"""
    paper = parse_detail(html)
    assert paper["title"] == "Fallback Title"
    assert paper["authors"] == "A. One, B. Two"
    assert paper["abstract"] == "An abstract from meta."


def test_详情页缺摘要时返回空串():
    paper = parse_detail("<html><body><div id='papertitle'>T</div></body></html>")
    assert paper["abstract"] == ""
    assert paper["title"] == "T"


def test_摘要清洗与截断():
    long_text = "Sentence one. " * 400           # 6000 字符
    cleaned, truncated = clean_abstract(long_text)
    assert truncated is True
    assert len(cleaned) <= 4000
    assert cleaned.endswith(".")                 # 截断落在句末

    short, truncated = clean_abstract("  Abstract:   hello \n\n world  ")
    assert (short, truncated) == ("hello world", False)


# ---------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------
def test_doi提取():
    assert doi_from_url("https://link.springer.com/chapter/10.1007/978-3-031-73232-4_1") \
        == "10.1007/978-3-031-73232-4_1"
    assert doi_from_url("") == ""
    assert doi_from_url("https://example.com/no-doi-here") == ""


def test_解析器按来源注册():
    from crawl.parsers import PARSERS, get_parser
    assert set(PARSERS) == {"cvf", "ecva"}
    assert get_parser("cvf") is cvf
    assert get_parser("ecva") is ecva


def test_meta_content读不到返回空串():
    soup = make_soup("<html><head></head><body></body></html>")
    assert meta_content(soup, "citation_doi") == ""
