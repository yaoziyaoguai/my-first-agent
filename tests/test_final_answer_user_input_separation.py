"""协议边界回归：把 final answer 与 request_user_input 在协议层分干净。

为什么不直接测「需要我帮你调整某些天数吗？」这句话：
v0.3 人工 smoke 暴露的问题表面是「模型问了又不等」，本质是 Runtime 的等待
信号源被混淆——历史上 Runtime 既看结构化的 `request_user_input` 工具，又用
`BLOCKING_USER_INPUT_PATTERNS` 关键词列表对普通文本做兜底分类。任何在文本里
对一句中文做匹配的修复都会让本系统继续依赖一张不断膨胀的关键词黑名单。

正确的修法是协议层契约：
1. `request_user_input` 是 Runtime 唯一识别的「等待用户输入」信号
2. `mark_step_complete` 是 Runtime 唯一识别的「步骤已完成」信号
3. 这两个信号语义互斥；不允许在同一响应里同时发出
4. final answer 文本里不要写看似等待用户回答的开放式追问；如需礼貌收尾，
   改用「如后续需要调整可以继续告诉我」这类非等待式陈述
5. 模型违反纪律时，Runtime 不靠问号、关键词去猜，而是按结构化信号执行

本文件下面 7 个测试守护的是上述「契约」，不是任何具体业务句式。
"""
from __future__ import annotations

from agent.model_output_resolution import (
    BLOCKING_USER_INPUT_PATTERNS,
    NON_BLOCKING_FOLLOWUP_PATTERNS,
    is_blocking_user_input_request,
    is_non_blocking_followup,
)
from config import SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 1. SYSTEM_PROMPT 必须把「request_user_input 是 Runtime 唯一等待信号」写明
# ---------------------------------------------------------------------------
# 用结构化语义关键词组合检索（而不是绑定一句完整中文），让 prompt 措辞可演进，
# 但「这条规则被声明过」这件事不能丢。

def test_system_prompt_declares_request_user_input_as_only_waiting_signal():
    text = SYSTEM_PROMPT
    assert "request_user_input" in text, "SYSTEM_PROMPT 必须显式提到 request_user_input 工具名"
    # 「唯一」这条边界必须出现在同一段（300 字内）
    idx = text.find("request_user_input")
    nearby = text[max(0, idx - 200): idx + 400]
    waiting_markers = ["唯一", "只有", "仅当"]
    assert any(m in nearby for m in waiting_markers), (
        "SYSTEM_PROMPT 必须明确 request_user_input 是 Runtime「唯一」等待信号；"
        f"实际附近文本未命中 {waiting_markers}"
    )


# ---------------------------------------------------------------------------
# 2. SYSTEM_PROMPT 必须禁止「同一响应里既追问又调用 mark_step_complete」
# ---------------------------------------------------------------------------

def test_system_prompt_forbids_mixing_question_with_mark_step_complete():
    text = SYSTEM_PROMPT
    assert "mark_step_complete" in text, "SYSTEM_PROMPT 必须显式提到 mark_step_complete"
    # 互斥规则需要落到字面上：找到 mark_step_complete 上下文里必须有「不要 / 不能 / 互斥」之类
    # 的禁止性词汇 + 与 request_user_input 的对照
    idx = text.find("mark_step_complete")
    # 同一段里两侧 500 字应同时出现 request_user_input 与禁止性词汇
    nearby = text[max(0, idx - 500): idx + 500]
    assert "request_user_input" in nearby, (
        "mark_step_complete 必须与 request_user_input 在同一段被对比说明，"
        "让模型理解两者不能混用"
    )
    forbid_markers = ["不要", "不能", "互斥", "禁止", "不会"]
    assert any(m in nearby for m in forbid_markers), (
        f"mark_step_complete 附近必须含禁止性表达，实际未命中 {forbid_markers}"
    )


# ---------------------------------------------------------------------------
# 3. SYSTEM_PROMPT 必须给「非等待式收尾」示例，让模型有可参照的正确写法
# ---------------------------------------------------------------------------

def test_system_prompt_offers_non_waiting_closing_examples():
    text = SYSTEM_PROMPT
    # 要求 prompt 里至少出现一个「✅ ... 」或「正例 / 非等待」类正例标记
    positive_markers = ["✅", "正例", "非等待"]
    assert any(m in text for m in positive_markers), (
        f"SYSTEM_PROMPT 必须给出至少一条非等待式收尾正例，未命中 {positive_markers}"
    )
    # 同时必须出现「❌ / 反例 / 等待式」对照，否则模型只看到正例不知道哪些写法是错的
    negative_markers = ["❌", "反例"]
    assert any(m in text for m in negative_markers), (
        f"SYSTEM_PROMPT 必须给出至少一条等待式追问反例对照，未命中 {negative_markers}"
    )


