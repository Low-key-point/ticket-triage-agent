import io
import json
import sqlite3
from unittest.mock import patch
import pytest
from triage.agent import Agent, Predictor, Store, ValidationError, ConflictError, export_csv
from triage.knowledge import Knowledge, MAPPING
from triage.policy import redact
from triage.web import create_app
from triage.data import DatasetViewer, load_splits
from .cases import CASES


class StubPredictor:
    metadata={"version":"测试模型","policy":{"probability":.35,"margin":0.}}
    def predict(self,text):
        return [{"intent":"查询余额","probability":.9},{"intent":"查询近期交易","probability":.08},{"intent":"银行卡故障","probability":.02}],[]


def run_case(case,agent):
    fault=case.get("fault")
    target=agent.knowledge if fault and fault.startswith("knowledge") else agent.predictor if fault=="model_error" else agent.store
    method="lookup" if fault and fault.startswith("knowledge") else "predict" if fault=="model_error" else "get"
    if fault=="knowledge_missing": kwargs={"return_value":None}
    elif fault=="knowledge_wrong_queue": kwargs={"return_value":{"id":"坏记录","version":"0","intent":"查询余额","queue":"不存在","instructions":"错误","disclaimer":"演示"}}
    elif fault=="knowledge_timeout": kwargs={"side_effect":TimeoutError("注入故障")}
    elif fault=="model_error": kwargs={"side_effect":ValueError("注入故障")}
    else: kwargs={"side_effect":sqlite3.OperationalError("注入故障")}
    try:
        if fault:
            with patch.object(target,method,**kwargs): result=agent.submit(case["text"],case["id"])
        else: result=agent.submit(case["text"],case["id"])
        return result["status"]
    except ValidationError: return "validation_error"
    except sqlite3.Error: return "tool_error"


@pytest.fixture(scope="session")
def predictor(): return Predictor()


@pytest.fixture
def agent(tmp_path): return Agent(StubPredictor(),Store(tmp_path/"test.sqlite"))


@pytest.mark.parametrize("case",CASES,ids=lambda c:c["id"])
def test_boundary(case,tmp_path,predictor):
    assert run_case(case,Agent(predictor,Store(tmp_path/"boundary.sqlite")))==case["expected"]


def test_idempotence_and_conflict(agent):
    assert agent.submit("我要查账户余额","a")["status"]=="closed"
    assert agent.submit("我要查账户余额","a")["reused"]
    with pytest.raises(ConflictError): agent.submit("我要查询近期交易","a")
    assert len(agent.store.list())==1


def test_review_state_persistence(agent):
    agent.submit("我的银行卡丢了","r")
    r=agent.store.review("r","冻结账户","自动化测试：转人工安全专席")
    assert r["final_intent"]=="冻结账户" and r["status"]=="closed"
    assert Store(agent.store.path).get("r")[1]["review"]["original_intent"]=="查询余额"
    with pytest.raises(ConflictError): agent.store.review("r","冻结账户","重复确认")


def test_bad_review_no_mutation(agent):
    agent.submit("我的银行卡丢了","r")
    with pytest.raises(ValidationError): agent.store.review("r",[],"错误类别")
    assert agent.store.get("r")[1]["status"]=="needs_review"


@pytest.mark.parametrize("text",["银行卡1234567890123456丢了","我的电话13800138000需要修改","联系abc@example.com修改账户"])
def test_chinese_redaction(agent,text):
    r=agent.submit(text)
    saved=json.dumps(agent.store.get(r["id"])[1],ensure_ascii=False)
    assert "123456789" not in saved and "13800138000" not in saved and "abc@example.com" not in saved


def test_low_probability(agent):
    with patch.object(agent.predictor,"predict",return_value=([{"intent":"查询余额","probability":.2},{"intent":"查询近期交易","probability":.19}],[])):
        assert "low_confidence" in agent.submit("查询账户余额")["review_reasons"]


def test_wrong_model_output(agent):
    with patch.object(agent.predictor,"predict",return_value=([{"intent":"不存在","probability":.9}],[])):
        r=agent.submit("查询账户余额")
    assert not r["candidates"] and r["status"]=="needs_review"
    assert any(t["state"]=="failed" for t in r["trace"])


def test_batch_and_export(agent):
    raw="ticket_id,text\na,我要查账户余额\na,修改我的地址\nb,\nc,我要冻结账户\n".encode()
    r=agent.batch(raw)
    assert len(r["results"])==2 and len(r["errors"])==2
    exported=export_csv([{"id":"=1+1","text_preview":"+危险","status":"closed"}])
    assert "'=1+1" in exported and "'+危险" in exported


def test_invalid_csv(agent):
    with pytest.raises(ValidationError): agent.batch(b"\xff\xff")
    with pytest.raises(ValidationError): agent.batch(b"ticket_id,ticket_id,text\na,b,c")


def test_real_http(tmp_path,predictor):
    c=create_app(Agent(predictor,Store(tmp_path/"http.sqlite"))).test_client()
    r=c.post("/api/tickets",json={"text":"我想查询一下银行账户的余额","ticket_id":"h"})
    assert r.status_code==200 and r.json["suggested_intent"]=="查询余额"
    assert r.json["mode"]=="automatic"
    assert c.get("/api/health").json["model"]["language"]=="中文"
    assert len(c.get("/api/labels").json["labels"])==14
    assert c.get("/").status_code==200
    assert c.post("/api/tickets",json={"text":"查询余额"},headers={"Origin":"https://evil.example"}).status_code==403
    assert c.post("/api/tickets",json={"text":"查询余额"},headers={"Sec-Fetch-Site":"cross-site"}).status_code==403
    assert c.post("/api/tickets",json=[]).status_code==400
    assert c.post("/api/tickets/missing/review",json={"intent":[],"reason":"测试"}).status_code==400


def test_db_closes_handle(tmp_path):
    p=tmp_path/"old.sqlite"; s=Store(p)
    Agent(StubPredictor(),s).submit("查询账户余额")
    s.list(); p.rename(tmp_path/"new.sqlite")


def test_split_isolation():
    parts=load_splits(); groups=[set(r["group"] for r in p) for p in parts.values()]
    assert all(not a&b for i,a in enumerate(groups) for b in groups[i+1:])
    assert all(set(r["label"] for r in part)==set(MAPPING) for part in parts.values())
    assert all(any("\u4e00"<=ch<="\u9fff" for ch in r["text"]) for part in parts.values() for r in part)


@pytest.mark.parametrize("payload",[b'{"num_rows_total":3}',b'{"rows":[],"num_rows_total":3}',b'{"rows":[1],"num_rows_total":"3"}'])
def test_viewer_schema(payload):
    with pytest.raises(ValueError): DatasetViewer(lambda u:payload).query("rows")


def test_viewer_no_other_language():
    with pytest.raises(ValueError): DatasetViewer(lambda u:b"{}").query("rows",config="en-US")


def test_bad_checksum_stops_training():
    from pathlib import Path
    original=Path.read_bytes
    with patch.object(Path,"read_bytes",lambda p:b"bad" if str(p).endswith("zh_splits.json") else original(p)):
        with pytest.raises(ValueError,match="完整性"): load_splits()
