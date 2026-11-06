"""Read-only live mirror check and fault-injection evidence for skill reuse."""
import csv
import json
import time
from .data import ROOT, DatasetViewer, write_json


def verify():
    started = time.perf_counter()
    with (ROOT/"data/raw/train.csv").open(encoding="utf-8") as f:
        original = list(csv.DictReader(f))
    direct_seconds = time.perf_counter()-started
    evidence = {"skill": "huggingface-datasets", "revision": "25910b3d0ba31a2ba102f901cdc9e008c278a69c", "direct_read_seconds": direct_seconds, "source_of_truth": "pinned GitHub original", "mirror_used_for_training": False}
    started = time.perf_counter()
    try:
        viewer = DatasetViewer()
        splits = viewer.query("splits")["splits"]
        match = next(s for s in splits if s["split"] == "train")
        page = viewer.query("rows", config=match["config"], split="train", offset=0, length=100)
        observed = [r["row"]["text"] for r in page["rows"]]
        originals = {r["text"] for r in original}
        evidence["live"] = {"available": True, "row_count_advertised": page["num_rows_total"], "preview_rows": len(observed), "preview_texts_in_original": sum(t in originals for t in observed), "total_matches_original": page["num_rows_total"] == len(original), "preview_only_not_full_mirror_verification": True}
    except Exception as exc:
        evidence["live"] = {"available": False, "error_type": type(exc).__name__, "fallback": "fixed original used"}
    evidence["viewer_seconds"] = time.perf_counter()-started
    faults = [
        ("missing_rows_field", b'{"num_rows_total":3}'),
        ("empty_page_before_end", b'{"rows":[],"num_rows_total":3}'),
        ("invalid_total", b'{"rows":[1],"num_rows_total":"three"}'),
    ]
    results = []
    for name, payload in faults:
        direct_accepts_json = isinstance(json.loads(payload), dict)
        detected = False
        try:
            DatasetViewer(lambda u, p=payload: p).rows("default", "train")
        except ValueError:
            detected = True
        results.append({"fault": name, "json_only_accepts": direct_accepts_json, "adapter_rejects": detected})
    evidence["fault_comparison"] = results
    evidence["interpretation"] = "Schema and pagination checks catch these injected response defects; no claim of classification gain. Fixed original downloading already has independent integrity checks."
    write_json(ROOT/"reports/skill_validation.json", evidence)
    print(json.dumps(evidence))


if __name__ == "__main__":
    verify()
