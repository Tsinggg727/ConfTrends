"""CVF Open Access 解析器（CVPR / ICCV）。

实测结构（2026-09-20，见 scripts/verify_cvf.py）：

  URL: https://openaccess.thecvf.com/CVPR2024?day=all
       ⚠️ `?day=all` 必需 —— 不带这个参数只返回约 3.7 KB 的空壳页
       实测 CVPR2024 = 7.1 MB / 2716 篇，ICCV2023 = 5.7 MB / 2156 篇

  列表页（一次就带回整届论文 + 完整 BibTeX，覆盖率 100%）：
    <dt class="ptitle"><br><a href="/content/CVPR2024/html/Xxx_2024_CVPR_paper.html">标题</a></dt>
    <dd>
      <form class="authsearch">
        <input type="hidden" name="query_author" value="Haijin Zeng">
        <a href="#">Haijin Zeng</a>,</form> ...
    </dd>
    <dd>
      [<a href="..._paper.pdf">pdf</a>]
      [<a href="..._supplemental.pdf">supp</a>]
      <div class="link2">[<a class="fakelink">bibtex</a>]
        <div class="bibref pre-white-space">@InProceedings{...}</div>
      </div>
    </dd>

  注意：论文条目是 `dt.ptitle`，**没有** `dl.ptitle` 包着 —— 这是最初踩过的坑。

  详情页（只有摘要需要进来，6.5 KB）：
    content/CVPR2024/html/Xxx_2024_CVPR_paper.html
    摘要解析走 common.parse_detail()，与 ECVA 共用。
"""
from ..textutil import normalize_authors, normalize_pages
from .common import abs_url, bib_field, bibtex_key, make_soup

BASE = "https://openaccess.thecvf.com"
SOURCE = "cvf"

# 这些链接是补充材料，不是正文 PDF
_SUPP_MARKERS = ("_supp", "supplemental", "supplementary")


def index_url(conference_code, year):
    """整届索引页。`?day=all` 不能省。"""
    return f"{BASE}/{conference_code}{year}?day=all"


def parse_list(html, tag=None):
    """解析整届索引页，返回条目列表。

    条目里保留**原始 BibTeX 字符串**而不是当场拆字段 ——
    整届 2716 条里我们通常只用得上 1 条，字段拆解留到命中之后再按需做
    （见 parse_bibtex），省下几万次正则，也省内存。

    `tag` 参数是为了和 ecva.parse_list 保持同一个签名（ECVA 需要它筛年份），
    CVF 一届一个页面，用不上。
    """
    soup = make_soup(html)
    entries = []

    for dt in soup.select("dt.ptitle"):
        a = dt.find("a")
        if not a:
            continue

        authors, pdf_url, bibtex = "", "", ""
        # 往后收集同级 <dd>，遇到下一个 <dt> 就停 —— 这是这一页的组织方式
        sib = dt.find_next_sibling()
        while sib is not None and sib.name != "dt":
            if sib.name == "dd":
                if not authors:
                    names = [
                        i.get("value", "").strip()
                        for i in sib.select("input[name=query_author]")
                    ]
                    if names:
                        authors = ", ".join(n for n in names if n)

                if not bibtex:
                    bib = sib.select_one("div.bibref")
                    if bib:
                        bibtex = bib.get_text().strip()

                if not pdf_url:
                    for link in sib.find_all("a"):
                        href = link.get("href", "")
                        low = href.lower()
                        if low.endswith(".pdf") and not any(m in low for m in _SUPP_MARKERS):
                            pdf_url = abs_url(href, BASE)
                            break
            sib = sib.find_next_sibling()

        entries.append({
            "title": a.get_text(" ", strip=True),
            "authors": authors,
            "detail_url": abs_url(a.get("href", ""), BASE),
            "pdf_url": pdf_url,
            "bibtex": bibtex,
        })

    return entries


def parse_bibtex(bibtex):
    """把一条 BibTeX 拆成字段。写库前才调用（只对命中的那一条）。"""
    if not bibtex:
        return {}
    return {
        "bibtex_key": bibtex_key(bibtex),
        "bibtex_title": bib_field(bibtex, "title"),
        "authors": normalize_authors(bib_field(bibtex, "author")),
        "venue_raw": bib_field(bibtex, "booktitle"),
        "year": bib_field(bibtex, "year"),
        "pages": normalize_pages(bib_field(bibtex, "pages")),
    }
