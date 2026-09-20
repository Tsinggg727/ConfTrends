"""初始化数据库：执行 data/schema.sql 建表并灌入会议初始数据。

用法：
    cd backend
    python scripts/init_db.py          # 已存在则补建缺失的表/字段，不动数据
    python scripts/init_db.py --reset  # 先删除旧库再重建
"""
import os
import sqlite3
import sys

# Windows 控制台默认 GBK，中文输出会乱码；这里统一按 UTF-8 打印
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 允许 `python scripts/init_db.py` 直接运行时找到上一级模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402

# schema.sql 里 CREATE TABLE IF NOT EXISTS 对**已存在的表**不会补字段，
# 所以 paper 表结构演进（功能1 §3.1：数据源从 DBLP 改为 CVF/ECVA）必须在这里补。
# 新增字段时往这里加一行即可，老库不需要重建、更不会丢数据。
PAPER_COLUMNS = {
    "pdf_url":       "VARCHAR(500)",
    "doi":           "VARCHAR(128)",
    "s2_paper_id":   "VARCHAR(64)",
    "bibtex_key":    "VARCHAR(255)",
    "venue_raw":     "VARCHAR(255)",
    "pages":         "VARCHAR(64)",
    "enrich_status": "VARCHAR(16) DEFAULT 'pending'",
    "match_score":   "REAL",
    "fail_reason":   "VARCHAR(64)",
}

# 已废弃字段：数据源里没有 DBLP 了
PAPER_DROPPED_COLUMNS = ("dblp_url",)

# crawl_task 同样按需补字段（功能1 §6.1 步骤 3：批量任务要记暂停原因）
TASK_COLUMNS = {
    "pause_reason": "VARCHAR(64)",
}


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def _add_columns(conn, table, columns):
    if not _table_exists(conn, table):
        return []                              # 新库交给 schema.sql 全量建，这里不越权
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    added = []
    for name, ddl in columns.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            added.append(f"{table}.{name}")
    return added


def _drop_columns(conn, table, columns, verbose):
    if not _table_exists(conn, table):
        return []
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    dropped = []
    for name in columns:
        if name in have:
            try:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {name}")   # SQLite 3.35+
                dropped.append(f"{table}.{name}")
            except sqlite3.OperationalError as e:
                # 老 SQLite 不支持 DROP COLUMN：留着这个可空字段无害，不值得为它重建表
                if verbose:
                    print(f"[warn] 未能删除 {table}.{name}（{e}），该字段已废弃但可忽略")
    return dropped


def migrate(conn, verbose=True):
    """给已存在的库补字段/删废弃字段，返回 (新增, 删除) 的字段名列表。"""
    added = _add_columns(conn, "paper", PAPER_COLUMNS)
    added += _add_columns(conn, "crawl_task", TASK_COLUMNS)
    dropped = _drop_columns(conn, "paper", PAPER_DROPPED_COLUMNS, verbose)
    conn.commit()

    if verbose and (added or dropped):
        print(f"[migrate] 新增字段：{', '.join(added) or '无'}")
        print(f"[migrate] 删除字段：{', '.join(dropped) or '无'}")
    return added, dropped


def main(reset=False):
    if reset and os.path.exists(Config.DB_PATH):
        # WAL 模式会留下 -wal/-shm 兄弟文件，只删主库会让新库读到旧日志
        for suffix in ("", "-wal", "-shm"):
            path = Config.DB_PATH + suffix
            if os.path.exists(path):
                os.remove(path)
        print(f"[reset] 已删除旧库 {Config.DB_PATH}")

    os.makedirs(os.path.dirname(Config.DB_PATH), exist_ok=True)

    with open(Config.SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()

    conn = sqlite3.connect(Config.DB_PATH)

    # 顺序有讲究：schema.sql 里有建在新字段上的索引（idx_paper_enrich / idx_paper_doi），
    # 老库的 paper 表还没有这些字段，直接 executescript 会卡在建索引那一步。
    # 所以先给已存在的表补字段，再跑 schema 建表建索引。
    if _table_exists(conn, "paper"):
        migrate(conn, verbose=False)

    conn.executescript(schema)
    conn.commit()

    # 新库走 schema 全量建表，这里确认字段齐全；老库此处是空操作
    migrate(conn)

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    confs = [r[0] for r in conn.execute("SELECT code FROM conference ORDER BY id")]
    conn.close()

    print(f"[ok] 数据库已就绪：{Config.DB_PATH}")
    print(f"[ok] 表：{', '.join(tables)}")
    print(f"[ok] 会议：{', '.join(confs)}")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
