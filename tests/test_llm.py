"""提供方使用显式替身；这些测试不代表已完成真实 DeepSeek 连接。"""
import io
import json
import threading
import time
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from triage.agent import Agent, Store, ValidationError, ConflictError
from triage.augmentation import Samples, candidate_experiment
from triage.data import ROOT, load_splits
from triage.llm import DeepSeek, LLMError, NoRedirect, summary
from triage.web import create_app
from .test_agent import StubPredictor


class Response(io.BytesIO):
    pass


class Opener:
    def __init__(self, envelope=None, error=None):
        self.envelope = envelope
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return Response(json.dumps(self.envelope).encode())


def envelope(value, finish="stop"):
    return {"choices": [{"message": {"content": json.dumps(value, ensure_ascii=False)}, "finish_reason": finish}], "usage": {"total_tokens": 33, "secret": "omit"}}


def test_deepseek_contract_and_no_redirect():
    op = Opener(envelope({"状态": "连接成功"}))
    client = DeepSeek("sk-test-only-not-real", opener=op)
    result = client.test()
    assert result["usage"] == {"total_tokens": 33}
    request = op.requests[0]
    assert request.full_url == "https://api.deepseek.com/chat/completions"
    payload = json.loads(request.data)
    assert payload["model"] == "deepseek-flash"
    assert payload["thinking"]["type"] == "disabled"
    assert payload["response_format"] == {"type": "json_object"}
    assert "sk-test-only" not in request.data.decode()
    assert NoRedirect().redirect_request(request, None, 302, "moved", {}, "https://example.com") is None


@pytest.mark.parametrize("bad", [[], {}, {"choices": [None]}, envelope([], "stop"), envelope({}, "length"), {"choices": [{"message": {"content": "坏JSON"}, "finish_reason": "stop"}]}])
def test_malformed_provider_response(bad):
    with pytest.raises(LLMError):
        DeepSeek("sk-test-only-not-real", opener=Opener(bad)).test()


@pytest.mark.parametrize("code", [400, 401, 402, 429, 500, 302])
def test_provider_error_does_not_leak(code):
    error = urllib.error.HTTPError("https://api.deepseek.com", code, "secret-sk-do-not-leak", {}, io.BytesIO(b"secret-sk-do-not-leak"))
    with pytest.raises(LLMError) as exc:
        DeepSeek("sk-test-only-not-real", opener=Opener(error=error)).test()
    assert "secret" not in str(exc.value) and str(code) in str(exc.value)


@pytest.mark.parametrize("error", [TimeoutError("secret"), urllib.error.URLError("secret")])
def test_timeout_clean(error):
    with pytest.raises(LLMError, match="连接失败或超时"):
        DeepSeek("sk-test-only-not-real", opener=Opener(error=error)).test()


class FakeClient:
    model = "明确测试替身"

    def __init__(self, key=None, model=None, output=None):
        self.output = output
        self.prompts = []

    def json(self, system, content, **kwargs):
        self.prompts.append(content)
        return self.output, {"model": self.model, "provider": "测试替身", "at": "2026-11-07", "usage": {"total_tokens": 0}}

    def test(self):
        return {"message": "明确测试替身连接", "model": self.model, "usage": {"total_tokens": 0}}


def valid_summary():
    return {"核心诉求": "客户请求冻结账户", "原文依据": ["请冻结我的账户"], "待补充信息": ["是否本人提出申请"], "复核建议": "请人工按规范核实身份"}


@pytest.fixture
def app_components(tmp_path):
    agent = Agent(StubPredictor(), Store(tmp_path / "tickets.sqlite"))
    samples = Samples(tmp_path / "samples")
    fake = FakeClient(output=valid_summary())
    app = create_app(agent, samples, lambda *args: fake)
    app.testing = True
    yield app, agent, samples, fake
    samples.executor.shutdown(wait=True)


def configure(c):
    return c.post("/api/llm/config", json={"api_key": "sk-this-is-a-test-key"})


