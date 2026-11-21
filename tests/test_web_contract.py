"""HTTP, static-asset, and safety contracts for the local Agent UI."""

import io
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

import triage.web as web_module
from triage.agent import Agent, Store
from triage.augmentation import Samples
from triage.data import ROOT
from triage.web import create_app
from .test_agent import StubPredictor
from .test_llm import FakeClient, valid_summary


@pytest.fixture
def web_components(tmp_path):
    agent = Agent(StubPredictor(), Store(tmp_path / "web.sqlite"))
    samples = Samples(tmp_path / "samples")
    fake = FakeClient(output=valid_summary())
    app = create_app(agent, samples, lambda *args: fake)
    app.testing = True
    try:
        yield app, agent, samples, fake
    finally:
        samples.executor.shutdown(wait=True)


def test_route_contract_covers_every_public_entry(web_components):
    app, _, _, _ = web_components
    routes = {}
    for rule in app.url_map.iter_rules():
        methods = rule.methods - {"HEAD", "OPTIONS"}
        routes.setdefault(rule.rule, set()).update(methods)
    assert routes == {
        "/": {"GET"},
        "/assets/<path:name>": {"GET"},
        "/api/health": {"GET"},
        "/api/labels": {"GET"},
        "/api/tickets": {"GET", "POST"},
        "/api/tickets/<ticket_id>/review": {"POST"},
        "/api/batch": {"POST"},
        "/api/export": {"GET"},
        "/api/metrics": {"GET"},
        "/api/llm/config": {"GET", "POST"},
        "/api/llm/disconnect": {"POST"},
        "/api/llm/test": {"POST"},
        "/api/tickets/<ticket_id>/summary": {"POST"},
        "/api/generation": {"GET", "POST"},
        "/api/generation/<batch_id>": {"GET"},
        "/api/generation/<batch_id>/review": {"POST"},
        "/api/generation/<batch_id>/train": {"POST"},
        "/api/generation/<batch_id>/download": {"GET"},
        "/static/<path:filename>": {"GET"},
    }


