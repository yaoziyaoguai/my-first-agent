"""Stage 4 fake/local MemoryStore skeleton。

本模块只提供测试可用的 in-memory store seam：它消费已经过
MemoryPolicy -> Confirmation UX -> OperationIntent -> AuditSummary 的结果，
不读取真实 sessions/runs/agent_log，不写真实长期记忆，不接 runtime/checkpoint，
也不让 prompt_builder 直接读取 store。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Iterable, Protocol

from agent.memory_contracts import MemoryScope
from agent.memory_operations import (
    MemoryAuditSummary,
    MemoryOperationIntent,
    MemoryOperationType,
)


MUTATING_OPERATION_TYPES = frozenset({
    MemoryOperationType.RETAIN,
    MemoryOperationType.UPDATE,
    MemoryOperationType.FORGET,
})

NON_WRITING_OPERATION_TYPES = frozenset({
    MemoryOperationType.REJECT,
    MemoryOperationType.USE_ONCE,
    MemoryOperationType.CLARIFY,
    MemoryOperationType.NO_OP,
})


class MemoryStoreApplyStatus(StrEnum):
    """fake store apply 的结果状态；不代表真实持久化状态。"""

    APPLIED = "applied"
    SKIPPED = "skipped"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """已确认、已审计、已应用到 fake store 的记录视图。

    MemoryRecord 和 MemoryCandidate 的边界必须清楚：Candidate 是候选输入，
    Record 是 apply_operation_intent 后的 fake/local 结果。这里保留 provenance、
    scope、safety、audit 信息，但不包含真实持久化路径、provider handle 或 runtime
    state。
    """

    id: str
    content: str
    scope: MemoryScope | None
    source_summary: str
    safety_summary: str
    audit_id: str
    created_by_operation: MemoryOperationType
    updated_by_operation: MemoryOperationType
    sensitive_redacted: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("MemoryRecord.id 不能为空")
        if not self.content.strip():
            raise ValueError("MemoryRecord.content 不能为空")
        if not self.source_summary.strip():
            raise ValueError("MemoryRecord.source_summary 不能为空")
        if not self.safety_summary.strip():
            raise ValueError("MemoryRecord.safety_summary 不能为空")
        if not self.audit_id.strip():
            raise ValueError("MemoryRecord.audit_id 不能为空")


@dataclass(frozen=True, slots=True)
class MemoryStoreApplyResult:
    """store apply 的可审计结果；不写日志、不触发 runtime。"""

    status: MemoryStoreApplyStatus
    operation_type: MemoryOperationType
    record: MemoryRecord | None
    audit_id: str
    message: str


class MemoryStoreProtocol(Protocol):
    """最小 storage seam，不是 Memory system 本身，也不是 runtime gateway。"""

    def apply_operation_intent(
        self,
        intent: MemoryOperationIntent,
        audit_summary: MemoryAuditSummary,
    ) -> MemoryStoreApplyResult:
        """应用已经确认并审计过的 operation intent。"""

    def get_record(self, record_id: str) -> MemoryRecord | None:
        """按 fake record id 查询当前 in-memory 记录。"""

    def list_records(self) -> tuple[MemoryRecord, ...]:
        """返回 deterministic fake records 视图。"""


def derive_memory_record_id(source_summary: str) -> str:
    """从 operation provenance 派生 fake record id。

    这是 deterministic local id，不是数据库主键，也不是跨会话持久 id。
    """

    if not source_summary.strip():
        raise ValueError("source_summary 不能为空")
    digest = sha256(source_summary.encode("utf-8")).hexdigest()
    return f"memory:fake:{digest[:16]}"


class InMemoryMemoryStore:
    """fake/local/test-only store。

    它只把传入的 MemoryRecord 保存在进程内 dict；没有文件 IO、网络、LLM、
    provider、MCP、checkpoint 或 runtime 默认接入。
    """

    def __init__(self, records: Iterable[MemoryRecord] = ()) -> None:
        self._records = {record.id: record for record in records}

    def apply_operation_intent(
        self,
        intent: MemoryOperationIntent,
        audit_summary: MemoryAuditSummary,
    ) -> MemoryStoreApplyResult:
        """应用已确认/已审计 intent，保持 fake store 边界。

        Store 不接收 raw MemoryDecision，也不自己调用 policy/confirmation/audit；
        所有安全治理必须在进入本函数前完成。本函数只做 fake/local state 变更。
        """

        _validate_apply_inputs(intent, audit_summary)
        audit_id = _derive_audit_id(audit_summary)

        if intent.operation_type in NON_WRITING_OPERATION_TYPES:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.SKIPPED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="operation does not authorize store write",
            )

        if (
            intent.operation_type in MUTATING_OPERATION_TYPES
            and intent.confirmation_status.value != "approved"
        ):
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.REJECTED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="mutating memory operation requires approved confirmation",
            )

        if intent.operation_type is MemoryOperationType.RETAIN:
            record = _record_from_intent(intent, audit_id)
            self._records[record.id] = record
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.APPLIED,
                operation_type=intent.operation_type,
                record=record,
                audit_id=audit_id,
                message="fake memory record retained",
            )

        if intent.operation_type is MemoryOperationType.UPDATE:
            return self._apply_update(intent, audit_id)

        if intent.operation_type is MemoryOperationType.FORGET:
            return self._apply_forget(intent, audit_id)

        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.SKIPPED,
            operation_type=intent.operation_type,
            record=None,
            audit_id=audit_id,
            message="operation is not handled by fake store",
        )

    def get_record(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def list_records(self) -> tuple[MemoryRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def _apply_update(
        self,
        intent: MemoryOperationIntent,
        audit_id: str,
    ) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        existing = self._records.get(record_id)
        if existing is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="fake memory record not found for update",
            )

        updated = MemoryRecord(
            id=existing.id,
            content=intent.content_summary,
            scope=intent.scope,
            source_summary=intent.source_summary,
            safety_summary=intent.safety_summary,
            audit_id=audit_id,
            created_by_operation=existing.created_by_operation,
            updated_by_operation=MemoryOperationType.UPDATE,
            sensitive_redacted=intent.sensitive_redacted,
        )
        self._records[record_id] = updated
        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.APPLIED,
            operation_type=intent.operation_type,
            record=updated,
            audit_id=audit_id,
            message="fake memory record updated",
        )

    def _apply_forget(
        self,
        intent: MemoryOperationIntent,
        audit_id: str,
    ) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        existing = self._records.pop(record_id, None)
        if existing is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="fake memory record not found for forget",
            )

        return MemoryStoreApplyResult(
            status=MemoryStoreApplyStatus.APPLIED,
            operation_type=intent.operation_type,
            record=existing,
            audit_id=audit_id,
            message="fake memory record forgotten",
        )


def _record_from_intent(
    intent: MemoryOperationIntent,
    audit_id: str,
) -> MemoryRecord:
    return MemoryRecord(
        id=derive_memory_record_id(intent.source_summary),
        content=intent.content_summary,
        scope=intent.scope,
        source_summary=intent.source_summary,
        safety_summary=intent.safety_summary,
        audit_id=audit_id,
        created_by_operation=intent.operation_type,
        updated_by_operation=intent.operation_type,
        sensitive_redacted=intent.sensitive_redacted,
    )


def _validate_apply_inputs(
    intent: MemoryOperationIntent,
    audit_summary: MemoryAuditSummary,
) -> None:
    if not isinstance(intent, MemoryOperationIntent):
        raise TypeError("MemoryOperationIntent is required")
    if not isinstance(audit_summary, MemoryAuditSummary):
        raise TypeError("MemoryAuditSummary is required")

    if (
        audit_summary.operation_type != intent.operation_type
        or audit_summary.decision_type != intent.decision_type
        or audit_summary.source_summary != intent.source_summary
        or audit_summary.user_choice != intent.user_choice.value
        or audit_summary.safety_summary != intent.safety_summary
        or audit_summary.sensitive_redacted != intent.sensitive_redacted
        or audit_summary.user_visible_summary != intent.user_visible_summary
    ):
        raise ValueError("audit summary does not match operation intent")


def _derive_audit_id(audit_summary: MemoryAuditSummary) -> str:
    payload = "|".join((
        audit_summary.operation_type.value,
        audit_summary.decision_type.value,
        audit_summary.source_summary,
        audit_summary.user_choice,
        audit_summary.safety_summary,
        str(audit_summary.sensitive_redacted),
    ))
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return f"audit:fake:{digest[:16]}"
