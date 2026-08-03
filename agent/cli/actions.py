"""Shared pure typed-action builder。

CLI 与 TUI 共用这套构造器：只按 authoritative ``ConversationState``（conversation_id、
next_action_seq、revision）+ 用户 intent 构造 typed action。legality 仍由 shared reducer
（``agent.runtime.state``）在 ``run_turn`` 时裁决；这里不复制状态机，也不做 UI-only mutation。
"""

from __future__ import annotations

from collections.abc import Callable

from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    CancelGoal,
    CancelRun,
    ConversationState,
    PauseGoal,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    SubmitMessage,
)


def build_ack_provider(
    state: ConversationState,
    *,
    acknowledged_at: str,
) -> AcknowledgeProviderDisclosure:
    request = state.provider_disclosure_request
    if request is None:
        raise ValueError("a pending provider disclosure is required")
    return AcknowledgeProviderDisclosure(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=request.request_digest,
        acknowledged_at=acknowledged_at,
    )


def build_submit(state: ConversationState, *, message: str, run_id: str) -> SubmitMessage:
    if not message.strip():
        raise ValueError("message must not be empty")
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message=message,
    )


def build_resolve_approval(
    state: ConversationState,
    *,
    request_id: str,
    binding_digest: str,
    approved: bool,
) -> ResolveApproval:
    return ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request_id,
        binding_digest=binding_digest,
        approved=approved,
    )


def build_resolve_recovery(
    state: ConversationState,
    *,
    request_id: str,
    binding_digest: str,
    resolution: RecoveryResolution,
) -> ResolveUnknownToolOutcome:
    return ResolveUnknownToolOutcome(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request_id,
        binding_digest=binding_digest,
        resolution=resolution,
    )


def build_resume(state: ConversationState) -> Resume:
    return Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )


def build_cancel(state: ConversationState) -> CancelRun:
    return CancelRun(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )


def build_pause_goal(state: ConversationState) -> PauseGoal:
    goal = state.goal
    if goal is None:
        raise ValueError("an active goal is required")
    return PauseGoal(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
    )


def build_resume_goal(state: ConversationState) -> ResumeGoal:
    goal = state.goal
    if goal is None:
        raise ValueError("an active goal is required")
    return ResumeGoal(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
    )


def build_cancel_goal(state: ConversationState) -> CancelGoal:
    goal = state.goal
    if goal is None:
        raise ValueError("an active goal is required")
    return CancelGoal(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
    )


def run_id_factory(prefix: str = "run") -> Callable[[], str]:
    from uuid import uuid4

    def factory() -> str:
        return f"{prefix}-{uuid4()}"

    return factory
