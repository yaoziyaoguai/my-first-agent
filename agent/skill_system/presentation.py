"""Skill CLI/TUI Presentation —— 格式化 Skill 信息用于终端显示。

设计原则：
- 只做字符串格式化，不导入 loader / runtime / selector
- 不持有 registry 引用，只接收 descriptor
- 呈现状态，不改变状态
"""
from __future__ import annotations

from agent.skill_system.descriptor import SkillDescriptor


def format_available_skills(skills: list[SkillDescriptor]) -> str:
    """格式化可用 Skill 列表。"""
    if not skills:
        return "（无可用 Skill）"

    lines: list[str] = []
    for s in skills:
        risk_tag = f"[{s.risk_level.upper()}]" if s.risk_level != "low" else ""
        status_tag = f"({s.status})"
        line = f"  {s.name} v{s.version} — {s.description} {status_tag}"
        if risk_tag:
            line += f" {risk_tag}"
        lines.append(line)

    header = f"可用 Skill（共 {len(skills)} 个）："
    return header + "\n" + "\n".join(lines)


def format_selected_skill(descriptor: SkillDescriptor) -> str:
    """格式化选中 Skill 的详细信息。"""
    lines = [
        f"Skill: {descriptor.name}",
        f"  版本: {descriptor.version}",
        f"  描述: {descriptor.description}",
        f"  风险等级: {descriptor.risk_level}",
        f"  状态: {descriptor.status}",
    ]
    if descriptor.tags:
        lines.append(f"  标签: {', '.join(descriptor.tags)}")
    if descriptor.allowed_tools:
        lines.append(f"  工具: {', '.join(descriptor.allowed_tools)}")
    if descriptor.memory_scope != "none":
        lines.append(f"  Memory: {descriptor.memory_scope}")
    return "\n".join(lines)


def format_selected_skill_for_display(descriptor: SkillDescriptor) -> str:
    """格式化选中 Skill 的紧凑单行展示。"""
    return f"[Skill] {descriptor.name} v{descriptor.version} — {descriptor.description[:60]}"


def format_blocked_action(skill_name: str, tool_name: str, reason: str) -> str:
    """格式化被阻止的工具动作。"""
    return (
        f"[BLOCKED] Skill '{skill_name}' 请求的工具 '{tool_name}' 被阻止：{reason}"
    )