def test_config_session_isolation_and_clear(app_components):
    app, agent, samples, fake = app_components
    a, b = app.test_client(), app.test_client()
    assert not a.get("/api/llm/config").json["configured"]
    assert configure(a).status_code == 200
    assert a.get("/api/llm/config").json["configured"]
    assert not b.get("/api/llm/config").json["configured"]
    assert b.post("/api/llm/test").status_code == 400
    assert a.post("/api/llm/test").status_code == 200
    response = a.get("/api/llm/config")
    assert "sk-this" not in response.get_data(as_text=True)
    assert a.post("/api/llm/disconnect").status_code == 200
    assert not a.get("/api/llm/config").json["configured"]
    assert a.post("/api/generation", json={}).status_code == 400
    assert a.post("/api/llm/config", json={}, headers={"Origin": "https://attacker.example"}).status_code == 403


def test_summary_persistence_and_fallback(app_components):
    app, agent, samples, fake = app_components
    c = app.test_client()
    original = agent.submit("银行卡被偷了，请冻结我的账户", "摘要测试")
    assert c.post("/api/tickets/摘要测试/summary").status_code == 400
    configure(c)
    good = c.post("/api/tickets/摘要测试/summary")
    assert good.status_code == 200 and good.json["ai_summary"]["content"] == valid_summary()
    assert good.json["status"] == original["status"]
    assert good.json["suggested_intent"] == original["suggested_intent"]
    assert good.json["trace"][-1]["state"] == "summarized"
    fake.output["原文依据"] = ["客户确认已损失五万元"]
    assert c.post("/api/tickets/摘要测试/summary").status_code == 502
    saved = agent.store.get("摘要测试")[1]
    assert saved["ai_summary"]["content"]["原文依据"] == ["请冻结我的账户"]
    assert saved["status"] == "needs_review"
    assert "sk-this" not in json.dumps(saved)
    assert "sk-this" not in Path(agent.store.path).read_bytes().decode(errors="ignore")


def test_summary_sends_redacted_only(app_components):
    app, agent, samples, fake = app_components
    r = agent.submit("卡号1234567890123456丢失，请冻结我的账户", "脱敏摘要")
    summary(fake, r)
    assert "123456789" not in json.dumps(fake.prompts)


def test_other_is_manual_only(app_components):
    app, agent, samples, fake = app_components
    c = app.test_client()
    labels = c.get("/api/labels").json
    assert len(labels["labels"]) == 14 and len(labels["review_labels"]) == 15
    assert "其他" not in {x["intent"] for x in labels["labels"]}
    other = next(x for x in labels["review_labels"] if x["intent"] == "其他")
    assert other["manual_only"]
    r = c.post("/api/tickets", json={"text": "请推荐一只值得购买的股票", "ticket_id": "范围外", "intent": "其他"}).json
    assert r["status"] == "needs_review" and r["final_intent"] is None
    assert all(x["intent"] != "其他" for x in r["candidates"])
    assert c.post("/api/tickets/范围外/review", json={"intent": "其他", "reason": ""}).status_code == 400
    closed = c.post("/api/tickets/范围外/review", json={"intent": "其他", "reason": "投资建议不属于目前14类业务"})
    assert closed.status_code == 200 and closed.json["final_intent"] == "其他"
    assert closed.json["final_queue"] == "其他工单队列" and closed.json["review"]["actor"] == "local_reviewer"
    assert agent.store.get("范围外")[1]["final_intent"] == "其他"
    assert "其他工单队列" in c.get("/api/export").get_data(as_text=True)
    auto = c.post("/api/tickets", json={"text": "查询账户余额", "ticket_id": "自动"}).json
    assert auto["status"] == "closed"
    assert c.post("/api/tickets/自动/review", json={"intent": "其他", "reason": "绕过复核"}).status_code == 409
    configure(c)
    assert c.post("/api/generation", json={"mode": "augmentation", "labels": ["其他"], "count": 1}).status_code == 400


def test_predictor_cannot_route_other(app_components):
    _, agent, _, _ = app_components
    with patch.object(agent.predictor, "predict", return_value=([{"intent": "其他", "probability": 1.0}], [])):
        r = agent.submit("这个业务目前不在范围里面")
    assert r["status"] == "needs_review" and r["final_intent"] is None
    assert not r["candidates"]


