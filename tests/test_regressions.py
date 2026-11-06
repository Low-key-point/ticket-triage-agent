from pathlib import Path
from unittest.mock import patch
import pytest
from triage.agent import Store, Agent, Predictor
from triage.data import DatasetViewer
from triage.evaluate import selection_metrics
from triage.knowledge import Knowledge
from .test_agent import StubPredictor


def test_store_releases_windows_file_handle(tmp_path):
    path = tmp_path/"handles.sqlite"
    store = Store(path)
    Agent(StubPredictor(), store, Knowledge()).submit("When will my card arrive?", "handle-check")
    store.get("handle-check")
    store.list()
    path.rename(tmp_path/"renamed.sqlite")


def test_zero_selected_precision_is_null():
    import numpy as np
    result = selection_metrics(["card_arrival"], ["card_arrival"], np.array([False]))
    assert result["queue_precision"] is None and result["coverage"] == 0


def test_invalid_model_version_stops_load():
    predictor = Predictor()
    package = {**predictor.package, "metadata": {**predictor.metadata, "sklearn": "0.0.0"}}
    with patch("triage.agent.joblib.load", return_value=package):
        with pytest.raises(ValueError, match="version mismatch"):
            Predictor()


def test_model_failure_has_trace_and_review(tmp_path):
    predictor = StubPredictor()
    agent = Agent(predictor, Store(tmp_path/"fail.sqlite"), Knowledge())
    with patch.object(predictor, "predict", side_effect=ValueError("injected")):
        result = agent.submit("When will my card arrive?")
    assert result["status"] == "needs_review"
    assert any(step["state"] == "failed" for step in result["trace"])


def test_training_checksum_validation_precedes_training():
    from triage.train import train
    original = Path.read_bytes
    def corrupted(path):
        if str(path).endswith("splits.json"):
            return b"corrupt"
        return original(path)
    with patch.object(Path, "read_bytes", corrupted):
        with pytest.raises(ValueError, match="integrity mismatch"):
            train()


def test_viewer_rejects_page_beyond_requested_length():
    with pytest.raises(ValueError, match="row count"):
        DatasetViewer(lambda u: b'{"rows":[1,2],"num_rows_total":2}').query("rows", length=1, offset=0)
