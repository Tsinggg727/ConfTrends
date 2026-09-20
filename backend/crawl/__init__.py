"""论文信息爬取模块 —— 对应设计文档《功能1_论文信息爬取_设计.md》。

模块划分（与设计文档的分层一一对应）：

    units.py       可抓取单元日历（9 个会议-年份组合，§1.0）
    fetcher.py     限速抓取器：间隔 0.5–1s、并发 ≤2、robots、熔断（§1.3）
    parsers/       解析器：cvf / ecva 各自解析列表页，共用详情页解析（§0.1）
    textutil.py    标题归一化与题目匹配（§1.4 阶段四）
    storage.py     crawl_task / crawl_task_item / paper 的持久化（§3.3）
    fail_reason.py §1.2 的失败码枚举
    service.py     检索→匹配→组装的核心（单条与批量共用，§6.1 步骤 2/3）
    batch.py       批量导入的异步执行、边爬边入库、断点续跑（§6.1 步骤 3/4）

前端页面（§5）不在本模块范围内。
"""

__all__ = ["service", "batch"]
