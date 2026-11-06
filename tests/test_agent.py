import io
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from triage.agent import Agent, ConflictError, Predictor, Store, ValidationError, export_csv
from triage.data import DatasetViewer, ROOT, validate_rows
from triage.knowledge import Knowledge, MAPPING
from triage.policy import redact
from triage.web import create_app
from .cases import CASES


class StubPredictor:
    metadata = {"version": "test", "policy": {"probability": .8, "margin": .1}}

    def predict(self, text):
        return [{"intent": "card_arrival", "probability": .94}, {"intent": "card_delivery_estimate", "probability": .04}, {"intent": "card_not_working", "probability": .02}], []


@pytest.fixture
def agent(tmp_path):
    return Agent(StubPredictor(), Store(tmp_path/"tickets.sqlite"), Knowledge())


@pytest.fixture(scope="session")
def predictor():
    return Predictor()


def run_case(case, agent):
    fault = case.get("fault")
    target = agent.knowledge if fault and fault.startswith("knowledge") else agent.predictor if fault == "model_error" else agent.store
    method = "lookup" if fault and fault.startswith("knowledge") else "predict" if fault == "model_error" else "get"
    kwargs = {"return_value": None} if fault == "knowledge_missing" else {"side_effect": TimeoutError("injected")} if fault == "knowledge_timeout" else {"side_effect": ValueError("injected")} if fault == "model_error" else {"side_effect": sqlite3.OperationalError("injected")}
    try:
        if fault:
            with patch.object(target, method, **kwargs):
                result = agent.submit(case["text"], case["id"])
        else:
            result = agent.submit(case["text"], case["id"])
        return result["status"]
    except ValidationError:
        return "validation_error"
    except sqlite3.OperationalError:
        return "tool_error"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_boundary(case, tmp_path, predictor):
    actual = run_case(case, Agent(predictor, Store(tmp_path/"boundary.sqlite"), Knowledge()))
    assert actual == case["expected"]


def test_idempotence_and_conflict(agent):
    first = agent.submit("When will my bank card arrive?", "abc")
    assert first["status"] == "closed"
    assert agent.submit("When will my bank card arrive?", "abc")["reused"]
    assert len(agent.store.list()) == 1
    with pytest.raises(ConflictError):
        agent.submit("My bank card is broken", "abc")


def test_review_state_and_persistence(agent):
    record = agent.submit("My card was stolen yesterday", "review")
    assert record["status"] == "needs_review"
    revised = agent.store.review("review", "lost_or_stolen_card", "确认卡片遗失，需要转人工安全队列")
    assert revised["final_queue"] == "安全与争议"
    assert revised["review"]["original_intent"] == "card_arrival"
    assert Store(agent.store.path).get("review")[1]["status"] == "closed"
    with pytest.raises(ConflictError):
        agent.store.review("review", "card_arrival", "再次确认")


def test_invalid_review_does_not_mutate(agent):
    agent.submit("My card was stolen yesterday", "review")
    with pytest.raises(ValidationError):
        agent.store.review("review", "not-a-label", "incorrect")
    assert agent.store.get("review")[1]["status"] == "needs_review"


def test_redaction_is_persisted(agent):
    record = agent.submit("My card was sent to test@example.com; number 1234 5678 1234 5678", "privacy")
    raw = agent.store.get("privacy")[1]
    assert "test@example.com" not in json.dumps(raw)
    assert "1234 5678" not in json.dumps(raw)
    assert "[EMAIL]" in record["text_preview"]


def test_low_confidence_and_margin(agent):
    agent.predictor.metadata = {"version": "test", "policy": {"probability": .99, "margin": .95}}
    result = agent.submit("When will my card arrive?")
    assert {"low_confidence", "ambiguous_candidates"}.issubset(result["review_reasons"])


