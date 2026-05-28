"""组装 Agent 的完整 system prompt。"""

from __future__ import annotations

from typing import Any

from agent.memory import build_memory_section
from agent.memory_contracts import MemorySnapshot
from agent.skill_system.prompt_section import (
    build_skills_prompt_section,
)
from config import SYSTEM_PROMPT


def build_skills_section(skill_registry: Any = None) -> str:
    """生成 Skill 列表 prompt section。

    Loop 2.2: 当 skill_registry 可用时，通过 build_skills_prompt_section()
    生成模型可见的可用技能列表。不可用时返回空字符串（兼容旧行为）。
    """
    if skill_registry is None:
        return ""
    return build_skills_prompt_section(skill_registry)


def build_system_prompt(
    memory_snapshot: MemorySnapshot | None = None,
    *,
    memory_section: str = "",
    skill_registry: Any = None,
    active_skill_section: str = "",
) -> str:
    """组装完整的 system prompt。

    各个 section 独立生成，在这里组装。prompt_builder 只消费已经构造好的
    MemorySnapshot 或预渲染的 memory_section；它不负责 memory policy、retrieval 或 storage 读取。

    memory_section 参数用于 dispatcher 统一 recall 路径：当调用方已通过
    MEMORY_RECALL dispatch 获取渲染后的 prompt section 时，直接传入，避免
    重复调用 build_memory_section()。

    Loop 2.2: skill_registry 用于生成可用技能列表；active_skill_section
    用于注入上一轮 SKILL_SELECT 成功加载的 skill body。
    """
    parts = [SYSTEM_PROMPT]

    if memory_section:
        parts.append(memory_section)
    else:
        section = build_memory_section(memory_snapshot)
        if section:
            parts.append(section)

    skills_section = build_skills_section(skill_registry)
    if skills_section:
        parts.append(skills_section)

    # Loop 2.2: 注入当前激活 Skill 的 body 作为模型 instruction
    if active_skill_section:
        parts.append(f"[Active Skill Instructions]\n{active_skill_section}")

    return "\n\n".join(parts)
