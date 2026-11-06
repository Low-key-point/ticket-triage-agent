"""Loopback-only demo UI and JSON API."""
import json
import sqlite3
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_from_directory
from .agent import Agent, ConflictError, ValidationError, export_csv
from .data import ROOT
from .knowledge import MAPPING


def create_app(agent=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    agent = agent or Agent()

    @app.before_request
    def local_only():
        if request.host.split(":")[0] not in {"127.0.0.1", "localhost", "[::1]"}:
            return jsonify(error="仅允许本机访问"), 403
        origin = request.headers.get("Origin")
        if request.method != "GET" and origin and urlparse(origin).netloc != request.host:
            return jsonify(error="拒绝跨来源修改"), 403
        if request.method != "GET" and request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(error="拒绝跨站修改"), 403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.errorhandler(ValidationError)
    def validation(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(ConflictError)
    def conflict(exc):
        return jsonify(error=str(exc)), 409

    @app.errorhandler(KeyError)
    def missing(exc):
        return jsonify(error="工单不存在"), 404

    @app.errorhandler(sqlite3.Error)
    @app.errorhandler(OSError)
    def storage_error(exc):
        return jsonify(error="本地工具不可用，操作未确认完成", code=type(exc).__name__), 503

    @app.errorhandler(413)
    def too_big(exc):
        return jsonify(error="上传内容超过2MB限制"), 413

    @app.get("/")
    def home():
        return send_from_directory(ROOT/"web", "index.html")

    @app.get("/assets/<path:name>")
    def assets(name):
        return send_from_directory(ROOT/"web", name)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", model=agent.predictor.metadata)

    @app.get("/api/labels")
    def labels():
        return jsonify(labels=[{"intent": k, "queue": v} for k, v in sorted(MAPPING.items())])

    @app.get("/api/tickets")
    def tickets():
        return jsonify(tickets=agent.store.list(request.args.get("status")))

    @app.post("/api/tickets")
    def submit():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("请提交JSON对象")
        return jsonify(agent.submit(body.get("text"), body.get("ticket_id")))

    @app.post("/api/tickets/<ticket_id>/review")
    def review(ticket_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("请提交JSON对象")
        return jsonify(agent.store.review(ticket_id, body.get("intent"), body.get("reason")))

    @app.post("/api/batch")
    def batch():
        if "file" not in request.files:
            raise ValidationError("请选择UTF-8 CSV文件")
        return jsonify(agent.batch(request.files["file"].read()))

    @app.get("/api/export")
    def export():
        return Response(export_csv(agent.store.list()), content_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=tickets.csv"})

    @app.get("/api/metrics")
    def metrics():
        path = ROOT/"reports/evaluation.json"
        return jsonify(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "not_evaluated"})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8765, debug=False)
