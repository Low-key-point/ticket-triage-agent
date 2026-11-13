import json
import pytest
from triage.data import DatasetViewer, check_source


def response(text="示例文本", label=0, index=0):
    return {"rows": [{"row_idx": index, "row": {"transcription": text, "intent_class": label}}], "num_rows_total": 1}


@pytest.mark.parametrize("payload", [response(index=2), response(label=True), response(label=14),
                                     {"rows": [{"row_idx": 0, "row": {}}], "num_rows_total": 1}])
def test_viewer_rejects_bad_row_contract(payload):
    with pytest.raises(ValueError):
        DatasetViewer(lambda _: json.dumps(payload).encode()).query("rows")


def test_skill_uses_fixed_file_when_live_preview_drifts_or_fails():
    original = [{"transcription": "示例文本", "intent_class": 0}]
    matched = DatasetViewer(lambda _: json.dumps(response()).encode())
    drift = DatasetViewer(lambda _: json.dumps(response(text="上游已变化")).encode())
    assert check_source(original, matched)["status"] == "matched"
    assert check_source(original, drift)["status"] == "different"
    def unavailable(_):
        raise OSError("network unavailable")
    result = check_source(original, DatasetViewer(unavailable))
    assert result["status"] == "unavailable"
    assert "固定文件" in result["decision"]
    assert original == [{"transcription": "示例文本", "intent_class": 0}]
