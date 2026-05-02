"""Stage 3 Slice 4 的 Memory confirmation UX contract。

本模块只把 :class:`MemoryDecision` 投影成用户可理解的确认问题、选项和结果。
它不写 MemoryStore、不保存 checkpoint、不调用 runtime core loop，也不接 TUI。

为什么单独成模块：
- MemoryPolicy 负责“该不该记住/更新/忘记”的 decision。
- confirmation UX contract 负责“如何让用户确认这个 decision”。
- 后续 MemoryStore / runtime integration 只能消费确认结果，不能把写入副作用塞回这里。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.memory_contracts import (
    MemoryDecision,
    MemoryDecisionType,
    MemorySensitivity,
)


class MemoryConfirmationChoice(StrEnum):
    """用户在 Memory confirmation UX 中可以选择的动作。"""

    ACCEPT = "accept"
    EDIT_AND_ACCEPT = "edit_and_accept"
    REJECT = "reject"
    SESSION_ONLY = "session_only"
    CLARIFY = "clarify"
    OTHER = "other"


class MemoryConfirmationStatus(StrEnum):
    """确认结果状态；它不是 store operation status。"""

    APPROVED = "approved"
    REJECTED = "rejected"
    SESSION_ONLY = "session_only"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass(frozen=True, slots=True)
class MemoryConfirmationOption:
    """展示给用户的单个选择。

    requires_free_text 表示该选择必须携带用户补充文本，例如“编辑后记住”或
    Other/free-text。这里不读取输入 backend，也不解析用户原文。
    """

    choice: MemoryConfirmationChoice
    label: str
    description: str
    requires_free_text: bool = False


@dataclass(frozen=True, slots=True)
class MemoryConfirmationRequest:
    """Memory decision 的用户确认请求视图。

    request 是 UI-agnostic contract：Ask User / TUI 可以展示它，但它本身不
    修改 runtime state，也不创建 pending confirmation。
    """

    decision: MemoryDecision
    question: str
    preview: str
    options: tuple[MemoryConfirmationOption, ...]

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("MemoryConfirmationRequest.question 不能为空")
        if not self.options:
            raise ValueError("MemoryConfirmationRequest.options 不能为空")


@dataclass(frozen=True, slots=True)
class MemoryConfirmationResult:
    """用户对 MemoryConfirmationRequest 的无副作用结果。

    APPROVED 只是说明用户同意这个 memory operation 的语义；真正写入、更新或
    删除必须留给未来 MemoryStore / audit slice。
    """

    request: MemoryConfirmationRequest
    choice: MemoryConfirmationChoice
    status: MemoryConfirmationStatus
    approved_content: str | None = None
    free_text: str | None = None


CONFIRMABLE_DECISIONS = frozenset({
    MemoryDecisionType.RETAIN,
    MemoryDecisionType.UPDATE,
    MemoryDecisionType.FORGET,
})


def build_memory_confirmation_request(
    decision: MemoryDecision,
) -> MemoryConfirmationRequest:
    """把 retain/update/forget decision 转成确认请求。

    这里故意拒绝 no-op/reject/clarify：confirmation contract 不能绕过
    MemoryPolicy 再制造 Ask User 噪音，也不能把 reject 重新包装成可批准写入。
    """

    if decision.decision_type not in CONFIRMABLE_DECISIONS:
        raise ValueError("Only retain/update/forget decisions need confirmation")

    preview = _decision_preview(decision)
    if decision.decision_type is MemoryDecisionType.RETAIN:
        return MemoryConfirmationRequest(
            decision=decision,
            question=f"我可以长期记住这条信息吗？\n{preview}",
            preview=preview,
            options=_retain_options(),
        )
    if decision.decision_type is MemoryDecisionType.UPDATE:
        return MemoryConfirmationRequest(
            decision=decision,
            question=f"要更新这条长期记忆吗？\n{preview}",
            preview=preview,
            options=_update_options(),
        )

    return MemoryConfirmationRequest(
        decision=decision,
        question=f"要忘记这条记忆或描述吗？\n{preview}",
        preview=preview,
        options=_forget_options(),
    )


def resolve_memory_confirmation_choice(
    request: MemoryConfirmationRequest,
    choice: MemoryConfirmationChoice,
    *,
    free_text: str | None = None,
) -> MemoryConfirmationResult:
    """把用户选择解析成 result，不执行 memory operation。

    这个函数只验证 choice 是否属于 request，并把自由文本选择归一化到 result；
    后续真正持久化前仍需要 MemoryStore / audit slice 单独消费。
    """

    option = _find_option(request, choice)
    normalized_free_text = free_text.strip() if free_text is not None else None
    if option.requires_free_text and not normalized_free_text:
        raise ValueError(f"{choice.value} requires free_text")

    if choice is MemoryConfirmationChoice.ACCEPT:
        return MemoryConfirmationResult(
            request=request,
            choice=choice,
            status=MemoryConfirmationStatus.APPROVED,
        )
    if choice is MemoryConfirmationChoice.EDIT_AND_ACCEPT:
        return MemoryConfirmationResult(
            request=request,
            choice=choice,
            status=MemoryConfirmationStatus.APPROVED,
            approved_content=normalized_free_text,
            free_text=normalized_free_text,
        )
    if choice is MemoryConfirmationChoice.SESSION_ONLY:
        return MemoryConfirmationResult(
            request=request,
            choice=choice,
            status=MemoryConfirmationStatus.SESSION_ONLY,
        )
    if choice is MemoryConfirmationChoice.REJECT:
        return MemoryConfirmationResult(
            request=request,
            choice=choice,
            status=MemoryConfirmationStatus.REJECTED,
        )

    return MemoryConfirmationResult(
        request=request,
        choice=choice,
        status=MemoryConfirmationStatus.NEEDS_CLARIFICATION,
        free_text=normalized_free_text,
    )


def _decision_preview(decision: MemoryDecision) -> str:
    candidate = decision.target_candidate
    if candidate is None:
        return "[无候选内容]"
    if candidate.sensitivity in {MemorySensitivity.HIGH, MemorySensitivity.SECRET}:
        content = "[已隐藏敏感内容]"
    else:
        content = candidate.content
    return f"{content}\n来源: {decision.provenance or candidate.id}\n原因: {decision.reason}"


def _retain_options() -> tuple[MemoryConfirmationOption, ...]:
    return (
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.ACCEPT,
            label="记住",
            description="确认你希望以后也使用这条信息。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.EDIT_AND_ACCEPT,
            label="编辑后记住",
            description="先用你的改写文本作为批准内容。",
            requires_free_text=True,
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.SESSION_ONLY,
            label="仅本次使用",
            description="用于当前对话，不授权长期记忆写入。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.REJECT,
            label="不要记住",
            description="拒绝长期记住这条信息。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.OTHER,
            label="Other/free-text",
            description="用自由文本说明你希望怎么处理。",
            requires_free_text=True,
        ),
    )


def _update_options() -> tuple[MemoryConfirmationOption, ...]:
    return (
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.ACCEPT,
            label="更新",
            description="确认你希望以后使用这条更新后的信息。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.EDIT_AND_ACCEPT,
            label="编辑后更新",
            description="先用你的改写文本作为更新内容。",
            requires_free_text=True,
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.REJECT,
            label="不要更新",
            description="保持现有记忆不变。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.OTHER,
            label="Other/free-text",
            description="用自由文本说明更新意图。",
            requires_free_text=True,
        ),
    )


def _forget_options() -> tuple[MemoryConfirmationOption, ...]:
    return (
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.ACCEPT,
            label="确认忘记",
            description="确认你希望以后不再使用这条信息。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.CLARIFY,
            label="换一个描述",
            description="提供更具体的遗忘目标或范围。",
            requires_free_text=True,
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.REJECT,
            label="不要忘记",
            description="取消这次遗忘请求。",
        ),
        MemoryConfirmationOption(
            choice=MemoryConfirmationChoice.OTHER,
            label="Other/free-text",
            description="用自由文本说明遗忘意图。",
            requires_free_text=True,
        ),
    )


def _find_option(
    request: MemoryConfirmationRequest,
    choice: MemoryConfirmationChoice,
) -> MemoryConfirmationOption:
    for option in request.options:
        if option.choice is choice:
            return option
    raise ValueError(f"{choice.value} is not valid for this memory confirmation request")
