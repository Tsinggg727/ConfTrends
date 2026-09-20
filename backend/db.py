"""SQLite 连接管理。

每个请求复用一个连接（挂在 flask.g 上），请求结束自动关闭。
表结构定义见 data/schema.sql。
"""
import sqlite3

from flask import current_app, g


def get_db():
    """取当前请求的数据库连接，不存在则新建。"""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row          # 让查询结果支持 row["列名"]
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    """执行写操作并提交，返回 lastrowid。"""
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


def register_db(app):
    """把连接生命周期挂到 app 上。"""
    app.teardown_appcontext(close_db)
