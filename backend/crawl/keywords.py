"""关键词抽取 —— 设计文档 §1.1 阶段五。

**为什么是全量批处理而不是逐篇算**：TF-IDF 的 IDF 必须「全量语料统一统计」——
逐篇入库时算，第 1 篇的 IDF 和第 7000 篇的 IDF 不可比，权重会随爬取进度漂移。
所以这里是「一次重建全库」的批处理：语料 = title + abstract（7,259 篇），
跑完统一写 keyword + paper_keyword。

方法（§1.1 阶段五）：
    TF-IDF 为主 + TextRank 为辅，综合分加权排序，取 Top 5–8。
    设计原文是「两套结果的交集加权」；实测严格取交集会系统性挤掉
    「单一指标极强」的真主题词（例：某篇 3DGS 论文里 3dgs 的 TF-IDF
    全文档第一，但 TextRank 恰好排 13，直接落榜），所以取两套候选池的
    **并集**打分，同时进两榜的词乘 INTERSECTION_BONUS 的交集增益 ——
    两种信号都参与打分，交集词仍占优，语义与原意一致。

词归一化：
    · 小写、按简单后缀规则合并单复数（models → model）；
    · 同义词短语归并成规范词（3D Gaussian Splatting → 3dgs）；
    · 停用词 = 通用英文停用词 + CV 领域高频无意义词（paper/method/…）。

写库复用 storage.link_keywords 的「keyword upsert + paper_keyword 去重插」
路径（步骤 4 铺好的），全程一个事务；重跑是安全的 —— 先清 source='extract'
的旧关联再重建，人工标记（source='manual'）不受影响。
"""
import math
import re
import time
from collections import Counter

from db import execute, query_all, transaction

from . import storage

