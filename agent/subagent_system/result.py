"""SubAgent result, audit, run, and adjudication contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolRequest:
    """SubAgent 请求工具的结构化意图；不代表已经执行。"""

    tool_name: str
    arguments: dict[str, Any]
    reason: str
    risk_level: str


@dataclass(frozen=True)
class FileSummary:
    """Bounded file summary，不能包含完整大文件内容。"""

    path: str
    summary: str
    line_count: int
    language: str = ""


@dataclass(frozen=True)
class ToolSnapshot:
    """Model-visible tool metadata snapshot, not execution authority."""

    name: str
    description: str
    risk_level: str
    requires_confirmation: bool
    is_hidden: bool = False


@dataclass(frozen=True)
class SubAgentAuditRecord:
    subagent_name: str
    delegation_id: str
    parent_trace_id: str
    execution_mode: str
    status: str
    stop_reason: str
    iterations_used: int
    max_iterations: int
    tools_requested: tuple[str, ...]
    tools_denied: tuple[str, ...]
    tools_executed: tuple[str, ...]
    memory_proposals_count: int
    warnings: tuple[str, ...]
    confidence: float
    elapsed_ms: int
    revision_count: int
    trace_event_count: int


@dataclass(frozen=True)
class SubAgentResult:
    status: str
    summary: str
    artifacts: tuple[str, ...]
    tool_requests: tuple[ToolRequest, ...]
    memory_proposals: tuple[object, ...]
    confidence: float
    warnings: tuple[str, ...]
    audit: SubAgentAuditRecord
    handoff_back: str
    clarification_question: str | None
    trace_events: tuple[object, ...]
    stop_reason: str
    batch_memory_proposals: tuple[object, ...] = ()


@dataclass(frozen=True)
class ParentAdjudicationResult:
    """Parent 的 L0 adjudication decision；不执行工具、不写 Memory。"""

    action: str
    reason: str
    merged_summary: str | None = None
    tool_calls_to_execute: tuple[str, ...] = ()
    memory_proposals_to_route: tuple[object, ...] = ()
    revised_request: object | None = None
    user_question: str | None = None

    @classmethod
    def accept(cls, reason: str, *, merged_summary: str | None = None) -> ParentAdjudicationResult:
        return cls(action="accept_result", reason=reason, merged_summary=merged_summary)

    @classmethod
    def reject(cls, reason: str) -> ParentAdjudicationResult:
        return cls(action="reject_result", reason=reason)

    @classmethod
    def request_revision(cls, reason: str, revised_request: object) -> ParentAdjudicationResult:
        return cls(action="request_revision", reason=reason, revised_request=revised_request)

    @classmethod
    def ask_user(cls, reason: str, user_question: str) -> ParentAdjudicationResult:
        return cls(action="ask_user", reason=reason, user_question=user_question)


@dataclass(frozen=True)
class SubAgentRun:
    """Runtime tracking for one parent-owned delegation lifecycle."""

    delegation_id: str
    state: str
    request: object
    descriptor: object | None
    context_package: object | None
    result: SubAgentResult | None
    adjudication: ParentAdjudicationResult | None
    revision_count: int
    revision_history: tuple[SubAgentRun, ...] = ()
    created_at: float = 0.0
    updated_at: float = 0.0

