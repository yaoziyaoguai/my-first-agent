"""组装 Agent 的完整 system prompt。"""

from __future__ import annotations

from config import SYSTEM_PROMPT
from agent.memory import build_memory_section
from agent.memory_contracts import MemorySnapshot
from agent.skills.registry import build_skills_section


def build_system_prompt(memory_snapshot: MemorySnapshot | None = None) -> str:
    """组装完整的 system prompt。

    各个 section 独立生成，在这里组装。prompt_builder 只消费已经构造好的
    MemorySnapshot；它不负责 memory policy、retrieval 或 storage 读取。
    """
    parts = [SYSTEM_PROMPT]

    memory_section = build_memory_section(memory_snapshot)
    if memory_section:
        parts.append(memory_section)

    skills_section = build_skills_section()
    if skills_section:
        parts.append(skills_section)

    return "\n\n".join(parts)
