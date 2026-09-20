"""统一响应体：{ "code": 0, "message": "ok", "data": {...} }

约定见系统设计 §3：code = 0 表示成功，非 0 表示失败。
"""
from flask import jsonify


def ok(data=None, message="ok"):
    return jsonify({"code": 0, "message": message, "data": data})


def fail(code=400, message="请求失败", data=None):
    return jsonify({"code": code, "message": message, "data": data})
