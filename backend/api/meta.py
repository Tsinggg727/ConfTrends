"""平台元信息：/api/v1/meta/*

导航栏右侧的「数据更新：2026-09-20 ｜ N 篇」标签、首页 Hero 统计条都读这里。
"""
from flask import Blueprint, current_app

from db import query_one
from utils.response import ok

bp = Blueprint("meta", __name__)


@bp.get("/meta/health")
def health():
    """存活探针：顺带验证数据库可读。"""
    query_one("SELECT 1")
    return ok({"status": "ok", "db": True})


@bp.get("/meta/summary")
def summary():
    """数据标签 + Hero 统计条。"""
    cfg = current_app.config

    paper_count = query_one(
        "SELECT COUNT(*) AS c FROM paper WHERE status = 'active'"
    )["c"]
    keyword_count = query_one("SELECT COUNT(*) AS c FROM keyword")["c"]
    updated_at = query_one(
        "SELECT MAX(updated_at) AS m FROM paper WHERE status = 'active'"
    )["m"]

    year_range = query_one(
        "SELECT MIN(year) AS a, MAX(year) AS b FROM paper WHERE status = 'active'"
    )
    conferences = query_one("SELECT COUNT(*) AS c FROM conference")["c"]

    return ok({
        "paper_count": paper_count,
        "keyword_count": keyword_count,
        "conference_count": conferences,
        "updated_at": updated_at or None,
        # 库中无数据时回落到配置的默认年份区间，前端展示不空白
        "year_range": [
            year_range["a"] or cfg["YEAR_MIN"],
            year_range["b"] or cfg["YEAR_MAX"],
        ],
    })