# ---------------------------------------------------------------
# 词表
# ---------------------------------------------------------------
# 通用英文停用词（紧凑版）+ 学术套话 + §1.1 点名的 CV 高频无意义词。
# 刻意保持偏小：停用词多删一个，候选池就多一分噪声；词形变体靠
# _singular 先归一（results → result 再匹配停用词）。
STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been
before being below between both but by can cannot could did do does doing down
during each few for from further had has have having he her here hers herself
him himself his how i if in into is it its itself just me more most my myself
no nor not now of off on once only or other our ours ourselves out over own
same she should so some such than that the their theirs them themselves then
there these they this those through to too under until up very was we were
what when where which while who whom why will with you your yours yourself
also however moreover therefore thus hence nevertheless meanwhile respectively
ie eg etc versus via within upon among across per except
paper papers method methods approach approaches propose proposes proposed
proposing result results show shows showed shown showing demonstrate
demonstrates demonstrated demonstrating experiment experiments experimental
based using use uses used novel existing various extensive multiple
kind growth exit additional single size third
""".split())
# ↑ 末行是弱实词边界表（评估报告方案C）：这些词永远不构成概念，放进
# STOPWORDS（从 token 流删除）而不是 UNIGRAM_BANNED，一举两得 —— 单字
# 不再成词，且它们参与的碎片 bigram（single blurry / size kernel /
# third kind）从源头消失，旁边真正的概念（blurry image）反而能浮现。

# 同义词短语 → 规范词。键是「归一化后的 token 序列」，在停用词过滤**之前**
# 整体替换 —— 这样 "3D Gaussian Splatting" 和 "gaussian splatting" 都归到
# 3dgs，且不会被介词过滤拆散。只收领域内公认的缩写，宁缺毋滥。
SYNONYMS = {
    ("3d", "gaussian", "splatting"): "3dgs",
    ("gaussian", "splatting"): "3dgs",
    ("convolutional", "neural", "network"): "cnn",
    ("generative", "adversarial", "network"): "gan",
    ("recurrent", "neural", "network"): "rnn",
    ("vision", "transformer"): "vit",
    ("vision", "transformers"): "vit",
    ("large", "language", "model"): "llm",
    ("vision", "language", "model"): "vlm",
    ("visual", "question", "answering"): "vqa",
}

# 词形折叠：变体 token → 规范 token（在**同义词短语合并之后**逐词应用 ——
# 放在合并之前会把 "visual question answering" 变成 "…question answer"，
# 破坏 →vqa 的短语匹配）。映射来自对库里 keyword 表的真实碰撞分析
# （segmentation/segment、tracking/track、3dg/3dgs、modeling/model…），
# 只收「两个形式都真实出现且指同一概念」的对 —— 不做通用词干化，
# 因为后者会把 display form 变成 detect/segment 这类生硬词干，
# 还会重塑短语（processing→process 会把 "point cloud processing" 搅坏）。
WORD_FOLD = {
    # 动词/动名词 → 领域惯用名词形（关键词的展示形态）
    "detect": "detection", "detected": "detection",
    "segment": "segmentation", "segmenting": "segmentation",
    "edit": "editing", "track": "tracking", "render": "rendering",
    "match": "matching", "train": "training", "learn": "learning",
    "cluster": "clustering", "searching": "search", "querying": "query",
    "masking": "mask", "prompting": "prompt", "labeling": "label",
    "count": "counting", "grasp": "grasping", "rank": "ranking",
    "poison": "poisoning", "deforming": "deformation", "adapt": "adaptation",
    "answering": "answer", "normalizing": "normalization",
    "summarizing": "summarization", "transform": "transformation",
    "transforming": "transformation", "viewing": "view", "sounding": "sound",
    "cleaning": "clean", "cloth": "clothing", "lift": "lifting",
    "filter": "filtering", "grouping": "group",
    # 缩写变体归并
    "modeling": "model",        # generative modeling → generative model …
    "3dg": "3dgs",              # 同一方向的两种缩写写法
    "llms": "llm",
}

# 单字禁用：CV 高频泛词 + 纯指标缩写。与 STOPWORDS 的区别：
# STOPWORDS 从 token 流里**删除**（"the"/"of" 没有资格参与任何组合），
# UNIGRAM_BANNED 的词**留在流里** —— "diffusion model" / "image segmentation"
# 这类有效短语照常构成（§ 需求：禁泛词但保留有效短语），只是不作为
# 独立关键词参选；两个成员都被禁的二元短语才一并丢弃。
# 方法缩写的取舍原则：已成为方向名的保留（clip / nerf / 3dgs / gan / vit），
# 纯指标/单篇方法名禁掉（mse / psnr / lpips / frossl…）。
UNIGRAM_BANNED = frozenset("""
model image feature task text system signal
mse psnr ssim lpips rmse iou fps frossl
""".split())

# 缩写假词门槛（评估报告方案C）：≤3 字母的纯字母 token，若 DF≤2 且不在
# 方向名白名单，不作候选 —— 杀掉 ttt/ed/bo sd 这类无方向信息的缩写碎片，
# 同时保住 clip/nerf/3dgs 这类已成为方向名的方法缩写（白名单显式豁免；
# 且高频方向名 DF 远超门槛，有双重保护，结构性不可能被误杀）。
ACRONYM_MAX_LEN = 3
ACRONYM_MAX_DF = 2
ACRONYM_WHITELIST = frozenset("""
clip nerf 3dgs gan cnn vit llm vqa ocr ssl ir peft rnn vlm
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")
_SENTENCE_SPLIT = re.compile(r"[.!?:;()\[\]\n]")
_WORD_MAX_LEN = 40                        # 防御性：超长 token 一律是解析噪声

# 候选池大小：TF-IDF 与 TextRank 各取前这么多，再求交集（§1.1「两套结果」）
POOL_SIZE = 12
# 每篇关键词数：交集加权后取 Top 5–8；不足 5 个时从并集回填
TOP_FLOOR, TOP_CEIL = 5, 8
# 综合分的权重：TF-IDF 为主（0.6），TextRank 为辅（0.4）——§1.1 的「为主/为辅」
W_TFIDF, W_TEXTRANK = 0.6, 0.4
# 两榜都进的交集增益：并集打分时，同时被 TF-IDF 和 TextRank 认可的词 ×(1+此值)
INTERSECTION_BONUS = 0.15
_TEXTLABEL_WINDOW = 4                     # TextRank 共现窗口（词）
_TEXTLABEL_ITERS = 30                     # 幂迭代轮数
_DAMPING = 0.85


