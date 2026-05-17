"""SubAgent delegation request contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.subagent_system.execution_mode import EXECUTION_MODE_VALUES


@dataclass(frozen=True)
class SubAgentRequest:
    """Parent Agent creates a bounded delegation request.

    默认值保持 L0：local_fake、无 Memory、无技能、单轮执行。SubAgent 不能通过
    request 自行提升 execution mode。
    """

    task: str
    role: str
    allowed_tools: tuple[str, ...]
    parent_trace_id: str
    delegation_reason: str
    allowed_skills: tuple[str, ...] = ()
    memory_scope: str = "none"
    max_iterations: int = 1
    execution_mode: str = "local_fake"
    risk_level: str = "low"
    confirmation_policy: str = "inherit_tool_policy"
    context: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    max_revisions: int = 1
    relevant_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.task:
            raise ValueError("task is required")
        if not self.role:
            raise ValueError("role is required")
        if not isinstance(self.allowed_tools, tuple):
            raise ValueError("allowed_tools must be a tuple")
        if not isinstance(self.allowed_skills, tuple):
            raise ValueError("allowed_skills must be a tuple")
        if self.memory_scope not in {"none", "read_context", "propose"}:
            raise ValueError("memory_scope is invalid")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.execution_mode not in EXECUTION_MODE_VALUES:
            raise ValueError("execution_mode is invalid")
        if self.max_revisions < 0:
            raise ValueError("max_revisions must be >= 0")
        if not isinstance(self.relevant_files, tuple):
            raise ValueError("relevant_files must be a tuple")
        object.__setattr__(self, "context", dict(self.context))