def test_static_assets_and_security_headers(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    pages = [c.get("/"), c.get("/assets/style.css"), c.get("/assets/app.js")]
    for response in pages:
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert "银行客服工单分流智能体" in pages[0].get_data(as_text=True)
    assert ".sidebar" in pages[1].get_data(as_text=True)
    assert "async function api" in pages[2].get_data(as_text=True)
    assert c.get("/assets/../triage/web.py").status_code == 404


def test_frontend_dom_contract_matches_scripts():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    script = (ROOT / "web/app.js").read_text(encoding="utf-8")
    referenced_ids = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", script))
    declared_ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert referenced_ids <= declared_ids
    assert {
        "tab-work", "tab-review", "tab-metrics", "tab-settings", "tab-generate",
        "submit", "confirm-review", "save-llm", "generate", "train-candidate",
    } <= declared_ids
    assert "https://github.com/Low-key-point/ticket-triage-agent" in html
    assert "不要发在聊天中" not in html


def test_read_and_local_workflow_endpoints(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    assert c.get("/api/health").json["status"] == "ok"
    assert len(c.get("/api/labels").json["labels"]) == 14
    created = c.post("/api/tickets", json={"text": "我想查询账户余额", "ticket_id": "web-1"})
    assert created.status_code == 200 and created.json["status"] == "closed"
    assert [x["id"] for x in c.get("/api/tickets").json["tickets"]] == ["web-1"]
    assert [x["id"] for x in c.get("/api/tickets?status=closed").json["tickets"]] == ["web-1"]
    metrics = c.get("/api/metrics").json
    if "status" in metrics:
        assert metrics["status"] == "not_evaluated"
    else:
        assert metrics["model_version"] == "e1786c6c519c"
        assert metrics["test_count"] == 95


def test_csv_batch_and_export_http_contract(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    payload = "ticket_id,text\n示例-余额,我想查询账户余额\n示例-范围外,请推荐股票\n".encode()
    result = c.post("/api/batch", data={"file": (io.BytesIO(payload), "tickets.csv")})
    assert result.status_code == 200
    assert len(result.json["results"]) == 2
    exported = c.get("/api/export")
    assert exported.status_code == 200
    assert "text/csv" in exported.content_type
    assert "attachment; filename=tickets.csv" == exported.headers["Content-Disposition"]
    assert "示例-余额" in exported.get_data(as_text=True)
    missing = c.post("/api/batch", data={})
    assert missing.status_code == 400


def test_missing_resources_and_unsupported_methods(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    assert c.get("/api/not-a-route").status_code == 404
    assert c.delete("/api/tickets").status_code == 405
    assert c.get("/api/generation/invalid").status_code == 400
    assert c.post("/api/tickets/missing/review", json={"intent": "其他", "reason": "测试"}).status_code == 404
    assert c.get("/api/tickets/missing/summary").status_code == 405


def test_remote_host_and_cross_site_mutations_are_rejected(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    remote = c.get("/api/health", base_url="http://example.com")
    assert remote.status_code == 403 and remote.json["error"] == "仅允许本机访问"
    cross_origin = c.post(
        "/api/tickets",
        json={"text": "查询余额"},
        headers={"Origin": "https://example.com"},
    )
    assert cross_origin.status_code == 403
    cross_site = c.post(
        "/api/tickets",
        json={"text": "查询余额"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site.status_code == 403


def test_payload_limit_and_invalid_json(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    huge = c.post("/api/tickets", data=b"{" + b"x" * (2 * 1024 * 1024) + b"}", content_type="application/json")
    assert huge.status_code == 413 and huge.json["error"] == "上传内容超过2MB限制"
    invalid = c.post("/api/tickets", data="[]", content_type="application/json")
    assert invalid.status_code == 400


def test_metrics_fallback_when_report_is_absent(web_components, tmp_path):
    app, _, _, _ = web_components
    with patch.object(web_module, "ROOT", tmp_path):
        assert app.test_client().get("/api/metrics").json == {"status": "not_evaluated"}


def test_llm_credentials_expire_after_eight_hours(web_components):
    app, _, _, _ = web_components
    c = app.test_client()
    with patch.object(web_module.time, "monotonic", return_value=100):
        assert c.post("/api/llm/config", json={"api_key": "sk-test"}).status_code == 200
    with patch.object(web_module.time, "monotonic", return_value=100 + 8 * 3600 + 1):
        assert c.get("/api/llm/config").json["configured"] is False
        assert c.post("/api/llm/test").status_code == 400


def test_llm_session_cap_is_enforced(web_components):
    app, _, _, _ = web_components
    clients = [app.test_client() for _ in range(65)]
    for client in clients[:64]:
        assert client.post("/api/llm/config", json={"api_key": "sk-test"}).status_code == 200
    overflow = clients[64].post("/api/llm/config", json={"api_key": "sk-test"})
    assert overflow.status_code == 409
    assert "会话数量过多" in overflow.json["error"]


def test_summary_requires_an_existing_ticket(web_components):
    app, _, _, fake = web_components
    c = app.test_client()
    assert c.post("/api/llm/config", json={"api_key": "sk-test"}).status_code == 200
    assert c.post("/api/tickets/missing/summary").status_code == 404
    assert fake.prompts == []


def test_project_contract_files_and_pinned_dependencies():
    expected = [
        "README.md",
        "DEMO.md",
        "requirements.txt",
        "scripts/start.ps1",
        "scripts/reproduce.ps1",
        "demo/tickets.csv",
        "demo/augmentation.json",
        "demo/architecture.png",
        "demo/workflow.png",
        "demo/AI_ACCEPTANCE_20261121.md",
        "tests/test_web_contract.py",
    ]
    assert all((ROOT / path).exists() for path in expected)
    requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert requirements and all("==" in line for line in requirements)
    demo = (ROOT / "DEMO.md").read_text(encoding="utf-8")
    assert "-m pytest -q" in demo
    assert "reproduce.ps1" in demo
    assert "DeepSeek" in demo


def test_cli_help_is_available():
    import os
    import subprocess
    import sys

    env = os.environ | {"PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "triage.cli", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert "银行客服咨询内容" in result.stdout
