"""可行性验证脚本（非爬虫，只验证假设）。

假设：CVF Open Access 的页面里是否内嵌了 BibTeX 和摘要？

已验证结论（2026-09-20 实测）：
  ✅ BibTeX —— 在【索引页】里就有，且是整届一次性返回
     例：CVPR2024 索引页 7.4MB，含 2716 篇论文 + 2716 段完整 BibTeX
         ICCV2023 索引页 5.7MB，含 2156 篇论文 + 2156 段完整 BibTeX
     → 取 BibTeX 只需 1 次请求，不用逐篇进详情页
  ✅ 摘要 —— 在【详情页】的 <div id="abstract"> 里（详情页仅 6.6KB）
     → 摘要仍需逐篇抓，但完全不消耗 Semantic Scholar 配额
  ⚠️ CVF 剥掉了摘要里的逗号（5/5 抽样，逗号 0 个，句号 7-11 个）
     → 影响可读性与短语识别，不影响 TF-IDF 词频统计，但需在文档中标注

用法：
    cd backend
    .venv/Scripts/python.exe scripts/verify_cvf.py              # 默认 CVPR2024
    .venv/Scripts/python.exe scripts/verify_cvf.py ICCV2023
"""
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "https://openaccess.thecvf.com"

# ⚠️ CVF 会拒绝默认的 python-requests UA，必须带标识
HEADERS = {
    "User-Agent": "ConfTrends/0.1 (course project; contact: student@example.edu)",
}
TIMEOUT = 90


# ---------------------------------------------------------------
# 索引页解析
#   URL：https://openaccess.thecvf.com/CVPR2024?day=all
#        ⚠️ ?day=all 必需；不带该参数只返回一个空壳页（约 3.7KB）
#
#   实测结构（注意：论文条目是 <dt class="ptitle">，没有 <dl class="ptitle"> 包着）：
#     <dt class="ptitle"><br><a href="/content/CVPR2024/html/....html">标题</a></dt>
#     <dd>
#       <form class="authsearch">
#         <input type="hidden" name="query_author" value="Haijin Zeng">
#         <a href="#">Haijin Zeng</a>,</form>
#       ...
#     </dd>
#     <dd>
#       [<a href="..._paper.pdf">pdf</a>]
#       [<a href="..._supplemental.pdf">supp</a>]
#       <div class="link2">[<a class="fakelink">bibtex</a>]
#         <div class="bibref pre-white-space">@InProceedings{...}</div>
#       </div>
#     </dd>
#
#   解析路径：遍历 dt.ptitle → 取标题与详情页链接；
#             往后收集同级的 <dd> 直到下一个 <dt>：
#               · 含 form.authsearch 的 dd → 作者（读 input[name=query_author] 的 value）
#               · 含 div.bibref 的 dd     → BibTeX + PDF 链接
# ---------------------------------------------------------------
def parse_index(html):
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for dt in soup.select("dt.ptitle"):
        a = dt.find("a")
        if not a:
            continue

        detail_url = a.get("href", "")
        if detail_url.startswith("/"):
            detail_url = BASE + detail_url

        # 收集紧随其后的同级 <dd>，直到遇到下一个 <dt>
        authors, pdf_url, bibtex = "", "", None
        sib = dt.find_next_sibling()
        while sib is not None and sib.name != "dt":
            if sib.name == "dd":
                if not authors:
                    names = [i.get("value", "").strip()
                             for i in sib.select("input[name=query_author]")]
                    if names:
                        authors = ", ".join(n for n in names if n)

                if bibtex is None:
                    bib = sib.select_one("div.bibref")
                    if bib:
                        bibtex = bib.get_text().strip()

                if not pdf_url:
                    for link in sib.find_all("a"):
                        href = link.get("href", "")
                        if href.endswith(".pdf") and "_supp" not in href and "supplemental" not in href:
                            pdf_url = href if href.startswith("http") else BASE + href
                            break
            sib = sib.find_next_sibling()

        entries.append({
            "title": a.get_text(" ", strip=True),
            "authors": authors,
            "detail_url": detail_url,
            "pdf_url": pdf_url,
            "bibtex": bibtex,
        })

    return entries