def test_batch_partial_errors(agent):
    result = agent.batch(b'ticket_id,text\na,When will my card arrive?\na,My card is broken\nb,\nc,What is the weather tomorrow?\n')
    assert result["total"] == 4 and len(result["results"]) == 2 and len(result["errors"]) == 2
    for raw in [b'ticket_id\na\n', b'ticket_id,text\na,\xff', b'ticket_id,text\n'+b'a,hello\n'*501]:
        with pytest.raises(ValidationError):
            agent.batch(raw)


def test_csv_formula_escaped():
    result = export_csv([{"id": "1", "text_preview": "  =HYPERLINK(x)"}])
    assert "'  =HYPERLINK" in result


def test_http_actions(agent):
    app = create_app(agent)
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/tickets", json={"text": "short", "ticket_id": "bad/id"}).status_code == 400
    result = client.post("/api/tickets", json={"text": "My card was stolen", "ticket_id": "http"})
    assert result.status_code == 200 and result.json["status"] == "needs_review"
    review = client.post("/api/tickets/http/review", json={"intent": "lost_or_stolen_card", "reason": "confirmed theft"})
    assert review.status_code == 200 and review.json["status"] == "closed"
    assert client.post("/api/tickets/http/review", json={"intent": "lost_or_stolen_card", "reason": "duplicate"}).status_code == 409
    assert client.post("/api/tickets", json={"text": "My card is broken"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/export").status_code == 200
    assert client.post("/api/batch", data={"file": (io.BytesIO(b'ticket_id,text\nbatch,When will my card arrive?'), 'sample.csv')}).json["total"] == 1


def test_database_failure_is_not_success(agent):
    client = create_app(agent).test_client()
    with patch.object(agent.store, "insert", side_effect=sqlite3.OperationalError("down")):
        response = client.post("/api/tickets", json={"text": "When will my card arrive?"})
    assert response.status_code == 503
    assert agent.store.list() == []


def test_mapping_all_labels():
    Knowledge()
    assert len(MAPPING) == 77


def test_viewer_guards_and_missing_fields():
    for endpoint, args in [("upload", {}), ("rows", {"offset": -1}), ("rows", {"length": 101}), ("splits", {"dataset": "other/private"})]:
        with pytest.raises(ValueError):
            DatasetViewer(lambda u: b'{}').query(endpoint, **args)
    with pytest.raises(ValueError):
        DatasetViewer(lambda u: b'{}').query("splits")


def test_viewer_pagination_and_incomplete():
    pages = iter([b'{"rows":[1,2],"num_rows_total":3}', b'{"rows":[3],"num_rows_total":3}'])
    assert DatasetViewer(lambda u: next(pages)).rows("default", "train")["complete"]
    with pytest.raises(ValueError):
        DatasetViewer(lambda u: b'{"rows":[],"num_rows_total":3}').rows("default", "train")
    result = DatasetViewer(lambda u: b'{"rows":[1],"num_rows_total":3}').rows("default", "train", maximum=1)
    assert not result["complete"]


def test_viewer_timeout_and_empty():
    def fail(url):
        raise TimeoutError("injected")
    with pytest.raises(TimeoutError):
        DatasetViewer(fail).query("splits")
    assert DatasetViewer(lambda u: b'{"rows":[],"num_rows_total":0}').rows("default", "train")["total"] == 0


def test_invalid_data_blocks_training():
    with pytest.raises(ValueError):
        validate_rows([{"text": "hello", "category": "unknown"}], set(MAPPING))


def test_grouped_splits_no_leakage():
    splits = json.loads((ROOT/"data/processed/splits.json").read_text(encoding="utf-8"))
    group_sets = [set(r["group"] for r in splits[s]) for s in ["train", "calibration", "validation"]]
    for a, b in [(0, 1), (0, 2), (1, 2)]:
        assert not group_sets[a] & group_sets[b]
    test_ids = {r["id"] for r in splits["test"]}
    assert len(test_ids) == 3080
    assert not test_ids & {r["id"] for r in splits["train"]}
