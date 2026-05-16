"""Prompt Section Builder——生成 Skill 的 prompt 注入内容。

设计原则（来自 RFC Sec 5 / SDD Sec 9）：
- Level 1: 生成 metadata-only 的 prompt section（name, description, status, tags）
- Level 2: 仅在选中后生成 body section
- 绝不注入所有 Skill body 到 prompt
- 不触及 ToolRegistry / Memory / Runtime loop
"""
from __future__ import annotations

from agent.skill_system.registry import SkillRegistry


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
