"""Stage 3 Slice 5 的 memory operation intent / audit summary contract。

本模块只把已确认的 Memory confirmation result 转成“下一步想做什么”的意图和
安全审计摘要。它不写 MemoryStore、不真实 update/forget、不读取历史会话、
不调用 policy/prompt_builder/runtime/checkpoint。

设计边界：
- operation intent 不是 store mutation，只是后续 store slice 的输入候选。
- audit summary 不是敏感全文日志，只记录选择、来源摘要和安全摘要。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationResult,
    MemoryConfirmationStatus,
)
from agent.memory_contracts import MemoryDecisionType, MemoryScope, MemorySensitivity


class MemoryOperationType(StrEnum):
    """Memory operation 意图词表；不代表已经执行。"""

    RETAIN = "retain_intent"
    UPDATE = "update_intent"
    FORGET = "forget_intent"
    REJECT = "reject_intent"
    USE_ONCE = "use_once_intent"
    CLARIFY = "clarify_intent"
    NO_OP = "no_op_intent"


@dataclass(frozen=True, slots=True)
class MemoryOperationIntent:
    """已确认 memory decision 的无副作用操作意图。

    intent 可以表达 retain/update/forget/reject/use_once/clarify，但它没有
    record_id、write/save/delete/persist 等真实存储能力。
    """

    operation_type: MemoryOperationType
    decision_type: MemoryDecisionType
    confirmation_status: MemoryConfirmationStatus
    user_choice: MemoryConfirmationChoice
    content_summary: str
    source_summary: str
    scope: MemoryScope | None
    safety_summary: str
    sensitive_redacted: bool
    user_visible_summary: str

    def __post_init__(self) -> None:
        if not self.content_summary.strip():
            raise ValueError("MemoryOperationIntent.content_summary 不能为空")
        if not self.source_summary.strip():
            raise ValueError("MemoryOperationIntent.source_summary 不能为空")
        if not self.safety_summary.strip():
            raise ValueError("MemoryOperationIntent.safety_summary 不能为空")
        if not self.user_visible_summary.strip():
            raise ValueError("MemoryOperationIntent.user_visible_summary 不能为空")


@dataclass(frozen=True, slots=True)
class MemoryAuditSummary:
    """安全审计摘要，不包含敏感全文。

    audit summary 只说明“用户确认了什么类型的意图、来源是什么、安全上如何处理”。
    它不是日志写入器，也不会读取 agent_log/sessions/runs。
    """

    operation_type: MemoryOperationType
    decision_type: MemoryDecisionType
    source_summary: str
    user_choice: str
    safety_summary: str
    sensitive_redacted: bool
    user_visible_summary: str


def build_memory_operation_intent(
    confirmation: MemoryConfirmationResult,
) -> MemoryOperationIntent:
    """从 confirmation result 生成 operation intent，不执行操作。"""

    decision = confirmation.request.decision
    operation_type = _operation_type_for(confirmation)
    sensitive_redacted = _is_sensitive(decision)
    content_summary = _content_summary(confirmation, sensitive_redacted)
    source_summary = _source_summary(confirmation)
    scope = _scope(confirmation)
    safety_summary = _safety_summary(confirmation, sensitive_redacted)

    return MemoryOperationIntent(
        operation_type=operation_type,
        decision_type=decision.decision_type,
        confirmation_status=confirmation.status,
        user_choice=confirmation.choice,
        content_summary=content_summary,
        source_summary=source_summary,
        scope=scope,
        safety_summary=safety_summary,
        sensitive_redacted=sensitive_redacted,
        user_visible_summary=_user_visible_summary(operation_type),
    )


def build_memory_audit_summary(intent: MemoryOperationIntent) -> MemoryAuditSummary:
    """把 operation intent 投影成安全 audit summary。

    这里不写日志文件，只返回可测试的摘要对象；后续如果接 audit sink，必须继续
    遵守“不记录敏感全文”的约束。
    """

    return MemoryAuditSummary(
        operation_type=intent.operation_type,
        decision_type=intent.decision_type,
        source_summary=intent.source_summary,
        user_choice=intent.user_choice.value,
        safety_summary=intent.safety_summary,
        sensitive_redacted=intent.sensitive_redacted,
        user_visible_summary=intent.user_visible_summary,
    )


def _operation_type_for(
    confirmation: MemoryConfirmationResult,
) -> MemoryOperationType:
    if confirmation.status is MemoryConfirmationStatus.REJECTED:
        return MemoryOperationType.REJECT
    if confirmation.status is MemoryConfirmationStatus.SESSION_ONLY:
        return MemoryOperationType.USE_ONCE
    if confirmation.status is MemoryConfirmationStatus.NEEDS_CLARIFICATION:
        return MemoryOperationType.CLARIFY

    decision_type = confirmation.request.decision.decision_type
    if decision_type is MemoryDecisionType.RETAIN:
        return MemoryOperationType.RETAIN
    if decision_type is MemoryDecisionType.UPDATE:
        return MemoryOperationType.UPDATE
    if decision_type is MemoryDecisionType.FORGET:
        return MemoryOperationType.FORGET
    return MemoryOperationType.NO_OP


def _content_summary(
    confirmation: MemoryConfirmationResult,
    sensitive_redacted: bool,
) -> str:
    if confirmation.status is MemoryConfirmationStatus.REJECTED:
        return "[用户拒绝长期记忆操作]"
    if confirmation.status is MemoryConfirmationStatus.SESSION_ONLY:
        return "[仅本次使用，不授权长期记忆]"
    if confirmation.status is MemoryConfirmationStatus.NEEDS_CLARIFICATION:
        return confirmation.free_text or "[需要用户补充说明]"
    if sensitive_redacted:
        return "[已隐藏敏感内容]"
    if confirmation.approved_content:
        return confirmation.approved_content

    candidate = confirmation.request.decision.target_candidate
    if candidate is None:
        return "[无候选内容]"
    return candidate.content


def _source_summary(confirmation: MemoryConfirmationResult) -> str:
    decision = confirmation.request.decision
    candidate = decision.target_candidate
    return decision.provenance or (candidate.id if candidate is not None else "unknown")


def _scope(confirmation: MemoryConfirmationResult) -> MemoryScope | None:
    """把候选 scope 带到 operation intent，供后续 fake store 记录来源范围。

    Stage 4 的 store 只能消费 OperationIntent，不能回头读取 MemoryDecision /
    ConfirmationRequest；因此 scope 必须在 Slice 5 的无副作用意图中显式携带。
    这只是元数据传递，不执行 store IO，也不改变 confirmation/runtime 语义。
    """

    candidate = confirmation.request.decision.target_candidate
    return candidate.scope if candidate is not None else None


def _safety_summary(
    confirmation: MemoryConfirmationResult,
    sensitive_redacted: bool,
) -> str:
    if confirmation.status is MemoryConfirmationStatus.SESSION_ONLY:
        return "仅本次使用；不授权长期记忆"
    if confirmation.status is MemoryConfirmationStatus.REJECTED:
        return "用户拒绝；不产生写入、更新或删除意图"

    flags = confirmation.request.decision.safety_flags
    if flags:
        return ",".join(flags)
    if sensitive_redacted:
        return "sensitive"
    return "无额外安全标记"


def _is_sensitive(decision) -> bool:
    candidate = decision.target_candidate
    return (
        candidate is not None
        and candidate.sensitivity in {MemorySensitivity.HIGH, MemorySensitivity.SECRET}
    )


def _user_visible_summary(operation_type: MemoryOperationType) -> str:
    if operation_type is MemoryOperationType.RETAIN:
        return "已形成“长期记住”的操作意图，但尚未写入长期记忆。"
    if operation_type is MemoryOperationType.UPDATE:
        return "已形成“更新记忆”的操作意图，但尚未更新任何长期记忆。"
    if operation_type is MemoryOperationType.FORGET:
        return "已形成“忘记”的操作意图，但尚未删除任何长期记忆。"
    if operation_type is MemoryOperationType.USE_ONCE:
        return "这条信息只用于当前对话，不会长期记住。"
    if operation_type is MemoryOperationType.REJECT:
        return "用户拒绝了这次长期记忆操作。"
    if operation_type is MemoryOperationType.CLARIFY:
        return "需要用户补充说明后再决定如何处理。"
    return "没有形成长期记忆操作意图。"
