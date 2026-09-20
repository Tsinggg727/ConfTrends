# 顶会热词 · ConfTrends

一键看懂计算机视觉三大顶会（CVPR / ICCV / ECCV）的研究热点与趋势。

技术栈：Vue 3 + Vite + Element Plus + ECharts + Pinia ／ Flask + SQLite
设计依据：[系统设计_v1.md](../系统设计_v1.md) ｜ [原型设计初稿_v3.md](../原型设计初稿_v3.md)

---

## 目录结构

```
conftrends/
├── frontend/          # Vue 3 单页应用
│   └── src/
│       ├── api/        # 接口层，与 backend/api/ 一一对应
│       ├── router/     # 路由表（6 个一级页面）
│       ├── layouts/    # BasicLayout：顶部固定导航 + 页脚
│       ├── stores/     # Pinia：全局年份 + 数据标签
│       ├── views/      # 6 个页面
│       └── components/ # 公共组件
└── backend/           # Flask REST API
    ├── app.py          # 应用工厂 + 入口
    ├── config.py       # 配置
    ├── db.py           # SQLite 连接管理
    ├── data/           # schema.sql + conftrends.db
    ├── api/            # 蓝图（meta / papers …）
    ├── utils/          # 统一响应、分页
    └── scripts/        # init_db.py 建表脚本
```

---

## 启动方式

### 1. 后端（端口 5000）

```bash
cd backend

# 首次：创建虚拟环境并装依赖
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

# 首次：建表 + 灌入三大会议初始数据
python scripts/init_db.py          # 加 --reset 可删库重建

# 启动
python app.py
```

验证：

```bash
curl http://127.0.0.1:5000/api/v1/meta/health
curl http://127.0.0.1:5000/api/v1/meta/summary
```

### 2. 前端（端口 5173）

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 <http://127.0.0.1:5173>，首页应显示 **Hello** 及后端连通状态。
Vite 已配置代理，`/api/*` 会转发到 `http://127.0.0.1:5000`，前端代码里不出现后端域名。

---

## 已完成 / 待实现

| 模块 | 状态 |
|------|------|
| 前后端骨架、6 页路由与顶部导航 | ✅ 已完成 |
| 数据库 5 张表建表 SQL + 会议初始数据 | ✅ 已完成 |
| `/meta/health`、`/meta/summary`、`/papers` 三个接口 | ✅ 已完成 |
| 首页 Top10 榜单 + 关键词图谱 + 抽屉 | ⬜ 待实现 |
| 走势页折线动图 + 导出 GIF | ⬜ 待实现 |
| 列表页 CRUD + 批量导入 + 删除确认 | ⬜ 待实现 |
| 爬取/导入页（DBLP 客户端 + 任务轮询） | ⬜ 待实现 |
| 详情页左右两栏 + 相关论文闭环 | ⬜ 待实现 |
| 关于页会议卡片 + 数据说明 | ⬜ 待实现 |

每个空页面用 `PagePlaceholder` 标注了「规划中的组件 + 对应设计文档章节」，按表逐个替换即可。

---

## 接口约定

统一前缀 `/api/v1`，统一响应体：

```json
{ "code": 0, "message": "ok", "data": { } }
```

`code = 0` 为成功，非 0 为失败（400 参数错 / 404 不存在 / 409 重复 / 500 服务端错）。
分页响应的 `data` 为 `{ list, total, page, page_size, pages }`。

前端 `src/api/request.js` 已在拦截器里拆包，调用方拿到的直接是 `data`，无需再判断 `code`。

---

## 下一步

按系统设计 §7 的实现顺序推进：

1. 关键词抽取（TF-IDF / TextRank）+ 统计重算 + `/keywords/*` → 首页图谱与 Top10
2. `/stats/trend` → 走势页
3. 论文 CRUD + 导入 → 列表页
4. 爬取模块（DBLP 客户端 + 任务化轮询）→ 爬取页
5. 详情页 + 关于页

> 注：骨架阶段数据库访问用的是 Python 标准库 `sqlite3`（配合 `data/schema.sql`），
> 依赖只需 Flask + flask-cors，在 Python 3.14 上零风险。
> 若后续要换成系统设计里提到的 SQLAlchemy ORM，`schema.sql` 与模型字段一一对应，替换成本很低。
