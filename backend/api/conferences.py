"""会议接口 —— 系统设计 §3.2 /conferences（关于页卡片 + 筛选栏选项数据源）。

    GET /api/v1/conferences         全部会议（三大顶会）
    GET /api/v1/conferences/<code>  单个会议

内容全部来自 conference 表（scripts/init_db.py 灌入的种子数据），
前端关于页不硬编码文案 —— 改会议介绍只需改库。
"""
from flask import Blueprint

from db import query_all, query_one
from utils.response import fail, ok

bp = Blueprint("conferences", __name__)

_FIELDS = "id, code, name, full_name, intro, cycle, scale, official_url"


@bp.get("/conferences")
def list_conferences():
    rows = query_all(f"SELECT {_FIELDS} FROM conference ORDER BY id")
    return ok([dict(r) for r in rows])


@bp.get("/conferences/<code>")
def get_conference(code):
    row = query_one(
        f"SELECT {_FIELDS} FROM conference WHERE code = ?", (code.upper(),))
    if row is None:
        return fail(404, f"会议 {code} 不存在"), 404
    return ok(dict(row))