def _singular(word):
    """简单后缀规则合并单复数。只处理规则变化 —— analyses/class/gas 这类
    例外用「保护后缀」兜住，个别切不干净的词对统计影响可忽略。"""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") \
            and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _tokenize(text):
    """小写 → 分句 → 分词 → 单复数归一。返回句子列表（TextRank 的窗口
    不跨句，避免句号两侧的词凑成假共现）。

    所有格撇号要剥掉（model's → model）：不剥的话 token 是 "model'"，
    既绕过泛词禁用也绕过词形折叠，最后还会经 normalize_title 洗成
    "model" 混进关键词表（实测产生过 model/llms 两行幽灵关键词）。
    strip 要做两次：_singular 剥掉所有格的 s 会**新暴露**出尾部撇号
    （model's → model'），只剥一次挡不住。"""
    sentences = []
    for sent in _SENTENCE_SPLIT.split((text or "").lower()):
        words = [w[:_WORD_MAX_LEN] for w in _TOKEN_RE.findall(sent)]
        words = [w.strip("'") for w in words]
        words = [_singular(w) for w in words]
        words = [w.strip("'") for w in words]
        words = [w for w in words if w]
        if words:
            sentences.append(words)
    return sentences


def _merge_synonyms(sentences):
    """在同义词表上做最长短语匹配替换（"3d gaussian splatting" → ["3dgs"]）。"""
    max_len = max(len(k) for k in SYNONYMS)
    out = []
    for words in sentences:
        merged, i, n = [], 0, len(words)
        while i < n:
            for size in range(min(max_len, n - i), 1, -1):
                canonical = SYNONYMS.get(tuple(words[i:i + size]))
                if canonical:
                    merged.append(canonical)
                    i += size
                    break
            else:
                merged.append(words[i])
                i += 1
        out.append(merged)
    return out


def _fold_words(sentences):
    """逐词应用 WORD_FOLD（必须在短语合并之后，理由见 WORD_FOLD 注释）。"""
    return [[WORD_FOLD.get(w, w) for w in words] for words in sentences]


def _filter_stopwords(sentences):
    """去停用词 / 纯数字 / 单字符，返回过滤后的 token 序列（供 Bigram 与
    TextRank 共用）。短语替换在过滤之前做，介词不会拆散同义词；
    UNIGRAM_BANNED 的词不过滤（要留给短语组合），在候选构造时排除。"""
    kept = []
    for words in sentences:
        tokens = [w for w in words
                  if w not in STOPWORDS and len(w) >= 2 and not w.isdigit()]
        if tokens:
            kept.append(tokens)
    return kept


def tokenize(text):
    """title + abstract → 过滤后的分句 token 序列。"""
    return _filter_stopwords(_fold_words(_merge_synonyms(_tokenize(text))))


def _candidates(sentences):
    """候选词 = 单词 + 相邻二元短语（"diffusion model" 这类词组才是 CV 论文
    真正的关键词形态）。返回 (Counter(候选), Counter(单词))。

    UNIGRAM_BANNED 的词不作单字候选（泛词/指标缩写），但留在流里参与
    二元短语 —— 只有两个成员都被禁的短语（"image model"）才丢弃。
    """
    uni = Counter()
    bi = Counter()
    for tokens in sentences:
        uni.update(t for t in tokens if t not in UNIGRAM_BANNED)
        bi.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:])
                  if not (a in UNIGRAM_BANNED and b in UNIGRAM_BANNED))
    return uni, bi


# ---------------------------------------------------------------
# TF-IDF（全量语料统一算 IDF —— §1.1 阶段五的硬要求）
# ---------------------------------------------------------------
def doc_freq(doc_terms):
    """doc_terms: 每篇的候选集合列表 → {候选: DF（出现的文档数）}。"""
    df = Counter()
    for cands in doc_terms:
        df.update(cands)
    return df


def compute_idf(doc_tokens):
    """doc_tokens: 每篇的候选集合列表 → {候选: IDF}。

    平滑式 idf = ln((1+N)/(1+df)) + 1：全语料都出现的候选 IDF 最低但
    不为 0，避免「词太常见」直接把权重打穿成 0。
    """
    df = doc_freq(doc_tokens)
    n_docs = len(doc_tokens)
    return {term: math.log((1 + n_docs) / (1 + df_c)) + 1.0
            for term, df_c in df.items()}


