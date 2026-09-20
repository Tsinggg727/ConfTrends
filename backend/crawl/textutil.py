"""标题归一化与题目匹配。

`normalize_title()` 就是设计文档 §1.4 阶段四要求的 `title_key` 生成规则，
同时被两处复用：
  · 入库去重（paper.title_key 唯一约束）
  · 单条爬取时「用户输入的题目」↔「索引页里的题目」的匹配

匹配是防「张冠李戴」的第一道闸门，宁可判失败也不要写错论文，
所以阈值取 0.90，且对短题目直接放弃匹配（详见 match_title）。
"""
import difflib
import html
import re
import unicodedata

# 低于这个长度的题目只允许精确命中 —— 短题目（"GANs"、"ResNet"）做包含匹配
# 会命中一大堆论文，是错配的主要来源。
MIN_FUZZY_LEN = 12

# 自动接受的最低相似度（与设计文档 §0.3 的 S2 匹配阈值保持一致）
MATCH_THRESHOLD = 0.90

# LaTeX 重音的两种写法都要认，且重音必须与其后的字母一起捉住 ——
# 否则 {\'e} 里的花括号一旦被当成分隔符，就会把 "Resume" 切成 "R e sum e"。
#   · 符号式：\'e   \'{e}   \"o   \^i   \~n   \=u   \.z   \`a
#   · 命令式：\u{g} \v{s} \c{c} \H{o} \d{a} \b{h}
_SYMBOL_ACCENT = re.compile(r"\\(['\"`^~=.])\s*\{?([a-zA-Z])\}?")
_BRACED_ACCENT = re.compile(r"\\([uvHtcdb])\s*\{([a-zA-Z])\}")
# 重音 → Unicode 组合符号。转成组合符再 NFC，就能得到真正的 é í ü，
# 而不是把重音丢掉变成 e i u。
_ACCENT_MARKS = {
    "'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308",
    "~": "\u0303", "=": "\u0304", ".": "\u0307",
}
_BRACED_ACCENT_MARKS = {
    "u": "\u0306", "v": "\u030c", "H": "\u030b",
    "c": "\u0327", "d": "\u0323", "b": "\u0331", "t": "\u0361",
}

# 不带重音的特殊字母（\ss \o \aa \ae \oe \l \i \j）与转义符号（\& \% \_ \#）
# 后面不能紧跟字母，否则 \bf 会被误当成 \b
_SPECIALS = {
    "ss": "ss", "aa": "aa", "AA": "AA", "ae": "ae", "AE": "AE",
    "oe": "oe", "OE": "OE", "o": "o", "O": "O", "l": "l", "L": "L",
    "i": "i", "j": "j", "&": "&", "%": "%", "_": "_", "#": "#", "$": "$",
}
_SPECIAL_RE = re.compile(r"\\(ss|aa|AA|ae|AE|oe|OE|[oOlLiIj&%$_#])(?![a-zA-Z])")

# 其余命令：\textit / \bf / \emph，连同后面的空白一起丢掉
_LATEX_CMD = re.compile(r"\\[a-zA-Z]+\s*")

# 行内公式 $...$
_MATH = re.compile(r"\$[^$]*\$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")


def _accent_repl(match, marks):
    return match.group(2) + marks.get(match.group(1), "")


def strip_latex(raw):
    """剥掉 LaTeX 转义，但**保留大小写、标点与重音**。

    作者、venue 这类要展示的字段用这个；normalize_title 会在此基础上再往下压。
    """
    if not raw:
        return ""

    s = str(raw).strip()
    # BibTeX 的字段常被一对花括号整体包着，先去掉最外层
    if len(s) > 1 and s.startswith("{") and s.endswith("}"):
        s = s[1:-1]

    s = _MATH.sub(" ", s)
    s = _BRACED_ACCENT.sub(lambda m: _accent_repl(m, _BRACED_ACCENT_MARKS), s)
    s = _SYMBOL_ACCENT.sub(lambda m: _accent_repl(m, _ACCENT_MARKS), s)
    s = _SPECIAL_RE.sub(lambda m: _SPECIALS.get(m.group(1), " "), s)
    s = _LATEX_CMD.sub(" ", s)
    s = s.replace("\\", " ")              # 剩下的转义反斜杠
    s = html.unescape(s)                  # &amp; -> &
    # 花括号只是分组标记，直接去掉而不是换成空格 —— 换成空格会把单词切断
    s = s.replace("{", "").replace("}", "")

    s = _WS.sub(" ", s).strip()
    return unicodedata.normalize("NFC", s)   # 把 字母+组合符 合成真正的 é í ü


