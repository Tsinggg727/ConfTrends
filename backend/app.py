"""顶会热词统计平台 · 后端入口。

启动：
    cd backend
    python app.py                 # 开发模式，http://127.0.0.1:5000
"""
import os

from flask import Flask, jsonify
from flask_cors import CORS

from api import register_blueprints
from config import Config
from db import register_db
from utils.response import fail


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.json.ensure_ascii = False          # 中文直接输出，不转义成 \uXXXX

    # 开发期前端跑在 5173，跨域放行 /api/*
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    register_db(app)
    register_blueprints(app)

    @app.get("/")
    def index():
        """根路径给个服务自述，方便浏览器直接确认后端活着。"""
        return jsonify({
            "service": "ConfTrends API",
            "version": "0.1.0",
            "api_base": "/api/v1",
            "endpoints": [
                "/api/v1/meta/health",
                "/api/v1/meta/summary",
                "/api/v1/papers",
            ],
        })

    @app.errorhandler(404)
    def handle_404(e):
        return fail(404, "资源不存在"), 404

    @app.errorhandler(500)
    def handle_500(e):
        app.logger.exception(e)
        return fail(500, "服务器内部错误"), 500

    return app


app = create_app()


if __name__ == "__main__":
    # 首次运行若库不存在，提示先建表
    if not os.path.exists(app.config["DB_PATH"]):
        print("[warn] 数据库不存在，请先执行：python scripts/init_db.py")
    else:
        # 上次进程退出时若还有任务在跑，把它们标成 paused，别留「永远 running」
        from crawl import batch
        recovered = batch.recover_stale_tasks(app)
        if recovered:
            print(f"[warn] 已把 {recovered} 个上次未跑完的任务标记为 paused（可从断点续跑）")

    app.run(host="127.0.0.1", port=5000, debug=True)
