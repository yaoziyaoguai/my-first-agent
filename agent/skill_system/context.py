"""SkillContext —— Runtime 准备的 Skill 调用上下文。

设计原则（来自 RFC/SDD）：
- 组装 descriptor / body / task goal / audit id / memory context
- 上下文不执行工具、不写 Memory、不拥有 loop
- 不可变——通过 SkillContext 传递，不修改 Runtime state
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.skill_system.descriptor import SkillDescriptor, MemoryScope


@dataclass(frozen=True)
class SkillContext:
    """Runtime 为一次 Skill invocation 准备的上下文。

    包含 selected descriptor、loaded body、task goal、audit id 等。
    不包含 tool execution 能力——tool 请求通过 ToolBinding 处理。
    """

    descriptor: SkillDescriptor | None = None
    """已选中的 Skill descriptor（Level 1 metadata）。"""

    body: str = ""
    """已加载的 SKILL.md body（Level 2，仅在选中后加载）。"""

    task_goal: str = ""
    """用户/调用者的任务目标摘要。"""

    audit_id: str = ""
    """本次调用的审计 ID。"""

    checkpoint_correlation_id: str = ""
    """关联的 checkpoint 标识（Phase 7b 使用）。"""

    memory_context: str = ""
    """已批准的 Memory 只读上下文（Phase 7 使用）。"""

    memory_scope: MemoryScope = "none"
    """当前 Skill 的 memory_scope 快照。"""

    @property
    def skill_name(self) -> str:
        return self.descriptor.name if self.descriptor else "unknown"
