"""Shared pure typed-action builder。

CLI 与 TUI 共用这套构造器：只按 authoritative ``ConversationState``（conversation_id、
next_action_seq、revision）+ 用户 intent 构造 typed action。legality 仍由 shared reducer
（``agent.runtime.state``）在 ``run_turn`` 时裁决；这里不复制状态机，也不做 UI-only mutation。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    CancelGoal,
    CancelRun,
    ConversationState,
    PauseGoal,
    RecoverUnknownObservation,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    RevokeProcessAuthority,
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
    approved_at: str | None = None,
    confirmed_artifact_path: str | None = None,
    confirmed_artifact_sha256: str | None = None,
) -> ResolveApproval:
    return ResolveApproval(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=request_id,
        binding_digest=binding_digest,
        approved=approved,
        approved_at=approved_at,
        confirmed_artifact_path=confirmed_artifact_path,
        confirmed_artifact_sha256=confirmed_artifact_sha256,
    )


def utc_now_rfc3339() -> str:
    """返回 adapter 写入 typed action 的带时区批准时刻。"""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_artifact_confirmation(argument: str) -> tuple[str, str]:
    """解析 ``<sha256> <workspace-relative-path>``，不使用 shell 语义。"""

    sha256, separator, path = argument.strip().partition(" ")
    path = path.strip()
    if (
        not separator
        or len(sha256) != 64
        or any(character not in "0123456789abcdef" for character in sha256)
        or not path
        or path.startswith("/")
        or "\x00" in path
        or ".." in path.split("/")
    ):
        raise ValueError(
            "Use /approve-artifact <64-lowercase-hex-sha256> "
            "<workspace-relative-path>."
        )
    return path, sha256


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


def build_recover_unknown_observation(
    state: ConversationState,
) -> RecoverUnknownObservation:
    active = state.active_run
    intent = active.executing_intent if active is not None else None
    if intent is None:
        raise ValueError("a persisted executing intent is required")
    return RecoverUnknownObservation(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        tool_call_id=intent.tool_call_id,
        intent_digest=intent.intent_digest,
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


def build_revoke_process_authority(
    state: ConversationState,
    *,
    lease_id: str | None,
) -> RevokeProcessAuthority:
    """F5/R11：把用户 revoke intent 翻译为 RevokeProcessAuthority typed action。

    ``lease_id=None`` 撤销全部；非 None 时必须是当前 active lease 的精确 id（typed
    反馈，不静默）；无 active lease 时拒绝。CAS（expected_revision）由共享构造保证。
    """

    if not state.process_leases:
        raise ValueError("no active process lease to revoke")
    if lease_id is not None and not any(
        lease.lease_id == lease_id for lease in state.process_leases
    ):
        raise ValueError(f"unknown process lease: {lease_id}")
    return RevokeProcessAuthority(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        lease_id=lease_id,
    )
