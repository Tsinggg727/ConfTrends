"""关键词抽取接口 —— §1.1 阶段五的统一触发入口。

    POST /api/v1/keywords/rebuild    全量重建 keyword / paper_keyword

这是阶段五的批处理入口，不是功能三的统计接口（热度榜/趋势读的是
hot_keyword_stat，由功能三另建）。同步执行：7,259 篇全量约 1–2 分钟，
幂等可重复调用 —— 每次都会清掉 source='extract' 的旧关联再重建。
"""
from flask import Blueprint

from crawl import keywords
from utils.response import ok

bp = Blueprint("keywords", __name__)


@bp.post("/keywords/rebuild")
def rebuild_keywords():
    counts = keywords.rebuild_keywords()
    return ok(counts, message=(
        f"关键词重建完成：{counts['with_keywords']}/{counts['papers']} 篇，"
        f"共 {counts['keywords']} 个词、{counts['links']} 条关联，"
        f"耗时 {counts['elapsed_sec']}s"))
