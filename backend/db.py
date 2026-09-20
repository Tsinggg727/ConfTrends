"""SQLite 连接管理。

每个请求复用一个连接（挂在 flask.g 上），请求结束自动关闭。
批量任务的 worker 线程自己开一个 app context，于是也拿到一份**独立**连接
（sqlite3 的连接不是线程安全的，不能跨线程共用），但它们写的是同一个库文件
—— 所以下面两条 PRAGMA 是必需的，不是优化。

表结构定义见 data/schema.sql。
"""
import sqlite3
from contextlib import contextmanager

from flask import current_app, g

# 等锁的上限（毫秒）。批量任务在后台线程里写、进度查询在主线程里读，
# 没有这个的话两边一撞就直接抛 database is locked。
BUSY_TIMEOUT_MS = 5000


def get_db():
    """取当前请求（或当前线程的 app context）的数据库连接，不存在则新建。"""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row          # 让查询结果支持 row["列名"]

        # WAL：读不阻塞写、写不阻塞读。轮询进度时不会把 worker 卡住，
        # worker 提交入库时也不会让轮询报错。这个模式记在库文件里，
        # 已经是 wal 就不必再切（切换本身要拿写锁，能省则省）。
        if g.db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            g.db.execute("PRAGMA journal_mode = WAL")

        g.db.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
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


def execute(sql, params=(), commit=True):
    """执行写操作，返回 lastrowid。

    commit=False 用于「一次入库几千篇」这类批量场景：调用方自己开事务，
    逐条提交会把时间全花在落盘上。
    """
    db = get_db()
    cur = db.execute(sql, params)
    if commit:
        db.commit()
    return cur.lastrowid


def execute_many(sql, seq_of_params, commit=True):
    """批量写，默认只提交一次。"""
    db = get_db()
    cur = db.executemany(sql, seq_of_params)
    if commit:
        db.commit()
    return cur.rowcount


@contextmanager
def transaction():
    """把一批写操作收进一个事务：要么全成，要么全不成。

    配合 execute(..., commit=False) 使用。
    """
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def register_db(app):
    """把连接生命周期挂到 app 上。"""
    app.teardown_appcontext(close_db)
