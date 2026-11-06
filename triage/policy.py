"""Conservative heuristics supplement calibrated model uncertainty."""
import re
from .knowledge import SENSITIVE

SENSITIVE_PATTERN = re.compile(r"\b(stolen|fraud\w*|hacked|compromised|unauthori[sz]ed|refund|scam\w*|identity theft)\b|\b(lost|missing)\b.{0,25}\b(card|phone)\b", re.I)
DOMAIN_PATTERN = re.compile(r"\b(card\w*|bank\w*|account\w*|trans\w*|pay\w*|money|cash|atm\w*|currenc\w*|exchange|deposit\w*|top.?up|topping|balance|pin|fee\w*|charge\w*|refund\w*|fund\w*|debit\w*|credit\w*|identity|verify|verification|passcode|cheque\w*|beneficiar\w*|withdraw\w*|visa|mastercard|revolut|apple|google|recipient)\b", re.I)


def redact(text):
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
    return re.sub(r"(?<!\w)\+?\d[\d\s-]{6,}\d(?!\w)", "[NUMBER]", text)


def sanitize_texts(texts):
    return [redact(text) for text in texts]


def input_reasons(text):
    reasons = []
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isascii() for c in letters) / len(letters) < 0.85:
        reasons.append("language_unsupported_or_uncertain")
    if not DOMAIN_PATTERN.search(text):
        reasons.append("out_of_domain_or_uncertain")
    if SENSITIVE_PATTERN.search(text):
        reasons.append("sensitive_request")
    # Multiple explicit business requests, not every occurrence of 'and'.
    clauses = re.split(r"\b(?:and|also|plus)\b|[;\n]", text, flags=re.I)
    business_clauses = [c for c in clauses if DOMAIN_PATTERN.search(c) and re.search(r"\b(need|want|cancel|lost|not|cannot|can't|failed|arriv\w*|refund|change|stolen|broken|withdraw\w*)\b", c, re.I)]
    if len(business_clauses) > 1:
        reasons.append("multiple_intents_possible")
    if re.search(r"ignore.{0,30}(rule|instruction)|system prompt|mark.{0,30}refunded", text, re.I):
        reasons.append("instruction_like_input")
    return reasons


def decide(text, candidates, thresholds):
    reasons = input_reasons(text)
    if not candidates:
        return list(dict.fromkeys(reasons + ["model_unavailable"]))
    if candidates[0]["intent"] in SENSITIVE:
        reasons.append("sensitive_intent")
    if candidates[0]["probability"] < thresholds["probability"]:
        reasons.append("low_confidence")
    if len(candidates) < 2 or candidates[0]["probability"] - candidates[1]["probability"] < thresholds["margin"]:
        reasons.append("ambiguous_candidates")
    return list(dict.fromkeys(reasons))
