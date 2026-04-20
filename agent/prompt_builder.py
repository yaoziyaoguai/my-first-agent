# agent/prompt_builder.py
"""组装 Agent 的完整 system prompt。"""

from config import SYSTEM_PROMPT
from agent.memory import build_memory_section
from agent.skills.registry import build_skills_section


def build_system_prompt() -> str:
    """组装完整的 system prompt。
    
    各个 section 独立生成，在这里组装。
    """
    parts = [SYSTEM_PROMPT]
    
    memory_section = build_memory_section()
    if memory_section:
        parts.append(memory_section)
    
    skills_section = build_skills_section()
    if skills_section:
        parts.append(skills_section)
    
    return "\n\n".join(parts)
