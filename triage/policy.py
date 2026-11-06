"""中文文本规范化、脱敏及可解释分流策略。"""
import re
import unicodedata
from .knowledge import SENSITIVE

HAN = re.compile(r"[\u3400-\u9fff]")
DOMAIN = re.compile(r"卡|银行|账户|账号|转账|汇款|付款|支付|充值|退款|取款|提现|余额|存款|扣款|账单|密码|身份|验证|交易|贷款|联名|境外|自动扣|地址|应用|软件|登录|ATM|PIN", re.I)
RISK = re.compile(r"被盗|偷|盗刷|诈骗|骗|冒用|未经授权|不是我|不认识|退款|退钱|注销|挂失|冻结|解冻|(?:卡|手机).{0,12}(?:丢|遗失|不见|失窃)|(?:丢|遗失).{0,12}(?:卡|手机)")
OUTSIDE = re.compile(r"股票|基金|保险|期货|汇率|兑换|外汇|物流|邮寄|快递|寄到|送达|到货|房贷|个人贷款")


def redact(text):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    text = re.sub(r"(?<![A-Za-z0-9])\+?\d[\d -]{6,}\d[Xx]?(?![A-Za-z0-9])", "[号码已隐藏]", text)
    return text


def sanitize_texts(texts):
    return [re.sub(r"\s+", "", redact(text)).lower() for text in texts]


def input_reasons(text):
    reasons = []
    if not HAN.search(text) or any(c.isalpha() and not c.isascii() and not HAN.fullmatch(c) for c in text):
        reasons.append("language_unsupported_or_uncertain")
    if not DOMAIN.search(text):
        reasons.append("out_of_domain_or_uncertain")
    if OUTSIDE.search(text):
        reasons.append("intent_out_of_scope")
    if RISK.search(text) or re.search(r"(?:密码|口令|PIN).{0,8}\[号码已隐藏\]", text, re.I):
        reasons.append("sensitive_request")
    clauses = re.split(r"而且|另外|同时|还想|还要|以及|并且|[；;\n]", text)
    if sum(bool(DOMAIN.search(c)) for c in clauses) > 1:
        reasons.append("multiple_intents_possible")
    if re.search(r"忽略|无视|系统提示|跳过.{0,8}复核|直接.{0,8}(?:成功|退款)", text):
        reasons.append("instruction_like_input")
    return reasons


def decide(text, candidates, thresholds):
    reasons = input_reasons(text)
    if not candidates:
        if "language_unsupported_or_uncertain" not in reasons:
            reasons.append("model_unavailable")
        return list(dict.fromkeys(reasons))
    if candidates[0]["intent"] in SENSITIVE:
        reasons.append("sensitive_intent")
    if candidates[0]["probability"] < thresholds["probability"]:
        reasons.append("low_confidence")
    if len(candidates)<2 or candidates[0]["probability"]-candidates[1]["probability"] < thresholds["margin"]:
        reasons.append("ambiguous_candidates")
    return list(dict.fromkeys(reasons))
