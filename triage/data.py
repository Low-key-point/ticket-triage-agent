"""Pinned public data download, integrity audit and grouped splits."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
SKILL_REVISION = "25910b3d0ba31a2ba102f901cdc9e008c278a69c"
EXPECTED_HASHES = {
    "train.csv": "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
    "test.csv": "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
    "categories.json": "53261da888122daf2d120d925458631d9619e15d82e56052e7a42e535ce32b63",
}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def get_bytes(url: str, retries: int = 2) -> bytes:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ticket-triage-course/0.1"})
            with urllib.request.urlopen(req, timeout=25) as response:
                return response.read()
        except (OSError, urllib.error.URLError):
            if attempt == retries:
                raise
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError("unreachable")


class DatasetViewer:
    """Read-only adapter based on the pinned huggingface-datasets skill.

    Deliberately implements no uploading, token discovery or session access.
    """
    DATASET = "PolyAI/banking77"

    def __init__(self, fetch=get_bytes):
        self.fetch = fetch

    def query(self, endpoint, **params):
        if endpoint not in {"splits", "rows", "size"}:
            raise ValueError("Only read-only splits, rows and size are allowed")
        if params.get("dataset", self.DATASET) != self.DATASET:
            raise ValueError("Dataset is not in the allowlist")
        if endpoint == "rows":
            length, offset = params.get("length", 100), params.get("offset", 0)
            if not isinstance(length, int) or not 1 <= length <= 100:
                raise ValueError("length must be between 1 and 100")
            if not isinstance(offset, int) or offset < 0:
                raise ValueError("offset must be nonnegative")
        params["dataset"] = self.DATASET
        url = "https://datasets-server.huggingface.co/" + endpoint + "?" + urllib.parse.urlencode(params)
        result = json.loads(self.fetch(url))
        required = {"splits": "splits", "rows": "rows", "size": "size"}[endpoint]
        if required not in result:
            raise ValueError("Viewer response lacks " + required)
        if endpoint in {"splits", "rows"} and not isinstance(result[required], list):
            raise ValueError("Viewer response has invalid row structure")
        if endpoint == "rows" and ("num_rows_total" not in result or not isinstance(result["num_rows_total"], int)):
            raise ValueError("Viewer response lacks valid total")
        if endpoint == "rows" and (result["num_rows_total"] < 0 or len(result["rows"]) > params.get("length", 100)):
            raise ValueError("Viewer returned an invalid row count")
        return result

    def rows(self, config, split, maximum=1000):
        result, offset = [], 0
        while offset < maximum:
            page = self.query("rows", config=config, split=split, offset=offset, length=min(100, maximum-offset))
            rows = page["rows"]
            if not rows and offset < page["num_rows_total"]:
                raise ValueError("Missing page before advertised total")
            result.extend(rows)
            offset += len(rows)
            if offset >= page["num_rows_total"]:
                return {"rows": result, "complete": not page.get("partial", False), "total": page["num_rows_total"]}
        return {"rows": result, "complete": False, "total": page["num_rows_total"]}


def validate_rows(rows, labels):
    if not rows or any(not isinstance(r.get("text"), str) or not r["text"].strip() or r.get("category") not in labels for r in rows):
        raise ValueError("Empty data/text or unknown category")
    return rows


def prepare():
    import numpy as np
    from sklearn.feature_extraction.text import HashingVectorizer
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.neighbors import NearestNeighbors

    base = f"https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/{REVISION}/"
    raw = ROOT / "data/raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifest = {"revision": REVISION, "files": {}, "seed": 42}
    payloads = {}
    for filename in ["train.csv", "test.csv", "categories.json"]:
        path = raw / filename
        url = base + "banking_data/" + filename
        if not path.exists():
            path.write_bytes(get_bytes(url))
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != EXPECTED_HASHES[filename]:
            raise ValueError("Pinned source checksum mismatch: " + filename)
        payloads[filename] = payload
        manifest["files"][filename] = {"url": url, "sha256": hashlib.sha256(payload).hexdigest()}
    labels = json.loads(payloads["categories.json"])
    if len(labels) != 77 or len(set(labels)) != 77:
        raise ValueError("Expected 77 unique labels")
    train = validate_rows(list(csv.DictReader(io.StringIO(payloads["train.csv"].decode("utf-8-sig")))), labels)
    test = validate_rows(list(csv.DictReader(io.StringIO(payloads["test.csv"].decode("utf-8-sig")))), labels)
    if len(train) != 10003 or len(test) != 3080:
        raise ValueError("Unexpected source dataset counts")
    for split, records in [("train", train), ("test", test)]:
        for i, row in enumerate(records):
            row["id"] = f"{split}-{i:05d}"
    # Diagnostic-only fixed hashing representation: no vocabulary learned from test.
    all_rows = train + test
    vectors = HashingVectorizer(analyzer="char_wb", ngram_range=(3, 5), n_features=2**16, alternate_sign=False).transform([r["text"].lower() for r in all_rows])
    nn = NearestNeighbors(metric="cosine", algorithm="brute", n_jobs=1).fit(vectors)
    parent = list(range(len(all_rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = 0
    for start in range(0, len(all_rows), 250):
        distances, neighbors = nn.radius_neighbors(vectors[start:start+250], radius=0.05)
        for offset, (ds, ns) in enumerate(zip(distances, neighbors)):
            for distance, other in zip(ds, ns):
                i = start + offset
                if int(other) > i:
                    parent[find(int(other))] = find(i)
                    edges += 1
    groups = [find(i) for i in range(len(all_rows))]
    test_groups = set(groups[len(train):])
    kept = [(i, row) for i, row in enumerate(train) if groups[i] not in test_groups]
    # Keep only one normalized exact duplicate in training; test remains official.
    seen, filtered = set(), []
    for i, row in kept:
        key = re.sub(r"\W+", " ", row["text"].lower()).strip()
        if key not in seen:
            filtered.append((i, row))
            seen.add(key)
    y = np.array([r["category"] for _, r in filtered])
    g = np.array([groups[i] for i, _ in filtered])
    assignments = np.zeros(len(filtered), dtype=int)
    for fold, (_, ix) in enumerate(StratifiedGroupKFold(20, shuffle=True, random_state=42).split(np.zeros(len(y)), y, g)):
        assignments[ix] = fold
    splits = {"train": [], "calibration": [], "validation": [], "test": test}
    for n, (i, row) in enumerate(filtered):
        target = "train" if assignments[n] < 14 else "calibration" if assignments[n] < 17 else "validation"
        splits[target].append({**row, "group": int(groups[i])})
    for name in ["train", "calibration", "validation"]:
        if {r["category"] for r in splits[name]} != set(labels):
            raise ValueError("Split lost a class: " + name)
    manifest.update({"original_counts": {"train": len(train), "test": len(test)}, "near_duplicate_cosine_threshold": 0.95, "near_duplicate_edges": edges,
                     "training_rows_removed_for_test_overlap": len(train)-len(kept), "exact_duplicates_removed": len(kept)-len(filtered),
                     "split_counts": {k: len(v) for k, v in splits.items()},
                     "class_support": {k: {label: sum(r["category"] == label for r in v) for label in labels} for k, v in splits.items()}})
    write_json(ROOT / "data/processed/splits.json", splits)
    manifest["processed_sha256"] = hashlib.sha256((ROOT/"data/processed/splits.json").read_bytes()).hexdigest()
    write_json(ROOT / "reports/data_manifest.json", manifest)
    write_json(ROOT / "reports/split_ids.json", {k: [r["id"] for r in v] for k, v in splits.items()})
    write_json(ROOT / "config/labels.json", labels)
    for local, url in [("BANKING77-LICENSE.txt", base+"LICENSE"), ("huggingface-skills-LICENSE.txt", f"https://raw.githubusercontent.com/huggingface/skills/{SKILL_REVISION}/LICENSE"), ("huggingface-datasets-SKILL.md", f"https://raw.githubusercontent.com/huggingface/skills/{SKILL_REVISION}/skills/huggingface-datasets/SKILL.md")]:
        dest = ROOT / "third_party" / local
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            dest.write_bytes(get_bytes(url))
    probe = {"skill_revision": SKILL_REVISION, "training_source": "pinned GitHub originals", "mirror_used_for_training": False}
    try:
        probe["splits"] = DatasetViewer().query("splits")["splits"]
        probe["status"] = "available"
    except Exception as exc:
        probe.update(status="fallback_to_pinned_original", error=type(exc).__name__)
    write_json(ROOT / "reports/skill_probe.json", probe)
    print(json.dumps(manifest["split_counts"]))


if __name__ == "__main__":
    prepare()
