"""Run locked tests; no threshold or model selection takes place here."""
import csv
import hashlib
import json
import math
import os
import platform
import statistics
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix

from .agent import Agent, Predictor, Store
from .data import ROOT, write_json
from .knowledge import Knowledge, MAPPING, SENSITIVE
from .policy import input_reasons, redact
from .train import score


def wilson(success, total):
    if not total:
        return None
    z, p = 1.96, success/total
    center = (p+z*z/(2*total))/(1+z*z/total)
    half = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return [max(0, center-half), min(1, center+half)]


def selection_metrics(y, prediction, selected):
    n = int(selected.sum())
    queue_correct = sum(MAPPING[a] == MAPPING[b] for a, b, keep in zip(y, prediction, selected) if keep)
    intent_correct = sum(a == b for a, b, keep in zip(y, prediction, selected) if keep)
    return {"selected": n, "total": len(y), "coverage": n/len(y), "queue_correct": queue_correct,
            "queue_precision": queue_correct/n if n else None, "intent_correct": intent_correct,
            "intent_precision": intent_correct/n if n else None, "queue_precision_95ci": wilson(queue_correct, n)}


def keyword_predict(text, default):
    # Fixed lexical baseline derived only from class names, with no test tuning.
    words = set(text.lower().replace("?", "").split())
    matches = [(len(words & set(label.lower().replace("?", "").split("_"))), label) for label in sorted(MAPPING)]
    best = max(matches, key=lambda pair: pair[0])
    return best[1] if best[0] else default


def reliability(y, prediction, probs):
    confidences = probs.max(axis=1)
    correct = np.asarray(y) == prediction
    bins, ece = [], 0.0
    for i in range(10):
        mask = (confidences >= i/10) & (confidences < (i+1)/10 if i < 9 else confidences <= 1)
        n = int(mask.sum())
        confidence, accuracy = (float(confidences[mask].mean()), float(correct[mask].mean())) if n else (None, None)
        if n:
            ece += n/len(y)*abs(confidence-accuracy)
        bins.append({"low": i/10, "high": (i+1)/10, "count": n, "confidence": confidence, "accuracy": accuracy})
    return {"top_label_ece_10_bins": ece, "bins": bins}


