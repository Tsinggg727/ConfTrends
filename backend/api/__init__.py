"""蓝图注册。新增蓝图时在 BLUEPRINTS 里追加即可。

系统设计 §3 规划的 6 组接口已全部实现：
meta / papers / crawl / keywords / stats / graph / conferences。
"""
from .conferences import bp as conferences_bp
from .crawl import bp as crawl_bp
from .graph import bp as graph_bp
from .keywords import bp as keywords_bp
from .meta import bp as meta_bp
from .papers import bp as papers_bp
from .stats import bp as stats_bp

BLUEPRINTS = (
    meta_bp,
    papers_bp,
    crawl_bp,
    keywords_bp,
    stats_bp,
    graph_bp,
    conferences_bp,
)


def register_blueprints(app, url_prefix="/api/v1"):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=url_prefix)
