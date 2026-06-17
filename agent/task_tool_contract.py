"""Task-level governed tool contract for S2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.task_context import TaskContextPackage, build_task_execution_context

_META_STATUSES = {"meta_recorded"}
_ALLOWED_STATUSES = {"executed"}
_BLOCKED_STATUSES = {"blocked_by_policy"}
_FAILED_STATUSES = {"failed", "rejected_by_check", "error"}
_KNOWN_STATUSES = _META_STATUSES | _ALLOWED_STATUSES | _BLOCKED_STATUSES | _FAILED_STATUSES


@dataclass(frozen=True, slots=True)
class GovernedToolCall:
    """Auditable summary for one durable tool_execution_log entry."""

    tool_use_id: str
    tool_name: str
    status: str
    step_index: int | None
    policy_decision: str
    result_recorded: bool
    result_size: int
    audit_ready: bool


@dataclass(frozen=True, slots=True)
class GovernedToolContractReport:
    """Task-level report for tool/policy/evidence contract checks."""

    calls: tuple[GovernedToolCall, ...]
    provider_callable: bool
    contract_violations: tuple[str, ...]

    @property
    def attempted_count(self) -> int:
        return len(self.calls)

    @property
    def executed_count(self) -> int:
        return sum(1 for call in self.calls if call.status in _ALLOWED_STATUSES)

    @property
    def blocked_count(self) -> int:
        return sum(1 for call in self.calls if call.status in _BLOCKED_STATUSES)

    @property
    def failed_count(self) -> int:
        return sum(1 for call in self.calls if call.status in _FAILED_STATUSES)

    @property
    def meta_count(self) -> int:
        return sum(1 for call in self.calls if call.status in _META_STATUSES)

    @property
    def audit_ready(self) -> bool:
        return self.provider_callable and not self.contract_violations


RecordEvidenceFn = Callable[..., dict[str, Any]]


def build_governed_tool_contract_report(
    state: Any,
    *,
    context_package: TaskContextPackage | None = None,
) -> GovernedToolContractReport:
    """Build a task-level tool contract report without executing tools."""

    package = context_package or build_task_execution_context(state)
    calls: list[GovernedToolCall] = []
    violations: list[str] = list(package.provider_callable_issues)

    for tool_use_id, entry in getattr(state.task, "tool_execution_log", {}).items():
        call, entry_violations = _build_call(str(tool_use_id), entry)
        calls.append(call)
        violations.extend(entry_violations)

    return GovernedToolContractReport(
        calls=tuple(calls),
        provider_callable=package.provider_callable,
        contract_violations=tuple(violations),
    )


def record_tool_contract_evidence(
    report: GovernedToolContractReport,
    *,
    operation: str = "task_tool_contract.summary",
    record_evidence_fn: RecordEvidenceFn | None = None,
) -> dict[str, Any]:
    """Record safe task-level evidence for governed tool contract review."""

    if record_evidence_fn is None:
        from agent.evidence_recorder import record_evidence as record_evidence_fn

    return record_evidence_fn(
        subsystem="tool",
        operation=operation,
        phase="summary",
        status="ok" if report.audit_ready else "blocked",
        reason_code="" if report.audit_ready else "tool_contract_violation",
        safe_summary="task governed tool contract summary",
        content_persisted=False,
        content_redacted=False,
        sensitive=False,
        metadata={
            "attempted_count": report.attempted_count,
            "executed_count": report.executed_count,
            "blocked_count": report.blocked_count,
            "failed_count": report.failed_count,
            "meta_count": report.meta_count,
            "provider_callable": report.provider_callable,
            "contract_violation_count": len(report.contract_violations),
        },
    )


def _build_call(
    tool_use_id: str,
    entry: Any,
) -> tuple[GovernedToolCall, list[str]]:
    violations: list[str] = []
    if not isinstance(entry, dict):
        return (
            GovernedToolCall(
                tool_use_id=tool_use_id,
                tool_name="",
                status="invalid",
                step_index=None,
                policy_decision="unknown",
                result_recorded=False,
                result_size=0,
                audit_ready=False,
            ),
            [f"{tool_use_id}: tool_execution_log entry is not a dict"],
        )

    tool_name = str(entry.get("tool") or "")
    status = str(entry.get("status") or "")
    result_recorded = "result" in entry
    result_size = len(str(entry.get("result", ""))) if result_recorded else 0
    step_index = entry.get("step_index")
    if not isinstance(step_index, int):
        step_index = None

    if not tool_name:
        violations.append(f"{tool_use_id}: missing tool name")
    if status not in _KNOWN_STATUSES:
        violations.append(f"{tool_use_id}: unknown tool status {status!r}")
    if status not in _META_STATUSES and not result_recorded:
        violations.append(f"{tool_use_id}: non-meta tool missing result")

    audit_ready = bool(tool_name) and status in _KNOWN_STATUSES and (
        status in _META_STATUSES or result_recorded
    )
    return (
        GovernedToolCall(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            status=status,
            step_index=step_index,
            policy_decision=_policy_decision(status),
            result_recorded=result_recorded,
            result_size=result_size,
            audit_ready=audit_ready,
        ),
        violations,
    )


def _policy_decision(status: str) -> str:
    if status in _ALLOWED_STATUSES:
        return "allowed"
    if status in _BLOCKED_STATUSES:
        return "rejected"
    if status in _FAILED_STATUSES:
        return "failed"
    if status in _META_STATUSES:
        return "control"
    return "unknown"
