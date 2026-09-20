"""抓取失败码 —— 设计文档《功能1_论文信息爬取_设计.md》§1.2 的固定枚举。

失败必须可归因：前端按 code 决定这一行显示 [重试] 还是 [忽略]，
后端按 retryable 决定它能不能进重试队列。

新增失败码时同步改三处：本表、设计文档 §1.2、前端的文案映射。
"""

# code -> (人话文案, 是否可重试)
FAIL_REASONS = {
    "NOT_FOUND_CVF": (
        "站内索引页未找到该论文，请核对题目或改用官网完整标题",
        False,
    ),
    "PAGE_FETCH_FAILED": (
        "详情页请求失败（超时或服务端错误）",
        True,
    ),
    "BIBTEX_PARSE_FAILED": (
        "页面存在但 BibTeX 解析不出",
        True,
    ),
    "CONFERENCE_UNKNOWN": (
        "无法把会议信息映射到三大顶会（CVPR / ICCV / ECCV）",
        False,
    ),
    "YEAR_UNKNOWN": (
        "年份缺失且无法从页面推断",
        False,
    ),
    "S2_NOT_FOUND": (
        "Semantic Scholar 无匹配（可能尚未收录）",
        True,
    ),
    "S2_LOW_SIMILARITY": (
        "Semantic Scholar 匹配到了但相似度不足，已放弃以免张冠李戴",
        False,
    ),
    "S2_RATE_LIMITED": (
        "Semantic Scholar 触发限流（429）",
        True,
    ),
    "ABSTRACT_MISSING": (
        "摘要为空（警告级：论文照常入库，关键词抽取质量会下降）",
        True,
    ),
    "DB_CONFLICT": (
        "入库时唯一约束冲突",
        True,
    ),
    "NETWORK_ERROR": (
        "网络错误",
        True,
    ),
}

# 记录在 paper.fail_reason / crawl_task_item.fail_reason 时不允许超出这个集合
ALL_CODES = tuple(FAIL_REASONS)

# 警告级失败码：不算真失败，论文仍然入库，只是质量降级
WARNING_CODES = frozenset({"ABSTRACT_MISSING"})


def describe(code):
    """取失败码的人话文案。"""
    return FAIL_REASONS.get(code, ("未知失败原因", False))[0]


def is_retryable(code):
    return FAIL_REASONS.get(code, ("", False))[1]


def is_warning(code):
    return code in WARNING_CODES


class CrawlError(Exception):
    """带失败码的抓取异常。

    业务失败（题目没找到、摘要为空……）用这个异常在内部流转，
    由 service 层统一转成 `data.status = "failed"` + fail_reason，
    不会变成 HTTP 4xx/5xx —— 见设计文档 §4.1 的设计取舍。
    """

    def __init__(self, code, message=None, detail=None):
        if code not in FAIL_REASONS:
            raise ValueError(f"未登记的失败码：{code}")
        self.code = code
        self.message = message or describe(code)
        self.detail = detail
        super().__init__(f"[{code}] {self.message}")

    def to_dict(self):
        d = {"fail_reason": self.code, "fail_message": self.message,
             "retryable": is_retryable(self.code)}
        if self.detail:
            d["fail_detail"] = str(self.detail)[:500]
        return d


class InvalidParam(Exception):
    """请求参数本身不合法（会议年份不存在、题目为空……）。

    与 CrawlError 区分开：这类是真正的参数错误，API 层返回 HTTP 4xx。
    """

    def __init__(self, message, code=400):
        self.message = message
        self.code = code
        super().__init__(message)
