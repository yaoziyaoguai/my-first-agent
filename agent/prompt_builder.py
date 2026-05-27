"""组装 Agent 的完整 system prompt。"""

from __future__ import annotations

from agent.memory import build_memory_section
from agent.memory_contracts import MemorySnapshot
from config import SYSTEM_PROMPT


def build_skills_section() -> str:
    """返回正式 Skill System 接入前的空 Skill prompt 段。

    旧 `agent.skills` prototype 已隔离到 `agent.legacy_skills`，prompt_builder
    不能再扫描旧 registry 或把 legacy descriptor 注入模型上下文。正式
    `agent/skill_system/` 后续实现时，应通过新的 progressive disclosure seam
    显式接入。
    """

    return ""


def build_system_prompt(
    memory_snapshot: MemorySnapshot | None = None,
    *,
    memory_section: str = "",
) -> str:
    """组装完整的 system prompt。

    各个 section 独立生成，在这里组装。prompt_builder 只消费已经构造好的
    MemorySnapshot 或预渲染的 memory_section；它不负责 memory policy、retrieval 或 storage 读取。

    memory_section 参数用于 dispatcher 统一 recall 路径：当调用方已通过
    MEMORY_RECALL dispatch 获取渲染后的 prompt section 时，直接传入，避免
    重复调用 build_memory_section()。
    """
    parts = [SYSTEM_PROMPT]

    if memory_section:
        parts.append(memory_section)
    else:
        section = build_memory_section(memory_snapshot)
        if section:
            parts.append(section)

    skills_section = build_skills_section()
    if skills_section:
        parts.append(skills_section)

    return "\n\n".join(parts)
