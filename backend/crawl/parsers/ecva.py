"""ECVA 解析器（ECCV）。

实测结构（2026-09-20，见 scripts/verify_ecva.py）：

  URL: https://www.ecva.net/papers.php
       单个页面用 accordion 列出**所有年份**（2024 / 2022 / 2020 / 2018），
       3.4–3.6 MB，实测 ECCV2024 = 2387 篇
       → 清单阶段只需 1 次请求，但必须按年份过滤

  列表页（给标题 / 作者 / PDF / Springer DOI，**没有摘要、没有 BibTeX**）：
    <dt class="ptitle"><br>
      <a href=papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php>标题</a>
    </dt><dd>
      作者1, 作者2, 作者3*</dd>
    <dd>[<a href='papers/eccv_2024/papers_ECCV/papers/00004.pdf'>pdf</a>]
      <div class="link2">[<a href='...-supp.pdf'>supplementary material</a>]</div>
      <div class="link2">[<a href="https://link.springer.com/chapter/10.1007/...">DOI</a>]</div>
    </dd>

  ⚠️ 两个坑：
    · href 属性**没有引号**（`href=papers/...`），不能自己拼字符串，走 common.abs_url
    · 链接是相对路径且**不带前导斜杠**

  详情页（4.9 KB，有摘要）：
    papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php
    摘要解析走 common.parse_detail()，与 CVF 共用 —— 两站详情页的 DOM id 完全一致。
"""
from ..textutil import normalize_authors
from .common import abs_url, doi_from_url, make_soup

BASE = "https://www.ecva.net"
SOURCE = "ecva"

LIST_URL = f"{BASE}/papers.php"

# 补充材料链接，不是正文 PDF
_SUPP_MARKERS = ("-supp", "supplemental", "supplementary", "_supp")

# 摘要正文不可能长这样；出现说明「第一个 dd」不是作者行（站点改版兜底）
_AUTHOR_DD_REJECTS = ("pdf", "doi", "springer", "supplementary")


def index_url(conference_code, year):
    """ECVA 只有一个列表页，所有年份都在里面 —— conference_code 参数用不上。"""
    return LIST_URL


def year_tag(year):
    """ECCV2024 -> eccv_2024，用于在 href 里筛出目标年份。"""
    return f"eccv_{year}"


def parse_list(html, tag):
    """解析 papers.php，只保留 href 里含 `tag`（如 eccv_2024）的条目。"""
    soup = make_soup(html)
    entries = []

    for dt in soup.select("dt.ptitle"):
        a = dt.find("a")
        if not a:
            continue

        detail_href = a.get("href", "")
        if tag not in detail_href:
            continue

        authors, pdf_url, doi_url = "", "", ""
        seen_dd = 0
        sib = dt.find_next_sibling()
        while sib is not None and sib.name != "dt":
            if sib.name == "dd":
                seen_dd += 1
                text = sib.get_text(" ", strip=True)

                # 第一个 dd 是作者行；但如果它含链接说明顺序变了，别硬当作者
                if seen_dd == 1 and not any(
                    m in text.lower() for m in _AUTHOR_DD_REJECTS
                ):
                    authors = text

                for link in sib.find_all("a"):
                    href = link.get("href", "")
                    low = href.lower()
                    if "springer" in low and not doi_url:
                        doi_url = abs_url(href, BASE)
                    elif low.endswith(".pdf") and not any(m in low for m in _SUPP_MARKERS):
                        if not pdf_url:
                            pdf_url = abs_url(href, BASE)
            sib = sib.find_next_sibling()

        entries.append({
            "title": a.get_text(" ", strip=True),
            "authors": normalize_authors(authors),
            "detail_url": abs_url(detail_href, BASE),
            "pdf_url": pdf_url,
            "doi": doi_from_url(doi_url),
            "doi_url": doi_url,
            "bibtex": "",           # ECVA 列表页没有 BibTeX，保持字段一致便于上层统一处理
        })

    return entries
