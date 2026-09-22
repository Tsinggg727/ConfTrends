# 顶会热词 · ConfTrends

一键看懂计算机视觉三大顶会（CVPR / ICCV / ECCV）的研究热点与趋势——
爬取 CVF Open Access / ECVA 的真实论文，抽取关键词，用「词频 × 年份增长率」
量化研究风向，并提供榜单、图谱与走势动画三种视角。

- **线上演示**：<https://tsinggg.pythonanywhere.com>（数据预置版；受平台出站白名单限制，爬取功能请在本地体验）
- **当前版本**：[v1.0.0](RELEASE.md)（发布说明见 `RELEASE.md`）

> 课程信息（请补全）：《软件工程实践》第二次作业 · 与 AI 结对编程 ｜
> 作业链接：`<待填>` ｜ 学号/姓名：`<待填>` ｜ 博客：`<待填>`

---

## 功能总览

| 功能 | 说明 |
|------|------|
| 论文爬取（功能1） | 单题 / 批量粘贴 / BibTeX / 整届清单四种方式；断点续爬、限速 + 并发约束、403/429 熔断、失败归因可重试 |
| 论文列表管理（功能2） | 论文编码（=id）/ 题目 / 关键词三路检索，精确 + 模糊双模式；增删改查；按会议年份批量软删除（可恢复）；联网爬取兜底 |
| Top10 热门方向（功能3） | 热度 = 词频 × 年份增长率；2022–2026 总计 / 单年 × 三大会议汇总 / 单会议多口径 |
| 关键词图谱（功能4） | 力导向布局：节点大小 = 热度、连线 = 同论文共现；点击节点查看相关论文（分页） |
| 热度走势对比（功能5） | 扫描线生长动画（Y 轴固定刻度、旧段不重画）；会议多选、Top N 调节、逐帧播放 |
| 关于页 | 三大会议资料卡 + 数据说明（统计口径 / 数据来源 / 范围与用途） |

**数据规模**：9 届共 **22,945 篇**真实论文（CVPR 2022–2026、ICCV 2023/2025、ECCV 2022/2024），
关键词 83,281 个 / 183,461 篇词关联；热度统计 219,714 行、14 个口径分区。

**数据来源**：[CVF Open Access](https://openaccess.thecvf.com)（CVPR / ICCV）、
[ECVA](https://www.ecva.net)（ECCV）、[Semantic Scholar](https://www.semanticscholar.org)（摘要兜底）。
仅用于课程教学。

---

## 技术栈与架构

- **前端**：Vue 3 + Vite + Element Plus + ECharts + Pinia
- **后端**：Flask 3 + SQLite（标准库 `sqlite3`，`data/schema.sql` 建表）
- **部署**：PythonAnywhere 免费版，Flask 同域托管前端构建产物（`frontend/dist`），
  无需独立前端服务器与跨域配置；详见 `RELEASE.md`

```
conftrends/
├── frontend/            # Vue 3 单页应用
│   └── src/
│       ├── api/          # 接口层，与 backend/api/ 一一对应
│       ├── router/       # 路由（首页/走势/论文管理/爬取导入/关于/详情）
│       ├── layouts/      # BasicLayout：顶部渐变导航 + 页脚
│       ├── stores/       # Pinia：全局年份、任务、可抓取单元
│       ├── views/        # 6 个页面
│       └── components/   # home / crawl / papers 组件
└── backend/             # Flask REST API
    ├── app.py            # 应用工厂；dist 存在时同域托管前端
    ├── api/              # 蓝图：meta / papers / crawl / keywords / stats / graph / conferences
    ├── crawl/            # 爬虫：service / batch / storage / fetcher / parsers(cvf|ecva) / keywords
    ├── hot_stats.py      # 热度统计底座（freq × (1+增长率)，按口径归一化排名）
    ├── data/             # schema.sql + conftrends.db
    └── tests/            # pytest：221 passed + 5 skipped
```

接口约定：统一前缀 `/api/v1`，统一响应体 `{ "code": 0, "message": "ok", "data": {} }`，
分页为 `{ list, total, page, page_size, pages }`；前端拦截器已拆包。

---

## 本地运行

### 1. 后端（端口 5000）

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate              # Windows（macOS/Linux 用 source .venv/bin/activate）
pip install -r requirements.txt

python scripts/init_db.py           # 首次：建表 + 会议种子数据（--reset 删库重建）
python app.py                       # 启动；开发模式 127.0.0.1:5000
```

> 部署环境用环境变量覆盖：`HOST=0.0.0.0 PORT=8000 DEBUG=0`（非 debug 模式）。
> `frontend/dist` 存在时，后端会自动同域托管前端构建产物。

### 2. 前端（端口 5173，开发模式）

```bash
cd frontend
npm install
npm run dev                         # http://127.0.0.1:5173；/api 已代理到 5000
```

### 3. 测试与构建

```bash
cd backend && .venv/Scripts/python -m pytest -q     # 221 passed + 5 skipped
cd frontend && npm run build                        # 产物在 frontend/dist
npm test                                            # 前端单元测试（vitest）
```

### 4. 数据说明

仓库不含数据库文件。从零恢复数据：`python scripts/init_db.py` 建表后，
在「爬取 / 导入」页按整届清单爬取（约 2,500 篇/届，限速下单届 10–20 分钟），
爬完调用 `POST /api/v1/stats/rebuild` 重算热度统计。

---

## AI 结对说明

本项目按课程要求采用「人机结对」方式开发：AI（ZCode / GLM）参与需求分析、
编码实现、bug 定位修复与测试回归；人负责设计决策、方案取舍与逐项验收，
并如实记录了三个结对案例（需求分析 / 编码 / 调试），详见课程博客。
