"""Bounded workflow, calibrated prediction, persistence and human review."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn

from .data import ROOT
from .knowledge import Knowledge, MAPPING
from .policy import decide, redact


class ValidationError(ValueError):
    pass


class ConflictError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def retry(action):
    for attempt in range(3):
        try:
            return action()
        except (OSError, sqlite3.OperationalError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(0.03 * (attempt + 1))


class Predictor:
    def __init__(self, path=None):
        # Only load a trusted artifact produced locally by triage.train.
        self.package = joblib.load(path or ROOT/"models/model.joblib")
        self.model = self.package["model"]
        self.base = self.package["base_model"]
        self.metadata = self.package["metadata"]
        if self.metadata.get("sklearn") != sklearn.__version__:
            raise ValueError("模型的机器学习库版本不匹配，请使用锁定环境或重新训练")
        if set(self.model.classes_) != set(MAPPING):
            raise ValueError("模型类别与知识库类别不一致")

    def predict(self, text):
        prob = self.model.predict_proba([text])[0]
        if len(prob) != len(MAPPING) or not np.isfinite(prob).all() or np.any(prob < 0) or not np.isclose(prob.sum(), 1):
            raise ValueError("模型概率输出不合法")
        order = np.argsort(prob)[-3:][::-1]
        candidates = [{"intent": str(self.model.classes_[i]), "probability": float(prob[i])} for i in order]
        features = self.base.named_steps["features"]
        vector = features.transform([text])
        class_index = list(self.base.classes_).index(candidates[0]["intent"])
        weights = self.base.named_steps["classifier"].coef_[class_index]
        contribution = vector.multiply(weights).tocsr()
        positive = [(int(i), float(v)) for i, v in zip(contribution.indices, contribution.data) if v > 0]
        names = features.get_feature_names_out()
        explanation = [{"feature": str(names[i]), "contribution": value} for i, value in sorted(positive, key=lambda p: p[1], reverse=True)[:6]]
        return candidates, explanation


class Store:
    def __init__(self, path=None):
        self.path = str(path or ROOT/"data/runtime/tickets.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tickets (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute("PRAGMA busy_timeout=3000")
            with db:
                yield db
        finally:
            db.close()

    def get(self, ticket_id):
        with self.connect() as db:
            row = db.execute("SELECT fingerprint,payload FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def insert(self, fingerprint, record):
        with self.connect() as db:
            try:
                db.execute("INSERT INTO tickets VALUES(?,?,?)", (record["id"], fingerprint, json.dumps(record, ensure_ascii=False)))
            except sqlite3.IntegrityError:
                existing = db.execute("SELECT fingerprint,payload FROM tickets WHERE id=?", (record["id"],)).fetchone()
                if existing[0] != fingerprint:
                    raise ConflictError("该工单编号已用于另一条内容")
                return json.loads(existing[1])
        return record

    def list(self, status=None):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM tickets ORDER BY rowid DESC").fetchall()
        records = [json.loads(row[0]) for row in rows]
        return [r for r in records if not status or r["status"] == status]

    def review(self, ticket_id, intent, reason):
        if not isinstance(intent, str) or intent not in MAPPING:
            raise ValidationError("请选择合法意图")
        if not isinstance(reason, str) or not 2 <= len(reason.strip()) <= 500:
            raise ValidationError("请填写2至500字符的复核理由")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if not row:
                raise KeyError(ticket_id)
            record = json.loads(row[0])
            if record["status"] != "needs_review":
                raise ConflictError("仅待复核工单可以确认，已结束工单不可重复复核")
            review = {"at": now(), "original_intent": record.get("suggested_intent"), "original_queue": record.get("suggested_queue"), "intent": intent, "queue": MAPPING[intent], "reason": redact(reason.strip()), "actor": "local_reviewer"}
            record.update(status="closed", final_intent=intent, final_queue=MAPPING[intent], review=review)
            record["trace"].append({"state": "closed", "at": now(), "action": "human_review"})
            db.execute("UPDATE tickets SET payload=? WHERE id=?", (json.dumps(record, ensure_ascii=False), ticket_id))
        return record


class Agent:
    def __init__(self, predictor=None, store=None, knowledge=None):
        self.predictor = predictor or Predictor()
        self.store = store or Store()
        self.knowledge = knowledge or Knowledge()

    def submit(self, text, ticket_id=None):
        started = time.perf_counter()
        if not isinstance(text, str) or not 2 <= len(text.strip()) <= 500:
            raise ValidationError("请输入2至500字符的中文咨询")
        text = text.strip()
        if ticket_id is not None and (not isinstance(ticket_id, str) or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9_-]{1,80}", ticket_id)):
            raise ValidationError("编号须为1至80位汉字、字母、数字、下划线或连字符")
        ticket_id = ticket_id or uuid.uuid4().hex[:16]
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        previous = retry(lambda: self.store.get(ticket_id))
        if previous:
            if previous[0] != fingerprint:
                raise ConflictError("该工单编号已用于另一条内容")
            return {**previous[1], "reused": True}
        preview = redact(text)
        trace = [{"state": s, "at": now(), "action": a} for s, a in [("received", "input"), ("validated", "validate_and_redact")]]
        candidates, explanation, errors, timings = [], [], [], {}
        step = time.perf_counter()
        try:
            candidates, explanation = self.predictor.predict(preview)
            if not candidates or any(c["intent"] not in MAPPING or not 0 <= c["probability"] <= 1 for c in candidates):
                raise ValueError("模型输出不合法")
            trace.append({"state": "classified", "at": now(), "action": "predict"})
        except (ValueError, OSError, RuntimeError) as exc:
            candidates, explanation = [], []
            errors.append("model_error:" + type(exc).__name__)
            trace.append({"state": "failed", "at": now(), "action": "model_error_then_human_fallback"})
        timings["classification_ms"] = (time.perf_counter()-step)*1000
        reasons = decide(preview, candidates, self.predictor.metadata["policy"])
        article = None
        step = time.perf_counter()
        if candidates:
            try:
                article = retry(lambda: self.knowledge.lookup(candidates[0]["intent"]))
                required = {"id", "version", "intent", "queue", "instructions", "disclaimer"}
                if not article or not required.issubset(article) or article["intent"] != candidates[0]["intent"] or article["queue"] != MAPPING[candidates[0]["intent"]]:
                    article = None
                    reasons.append("knowledge_missing_or_invalid")
            except (OSError, TimeoutError, ValueError) as exc:
                reasons.append("knowledge_tool_failure")
                errors.append("knowledge_error:" + type(exc).__name__)
        timings["knowledge_ms"] = (time.perf_counter()-step)*1000
        reasons = list(dict.fromkeys(reasons))
        review = bool(reasons)
        intent = candidates[0]["intent"] if candidates else None
        if review:
            trace.append({"state": "needs_review", "at": now(), "action": "request_human_review"})
        else:
            trace.extend([{ "state": s, "at": now(), "action": a} for s, a in [("routed", "create_simulated_ticket"), ("closed", "automatic_triage_complete")]])
        record = {"id": ticket_id, "created_at": now(), "text_preview": preview,
                  "status": "needs_review" if review else "closed", "mode": "human_review" if review else "automatic",
                  "candidates": candidates, "explanation": explanation, "model_version": self.predictor.metadata["version"],
                  "suggested_intent": intent, "suggested_queue": MAPPING.get(intent), "final_intent": None if review else intent,
                  "final_queue": None if review else MAPPING.get(intent), "knowledge": article, "review_reasons": reasons,
                  "errors": errors, "trace": trace, "timings": timings, "reused": False,
                  "input_language": "中文"}
        record["timings"]["processing_ms"] = (time.perf_counter()-started)*1000
        return retry(lambda: self.store.insert(fingerprint, record))

    def batch(self, raw):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("CSV必须为UTF-8编码") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not {"ticket_id", "text"}.issubset(reader.fieldnames):
            raise ValidationError("CSV须包含唯一的ticket_id和text字段")
        rows = list(reader)
        if not 1 <= len(rows) <= 500:
            raise ValidationError("CSV须包含1至500条记录")
        results, errors, seen = [], [], set()
        for line, row in enumerate(rows, 2):
            try:
                ticket_id = row.get("ticket_id")
                if not ticket_id or ticket_id in seen or None in row:
                    raise ValidationError("编号缺失、重复或字段数量错误")
                seen.add(ticket_id)
                results.append(self.submit(row.get("text"), ticket_id))
            except (ValidationError, ConflictError) as exc:
                errors.append({"line": line, "error": str(exc)})
            except (OSError, sqlite3.Error):
                errors.append({"line": line, "error": "存储工具不可用，本行未确认保存"})
        return {"results": results, "errors": errors, "total": len(rows)}


def export_csv(records):
    out = io.StringIO(newline="")
    fields = ["id", "status", "mode", "text_preview", "suggested_intent", "final_intent", "final_queue"]
    writer = csv.DictWriter(out, fields)
    writer.writeheader()
    for record in records:
        row = {}
        for field in fields:
            value = str(record.get(field) or "")
            row[field] = "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        writer.writerow(row)
    return "\ufeff" + out.getvalue()