def test_generation_api_end_to_end(app_components):
    app, agent, samples, fake = app_components
    c = app.test_client()
    configure(c)
    fake.output = {"工单": [{"文本": "手机页面找不到活期存款剩余金额的栏目，客服能告诉我查询入口在哪里吗", "类别": "查询余额"}]}
    created = c.post("/api/generation", json={"mode": "augmentation", "labels": ["查询余额"], "count": 1})
    assert created.status_code == 202
    b = wait_generation(samples, created.json["id"])
    assert b["samples"][0]["status"] == "pending"
    assert c.get("/api/generation").json["batches"][0]["id"] == b["id"]
    assert c.get("/api/generation/invalid").status_code == 400
    assert c.post("/api/generation/" + b["id"] + "/train", json={}).status_code == 400
    approved = c.post("/api/generation/" + b["id"] + "/review", json={"sample_id": b["samples"][0]["id"], "decision": "approved"})
    assert approved.status_code == 200
    download = c.get("/api/generation/" + b["id"] + "/download")
    assert download.status_code == 200 and "attachment" in download.headers["Content-Disposition"]
    assert "sk-this" not in download.get_data(as_text=True)
    train = c.post("/api/generation/" + b["id"] + "/train", json={})
    assert train.status_code == 202
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        final = c.get("/api/generation/" + b["id"]).json
        if final.get("experiment", {}).get("status") != "running":
            break
        time.sleep(.02)
    assert final["experiment"]["status"] == "completed"
    assert not final["experiment"]["activated"]
    saved = "".join(p.read_text(encoding="utf-8") for p in samples.directory.glob("*.json"))
    assert "sk-this" not in saved


def test_interrupted_jobs_are_not_automatically_retried(tmp_path):
    s = Samples(tmp_path, tiny_splits)
    b = {"id": "a" * 32, "created_at": "2026-11-07", "status": "running", "errors": [], "samples": [], "experiment": {"status": "running"}}
    s.save(b)
    s.executor.shutdown(wait=True)
    resumed = Samples(tmp_path, tiny_splits)
    try:
        restored = resumed.get(b["id"])
        assert restored["status"] == "failed" and restored["experiment"]["status"] == "failed"
        assert not resumed.busy
    finally:
        resumed.executor.shutdown(wait=True)


def tiny_splits():
    return {"train": [{"id": "train-only", "label": "查询余额", "text": "账户里面现在有多少钱"}],
            "calibration": [{"id": "cal-only", "label": "查询余额", "text": "校准私有文本不进提示"}],
            "validation": [{"id": "val-only", "label": "查询余额", "text": "验证私有文本不进提示"}],
            "test": [{"id": "test-only", "label": "查询余额", "text": "测试私有文本不进提示"}]}


