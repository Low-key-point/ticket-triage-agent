"""AI-assisted synthetic behavior tests, never claimed as real user studies."""
OUTSIDE = [
    "What will the weather be tomorrow?", "Write a poem about mountains.",
    "How do I bake a chocolate cake?", "Explain photosynthesis to a child.",
    "Who won the football tournament?", "Book a hotel room for next week.",
    "Translate hello into Spanish.", "My printer is making a loud noise.",
    "Recommend a science fiction novel.", "How far away is the moon?",
    "My university lecture starts at noon.", "Find a recipe for vegetable soup.",
    "The internet router keeps restarting.", "What is the capital of Norway?",
    "I need help fixing a bicycle tyre.", "Please solve this algebra problem.",
    "My flight was cancelled yesterday.", "Teach me how to play chess.",
    "The washing machine is leaking water.", "When does the museum close?",
]
NON_ENGLISH = [
    "我的银行卡还没有寄到", "请帮我查询转账状态", "银行卡丢失了怎么办", "为什么账户余额没有更新", "我需要修改个人资料",
    "我的银行卡无法正常使用", "充值失败但已经扣款", "请解释本次兑换费用", "我要查询退款进度", "我想注销这个账户",
    "我的手机丢失了请帮助我", "账号无法通过身份验证", "我需要重新设置密码", "取款机吞掉了我的卡片", "我的卡即将过期",
    "银行卡が届きません", "送金の状態を確認したい", "카드가 아직 도착하지 않았습니다", "Моя карта ещё не пришла", "أريد معرفة حالة التحويل",
]
MULTI = [
    "My card has not arrived and I need to cancel a transfer.",
    "I want a new card and I need to change my bank details.",
    "I cannot withdraw cash and my transfer has failed.",
    "I need to change my PIN and I want a new card.",
    "My card is broken and I want to cancel my transfer.",
    "I need a refund and my card has not arrived.",
    "My payment failed and I cannot withdraw cash.",
    "I want to change my account details and I need to cancel a payment.",
    "I cannot top up my account and I need a new card.",
    "My transfer has failed and I want to change my PIN.",
    "I want to withdraw cash and I need to change my card.",
    "My card is not working and my payment has failed.",
    "I need to cancel a transfer and I want to change my account details.",
    "I need a card refund and I cannot withdraw cash.",
    "My new card has not arrived and I want to change my PIN.",
    "I want a bank transfer refund and my card is broken.",
    "My cash withdrawal failed and I need to cancel my card payment.",
    "I cannot change my PIN and I want to withdraw cash.",
    "I need a new card and my bank transfer failed.",
    "My payment is not working and I need to change my bank details.",
]
SENSITIVE = [
    "My card was stolen yesterday.", "My phone was stolen and has the banking app.",
    "Someone hacked my bank account.", "I think my bank card is compromised.",
    "There is an unauthorized card payment.", "I see an unauthorised bank transfer.",
    "I believe this is a fraudulent transaction.", "Please help me with identity theft.",
    "I lost my card while travelling.", "I lost my phone with my banking app.",
    "I want a refund for a card purchase.", "The card refund has not appeared.",
    "I was scammed into sending money.", "My account has fraudulent charges.",
    "Please investigate this stolen bank card.", "My compromised card was used abroad.",
    "A scammer asked for my account password.", "Someone made unauthorized withdrawals.",
    "My bank account was hacked today.", "I found a charge for a stolen card.",
]
INVALID = [None, 42, False, {}, [], "", " ", "\t", "\n", "   \r\n", "a", "ab", "abc", "abcd", "123", "?!", "\t abc ", "a"*2001, "x"*2500, "卡"*2001]
TOOL_TEXTS = ["When will my new card arrive?", "I would like to know the exchange rate.", "How do I change my card PIN?", "How long does a bank transfer take?", "Can I use my card abroad?"]
CASES = []
for group, texts in [("out_of_domain", OUTSIDE), ("non_english", NON_ENGLISH), ("invalid", INVALID), ("multi_intent", MULTI), ("sensitive", SENSITIVE)]:
    for i, text in enumerate(texts):
        CASES.append({"id": f"{group}-{i+1:02d}", "group": group, "text": text, "expected": "validation_error" if group == "invalid" else "needs_review"})
for i, text in enumerate(TOOL_TEXTS):
    for fault in ["knowledge_missing", "knowledge_timeout", "model_error", "store_error"]:
        CASES.append({"id": f"tool-{i+1}-{fault}", "group": "tool_failure", "text": text, "fault": fault, "expected": "tool_error" if fault == "store_error" else "needs_review"})
