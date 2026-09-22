"""顶会热词统计平台 · 后端入口。

启动：
    cd backend
    python app.py                 # 开发模式，http://127.0.0.1:5000

部署（PythonAnywhere 等 WSGI 环境）：
    前端构建产物 frontend/dist 存在时自动同域托管 SPA —— / 与非 API
    路径回退到 index.html，API 与静态资源路径不变；dist 不存在（本地
    开发）时根路径保持服务自述 JSON。
"""
import os

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import NotFound

try:
    from flask_cors import CORS
except ImportError:
    # 部署环境（如 PythonAnywhere）可不装 flask-cors：生产同域托管用不到跨域
    CORS = None

from api import register_blueprints
from config import Config
from db import register_db
from utils.response import fail

# 前端构建产物目录（backend 的上一级 / frontend / dist）
DIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "dist")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.json.ensure_ascii = False          # 中文直接输出，不转义成 \uXXXX

    # 开发期前端跑在 5173，跨域放行 /api/*；生产同域托管后不需要跨域放行
    if CORS is not None:
        CORS(app, resources={r"/api/*": {"origins": "*"}})

    register_db(app)
    register_blueprints(app)

    def api_index():
        """服务自述：确认后端活着 + 一眼看到主要端点。"""
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

    if os.path.isdir(DIST_DIR):
        # ---- 生产：同域托管前端 SPA ----
        @app.get("/api")
        def api_doc():
            return api_index()

        @app.route("/")
        @app.route("/<path:path>")
        def spa(path=""):
            if path.startswith("api/"):    # 未匹配到的 API 路径 → JSON 404
                return fail(404, "资源不存在"), 404
            try:
                # send_from_directory 自带目录穿越防护
                return send_from_directory(DIST_DIR, path)
            except NotFound:
                index_html = os.path.join(DIST_DIR, "index.html")
                if os.path.isfile(index_html):
                    return send_from_directory(DIST_DIR, "index.html")
                return fail(404, "资源不存在"), 404
    else:
        @app.get("/")
        def index():
            """根路径给个服务自述，方便浏览器直接确认后端活着。"""
            return api_index()

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