def evaluate():
    from tests.cases import CASES
    from tests.test_agent import run_case
    started = time.perf_counter()
    predictor = Predictor()
    cold = time.perf_counter()-started
    data = json.loads((ROOT/"data/processed/splits.json").read_text(encoding="utf-8"))["test"]
    x, y = [r["text"] for r in data], np.array([r["category"] for r in data])
    package = predictor.package
    probs = predictor.model.predict_proba(x)
    prediction = predictor.model.classes_[probs.argmax(axis=1)]
    models = {
        "majority": score(y, [package["majority"]]*len(y)),
        "keywords": score(y, [keyword_predict(t, package["majority"]) for t in x]),
        "naive_bayes": score(y, package["nb"].predict(x)),
        "svm_word_only": score(y, package["word_only"].predict(x)),
        "selected_uncalibrated": score(y, predictor.base.predict(x)),
        "calibrated": score(y, prediction),
    }
    sorted_p = np.sort(probs, axis=1)
    top, margins = sorted_p[:, -1], sorted_p[:, -1]-sorted_p[:, -2]
    policy = predictor.metadata["policy"]
    eligible = np.array([not input_reasons(redact(t)) and p not in SENSITIVE for t, p in zip(x, prediction)])
    selected = eligible & (top >= policy["probability"]) & (margins >= policy["margin"])
    routing = selection_metrics(y, prediction, selected)
    calibrated_reliability = reliability(y, prediction, probs)
    class_report = classification_report(y, prediction, output_dict=True, zero_division=0)
    write_json(ROOT/"reports/classification_report.json", class_report)
    write_json(ROOT/"reports/reliability.json", calibrated_reliability)
    labels = list(predictor.model.classes_)
    matrix = confusion_matrix(y, prediction, labels=labels)
    with (ROOT/"reports/confusion_matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["true/predicted"]+labels)
        writer.writerows([[label]+row.tolist() for label, row in zip(labels, matrix)])
    with (ROOT/"reports/test_predictions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_id", "true_intent", "predicted_intent", "probability", "margin", "automatic", "correct_queue"])
        writer.writerows([[r["id"], a, b, float(p), float(m), bool(s), MAPPING[a] == MAPPING[b]] for r, a, b, p, m, s in zip(data, y, prediction, top, margins, selected)])
    failures = []
    for i, (actual, guess) in enumerate(zip(y, prediction)):
        if actual != guess:
            failures.append({"source_id": data[i]["id"], "text": redact(x[i]), "truth": str(actual), "prediction": str(guess), "probability": float(top[i]), "automatic": bool(selected[i]), "queue_correct": MAPPING[actual] == MAPPING[guess]})
    write_json(ROOT/"reports/error_cases.json", failures)
    boundary = []
    workflow = []
    # Seeded 60-class subset: one sample per shuffled class; not new independent data.
    rng = np.random.default_rng(42)
    chosen = rng.permutation(labels)[:60]
    indices = [int(rng.choice(np.flatnonzero(y == label))) for label in chosen]
    with tempfile.TemporaryDirectory() as tmp:
        agent = Agent(predictor, Store(Path(tmp)/"eval.sqlite"), Knowledge())
        for case in CASES:
            actual = run_case(case, agent)
            boundary.append({"id": case["id"], "group": case["group"], "expected": case["expected"], "actual": actual, "passed": actual == case["expected"]})
        for i in indices:
            record = agent.submit(x[i], "flow-"+data[i]["id"])
            before = record["status"]
            initial_correct = record["final_queue"] == MAPPING[y[i]] if before == "closed" else False
            # Oracle-driven scripted UI-equivalent action, not a human observation.
            if before == "needs_review":
                record = agent.store.review(record["id"], str(y[i]), "自动化测试驱动器使用公开真值验证复核接口，不代表真实人工判断")
            workflow.append({"source_id": data[i]["id"], "before_review": before, "auto_queue_correct": initial_correct, "after_scripted_review": record["status"], "final_queue_correct": record["final_queue"] == MAPPING[y[i]]})
        latency = []
        for i in range(200):
            t = time.perf_counter()
            agent.submit(x[i], "perf-"+str(i))
            latency.append((time.perf_counter()-t)*1000)
    group_results = {}
    for group in sorted({c["group"] for c in CASES}):
        subset = [r for r in boundary if r["group"] == group]
        group_results[group] = {"passed": sum(r["passed"] for r in subset), "total": len(subset)}
    review_rows = [r for r in boundary if r["group"] in {"out_of_domain", "non_english", "multi_intent", "sensitive"}]
    results = {
        "model_version": predictor.metadata["version"], "test_count": len(data), "test_source": "official BANKING77 test; no tuning", "models": models,
        "routing": routing, "policy": policy, "ablation": {"all_direct": selection_metrics(y, prediction, np.ones(len(y), dtype=bool)), "without_probability_gate": selection_metrics(y, prediction, eligible)},
        "calibration": {"top_label_ece_10_bins": calibrated_reliability["top_label_ece_10_bins"]},
        "boundary": {"synthetic": True, "passed": sum(r["passed"] for r in boundary), "total": len(boundary), "groups": group_results, "review_recall": sum(r["actual"] == "needs_review" for r in review_rows)/len(review_rows)},
        "workflow": {"total": len(workflow), "automatic_correct": sum(r["auto_queue_correct"] for r in workflow), "waiting_before_scripted_review": sum(r["before_review"] == "needs_review" for r in workflow), "completed_correct_after_oracle_review": sum(r["final_queue_correct"] for r in workflow), "oracle_review_is_not_human_evidence": True},
        "performance": {"requests": 200, "concurrency": 1, "cold_model_load_ms": cold*1000, "median_ms": statistics.median(latency), "p95_ms": float(np.percentile(latency, 95)), "max_ms": max(latency), "scope": "Agent.submit including SQLite; excludes HTTP/browser/network", "platform": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count()},
        "limitations": ["No user interviews or human time study", "Synthetic boundaries are not a comprehensive unknown-input benchmark", "Queue mapping is a teaching policy", "English only; language heuristics are incomplete", "Oracle review measures interface completion, not autonomous accuracy"],
    }
    write_json(ROOT/"reports/evaluation.json", results)
    write_json(ROOT/"reports/boundary_results.json", boundary)
    write_json(ROOT/"reports/workflow_results.json", workflow)
    write_json(ROOT/"reports/performance_samples.json", latency)
    write_json(ROOT/"reports/boundary_cases.json", CASES)
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    evaluate()
