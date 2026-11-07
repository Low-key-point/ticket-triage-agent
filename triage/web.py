"""Loopback-only demo UI and JSON API."""
import json
import sqlite3
import secrets
import threading
import time
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_from_directory, session
from .agent import Agent, ConflictError, ValidationError, export_csv
from .data import ROOT
from .knowledge import MAPPING, REVIEW_MAPPING
from .llm import DeepSeek, LLMError, summary
from .augmentation import Samples


def create_app(agent=None, samples=None, client_factory=None):
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    agent = agent or Agent()
    samples = samples or Samples()
    client_factory = client_factory or DeepSeek
    credentials = {}
    credential_lock = threading.Lock()

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValidationError("请提交JSON对象")
        return value

    def client(required=True):
        with credential_lock:
            expired = [sid for sid, item in credentials.items() if time.monotonic() - item[1] > 8 * 3600]
            for sid in expired:
                del credentials[sid]
            value = credentials.get(session.get("llm_sid"))
        if not value and required:
            raise ValidationError("请先在大模型设置中填写 DeepSeek 密钥")
        return value[0] if value else None

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

    @app.errorhandler(LLMError)
    def llm_error(exc):
        return jsonify(error=str(exc), local_classification_available=True), 502

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
        return jsonify(labels=[{"intent": k, "queue": v} for k, v in sorted(MAPPING.items())],
                       review_labels=[{"intent": k, "queue": v, "manual_only": k == "其他"} for k, v in sorted(REVIEW_MAPPING.items())])

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

    @app.get("/api/llm/config")
    def llm_config():
        configured = client(False)
        return jsonify(configured=bool(configured), provider="DeepSeek", model=configured.model if configured else "deepseek-flash",
                       endpoint="https://api.deepseek.com", storage="仅服务端内存，8小时过期；重启服务后清除")

    @app.post("/api/llm/config")
    def configure_llm():
        data = body()
        sid = session.get("llm_sid") or secrets.token_urlsafe(32)
        new_client = client_factory(data.get("api_key"), data.get("model", "deepseek-flash"))
        client(False)  # 清理已过期配置。
        with credential_lock:
            if sid not in credentials and len(credentials) >= 64:
                raise ConflictError("本地配置会话数量过多，请重启服务")
            credentials[sid] = (new_client, time.monotonic())
        session["llm_sid"] = sid
        return jsonify(configured=True, model=new_client.model, message="密钥已存入服务端内存，尚未进行网络连接测试")

    @app.post("/api/llm/disconnect")
    def disconnect_llm():
        with credential_lock:
            credentials.pop(session.get("llm_sid"), None)
        session.clear()
        return jsonify(configured=False)

    @app.post("/api/llm/test")
    def test_llm():
        return jsonify(client().test())

    @app.post("/api/tickets/<ticket_id>/summary")
    def summarize(ticket_id):
        configured = client()
        existing = agent.store.get(ticket_id)
        if not existing:
            raise KeyError(ticket_id)
        result = summary(configured, existing[1])
        return jsonify(agent.store.save_summary(ticket_id, result))

    @app.get("/api/generation")
    def batches():
        return jsonify(batches=samples.list())

    @app.post("/api/generation")
    def generate():
        data = body()
        return jsonify(samples.start(client(), data.get("mode"), data.get("labels"), data.get("count"), data.get("scenario", "普通咨询"))), 202

    @app.get("/api/generation/<batch_id>")
    def batch_status(batch_id):
        return jsonify(samples.get(batch_id))

    @app.post("/api/generation/<batch_id>/review")
    def review_sample(batch_id):
        data = body()
        return jsonify(samples.review(batch_id, data.get("sample_id"), data.get("decision")))

    @app.post("/api/generation/<batch_id>/train")
    def candidate_train(batch_id):
        return jsonify(samples.train(batch_id)), 202

    @app.get("/api/generation/<batch_id>/download")
    def download_batch(batch_id):
        return Response(json.dumps(samples.get(batch_id), ensure_ascii=False, indent=2), content_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=synthetic-" + batch_id + ".json"})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8765, debug=False)
