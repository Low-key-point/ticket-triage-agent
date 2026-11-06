"""Explicit teaching queues; these are not any bank's organization or policy."""
from .data import ROOT
import json

GROUPS = {
    "卡片物流": "card_arrival card_delivery_estimate get_physical_card getting_spare_card order_physical_card",
    "卡片使用": "card_linking card_not_working pin_blocked contactless_not_working getting_virtual_card card_acceptance visa_or_mastercard disposable_card_limits pending_card_payment declined_card_payment card_swallowed change_pin virtual_card_not_working get_disposable_virtual_card activate_my_card card_about_to_expire apple_pay_or_google_pay",
    "转账": "cancel_transfer transfer_not_received_by_recipient declined_transfer pending_transfer transfer_timing beneficiary_not_allowed transfer_fee_charged receiving_money failed_transfer transfer_into_account balance_not_updated_after_bank_transfer",
    "现金与充值": "pending_cash_withdrawal automatic_top_up top_up_by_bank_transfer_charge pending_top_up top_up_limits wrong_amount_of_cash_received supported_cards_and_currencies top_up_reverted balance_not_updated_after_cheque_or_cash_deposit topping_up_by_card atm_support declined_cash_withdrawal verify_top_up top_up_by_cash_or_cheque wrong_exchange_rate_for_cash_withdrawal top_up_failed top_up_by_card_charge cash_withdrawal_charge",
    "账户资料": "age_limit edit_personal_details why_verify_identity unable_to_verify_identity passcode_forgotten terminate_account verify_source_of_funds verify_my_identity country_support",
    "费用与兑换": "exchange_rate card_payment_wrong_exchange_rate extra_charge_on_statement fiat_currency_support exchange_via_app card_payment_fee_charged transaction_charged_twice reverted_card_payment? exchange_charge",
    "安全与争议": "lost_or_stolen_card card_payment_not_recognised compromised_card direct_debit_payment_not_recognised lost_or_stolen_phone request_refund Refund_not_showing_up cash_withdrawal_not_recognised",
}
MAPPING = {label: queue for queue, labels in GROUPS.items() for label in labels.split()}
SENSITIVE = set(GROUPS["安全与争议"].split()) | {"terminate_account", "verify_source_of_funds"}
QUESTIONS = {
    "卡片物流": "询问订卡日期、当前配送状态及是否超过页面预计时间；不要索取完整地址。",
    "卡片使用": "询问卡片类型、具体使用场景及错误提示；不要收集 PIN 或完整卡号。",
    "转账": "询问转账时间、状态及转账类型；不要收集完整账户信息。",
    "现金与充值": "询问现金或充值渠道、时间和页面状态；敏感金额凭证交人工渠道处理。",
    "账户资料": "确认需要更新或核验的信息类型；身份证件和口令仅能在官方安全渠道处理。",
    "费用与兑换": "确认费用类型、发生时间与币种；由人工结合正式账单及政策核验。",
    "安全与争议": "请转人工安全处理；演示系统不承诺退款、冻结、挂失或资金追回。",
}


class Knowledge:
    version = "demo-kb-1.0"

    def __init__(self):
        labels_path = ROOT / "config/labels.json"
        labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else list(MAPPING)
        entries = [x for values in GROUPS.values() for x in values.split()]
        if len(entries) != len(set(entries)) or set(labels) != set(MAPPING):
            raise ValueError("Knowledge mapping must cover every label exactly once")

    def lookup(self, intent):
        if intent not in MAPPING:
            return None
        return {"id": "kb-" + intent, "version": self.version, "intent": intent, "queue": MAPPING[intent],
                "title": intent.replace("_", " "), "instructions": QUESTIONS[MAPPING[intent]],
                "escalation": "分类不明确、出现个人敏感信息或用户要求执行实际账户操作时转人工。",
                "disclaimer": "课程自编演示说明，不是银行官方政策。"}
