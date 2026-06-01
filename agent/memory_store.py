"""Stage 4 fake/local MemoryStore skeleton。

本模块只提供测试可用的 in-memory store seam：它消费已经过
MemoryPolicy -> Confirmation UX -> OperationIntent -> AuditSummary 的结果，
不读取真实 sessions/runs/agent_log，不写真实长期记忆，不接 runtime/checkpoint，
也不让 prompt_builder 直接读取 store。

Memory Kernel v1 — MemoryRecord 字段说明：
- ``memory_type``: semantic / episodic / procedural，当前默认 "semantic"。
- ``source_type``: explicit_user_request / agent_suggested / reflection / imported，
  当前默认 "explicit_user_request"。
- ``approval_status``: pending / approved / rejected / edited，当前默认 "approved"
  （经过 confirmation adapter 后已是 approved）。
- ``metadata``: 通用扩展 dict，当前默认空。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

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
    MemoryOperationType.CLARIFY,
    MemoryOperationType.NO_OP,
})

WRITING_CONFIRMATION_STATUS_VALUES = frozenset({"approved", "auto_retained"})
REJECTED_CONFIRMATION_STATUS_VALUES = frozenset({"rejected"})
REJECTING_USER_CHOICE_VALUES = frozenset({"reject"})


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

    Memory Kernel v1 显式字段：
    - memory_type: 默认 "semantic"，未来可扩展 episodic/procedural。
    - source_type: 默认 "explicit_user_request"，未来可扩展 agent_suggested 等。
    - approval_status: 默认 "approved"，记录确认结果。
    - metadata: 通用扩展 dict。
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
    memory_type: str = "semantic"
    source_type: str = "explicit_user_request"
    approval_status: str = "approved"
    metadata: dict = field(default_factory=dict)

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

    def remove_record(self, record_id: str) -> bool:
        """按 record_id 移除一条记录；返回 True 表示成功移除。

        这是 store 层的直接操作接口，不经过 policy/confirmation 管线。
        调用方（如 CLI forget 命令）已自行确认用户意图。
        """


def derive_memory_record_id(source_summary: str) -> str:
    """从 operation provenance 派生 fake record id。

    这是 deterministic local id，不是数据库主键，也不是跨会话持久 id。
    """

    if not source_summary.strip():
        raise ValueError("source_summary 不能为空")
    digest = sha256(source_summary.encode("utf-8")).hexdigest()
    return f"memory:fake:{digest[:16]}"


def _normalize_for_dedup(content: str) -> str:
    """规范化内容用于去重比较：strip 空白，统一内部空白。"""
    return " ".join(content.strip().split())


def find_duplicate_record(
    content: str,
    memory_type: str,
    scope: MemoryScope | None,
    existing_records: Iterable,
) -> MemoryRecord | None:
    """在所有已有 record 中 deterministic 查重。

    去重依据：
    - 规范化后的 content（去首尾空白、统一内部空白）
    - memory_type 一致
    - scope 一致

    不做 fuzzy matching、不做 embedding similarity。返回第一条匹配到的 record，
    或 None。
    """
    normalized = _normalize_for_dedup(content)
    for record in existing_records:
        if _normalize_for_dedup(record.content) != normalized:
            continue
        if record.memory_type != memory_type:
            continue
        if scope is not None and record.scope != scope:
            continue
        return record
    return None


def find_record_by_content(
    content: str,
    existing_records: Iterable,
) -> MemoryRecord | None:
    """按规范化后的 content 查找 record，用于 forget 等不需要 memory_type/scope 匹配的场景。

    仅做确定性精确匹配，不做 fuzzy matching。
    """
    normalized = _normalize_for_dedup(content)
    for record in existing_records:
        if _normalize_for_dedup(record.content) == normalized:
            return record
    return None


def intent_rejects_store_write(intent: MemoryOperationIntent) -> bool:
    """Store backend 的 rejected fail-closed 边界。

    Governance/confirmation 仍在上游完成；store 不重新解释用户意图。
    这里仅防御不一致的 MemoryOperationIntent：只要 confirmation_status 或
    user_choice 明确表达 rejected，就不允许写正式 record，避免不同 backend
    对 malformed intent 产生不一致副作用。
    """
    return (
        intent.confirmation_status.value in REJECTED_CONFIRMATION_STATUS_VALUES
        or intent.user_choice.value in REJECTING_USER_CHOICE_VALUES
    )


def mutating_intent_allows_store_write(intent: MemoryOperationIntent) -> bool:
    """判断 mutating intent 是否授权写入正式 store。

    允许值仍是 RFC 治理语义中的 T1 approved 与 T2 auto_retained；
    rejected 是 backend fail-closed，不改变 memory governance。
    """
    if intent_rejects_store_write(intent):
        return False
    return intent.confirmation_status.value in WRITING_CONFIRMATION_STATUS_VALUES


class InMemoryMemoryStore:
    """fake/local/test-only store。

    它只把传入的 MemoryRecord 保存在进程内 dict；没有文件 IO、网络、LLM、
    provider、MCP、checkpoint 或 runtime 默认接入。

    B7: namespace 参数提供 per-session 内存隔离。内部 key 前缀为 f"{namespace}:{record.id}"。
    """

    def __init__(self, records: Iterable[MemoryRecord] = (), *, namespace: str = "default") -> None:
        self._records = {f"{namespace}:{record.id}": record for record in records}
        self._namespace = namespace

    def _namespaced_key(self, record_id: str) -> str:
        return f"{self._namespace}:{record_id}"

    def _extract_id(self, namespaced_key: str) -> str:
        prefix = f"{self._namespace}:"
        if namespaced_key.startswith(prefix):
            return namespaced_key[len(prefix):]
        return namespaced_key

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

        if intent_rejects_store_write(intent):
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.REJECTED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="rejected memory intent does not authorize store write",
            )

        # USE_ONCE：仅本次会话使用，写入 store 但不授权长期记忆
        if intent.operation_type is MemoryOperationType.USE_ONCE:
            record = _record_from_intent(intent, audit_id, approval_status="session_only")
            self._records[self._namespaced_key(record.id)] = record
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.APPLIED,
                operation_type=intent.operation_type,
                record=record,
                audit_id=audit_id,
                message="session-only memory record retained",
            )

        # T1 explicit approval 和 T2 auto_retained 均可写入 store。
        # T2 auto_retained 是 governed routing 结果，不需人类确认但需标记 provenance。
        if (
            intent.operation_type in MUTATING_OPERATION_TYPES
            and not mutating_intent_allows_store_write(intent)
        ):
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.REJECTED,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="mutating memory operation requires approved or auto_retained confirmation",
            )

        if intent.operation_type is MemoryOperationType.RETAIN:
            # 去重检查：相同 content + memory_type + scope 不重复写入
            # Metadata Continuity (RFC §14.5): 使用 intent.memory_type，不 fallback
            # B7: 仅在当前 namespace 内去重
            memory_type = intent.memory_type
            existing = find_duplicate_record(
                intent.content_summary, memory_type, intent.scope,
                self.list_records(),
            )
            if existing is not None:
                return MemoryStoreApplyResult(
                    status=MemoryStoreApplyStatus.APPLIED,
                    operation_type=intent.operation_type,
                    record=existing,
                    audit_id=audit_id,
                    message="dedup_hit: 内容已存在，返回已有 record，不重复写入",
                )
            # approval_status 跟随 confirmation_status：
            # T1 → "approved", T2 → "auto_retained", USE_ONCE → "session_only"
            record = _record_from_intent(
                intent, audit_id,
                approval_status=intent.confirmation_status.value,
            )
            self._records[self._namespaced_key(record.id)] = record
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
        return self._records.get(self._namespaced_key(record_id))

    def list_records(self) -> tuple[MemoryRecord, ...]:
        prefix = f"{self._namespace}:"
        return tuple(
            self._records[key]
            for key in sorted(self._records)
            if key.startswith(prefix)
        )

    def remove_record(self, record_id: str) -> bool:
        """按 record_id 移除一条记录（直接操作，不经过 policy 管线）。"""
        ns_key = self._namespaced_key(record_id)
        if ns_key in self._records:
            del self._records[ns_key]
            return True
        return False

    def _apply_update(
        self,
        intent: MemoryOperationIntent,
        audit_id: str,
    ) -> MemoryStoreApplyResult:
        record_id = derive_memory_record_id(intent.source_summary)
        ns_key = self._namespaced_key(record_id)
        existing = self._records.get(ns_key)
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
        self._records[ns_key] = updated
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
        # 按 content 匹配而非 source_summary 派生 ID
        # source_summary 的 identity 不稳定（依赖原始输入措辞）
        # B7: 仅在当前 namespace 内搜索
        target = find_record_by_content(intent.content_summary, self.list_records())
        if target is None:
            return MemoryStoreApplyResult(
                status=MemoryStoreApplyStatus.NOT_FOUND,
                operation_type=intent.operation_type,
                record=None,
                audit_id=audit_id,
                message="memory record not found for forget (按 content 未匹配到任何 record)",
            )
        ns_key = self._namespaced_key(target.id)
        existing = self._records.pop(ns_key, None)
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
    *,
    approval_status: str = "approved",
) -> MemoryRecord:
    """从 MemoryOperationIntent 构造 MemoryRecord。

    Metadata Continuity (RFC §14.5):
    memory_type / source_type / approval_status 由 governance routing 设置，
    store 层原样使用 intent 字段，不 fallback 硬编码值。
    """
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
        memory_type=intent.memory_type,
        source_type=intent.source_type,
        approval_status=approval_status,
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


class FilesystemMemoryStore(InMemoryMemoryStore):
    """基于文件系统的 memory store 骨架。

    D2 测试需要的外部副作用 store backend。与 InMemoryMemoryStore 共享
    同一 apply_operation_intent 逻辑（继承），仅标记为 filesystem backend。
    """

    def __init__(self, base_dir: str) -> None:
        super().__init__()
        self.base_dir = base_dir