# ---------------------------------------------------------------
# TextRank（§1.1：为辅）
# ---------------------------------------------------------------
def _textrank(sentences):
    """单词共现图上的加权 PageRank（窗口 _TEXTLABEL_WINDOW，不跨句）。
    返回 {单词: 分数}。二元短语由调用方按成员均分折算。"""
    graph = {}
    for tokens in sentences:
        uniq = list(dict.fromkeys(tokens))          # 句内去重防自环堆权重
        for i, a in enumerate(uniq):
            for b in uniq[i + 1:i + 1 + _TEXTLABEL_WINDOW]:
                graph.setdefault(a, {})[b] = graph.get(a, {}).get(b, 0) + 1
                graph.setdefault(b, {})[a] = graph.get(b, {}).get(a, 0) + 1
    if not graph:
        return {}

    out_weight = {node: sum(nbrs.values()) for node, nbrs in graph.items()}
    scores = {node: 1.0 / len(graph) for node in graph}
    for _ in range(_TEXTLABEL_ITERS):
        new_scores = {}
        for node in graph:
            acc = 0.0
            for nbr, w in graph[node].items():
                acc += w * scores[nbr] / out_weight[nbr]
            new_scores[node] = (1 - _DAMPING) + _DAMPING * acc
        scores = new_scores
    return scores


# ---------------------------------------------------------------
# 单篇抽取
# ---------------------------------------------------------------
def extract(sentences, idf, weak_acronyms=None):
    """一篇的 token 句列表 → [(关键词, 综合分)]，综合分降序、5–8 个。

    两套候选池取并集按综合分排序，交集词享受 INTERSECTION_BONUS 增益
    （理由见模块 docstring）；候选总量不足 TOP_FLOOR 的短文档从全部
    候选按综合分回填。

    weak_acronyms：缩写假词门槛（方案C）筛出的 token 集，这些词不作
    单字候选，两个成员都是缩写假词的 bigram 一并丢弃（bo sd 类）。
    """
    uni, bi = _candidates(sentences)
    if not uni:
        return []
    weak = weak_acronyms or frozenset()
    uni = Counter({t: c for t, c in uni.items() if t not in weak})
    bi = Counter({t: c for t, c in bi.items()
                  if not all(p in weak for p in t.split(" "))})
    if not uni and not bi:
        return []

    # 候选 = 单词 + 二元短语；tf_idf = tf × idf（二元短语的 df 也按全库算）
    tfidf = {}
    for term, tf in uni.items():
        if term in idf:
            tfidf[term] = tf * idf[term]
    for term, tf in bi.items():
        if term in idf:
            tfidf[term] = tf * idf[term]
    if not tfidf:
        return []

    tr_uni = _textrank(sentences)
    textrank = {}
    for term in tfidf:
        parts = term.split(" ")
        scores = [tr_uni.get(p, 0.0) for p in parts]
        textrank[term] = sum(scores) / len(scores)   # 短语 = 成员均分

    max_tfidf = max(tfidf.values())
    max_tr = max(textrank.values()) or 1.0
    combined = {term: W_TFIDF * (s / max_tfidf) + W_TEXTRANK * (textrank[term] / max_tr)
                for term, s in tfidf.items()}

    pool_tf = {t for t, _ in sorted(tfidf.items(), key=lambda kv: -kv[1])[:POOL_SIZE]}
    pool_tr = {t for t, _ in sorted(textrank.items(), key=lambda kv: -kv[1])[:POOL_SIZE]}
    union = pool_tf | pool_tr
    scored = {t: combined[t] * (1 + INTERSECTION_BONUS)
              if t in pool_tf and t in pool_tr else combined[t]
              for t in union}

    selected = sorted(union, key=lambda t: -scored[t])[:TOP_CEIL]
    if len(selected) < TOP_FLOOR:
        rest = sorted(set(combined) - set(selected), key=lambda t: -combined[t])
        selected += rest[:TOP_FLOOR - len(selected)]

    top = scored[selected[0]] or 1.0
    return [(t, scored[t] / top) for t in selected]


