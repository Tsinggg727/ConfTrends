"""全局配置。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


class Config:
    # SQLite 数据库文件与建表脚本
    DB_PATH = os.path.join(DATA_DIR, "conftrends.db")
    SCHEMA_PATH = os.path.join(DATA_DIR, "schema.sql")

    # 分页约定（与系统设计 §3 一致）
    DEFAULT_PAGE = 1
    DEFAULT_PAGE_SIZE = 10
    PAGE_SIZE_CHOICES = (10, 20, 50)
    MAX_PAGE_SIZE = 100

    # 统计口径
    YEAR_MIN = 2022
    YEAR_MAX = 2026

    # ---------------- 爬取（见《功能1_论文信息爬取_设计.md》§1.3） ----------------
    # 标识性 UA：带项目名与联系方式，不伪装浏览器
    CRAWL_USER_AGENT = (
        "ConfTrends/0.2 (course project; "
        "contact: student@example.edu) requests"
    )
    # 礼貌抓取的硬约束：两次请求间隔 0.5–1.0s，并发不超过 2
    CRAWL_MIN_INTERVAL = 0.5
    CRAWL_MAX_INTERVAL = 1.0
    CRAWL_CONCURRENCY = 2
    # 索引页 5–7 MB（ECVA 的 papers.php 实测 15 秒），详情页只有 5–7 KB
    CRAWL_LIST_TIMEOUT = 60
    CRAWL_DETAIL_TIMEOUT = 30
    CRAWL_MAX_RETRIES = 2
    CRAWL_RESPECT_ROBOTS = True
    # 解析后的索引结果缓存时长（秒）。一届约 2–3 MB，缓存后连爬多篇只拉一次。
    CRAWL_INDEX_CACHE_TTL = 1800
    # 索引缓存保留几个单元。批量任务不限定会议年份时要依次检索全部 9 个单元，
    # 缓存装不下就会每道题都把 5–7 MB 的索引页重拉一遍 ——
    # 那种批量任务请把这里调到 9（约 25 MB 内存）。
    CRAWL_INDEX_CACHE_MAX_UNITS = 3
    # 单条爬取的总时限（秒）。不限定会议年份时要依次检索 9 个单元，
    # 逐个拉索引页很慢；超时后返回「未找到」并在文案里说明检索被提前结束。
    # 批量任务里这一条是「每个题目」的时限，语义相同。
    CRAWL_SINGLE_DEADLINE_SEC = 240
    # 批量任务连续这么多条**抓取层面**失败（不是「没找到这篇」）就停下来。
    # 站点改版或开始限流时，不能让 5,000 道题一路跑废 —— 停机比跑完更有价值。
    CRAWL_BATCH_MAX_CONSECUTIVE_FAILURES = 20
