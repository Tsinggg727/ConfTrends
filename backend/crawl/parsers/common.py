"""两站共用的解析工具。

**详情页解析是共用的**：实测 CVF 的 `_paper.html` 与 ECVA 的 `_paper.php`
用的是完全相同的三个 id —— `div#papertitle` / `div#authors` / `div#abstract`
（见设计文档 §0.1 的对照表），所以只需要一份实现。

列表页解析两站差异较大，各自放在 cvf.py / ecva.py 里。
"""
import re

from bs4 import BeautifulSoup

try:                                        # 有 lxml 就用，7 MB 的索引页快很多
    _PARSER = "lxml"
    import lxml                             # noqa: F401
except ImportError:                         # 没装也能跑，只是慢一点
    _PARSER = "html.parser"

# 摘要入库上限（设计文档 §1.4：截断超长，建议 ≤ 4000 字符）
MAX_ABSTRACT_LEN = 4000

_WS = re.compile(r"\s+")
_LEADING_LABEL = re.compile(r"^\s*abstract\b[\s:：.\-—]*", re.IGNORECASE)


def make_soup(html):
    """统一的 BeautifulSoup 构造入口，保证解析器一致。

    lxml 比 html.parser 快约 3–5 倍且内存占用更低；索引页 5–7 MB，
    实测用 html.parser 要 4 秒左右，lxml 明显更快。
    """
    return BeautifulSoup(html, _PARSER)


def clean_text(text):
    """压缩空白、去首尾。HTML 里的换行与缩进对入库毫无价值。"""
    if not text:
        return ""
    return _WS.sub(" ", str(text)).strip()


def clean_abstract(text, max_len=MAX_ABSTRACT_LEN):
    """摘要清洗：压缩空白、去掉页面上多余的 "Abstract" 标签、截断超长。

    返回 (摘要文本, 是否被截断)。截断这件事要如实上报，
    否则「摘要看起来是完整的」会误导后续的关键词抽取。
    """
    s = clean_text(text)
    s = _LEADING_LABEL.sub("", s)
    if max_len and len(s) > max_len:
        # 尽量断在句末，断不了就硬切
        cut = s.rfind(". ", 0, max_len)
        s = s[: cut + 1] if cut > max_len * 0.6 else s[:max_len]
        return s, True
    return s, False


def abs_url(href, base):
    """把站内相对链接补成绝对链接。

    ECVA 的 href **没有引号**（`<a href=papers/...>`），且不带前导斜杠；
    CVF 的 href 以 `/` 开头。两种都要处理，所以不能简单拼字符串。
    """
    if not href:
        return ""
    href = href.strip().strip("'\"")
    if href.startswith(("http://", "https://")):
        return href
    return f"{base.rstrip('/')}/{href.lstrip('/')}"


def meta_content(soup, name):
    """读 <meta name="xxx" content="...">，Google Scholar 的 citation_* 标签。

    作为 div#... 的选择器兜底：站点改版时这两个来源至少还有一个能活。
    """
    tag = soup.find("meta", attrs={"name": name})
    return tag.get("content", "").strip() if tag else ""


def parse_detail(html):
    """解析论文详情页 —— **CVF 与 ECVA 共用这一份**。

    优先读三个 id，读不到再退回 citation_* meta 标签。
    返回 dict：title / authors / abstract / abstract_truncated

    注意：title 与 authors 只是「交叉校验」用，权威值来自列表页
    （列表页一次带回整届，不依赖详情页是否改了版）。
    """
    soup = make_soup(html)

    def by_id(div_id):
        tag = soup.find("div", id=div_id)
        return clean_text(tag.get_text(" ", strip=True)) if tag else ""

    title = by_id("papertitle") or meta_content(soup, "citation_title")

    authors = by_id("authors")
    if not authors:
        # citation_author 是多个平铺的 meta 标签
        authors = ", ".join(
            t.get("content", "").strip()
            for t in soup.find_all("meta", attrs={"name": "citation_author"})
            if t.get("content")
        )

    abstract_raw = by_id("abstract") or meta_content(soup, "citation_abstract")
    abstract, truncated = clean_abstract(abstract_raw)

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "abstract_truncated": truncated,
        "pdf_url": meta_content(soup, "citation_pdf_url"),
        # CVF 的列表页不带 DOI（ECVA 带），详情页的 citation_doi 是它唯一的来源
        "doi": meta_content(soup, "citation_doi"),
    }


# ---------------------------------------------------------------
# BibTeX
# ---------------------------------------------------------------
_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,", re.IGNORECASE)


def bibtex_key(bibtex):
    """取 @InProceedings{Zeng_2024_CVPR, 里的 Zeng_2024_CVPR。"""
    if not bibtex:
        return ""
    m = _KEY_RE.search(bibtex)
    return m.group(1) if m else ""


def bib_field(bibtex, field):
    """从 BibTeX 记录里取一个字段的值。

    用花括号配对扫描而不是正则非贪婪匹配 —— 标题里带花括号的情况很常见
    （`title = {A {3D} Approach}`），非贪婪匹配会在第一个 `}` 就截断。
    """
    if not bibtex:
        return ""
    m = re.search(rf"\b{re.escape(field)}\s*=\s*\{{", bibtex, re.IGNORECASE)
    if not m:
        return ""
    i, depth, start = m.end(), 1, m.end()
    while i < len(bibtex) and depth > 0:
        ch = bibtex[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return clean_text(bibtex[start : i - 1])


def doi_from_url(url):
    """从 Springer 链接里抠出 DOI。

    https://link.springer.com/chapter/10.1007/978-3-031-73232-4_1
      -> 10.1007/978-3-031-73232-4_1
    """
    if not url:
        return ""
    m = re.search(r"(10\.\d{4,9}/[^\s\"'<>?]+)", url)
    return m.group(1).rstrip("/.") if m else ""