def normalize_title(raw):
    """把题目压成可比较、可去重的 title_key。

    处理顺序（顺序有讲究）：剥 LaTeX → 消音符号 → 转小写 →
    非字母数字统一成空格 → 压缩空白。

    例：
        "{Neural\\'s Radiance Fields}"          -> "neurals radiance fields"
        "3D&nbsp;Gaussian Splatting, Revisited" -> "3d gaussian splatting revisited"
        "R\\'esum\\'e of ViT"                    -> "resume of vit"
    """
    s = strip_latex(raw)
    if not s:
        return ""

    # NFKD 把 é 拆成 e + 组合符，再把组合符扔掉 —— 这样 "Résumé"/"Resume" 可比较
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    s = s.lower()
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def similarity(a, b):
    """两个已归一化字符串的相似度，0.0–1.0。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class MatchResult:
    """匹配结果。

    entry —— 命中的索引条目，未命中为 None
    score —— 相似度 0.0–1.0
    reason —— 命中方式：exact / contains / fuzzy / none，写进 parsed_json 便于排查
    candidates —— 未命中时给出的近似候选（最多 3 条），供前端做「你是不是要找」提示
    """

    def __init__(self, entry=None, score=0.0, reason="none", candidates=None):
        self.entry = entry
        self.score = score
        self.reason = reason
        self.candidates = candidates or []

    @property
    def matched(self):
        return self.entry is not None

    def __repr__(self):
        title = self.entry["title"][:40] if self.entry else "-"
        return f"<MatchResult {self.reason} {self.score:.3f} {title!r}>"


def build_index(entries):
    """把解析出的条目列表转成 {title_key: entry}，供 O(1) 精确命中。"""
    index = {}
    for e in entries:
        key = normalize_title(e.get("title"))
        if key and key not in index:      # 同届重题极少，保留先出现的
            index[key] = e
    return index


def match_title(query, index, threshold=MATCH_THRESHOLD):
    """在 {title_key: entry} 里找 query 对应的论文。

    三级策略，从可信到宽松：
      1. exact    —— 归一化后完全相同，score = 1.0
      2. contains —— 一方包含另一方（用户只记得半截题目时走这里）
      3. fuzzy    —— 编辑距离相似度，只在 quick_ratio 最高的 5 个候选里算真值
                      （全量算 SequenceMatcher 在 2700 条上要好几秒）

    短于 MIN_FUZZY_LEN 的题目只走第 1 级。
    """
    qk = normalize_title(query)
    if not qk:
        return MatchResult()

    hit = index.get(qk)
    if hit is not None:
        return MatchResult(hit, 1.0, "exact")

    if len(qk) < MIN_FUZZY_LEN:
        return MatchResult()

    # --- 2. 包含匹配 ---
    # 分数随「短边占长边的比例」上升：查询越接近完整题目越可信。
    # 分母加 0.09 的刻度是为了让半个题目的得分落在 0.90 附近而不是满分。
    best_entry, best_score = None, 0.0
    for key, entry in index.items():
        if qk in key or key in qk:
            short, long_ = sorted((len(qk), len(key)))
            score = min(0.99, threshold + 0.09 * (short / long_))
            if score > best_score:
                best_entry, best_score = entry, score
    if best_entry is not None:
        return MatchResult(best_entry, round(best_score, 4), "contains")

    # --- 3. 编辑距离兜底 ---
    # quick_ratio 只统计字符出现次数，比 ratio 快一个数量级，用来先筛出候选
    sm = difflib.SequenceMatcher()
    sm.set_seq2(qk)
    pre = []
    for key, entry in index.items():
        sm.set_seq1(key)
        pre.append((sm.quick_ratio(), key, entry))
    pre.sort(key=lambda t: t[0], reverse=True)

    scored = []
    for _, key, entry in pre[:5]:
        scored.append((similarity(qk, key), entry))
    scored.sort(key=lambda t: t[0], reverse=True)

    if scored and scored[0][0] >= threshold:
        score, entry = scored[0]
        return MatchResult(entry, round(score, 4), "fuzzy")

    # 没达到阈值：把最像的几条带回去做提示，但绝不写入
    candidates = [
        {"title": e["title"], "score": round(s, 4),
         "detail_url": e.get("detail_url", "")}
        for s, e in scored[:3] if s >= 0.60
    ]
    return MatchResult(None, round(scored[0][0], 4) if scored else 0.0,
                       "none", candidates)


def normalize_authors(raw):
    """作者串归一化：剥 LaTeX、把 BibTeX 的 `and` 分隔统一成逗号。

    `Mart{\\'i}n, Ana and Li, Wei` -> `Martín, Ana, Li, Wei`
    """
    if not raw:
        return ""
    s = strip_latex(raw)
    if " and " in s:
        parts = [p.strip() for p in re.split(r"\s+and\s+", s)]
        return ", ".join(p for p in parts if p)
    return s


def normalize_pages(raw):
    """BibTeX 的页码是 1234--1243，统一成 1234-1243。"""
    if not raw:
        return ""
    return re.sub(r"-{2,}", "-", str(raw).strip()).replace(" ", "")
