"""命令行触发全量关键词抽取（§1.1 阶段五）。

    cd backend
    .venv/Scripts/python.exe scripts/extract_keywords.py

与 POST /api/v1/keywords/rebuild 等价；命令行版没有 HTTP 超时问题，
适合第一次全量跑。
"""
import os
import sys
import time

# 允许 `python scripts/extract_keywords.py` 直接运行时找到上一级模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app          # noqa: E402
from crawl import keywords   # noqa: E402


def main():
    with app.app_context():
        counts = keywords.rebuild_keywords()
    print(f"[keywords] {counts['with_keywords']}/{counts['papers']} 篇命中，"
          f"{counts['keywords']} 个关键词，{counts['links']} 条关联，"
          f"耗时 {counts['elapsed_sec']}s")


if __name__ == "__main__":
    main()
