# codestyle.md — 本仓库代码风格约定

> 供功能 2~5 与 AI 辅助开发遵守。功能 1（步骤 1–4）的现有代码均按此风格书写，
> 拿不准的地方以现有代码为准，而不是另起一套。

## 1. 总则

- 可读性优先于简短：写完整句子，不造只有作者自己懂的缩写和黑话。
- 注释只写代码本身表达不了的东西：**为什么**这么做、约束是什么、坑在哪。
  「这行在干什么」不需要注释；「我这次改了什么」是提交说明的事，不进代码。
- 设计取舍写进模块 docstring（例：`batch.py` 开头解释为什么是「线程 + 数据库」
  而不是 Celery）。读者打开文件第一眼看到的是「为什么」，而不只是「是什么」。
- 与设计文档的对应关系用 § 编号交叉引用（例：§4.1 ②、§6.1 步骤 3、§1.2）。

## 2. Python

- PEP 8 为基线，行宽尽量 ≤ 88。
- 命名：模块 / 函数 / 变量 snake_case；模块级常量全大写；私有加 `_` 前缀。
- 模块、公开函数、类必须有中文 docstring；新的公开行为配套单元测试。
- 测试函数名用中文描述行为（如 `test_API_同会议年份已有任务返回409`），
  名字读出来就是验收标准。

## 3. 架构硬约束（功能 1 已定型，只扩展不改写）

- **不引入 ORM**：sqlite3 + `data/schema.sql`；连接统一走 `db.py`
  （flask.g 复用、WAL、busy_timeout、foreign_keys）。
- **异步任务用 daemon 线程** + `with app.app_context()`，不引入 Celery / Redis。
  任务状态一律落 `crawl_task` / `crawl_task_item`；内存注册表只放天然易失、
  丢了不影响正确性的信息（如 current_title）。
- **出网口全站唯一**：`crawl/fetcher.py`（间隔 0.5–1s、并发 ≤ 2、403/429 熔断）。
  任何新抓取需求复用它，不另开 requests 调用。
- **解析器与流程分离**：对站点 DOM 结构的假设只出现在 `crawl/parsers/`。
- **失败码只用 `crawl/fail_reason.py` 的枚举**，不新造裸字符串。

## 4. HTTP 与错误语义

- 业务失败（论文没找到、摘要为空）返回 **HTTP 200 + `data.status="failed"` +
  `fail_reason`**，不用 4xx —— 前端拦截器对 4xx 会弹 toast，与原型④
  「失败行内展示原因」冲突（设计 §4.1 的取舍）。
- 只有请求本身的错才用状态码：参数不合法 400、资源不存在 404、
  状态冲突 409、上游不可用 503。
- 响应体统一 `{ code, message, data }`（`utils/response.py` 的 `ok` / `fail`）。

## 5. 数据库写法

- **单条一个事务**：`db.transaction()` 包住一篇论文的全部写操作
  （paper + 明细指回 + 关键词关联），中途崩溃整条回滚。
- 批量场景由调用方开一个事务、`execute(..., commit=False)` 逐条喂 ——
  几千次独立 commit 的时间全花在落盘上（见 `commit_staged`）。
- 时间戳统一走 SQLite 的 `CURRENT_TIMESTAMP`，不用 Python 本地时钟（时区会混）。
- 去重以 UNIQUE 约束为准（`paper.title_key`、`paper_keyword(paper_id, keyword_id)`），
  用 `ON CONFLICT` 处理，不先 SELECT 再决定。

## 6. 测试

- **默认不联网**：`FakeFetcher`（`tests/fakes.py`）按 URL 派发本地 fixture HTML，
  用例确定性、秒级。
- 真实站点冒烟默认 skip，显式 `CRAWL_LIVE=1` 才跑（`tests/test_live_crawl.py`）。
- 每个用例一个全新的库（conftest 的 `tmp_path`），用例间不共享状态。
- 需要特定任务状态的用例**直接落库构造**（`storage.create_task` +
  `pause_task` 等），不靠「和后台线程赛跑」拿状态 —— 那是竞态，不是测试
  （`test_API_同会议年份已有任务返回409` 踩过这个坑）。

## 7. Git

- Conventional Commits：`feat` / `fix` / `docs` / `refactor` / `test` / `chore`
  前缀，标题与正文用中文。
- 一次提交做一件事；修 bug 的提交说明写清「为什么错」和「为什么这么修」。
- 不提交 `.venv`、db 文件、`__pycache__`（见 `.gitignore`）。
