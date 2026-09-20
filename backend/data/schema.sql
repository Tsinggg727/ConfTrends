-- 顶会热词统计平台 · SQLite 建表脚本
-- 对应系统设计 §2：4 张主表 + 1 张多对多关联表
-- 执行方式：python scripts/init_db.py

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- 1. 会议表 conference
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conference (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         VARCHAR(16)  NOT NULL UNIQUE,          -- CVPR / ICCV / ECCV
    name         VARCHAR(64)  NOT NULL,                 -- 展示简称
    full_name    VARCHAR(200),                          -- 会议全称
    intro        TEXT,                                  -- 简介（关于页卡片展开）
    cycle        VARCHAR(32),                           -- 周期，如「每年一届」
    scale        VARCHAR(64),                           -- 规模，如「约 3000 篇录用」
    official_url VARCHAR(255),                          -- 官网链接
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------
-- 2. 论文表 paper
--    字段来源见《功能1_论文信息爬取_设计.md》§2 / §3.1
--    注：原设计的 dblp_url 已废弃（数据源从 DBLP 改为 CVF / ECVA）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         VARCHAR(500) NOT NULL,                -- 原始题目
    title_key     VARCHAR(500) NOT NULL UNIQUE,         -- 归一化题目，用于入库去重
    conference_id INTEGER      REFERENCES conference(id),
    year          INTEGER      NOT NULL,                -- 2022–2026
    abstract      TEXT,                                 -- 摘要（详情页折叠展示）
    authors       VARCHAR(500),                         -- 作者，逗号分隔
    url           VARCHAR(500),                         -- 原文链接（详情页）
    pdf_url       VARCHAR(500),                         -- PDF 直链
    doi           VARCHAR(128),                         -- DOI（ECVA 列表页 100%，CVF 走详情页 meta）
    s2_paper_id   VARCHAR(64),                          -- Semantic Scholar paperId（兜底补全用）
    bibtex_key    VARCHAR(255),                         -- BibTeX 键，溯源
    venue_raw     VARCHAR(255),                         -- booktitle / 会议原文
    pages         VARCHAR(64),                          -- 页码
    source        VARCHAR(16)  DEFAULT 'manual',        -- cvf / ecva / manual / csv
    status        VARCHAR(16)  DEFAULT 'active',        -- active / deleted（软删除）
    enrich_status VARCHAR(16)  DEFAULT 'pending',       -- pending / partial / enriched / failed
    match_score   REAL,                                 -- 标题匹配相似度，低于阈值需人工复核
    fail_reason   VARCHAR(64),                          -- 失败码，见功能1设计 §1.2
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_conf_year ON paper(conference_id, year);
CREATE INDEX IF NOT EXISTS idx_paper_year      ON paper(year);
CREATE INDEX IF NOT EXISTS idx_paper_status    ON paper(status);
CREATE INDEX IF NOT EXISTS idx_paper_enrich    ON paper(enrich_status);
CREATE INDEX IF NOT EXISTS idx_paper_doi       ON paper(doi);

-- ---------------------------------------------------------------
-- 3. 关键词表 keyword
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS keyword (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(128) NOT NULL,                  -- 展示名 Diffusion Model
    name_key    VARCHAR(128) NOT NULL UNIQUE,           -- 归一化名 diffusion model
    alias       VARCHAR(255),                           -- 同义词，逗号分隔
    is_hot_tag  BOOLEAN DEFAULT 0,                      -- 是否作为首页热门快捷标签
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_keyword_name_key ON keyword(name_key);

-- ---------------------------------------------------------------
-- 4. 论文-关键词关联表 paper_keyword（多对多）
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paper_keyword (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id   INTEGER NOT NULL REFERENCES paper(id)   ON DELETE CASCADE,
    keyword_id INTEGER NOT NULL REFERENCES keyword(id) ON DELETE CASCADE,
    weight     REAL    DEFAULT 0,                       -- TF-IDF / TextRank 权重
    rank       INTEGER,                                 -- 该词在本篇内的序位，1 = 最相关
    source     VARCHAR(16) DEFAULT 'extract',           -- extract 自动抽取 / manual 人工编辑
    UNIQUE (paper_id, keyword_id)
);

CREATE INDEX IF NOT EXISTS idx_pk_paper   ON paper_keyword(paper_id);
CREATE INDEX IF NOT EXISTS idx_pk_keyword ON paper_keyword(keyword_id);

-- ---------------------------------------------------------------
-- 5. 热词统计表 hot_keyword_stat
--    conference_id 为 NULL 表示「三大会议汇总」口径
--    唯一约束保证同一 (词, 会议, 年) 只存一行，重算时用 INSERT OR REPLACE
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hot_keyword_stat (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id    INTEGER NOT NULL REFERENCES keyword(id),
    conference_id INTEGER          REFERENCES conference(id),   -- NULL = 汇总
    year          INTEGER NOT NULL,
    freq          INTEGER NOT NULL DEFAULT 0,               -- 词频
    prev_freq     INTEGER DEFAULT 0,                        -- 上一年词频
    growth_rate   REAL    DEFAULT 0,                        -- 年度增长率
    heat          REAL    NOT NULL DEFAULT 0,               -- 热度 = freq × (1 + growth_rate)
    heat_norm     REAL    DEFAULT 0,                        -- 归一化热度 0–100
    rank          INTEGER,                                  -- 该年该范围内排名，1 = Top1
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (keyword_id, conference_id, year)
);

CREATE INDEX IF NOT EXISTS idx_stat_year_rank ON hot_keyword_stat(year, conference_id, rank);
CREATE INDEX IF NOT EXISTS idx_stat_heat      ON hot_keyword_stat(heat DESC);

-- ---------------------------------------------------------------
-- 6. 抓取任务表 crawl_task
--    批量导入是长时任务，进度/断点/重试都要持久化。
--    只放内存的话，Flask debug 模式一热重载就前功尽弃。
--    见《功能1_论文信息爬取_设计.md》§3.3
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_task (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         VARCHAR(36) NOT NULL UNIQUE,        -- UUID，对外暴露
    type            VARCHAR(16) NOT NULL,               -- single / batch_titles / bibtex / unit
    conference_code VARCHAR(16),                        -- 目标会议
    year            INTEGER,                            -- 目标年份
    auto_commit     BOOLEAN DEFAULT 0,                  -- 边爬边入库 / 暂存待确认
    status          VARCHAR(16) DEFAULT 'queued',       -- queued/running/paused/done/cancelled/failed
    stage           VARCHAR(16) DEFAULT 'discover',     -- discover/enrich/s2/extract/commit
    total           INTEGER DEFAULT 0,
    finished        INTEGER DEFAULT 0,
    success         INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    cursor          INTEGER DEFAULT 0,                  -- 断点游标，续跑从这里开始
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME,
    finished_at     DATETIME
);

CREATE INDEX IF NOT EXISTS idx_task_status ON crawl_task(status);
CREATE INDEX IF NOT EXISTS idx_task_unit   ON crawl_task(conference_code, year);

-- ---------------------------------------------------------------
-- 7. 抓取任务明细表 crawl_task_item
--    parsed_json 是「暂存 → 全部入库」模式的关键：解析结果先落这里，
--    用户点「全部入库」时才写 paper 表，中途刷新页面结果也不会丢。
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_task_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES crawl_task(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,                       -- 序号，与 crawl_task.cursor 对应
    input_title VARCHAR(500),                           -- 输入题目
    detail_url  VARCHAR(500),                           -- 阶段一产出
    pdf_url     VARCHAR(500),
    status      VARCHAR(16) DEFAULT 'pending',          -- pending/success/failed/skipped
    paper_id    INTEGER REFERENCES paper(id),           -- 成功后指向 paper.id，供结果行「查看」跳转
    fail_reason VARCHAR(64),                            -- 失败码，见功能1设计 §1.2
    parsed_json TEXT,                                   -- 解析结果中间态
    retry_count INTEGER DEFAULT 0,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_item_task   ON crawl_task_item(task_id);
CREATE INDEX IF NOT EXISTS idx_item_status ON crawl_task_item(status);

-- ---------------------------------------------------------------
-- 初始数据：三大顶会
-- ---------------------------------------------------------------
INSERT OR IGNORE INTO conference (code, name, full_name, cycle, scale, official_url, intro) VALUES
('CVPR', 'CVPR', 'IEEE/CVF Conference on Computer Vision and Pattern Recognition',
 '每年一届', '约 3000 篇录用', 'https://cvpr.thecvf.com/',
 '计算机视觉领域规模最大、影响力最高的顶级会议，论文涵盖图像识别、生成模型、三维重建等方向。'),
('ICCV', 'ICCV', 'IEEE/CVF International Conference on Computer Vision',
 '两年一届（奇数年）', '约 2000 篇录用', 'https://iccv.thecvf.com/',
 '与 CVPR 并列的计算机视觉顶级会议，每两年举办一次，录取率通常低于 CVPR。'),
('ECCV', 'ECCV', 'European Conference on Computer Vision',
 '两年一届（偶数年）', '约 2000 篇录用', 'https://eccv.ecva.net/',
 '欧洲计算机视觉会议，与 CVPR、ICCV 并称三大顶会，偶数年举办。');
