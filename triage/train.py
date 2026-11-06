"""Pre-registered grouped CV, held-out calibration and policy selection."""
import hashlib
import json
import platform
import time
from collections import Counter

import joblib
import numpy as np
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.svm import LinearSVC
from threadpoolctl import threadpool_limits

from .data import ROOT, write_json
from .knowledge import MAPPING
from .policy import input_reasons, redact, sanitize_texts


def pipeline(kind, ngram=(1, 2), c=1.0, chars=False):
    word = TfidfVectorizer(ngram_range=tuple(ngram), sublinear_tf=True, min_df=1, max_features=35000)
    features = FeatureUnion([("word", word), ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=40000, sublinear_tf=True))], transformer_weights={"word": 1.0, "char": 0.5}) if chars else word
    estimator = MultinomialNB(alpha=0.3) if kind == "nb" else LogisticRegression(C=c, max_iter=600, random_state=42) if kind == "lr" else LinearSVC(C=c, random_state=42, dual="auto")
    return Pipeline([("redaction", FunctionTransformer(sanitize_texts)), ("features", features), ("classifier", estimator)])


def score(y, prediction):
    return {"accuracy": float(accuracy_score(y, prediction)), "macro_f1": float(f1_score(y, prediction, average="macro", zero_division=0))}


def choose_thresholds(texts, y, probs, labels, config):
    ix = probs.argsort(axis=1)
    top = probs[np.arange(len(probs)), ix[:, -1]]
    margin = top - probs[np.arange(len(probs)), ix[:, -2]]
    prediction = labels[ix[:, -1]]
    from .knowledge import SENSITIVE
    eligible = np.array([not input_reasons(redact(t)) and p not in SENSITIVE for t, p in zip(texts, prediction)])
    correct = np.array([MAPPING[a] == MAPPING[b] for a, b in zip(y, prediction)])
    grid = []
    for tau in config["probability_thresholds"]:
        for delta in config["margin_thresholds"]:
            keep = eligible & (top >= tau) & (margin >= delta)
            count = int(keep.sum())
            precision = float(correct[keep].mean()) if count else None
            grid.append({"probability": tau, "margin": delta, "count": count, "coverage": count/len(y), "queue_precision": precision})
    valid = [g for g in grid if g["count"] >= 30 and g["queue_precision"] >= config["target_queue_precision"]]
    best = max(valid, key=lambda g: (g["coverage"], g["queue_precision"], g["probability"])) if valid else {"probability": 1.01, "margin": 1.01, "coverage": 0, "queue_precision": None, "count": 0}
    return best, grid


def train():
    started = time.perf_counter()
    config = json.loads((ROOT/"config/experiment.json").read_text())
    manifest = json.loads((ROOT/"reports/data_manifest.json").read_text())
    if hashlib.sha256((ROOT/"data/processed/splits.json").read_bytes()).hexdigest() != manifest["processed_sha256"]:
        raise ValueError("Processed split integrity mismatch; rerun data preparation")
    splits = json.loads((ROOT/"data/processed/splits.json").read_text(encoding="utf-8"))
    x = [r["text"] for r in splits["train"]]
    y = [r["category"] for r in splits["train"]]
    groups = [r["group"] for r in splits["train"]]
    cv = list(StratifiedGroupKFold(3, shuffle=True, random_state=42).split(x, y, groups))
    candidates = []
    for kind in ["lr", "svm"]:
        for ngram in config["word_ngram_ranges"]:
            for c in config["C"]:
                candidates.append({"kind": kind, "ngram": ngram, "c": c, "chars": False})
    candidates.append({"kind": "svm", "ngram": [1, 2], "c": 1.0, "chars": True})
    results = []
    with threadpool_limits(limits=1):
        for spec in candidates:
            t = time.perf_counter()
            scores = cross_val_score(pipeline(**spec), x, y, cv=cv, scoring="f1_macro", n_jobs=1)
            results.append({**spec, "fold_macro_f1": scores.tolist(), "mean_macro_f1": float(scores.mean()), "seconds": time.perf_counter()-t})
            print(json.dumps(results[-1]), flush=True)
            write_json(ROOT/"reports/cv_results.json", results)
        best = max(results, key=lambda row: row["mean_macro_f1"])
        best_spec = {k: best[k] for k in ["kind", "ngram", "c", "chars"]}
        model = pipeline(**best_spec).fit(x, y)
        calibration = splits["calibration"]
        calibrated = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid").fit([r["text"] for r in calibration], [r["category"] for r in calibration])
        nb = pipeline("nb").fit(x, y)
        # Pre-registered word-only comparison for the optional character features.
        word_only = pipeline("svm", ngram=(1, 2), c=1).fit(x, y)
    validation = splits["validation"]
    vx, vy = [r["text"] for r in validation], [r["category"] for r in validation]
    probs = calibrated.predict_proba(vx)
    policy, grid = choose_thresholds(vx, vy, probs, calibrated.classes_, config)
    manifest = json.loads((ROOT/"reports/data_manifest.json").read_text())
    source_hashes = {name: hashlib.sha256((ROOT/"triage"/name).read_bytes()).hexdigest() for name in ["data.py", "train.py", "policy.py", "knowledge.py"]}
    fingerprint = hashlib.sha256(json.dumps({"config": config, "manifest": manifest, "spec": best_spec, "source_hashes": source_hashes}, sort_keys=True).encode()).hexdigest()[:12]
    metadata = {"version": fingerprint, "selected_spec": best_spec, "policy": policy, "validation": score(vy, calibrated.classes_[probs.argmax(axis=1)]), "sklearn": sklearn.__version__, "python": platform.python_version(), "training_seconds": time.perf_counter()-started, "test_used_for_selection": False}
    package = {"model": calibrated, "base_model": model, "nb": nb, "word_only": word_only, "majority": Counter(y).most_common(1)[0][0], "metadata": metadata}
    (ROOT/"models").mkdir(exist_ok=True)
    joblib.dump(package, ROOT/"models/model.joblib", compress=3)
    metadata["artifact_sha256"] = hashlib.sha256((ROOT/"models/model.joblib").read_bytes()).hexdigest()
    metadata["source_hashes"] = source_hashes
    write_json(ROOT/"reports/model_metadata.json", metadata)
    write_json(ROOT/"reports/threshold_search.json", grid)
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    train()