# ---------------------------------------------------------------------------
# 4. Runtime 不靠问号猜状态：纯问号文本不会被分类为 blocking 求助
# ---------------------------------------------------------------------------
# 这是最关键的一条「不是关键词 hack」守护：
# 即便文本看起来非常像在问问题，只要它没命中 BLOCKING_USER_INPUT_PATTERNS（小而稳）
# 且没调用 request_user_input 工具，Runtime 就不应该把它当成等待信号。

def test_runtime_does_not_enter_waiting_on_plain_question_text():
    # 一系列「看起来在问用户」的句子，但都不是 BLOCKING_USER_INPUT_PATTERNS 命中
    # 也不是 request_user_input。Runtime 必须保持「不进入等待」。
    samples = [
        "需要我帮你调整某些天数，或者提供更具体的酒店/餐厅推荐吗？",
        "要不要继续优化下一步？",
        "是否需要我进一步调整？",
        "你觉得这个方案怎么样？",
        "还需要我做什么？",
    ]
    for s in samples:
        assert is_blocking_user_input_request(s) is False, (
            f"问号 / 看似追问的文本不应被分类为阻塞求助；否则就是回到关键词猜测的老路。"
            f"违例文本：{s!r}"
        )


# ---------------------------------------------------------------------------
# 5. 非等待式收尾应被正确识别为 non-blocking follow-up
# ---------------------------------------------------------------------------

def test_runtime_recognizes_non_waiting_closing_phrase_as_followup():
    # SYSTEM_PROMPT 推荐的两类非等待式收尾必须被 resolver 当作 follow-up
    samples = [
        "如后续需要调整，可以继续告诉我。",
        "如需调整，请告诉我。",
    ]
    for s in samples:
        assert is_non_blocking_followup(s) is True, (
            f"非等待式收尾文本必须被识别为 follow-up，否则会被误判进等待。"
            f"违例文本：{s!r}"
        )
        # 同时验证它们不会被升级到 blocking
        assert is_blocking_user_input_request(s) is False


# ---------------------------------------------------------------------------
# 6. BLOCKING_USER_INPUT_PATTERNS 是历史兜底，不允许悄悄扩张
# ---------------------------------------------------------------------------
# 给关键词列表加一条「上限守护」：若未来有人尝试把业务句式塞进黑名单，
# 这条测试会直接失败，强制走 SYSTEM_PROMPT 修法。
# 阈值取目前长度 + 4 的余量，留极少数真正的"无法继续"语义兜底空间。

def test_blocking_pattern_list_does_not_grow_into_keyword_blacklist():
    assert len(BLOCKING_USER_INPUT_PATTERNS) <= 23, (
        f"BLOCKING_USER_INPUT_PATTERNS 当前 {len(BLOCKING_USER_INPUT_PATTERNS)} 项；"
        "继续扩张就是回到关键词猜状态的老路。如果模型用文本求助导致了新问题，"
        "正确修法是更新 SYSTEM_PROMPT 的「用户输入与任务收尾协议」段，"
        "而不是在这里加关键词。"
    )
    assert len(NON_BLOCKING_FOLLOWUP_PATTERNS) <= 22, (
        f"NON_BLOCKING_FOLLOWUP_PATTERNS 当前 {len(NON_BLOCKING_FOLLOWUP_PATTERNS)} 项；"
        "同上限制；不要为了某个 smoke 例子继续叠加业务句式。"
    )


# ---------------------------------------------------------------------------
# 7. SYSTEM_PROMPT 反例 与 resolver 实际行为自洽
# ---------------------------------------------------------------------------
# 跨层一致性：prompt 里给模型看的「❌ 反例」如果反过来被 resolver 当成 blocking
# 求助，文档与实现就矛盾了——模型遵循 prompt 不写反例，结果实际系统又把它当
# 等待信号。两边必须自洽。

def test_system_prompt_negative_examples_are_not_resolved_as_blocking():
    # 从 SYSTEM_PROMPT 里抽取所有「❌ ...」反例行
    negatives = [
        line.split("❌", 1)[1].strip()
        for line in SYSTEM_PROMPT.splitlines()
        if "❌" in line
    ]
    assert negatives, "SYSTEM_PROMPT 应至少含一个 ❌ 反例"
    for example in negatives:
        # 反例本质都是「看似等待用户回答的追问」，按协议它们就是不该进入等待。
        # resolver 必须与这条契约自洽：不能把这些反例分类成 blocking 求助。
        assert is_blocking_user_input_request(example) is False, (
            f"SYSTEM_PROMPT 反例 {example!r} 被 resolver 判为 blocking — 文档与实现不自洽；"
            "要么改 prompt 反例，要么调整 resolver / pattern 列表"
        )