def wait_generation(samples, batch_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        b = samples.get(batch_id)
        if b["status"] not in {"queued", "running"}:
            return b
        time.sleep(.01)
    pytest.fail("测试替身任务超时")


def test_generation_isolation_review_and_simulation(tmp_path):
    samples = Samples(tmp_path / "samples", tiny_splits)
    fake = FakeClient(output={"工单": [{"文本": "麻烦客服帮忙看看活期存款还剩多少元呀", "类别": "查询余额"}]})
    try:
        b = samples.start(fake, "augmentation", ["查询余额"], 1)
        b = wait_generation(samples, b["id"])
        assert b["status"] == "completed"
        s = b["samples"][0]
        assert s["status"] == "pending" and s["seed_ids"] == ["train-only"]
        prompt = json.dumps(fake.prompts, ensure_ascii=False)
        assert "train-only" in prompt and all(x not in prompt for x in ["cal-only", "val-only", "test-only", "私有文本"])
        with pytest.raises(ValidationError, match="至少一条"):
            samples.train(b["id"])
        assert samples.review(b["id"], s["id"], "approved")["samples"][0]["status"] == "approved"
        # 模拟边界永不参与训练，即使手动点击保留。
        b2 = samples.start(fake, "simulation", ["查询余额"], 1, "多诉求")
        b2 = wait_generation(samples, b2["id"])
        with pytest.raises(ValidationError):
            samples.train(b2["id"])
    finally:
        samples.executor.shutdown(wait=True)


def test_duplicate_test_contamination_and_pii(tmp_path):
    samples = Samples(tmp_path / "samples", tiny_splits)
    fake = FakeClient(output={"工单": [{"文本": tiny_splits()["test"][0]["text"], "类别": "查询余额"}]})
    try:
        b = wait_generation(samples, samples.start(fake, "augmentation", ["查询余额"], 1)["id"])
        s = b["samples"][0]
        assert s["status"] == "filtered"
        with pytest.raises(ValidationError, match="隔离"):
            samples.review(b["id"], s["id"], "approved")
        assert Samples.filter("我的银行预留手机号是13800138000请处理", []) == "含疑似个人号码或邮箱"
        assert Samples.filter("能否帮忙查询一下我的银行账户余额呢？", ["能否帮忙查询一下我的银行账户余额呢！"]) is not None
    finally:
        samples.executor.shutdown(wait=True)


@pytest.mark.parametrize("mode,labels,count,scenario", [("bad", ["查询余额"], 1, "普通咨询"), ("augmentation", [], 1, "普通咨询"),
    ("augmentation", ["错误"], 1, "普通咨询"), ("augmentation", ["查询余额"], True, "普通咨询"), ("augmentation", ["查询余额"], 11, "普通咨询"),
    ("augmentation", ["查询余额"], 1, "范围外")])
def test_generation_parameter_validation(tmp_path, mode, labels, count, scenario):
    s = Samples(tmp_path, tiny_splits)
    try:
        with pytest.raises(ValidationError):
            s.start(FakeClient(), mode, labels, count, scenario)
    finally:
        s.executor.shutdown(wait=True)


def test_generation_error_record_and_busy(tmp_path):
    gate, started = threading.Event(), threading.Event()
    class Broken(FakeClient):
        def json(self, *args, **kwargs):
            started.set()
            gate.wait(5)
            raise LLMError("DeepSeek：余额不足")
    samples = Samples(tmp_path, tiny_splits)
    try:
        b = samples.start(Broken(), "augmentation", ["查询余额"], 1)
        assert started.wait(2)
        with pytest.raises(ConflictError):
            samples.start(FakeClient(), "augmentation", ["查询余额"], 1)
        gate.set()
        final = wait_generation(samples, b["id"])
        assert final["status"] == "completed_with_errors" and final["errors"] and not final["samples"]
    finally:
        gate.set()
        samples.executor.shutdown(wait=True)


def test_candidate_training_preserves_baseline_and_splits(tmp_path):
    import hashlib
    splits = load_splits()
    frozen_model = (ROOT / "models/model.joblib").read_bytes()
    frozen_split = (ROOT / "data/processed/zh_splits.json").read_bytes()
    sample = {"id": "engineering-test", "text": "手机页面找不到活期存款剩余金额的栏目，客服能告诉我查询入口在哪里吗", "label": "查询余额"}
    result = candidate_experiment(splits, [sample], tmp_path / "candidate.joblib")
    assert result["status"] == "completed" and not result["activated"] and not result["test_used_for_selection"]
    assert result["synthetic_count"] == 1 and result["validation_count"] == 74
    assert (tmp_path / "candidate.joblib").exists()
    assert hashlib.sha256(frozen_model).digest() == hashlib.sha256((ROOT / "models/model.joblib").read_bytes()).digest()
    assert frozen_split == (ROOT / "data/processed/zh_splits.json").read_bytes()
    # 已见过的测试文本，即使标为审核通过也必须被训练前检查拒绝。
    with pytest.raises(ValidationError):
        candidate_experiment(splits, [splits["test"][0]], tmp_path / "forbidden.joblib")
    assert not (tmp_path / "forbidden.joblib").exists()
