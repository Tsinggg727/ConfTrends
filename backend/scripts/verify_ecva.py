"""ECVA 站点结构验证脚本（非爬虫，只验证假设）。

假设：ECCV 的开放获取论文在 ECVA（ecva.net），列表页是否给出标题/作者/PDF？
      ECVA 是否提供摘要，还是只有 PDF（摘要必须走 Semantic Scholar）？

已验证结论（2026-09-20 实测）：
  ✅ 列表页 —— https://www.ecva.net/papers.php
     单页 3.6 MB，用 accordion 分节列出全部年份（2024 / 2022 / 2020 / 2018）
     ECCV2024 共 2387 篇，每篇给出：标题 / 作者 / PDF / 补充材料 / **Springer DOI**
  ❌ 列表页**无摘要**（marker 'abstract' = 0），也**无 BibTeX**
     （对比：CVF 索引页带完整 BibTeX；ECVA 只有 2018 等老年份才有内嵌 bibref）
  ✅ 详情页 —— papers/eccv_{year}/papers_ECCV/html/{id}_ECCV_{year}_paper.php
     仅 5 KB，含 <div id="abstract"> 摘要全文
     → 摘要**不需要** Semantic Scholar，ECVA 直连即可拿到
  ✅ 摘要标点完整（抽样 4 篇：逗号 8/16/23/10 个）
     → CVF 那个「逗号被剥」的问题在 ECVA 上不存在
  ⚠️ 详情页同样**无 BibTeX**（InProceedings = 0），会议/年份需从 URL 与所属段落推断
  ⚠️ 截至 2026-09-20，ECVA 上**没有 ECCV 2026 段落**（最新是 2024）
     → ECCV 可抓范围为 2022 / 2024 两届

用法：
    cd backend
    .venv/Scripts/python.exe scripts/verify_ecva.py           # 默认 ECCV2024
    .venv/Scripts/python.exe scripts/verify_ecva.py ECCV2022
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

BASE = "https://www.ecva.net"
LIST_URL = f"{BASE}/papers.php"

HEADERS = {
    "User-Agent": "ConfTrends/0.1 (course project; contact: student@example.edu)",
}
TIMEOUT = 90


# ---------------------------------------------------------------
# robots.txt 检查
#   实测结果：ECVA 的 robots.txt 只声明了 Googlebot，没有对其他 UA 设限，
#   也没有 Disallow 规则 → 对我们是「未限制」。
#   但仍应按礼貌抓取处理（详见文件末尾的间隔建议）。
# ---------------------------------------------------------------
def check_robots():
    try:
        r = requests.get(f"{BASE}/robots.txt", headers=HEADERS, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return "无 robots.txt（视为未限制）"
        has_disallow = "Disallow:" in r.text and not re.search(
            r"Disallow:\s*$\s*", r.text, re.MULTILINE)
        return "有限制，需人工确认" if has_disallow else "未限制（仅声明 Googlebot）"
    except Exception as e:
        return f"获取失败：{type(e).__name__}"


# ---------------------------------------------------------------
# 列表页解析
#   https://www.ecva.net/papers.php   ← 一个页面包含所有年份
#
#   实测结构（注意 ECVA 的 href 属性**没有引号**，BeautifulSoup 能正常处理）：
#     <dt class="ptitle"><br>
#       <a href=papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php>标题</a>
#     </dt><dd>
#       作者1, 作者2, 作者3*</dd>
#     <dd>[<a href='papers/eccv_2024/papers_ECCV/papers/00004.pdf'>pdf</a>]
#       <div class="link2">[<a href='...-supp.pdf'>supplementary material</a>]</div>
#       <div class="link2">[<a href="https://link.springer.com/chapter/10.1007/...">DOI</a>]</div>
#     </dd>
#
#   解析路径：遍历 dt.ptitle → 取标题 + 详情页链接；
#             往后收集同级 <dd> 直到下一个 <dt>：
#               · 第一个 dd           → 作者（纯文本，无标签包裹）
#               · 含 .pdf 的 dd       → PDF 链接
#               · 含 springer 的 dd   → DOI 链接
#   注意：详情页链接是相对路径（无前导 /），需拼 BASE + "/" + href
# ---------------------------------------------------------------
def parse_list(html, year_tag):
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for dt in soup.select("dt.ptitle"):
        a = dt.find("a")
        if not a:
            continue

        detail_href = a.get("href", "")
        # 只保留目标年份，papers.php 里混着所有年份
        if year_tag not in detail_href:
            continue

        detail_url = detail_href if detail_href.startswith("http") else f"{BASE}/{detail_href.lstrip('/')}"

        authors, pdf_url, doi_url = "", "", ""
        seen_dd = 0
        sib = dt.find_next_sibling()
        while sib is not None and sib.name != "dt":
            if sib.name == "dd":
                seen_dd += 1
                if seen_dd == 1:
                    authors = sib.get_text(" ", strip=True)
                for link in sib.find_all("a"):
                    href = link.get("href", "")
                    if "springer" in href and not doi_url:
                        doi_url = href
                    elif href.endswith(".pdf") and "-supp" not in href and not pdf_url:
                        pdf_url = href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"
            sib = sib.find_next_sibling()

        entries.append({
            "title": a.get_text(" ", strip=True),
            "authors": authors,
            "detail_url": detail_url,
            "pdf_url": pdf_url,
            "doi_url": doi_url,
        })

    return entries


# ---------------------------------------------------------------
# 详情页解析
#   <div id="papertitle">标题</div>
#   <div id="authors">作者</div>
#   <div id="abstract">摘要</div>
#   注意：结构与 CVF 详情页几乎一致（同样的 3 个 id），
#   所以正式实现时 cvf_parser 与 ecva_parser 可以共用大部分代码。
# ---------------------------------------------------------------
def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")

    def text_of(div_id):
        d = soup.find("div", id=div_id)
        return d.get_text(" ", strip=True) if d else None

    return {
        "title": text_of("papertitle"),
        "authors": text_of("authors"),
        "abstract": text_of("abstract"),
    }


def main(year_tag="ECCV2024"):
    # 从 "ECCV2024" 推出列表页里的年份标记 "eccv_2024"
    m = re.match(r"ECCV(\d{4})", year_tag)
    if not m:
        print(f"✗ 参数格式应为 ECCV2024 这样的形式，收到：{year_tag}")
        return 1
    year = m.group(1)
    url_tag = f"eccv_{year}"

    print(f"=== 验证 ECVA 站点结构（{year_tag}）===\n")

    print(f"[0] robots.txt：{check_robots()}")

    # --- 1. 列表页 ---
    print(f"\n[1] 抓列表页 {LIST_URL}")
    t0 = time.time()
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    print(f"    HTTP {resp.status_code}｜{len(resp.text)/1024/1024:.1f} MB｜耗时 {time.time()-t0:.1f}s")

    # 列出页面里有哪些年份段落
    sections = re.findall(r">\s*(ECCV \d{4} Papers)\s*<", resp.text)
    print(f"    页面包含的年份段落：{', '.join(sections) if sections else '未识别'}")

    entries = parse_list(resp.text, url_tag)
    print(f"    {year_tag} 解析到 {len(entries)} 篇论文")
    if not entries:
        print(f"    ✗ 未解析到 {year_tag} 论文 —— 该年份可能尚未发布，或选择器需调整")
        return 1

    first = entries[0]
    with_pdf = sum(1 for e in entries if e["pdf_url"])
    with_doi = sum(1 for e in entries if e["doi_url"])
    print(f"    PDF 覆盖率 {with_pdf/len(entries)*100:.1f}%｜DOI 覆盖率 {with_doi/len(entries)*100:.1f}%")

    print(f"\n    样例：{first['title'][:70]}")
    print(f"          作者：{first['authors'][:70]}")
    print(f"          详情页：{first['detail_url']}")
    print(f"          PDF：{first['pdf_url']}")
    print(f"          DOI：{first['doi_url']}")

    print("\n" + "=" * 64)
    print("列表页是否含摘要 / BibTeX")
    print("=" * 64)
    # 只看目标年份的片段，避免被其他年份的 bibref 干扰
    a = resp.text.find(f"ECCV {year} Papers")
    b = resp.text.find("ECCV 2022 Papers")
    seg = resp.text[a:b] if a > 0 and b > a else resp.text[a:a + 2_000_000] if a > 0 else resp.text
    print(f"  该年份段落中 'abstract' 出现：{seg.count('abstract')} 次")
    print(f"  该年份段落中 'bibref'   出现：{seg.count('bibref')} 次")
    print(f"  该年份段落中 'InProceedings' 出现：{seg.count('InProceedings')} 次")

    # --- 2. 详情页（只抓 1 篇）---
    print(f"\n[2] 抓 1 篇详情页取摘要（礼貌访问）")
    time.sleep(1)
    d = requests.get(first["detail_url"], headers=HEADERS, timeout=TIMEOUT)
    d.raise_for_status()
    parsed = parse_detail(d.text)
    print(f"    HTTP {d.status_code}｜{len(d.text)/1024:.1f} KB")

    print("\n" + "=" * 64)
    print("详情页解析结果")
    print("=" * 64)
    print(f"  papertitle：{(parsed['title'] or '')[:70]}")
    print(f"  authors   ：{(parsed['authors'] or '')[:70]}")
    if parsed["abstract"]:
        ab = parsed["abstract"]
        print(f"\n  摘要（{len(ab)} 字符｜逗号 {ab.count(',')} 个｜句号 {ab.count('.')} 个）：")
        print("  " + ab[:400] + ("..." if len(ab) > 400 else ""))
    else:
        print("\n  ✗ 未找到摘要")

    # --- 3. 判定 ---
    print("\n" + "=" * 64)
    print("结论")
    print("=" * 64)
    print(f"  列表页给出标题/作者/PDF/DOI：{'✅ 是' if with_pdf else '❌ 否'}")
    print(f"  列表页含摘要              ：{'✅ 是' if seg.count('abstract') else '❌ 否'}")
    print(f"  列表页含 BibTeX           ：{'✅ 是' if seg.count('InProceedings') else '❌ 否'}")
    print(f"  详情页含摘要              ：{'✅ 是' if parsed['abstract'] else '❌ 否'}")

    if parsed["abstract"]:
        print("\n  ✅ ECVA 提供摘要 —— Semantic Scholar 对 ECCV 也不是必需的。")
        print("     摘要逐篇抓详情页（约 5 KB/篇），与 CVPR/ICCV 走同一套流程。")
        if not seg.count("InProceedings"):
            print("\n  ⚠️ 但列表页无 BibTeX：booktitle / pages 需自行拼装或省略。")
            print("     title / authors / year / conference / DOI / url 都能拿到，不影响入库。")
        if parsed["abstract"].count(",") > 0:
            print("\n  ✅ 摘要标点完整（对比：CVF 的摘要逗号被剥，ECVA 没有这个问题）。")
        return 0

    print("\n  ⚠️ 详情页无摘要 —— ECCV 摘要需走 Semantic Scholar。")
    return 2


# ---------------------------------------------------------------------------
# robots.txt 与请求间隔建议（实测 2026-09-20）
# ---------------------------------------------------------------------------
# robots.txt：ECVA 只声明了 Googlebot 的 Allow，没有对其他 UA 设限，也没有
#             Disallow 规则。技术上「未限制」，但"没被禁止"不等于"鼓励抓取"。
#
# 建议的礼貌抓取参数（与 CVF 保持一致，便于共用同一个限速器）：
#   · 并发：≤ 2（ECVA 是单机 PHP 站点，比 CVF 脆弱，建议实际用 1）
#   · 请求间隔：0.5 – 1.0s（保守起步用 1.0s）
#   · User-Agent：带项目标识与联系方式，不要伪装成浏览器
#   · 超时：30s，失败重试 2 次后放弃并记入失败原因
#   · 只抓 5 KB 的详情页取摘要，**不要下载 PDF 全文**
#   · 遇到 403 / 429 / 5xx 连续出现 → 暂停该站点全部任务，不硬闯
#
# 效率提示：papers.php 是 3.6 MB 的单页，**一次请求就包含全部年份的清单**
#          （2024/2022/2020/2018 全在里面）。所以清单阶段只需 1 次请求，
#          真正的请求量全部在「逐篇取摘要」上。
#
#   ECCV2024：2387 篇 × 1.0s ≈ 40 分钟
#   ECCV2022：≈ 2400 篇 × 1.0s ≈ 40 分钟
#   两届合计 ≈ 1.3 小时（不消耗任何 Semantic Scholar 配额）

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "ECCV2024"))