# ---------------------------------------------------------------
# 全量重建
# ---------------------------------------------------------------
def rebuild_keywords():
    """全库重建关键词（阶段五批处理）。返回统计 dict。

    一个事务内完成：清 source='extract' 的旧关联 → 逐篇写 keyword +
    paper_keyword（复用 storage.link_keywords，weight=综合分归一、rank=1 起）
    → 清理不再被引用的关键词行。重跑安全（幂等）。
    """
    started = time.time()
    papers = query_all(
        """SELECT id, title, abstract FROM paper
            WHERE status = 'active' ORDER BY id""")
    docs = [(p["id"], f"{p['title'] or ''} {p['abstract'] or ''}")
            for p in papers]

    tokenized = [tokenize(text) for _, text in docs]
    # IDF 的 df 按「候选 = 单词 + 二元短语」统计 —— 只按单词统计的话，
    # 二元短语 df 恒为 0，会被 extract 里的 `term in idf` 全部滤掉
    doc_terms = []
    for toks in tokenized:
        uni, bi = _candidates(toks)
        doc_terms.append(set(uni) | set(bi))
    df = doc_freq(doc_terms)
    idf = compute_idf(doc_terms)
    # 缩写假词门槛（方案C）：低频短字母 token，白名单豁免方向名
    weak_acronyms = frozenset(
        t for t, c in df.items()
        if len(t) <= ACRONYM_MAX_LEN and t.isalpha()
        and c <= ACRONYM_MAX_DF and t not in ACRONYM_WHITELIST)

    n_with = 0
    links = 0
    with transaction():
        execute("DELETE FROM paper_keyword WHERE source = 'extract'",
                commit=False)
        for (paper_id, _), toks in zip(docs, tokenized):
            picked = extract(toks, idf, weak_acronyms)
            if not picked:
                continue
            n_with += 1
            storage.link_keywords(
                paper_id,
                [{"name": term, "weight": round(w, 4), "rank": rank}
                 for rank, (term, w) in enumerate(picked, start=1)],
                commit=False)
        links = query_all(
            "SELECT COUNT(*) AS c FROM paper_keyword WHERE source = 'extract'",
        )[0]["c"]
        # 上轮有关联、这轮没有的关键词行：功能三的统计会按 keyword_id 聚合，
        # 悬空行会成为「0 篇论文的关键词」——清理掉（不碰被统计引用的）。
        execute(
            """DELETE FROM keyword
                WHERE id NOT IN (SELECT keyword_id FROM paper_keyword)
                  AND id NOT IN (SELECT keyword_id FROM hot_keyword_stat)""",
            commit=False)

    return {
        "papers": len(docs),
        "with_keywords": n_with,
        "links": links,
        "keywords": query_all("SELECT COUNT(*) AS c FROM keyword")[0]["c"],
        "elapsed_sec": round(time.time() - started, 1),
    }


# ---------------------------------------------------------------
# 统计口径查询（评估报告方案A）—— 功能3/4 的数据源过滤
# ---------------------------------------------------------------
# 功能3/4 尚未实现；这两个函数是它们将来要调的查询，DF 门槛在这里
# 统一收口，阈值取 config（STATS_KEYWORD_MIN_DF / GRAPH_KEYWORD_MIN_DF），
# 可配置、可回滚（改成 1 即关闭）。论文详情页的关键词标签**不过滤**
# ——那里展示的是逐篇结果，长尾概念照常显示。

def top_keywords(min_df=3, limit=10):
    """功能3 Top 热词榜口径：按 DF 降序，DF ≥ min_df 才有上榜资格。"""
    return [dict(r) for r in query_all(
        """SELECT k.id, k.name, COUNT(pk.id) AS df
             FROM keyword k JOIN paper_keyword pk ON pk.keyword_id = k.id
            GROUP BY k.id
           HAVING COUNT(pk.id) >= ?
            ORDER BY df DESC, k.name
            LIMIT ?""",
        (min_df, limit),
    )]


def graph_keywords(min_df=5):
    """功能4 图谱节点口径：DF ≥ min_df 的全部关键词（含 id 供连边）。"""
    return [dict(r) for r in query_all(
        """SELECT k.id, k.name, COUNT(pk.id) AS df
             FROM keyword k JOIN paper_keyword pk ON pk.keyword_id = k.id
            GROUP BY k.id
           HAVING COUNT(pk.id) >= ?
            ORDER BY df DESC""",
        (min_df,),
    )]
