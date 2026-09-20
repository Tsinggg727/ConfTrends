"""分页参数解析与返回结构。"""
from flask import current_app


def parse_pagination(args):
    """从 query string 解析 page / page_size，并做边界收敛。"""
    cfg = current_app.config
    try:
        page = int(args.get("page", cfg["DEFAULT_PAGE"]))
    except (TypeError, ValueError):
        page = cfg["DEFAULT_PAGE"]
    try:
        page_size = int(args.get("page_size", cfg["DEFAULT_PAGE_SIZE"]))
    except (TypeError, ValueError):
        page_size = cfg["DEFAULT_PAGE_SIZE"]

    page = max(1, page)
    page_size = min(max(1, page_size), cfg["MAX_PAGE_SIZE"])
    return page, page_size


def paginated(items, total, page, page_size):
    """组装 data 字段。"""
    return {
        "list": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
    }
