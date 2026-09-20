"""解析器注册表。

设计文档要求「解析器分两部分」，所以这里就是两个：cvf / ecva。

  · 列表页解析：两站结构差异大，各写各的（parse_list）
  · 详情页解析：两站 DOM 的 id 完全一致，共用 common.parse_detail

新增数据源时：在本目录加一个模块，实现 SOURCE / index_url / parse_list，
然后注册进 PARSERS 即可，service 层不用改。
"""
from . import common, cvf, ecva
from .common import make_soup, parse_detail

PARSERS = {
    cvf.SOURCE: cvf,
    ecva.SOURCE: ecva,
}

# 两站详情页共用的解析函数，单独导出便于测试与直接调用
parse_common_detail = common.parse_detail

__all__ = ["PARSERS", "cvf", "ecva", "common", "make_soup", "parse_detail",
           "parse_common_detail", "get_parser"]


def get_parser(source):
    try:
        return PARSERS[source]
    except KeyError:
        raise ValueError(f"没有注册名为 {source!r} 的解析器，可选：{list(PARSERS)}")
