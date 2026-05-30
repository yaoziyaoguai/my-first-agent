"""真实 provider 的确定性 skill selection fallback。

中文学习注释 —— 为什么需要这个模块：
=============================================

问题：agent/loop.py 的 turn-end hook 中，SKILL_SELECT 的 model_decision_metadata
仅在 `provider_kind == "fake"` 时被填充（自动选择第一个可见 skill）。真实 provider
路径下 model_decision_metadata 为空，导致 SkillRuntimeActionHandler.handle() 在
skill_action.py:65 因 `selected_skill_id` 缺失而返回 no_suitable_skill。

这不是"真实模型不会选 skill"的问题——真实模型根本**没有机会**选，因为 turn-end
hook 在模型响应完成后才触发，模型输出中不包含 skill selection 信息。

解决方案不是让真实模型在 prompt 中输出 skill selection（那会污染对话），而是在
turn-end hook 中用确定性 keyword matching 判断用户意图是否匹配某个 skill。

与 fake provider auto-select 的关键区别：
- fake: 无条件选择第一个可见 skill → 仅用于测试 L3 evidence chain
- real: 基于 user_input 与 skill name/description/tags 的 keyword matching
  → 没有匹配时不选择，保持 no_suitable_skill
  → 匹配结果可解释（matched_terms, match_score）
  → 匹配结果是确定性的（相同输入总是相同输出）
"""

from __future__ import annotations

from agent.skill_system.descriptor import SkillDescriptor


def select_skill_for_real_provider(
    user_input: str,
    visible_skills: list[SkillDescriptor],
) -> dict | None:
    """基于用户输入的确定性 keyword matching 选择 skill。

    匹配策略（按权重降序）：
    1. name 分词匹配（权重 3）：将 skill name 按 -/_ 分割为词，
       检查每个词（>=3 字符）是否出现在 user_input 中
    2. tags 匹配（权重 2）：检查 skill tags 是否出现在 user_input 中
    3. description 词匹配（权重 1）：检查 description 中的词（>=3 字符）
       是否出现在 user_input 中

    返回 None 表示没有匹配——调用方不应填充 model_decision_metadata，
    handler 将返回 no_suitable_skill。

    返回 dict 包含：
    - selected_skill_id: 匹配的 skill name
    - selection_reason: 可解释的选择原因
    - selection_confidence: high/medium/low（基于匹配分数）
    - matched_terms: 匹配到的词列表
    - match_score: 原始匹配分数
    """
    if not user_input or not visible_skills:
        return None

    normalized_input = user_input.lower()

    best_score = 0
    best_skill: SkillDescriptor | None = None
    best_matched_terms: list[str] = []

    for skill in visible_skills:
        score = 0
        matched_terms: list[str] = []

        # 1. name 分词匹配（权重 3）
        name_lower = skill.name.lower()
        name_parts = set(
            name_lower.replace("-", " ").replace("_", " ").split()
        )
        for part in name_parts:
            if len(part) >= 3 and part in normalized_input:
                score += 3
                matched_terms.append(f"name:{part}")

        # 2. tags 匹配（权重 2）
        for tag in skill.tags:
            tag_lower = tag.lower()
            if len(tag_lower) >= 2 and tag_lower in normalized_input:
                score += 2
                matched_terms.append(f"tag:{tag}")

        # 3. description 词匹配（权重 1）
        desc_lower = skill.description.lower()
        import re
        # 分割符：空白 + 中英文标点 + 中文引号 “ ” ‘ ’
        desc_words = set(
            re.split(r"[\s,，。、；：！？“”‘’]+", desc_lower)
        )
        for word in desc_words:
            if len(word) >= 2 and word in normalized_input:
                score += 1
                matched_terms.append(f"desc:{word}")

        # 3b. 中文 bigram 重叠匹配：中文不像英文有空格分词，
        # "写笔记" 在 "帮我写一个笔记" 中不是连续子串，
        # 但它们的 bigram 集合有交集（"笔记"），因此可以匹配。
        # bigram 匹配比精确子串匹配更宽松，但结合多信号
        # （name/tags/description）和分数阈值可控制精度。
        _chinese_spans: list[str] = re.findall(r"[一-鿿]+", desc_lower)
        _input_cn_spans: list[str] = re.findall(r"[一-鿿]+", normalized_input)
        _input_bigrams: set[str] = set()
        for _cn in _input_cn_spans:
            for _j in range(len(_cn) - 1):
                _input_bigrams.add(_cn[_j:_j + 2])

        for span in _chinese_spans:
            span_stripped = span.strip()
            if len(span_stripped) < 2:
                continue
            # 精确子串匹配（保留原有逻辑，覆盖"记录任务"这类完整匹配）
            if span_stripped in normalized_input:
                score += 1
                matched_terms.append(f"desc_cn:{span_stripped}")
                continue
            # bigram 重叠匹配：至少需要 1 个 bigram 重叠
            _span_bigrams = {
                span_stripped[_j:_j + 2]
                for _j in range(len(span_stripped) - 1)
            }
            if _span_bigrams & _input_bigrams:
                score += 1
                matched_terms.append(f"desc_cn_bigram:{span_stripped}")

        if score > best_score:
            best_score = score
            best_skill = skill
            best_matched_terms = matched_terms

    # 最低阈值：至少 1 个匹配项
    if best_score == 0 or best_skill is None:
        return None

    # confidence 映射：基于匹配分数的启发式
    if best_score >= 5:
        confidence = "high"
    elif best_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "selected_skill_id": best_skill.name,
        "selection_reason": (
            f"deterministic keyword match: user input matched skill "
            f"'{best_skill.name}' via terms {best_matched_terms} (score={best_score})"
        ),
        "selection_confidence": confidence,
        "matched_terms": best_matched_terms,
        "match_score": best_score,
    }
