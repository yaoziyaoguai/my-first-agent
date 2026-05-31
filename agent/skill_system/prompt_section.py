"""Prompt Section Builder——生成 Skill 的 prompt 注入内容。

设计原则（来自 RFC Sec 5 / SDD Sec 9）：
- Level 1: 生成 metadata-only 的 prompt section（name, description, status, tags）
- Level 2: 仅在选中后生成 body section
- 绝不注入所有 Skill body 到 prompt
- 不触及 ToolRegistry / Memory / Runtime loop

Phase 3: build_skill_selection_section() 在 turn-start 阶段注入候选 skill
的选择器 section，让模型从候选列表中自主选择，而非依赖关键词匹配。
"""
from __future__ import annotations

from agent.skill_system.registry import SkillRegistry
from agent.skill_system.retriever import SkillCandidate


def build_skills_prompt_section(registry: SkillRegistry) -> str:
    """Level 1 prompt section: 列出所有可见 Skill 的 metadata。

    只包含 name / description / status / tags——绝不包含 body。
    返回空字符串当没有任何可见 Skill。
    """
    visible = registry.list_visible()
    if not visible:
        return ""

    lines: list[str] = [
        "## 可用 Skills",
        "",
        "以下 Skills 可通过名称显式调用。每个 Skill 是一个专业能力包。",
        "",
    ]

    for desc in visible:
        tags_str = ", ".join(desc.tags) if desc.tags else "无"
        lines.append(f"- **{desc.name}** (状态: {desc.status})")
        lines.append(f"  {desc.description}")
        lines.append(f"  标签: {tags_str}")
        lines.append("")

    return "\n".join(lines)


def build_skill_selection_section(candidates: list[SkillCandidate]) -> str:
    """Phase 3: 生成 turn-start skill 选择 section。

    在 model call 前注入到 system prompt 中，告知模型当前可用的候选 skill
    及其匹配原因，让模型自主决定是否通过 SKILL_SELECT 工具激活某个 skill。

    Args:
        candidates: SkillCandidateRetriever.retrieve() 返回的候选列表，
                   按 score 降序排列。

    Returns:
        候选列表非空时返回格式化的 selection section；空列表返回 ""。
    """
    if not candidates:
        return ""

    lines: list[str] = [
        "## Skill 选择",
        "",
        "根据用户输入，以下 Skills 可能适合当前任务：",
        "",
    ]

    for c in candidates:
        reason_cn = _match_reason_label(c.match_reason)
        terms_str = "、".join(c.matched_terms) if c.matched_terms else "无"
        lines.append(f"- **{c.skill_name}** (匹配度: {c.score:.1f} — {reason_cn}: {terms_str})")

    lines.append("")
    lines.append(
        "如果以上某个 Skill 适合当前任务，请调用 `SKILL_SELECT` 工具并传入 "
        "对应的 `skill_id` 来激活它。激活后 Skill 的完整指令会注入到后续对话中。"
    )
    lines.append(
        "如果以上 Skills 都不适合，请直接回复用户，**不要**调用 SKILL_SELECT。"
    )

    return "\n".join(lines)


def _match_reason_label(reason: str) -> str:
    """match_reason 的中文标签。"""
    _labels = {
        "trigger_exact": "触发器精确匹配",
        "trigger_substring": "触发器子串匹配",
        "alias_match": "别名匹配",
        "keyword_match": "关键词匹配",
    }
    return _labels.get(reason, reason)


def build_skill_body_section(name: str, body: str) -> str:
    """Level 2 body section: 为已选中的 Skill 生成 body 注入。

    只在 Skill 被选中后调用。body 来自 SkillLoader.load_body()。
    """
    if not body.strip():
        return ""

    return f"""## Skill: {name}

{body}

---
*以上为 Skill `{name}` 的完整指令。请按 Skill 定义执行。*
"""