# ---------------------------------------------------------------
# 详情页解析（只有摘要需要走这里）
#   <div id="abstract"> ... </div>
#   兜底：<meta name="citation_abstract">（实测 CVF 没有此标签，保留以防改版）
# ---------------------------------------------------------------
def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")

    div = soup.find("div", id="abstract")
    if div:
        return div.get_text(" ", strip=True)

    meta = soup.find("meta", attrs={"name": "citation_abstract"})
    return meta.get("content", "").strip() if meta else None


def bib_field(bibtex, field):
    if not bibtex:
        return None
    m = re.search(rf"{field}\s*=\s*\{{(.*?)\}}\s*,?\s*\n", bibtex, re.DOTALL)
    return m.group(1).strip() if m else None


def main(conf_year="CVPR2024"):
    print(f"=== 验证 CVF 页面结构（{conf_year}）===\n")

    # --- 1. 索引页 ---
    index_url = f"{BASE}/{conf_year}?day=all"
    print(f"[1] 抓索引页 {index_url}")
    t0 = time.time()
    resp = requests.get(index_url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    print(f"    HTTP {resp.status_code}｜{len(resp.text)/1024/1024:.1f} MB｜耗时 {time.time()-t0:.1f}s")

    entries = parse_index(resp.text)
    with_bib = sum(1 for e in entries if e["bibtex"])
    print(f"    解析到 {len(entries)} 篇论文，其中 {with_bib} 篇含 BibTeX")
    print(f"    覆盖率：{with_bib / len(entries) * 100:.1f}%" if entries else "    ✗ 解析失败")
    if not entries:
        return 1

    first = entries[0]
    print(f"\n    样例：{first['title'][:70]}")
    print(f"          作者：{first['authors'][:70]}")
    print(f"          详情页：{first['detail_url']}")

    print("\n" + "=" * 64)
    print("索引页里的 BibTeX（无需进详情页）")
    print("=" * 64)
    if first["bibtex"]:
        print(first["bibtex"])
        print("\n  → 解析出的字段：")
        for f in ("title", "author", "booktitle", "year", "pages"):
            print(f"     {f:10} = {str(bib_field(first['bibtex'], f))[:66]}")
    else:
        print("  ✗ 未找到 BibTeX")

    # --- 2. 详情页（只抓 1 篇）---
    print(f"\n[2] 抓 1 篇详情页取摘要（礼貌访问）")
    time.sleep(1)
    d = requests.get(first["detail_url"], headers=HEADERS, timeout=TIMEOUT)
    d.raise_for_status()
    abstract = parse_detail(d.text)
    print(f"    HTTP {d.status_code}｜{len(d.text)/1024:.1f} KB")

    print("\n" + "=" * 64)
    print("详情页里的摘要")
    print("=" * 64)
    if abstract:
        print(abstract[:500] + ("..." if len(abstract) > 500 else ""))
        print(f"\n  → 长度 {len(abstract)} 字符"
              f"｜逗号 {abstract.count(',')} 个｜句号 {abstract.count('.')} 个")
    else:
        print("  ✗ 未找到摘要")

    # --- 3. 判定 ---
    print("\n" + "=" * 64)
    print("结论")
    print("=" * 64)
    has_bib, has_abs = bool(first["bibtex"]), bool(abstract)
    print(f"  BibTeX 内嵌（索引页）：{'✅ 是' if has_bib else '❌ 否'}")
    print(f"  摘要内嵌（详情页）    ：{'✅ 是' if has_abs else '❌ 否'}")
    if with_bib and entries:
        print(f"  BibTeX 覆盖率        ：{with_bib / len(entries) * 100:.1f}%")

    if has_bib and has_abs:
        print("\n  ✅ 假设成立 —— 分层补全策略可用：")
        print("     · BibTeX：1 次请求拿整届（不用逐篇抓）")
        print("     · 摘要  ：逐篇抓详情页，零 Semantic Scholar 配额消耗")
        print("     · S2 仅用于 ECVA(ECCV) 与摘要缺失的论文")
        if abstract and abstract.count(",") == 0:
            print("\n  ⚠️ 注意：CVF 剥掉了摘要里的逗号（实测 5/5 篇均如此）。")
            print("     不影响 TF-IDF 词频，但影响可读性与短语识别，需在文档中标注。")
        return 0

    print("\n  ❌ 假设不成立 —— 需重新确认页面结构。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "CVPR2024"))
