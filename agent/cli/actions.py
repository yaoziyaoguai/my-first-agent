"""Shared pure typed-action builder。

CLI 与 TUI 共用这套构造器：只按 authoritative ``ConversationState``（conversation_id、
next_action_seq、revision）+ 用户 intent 构造 typed action。legality 仍由 shared reducer
（``agent.runtime.state``）在 ``run_turn`` 时裁决；这里不复制状态机，也不做 UI-only mutation。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from agent.runtime.contracts import (
    TERMINAL_GOAL_STATUSES,
    AcknowledgeProviderDisclosure,
    CancelBrowserTakeover,
    CancelGoal,
    CancelRun,
    CompleteBrowserTakeover,
    ConversationState,
    GoalStatus,
    GrantProviderConsent,
    GrantProviderWorkspaceReadConsent,
    PauseGoal,
    ProviderDisclosureRequestV2,
    RecoverUnknownObservation,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    RevokeGoalTargetAuthority,
    RevokeProcessAuthority,
    RevokeProviderConsent,
    SubmitMessage,
)
from agent.runtime.provider_consent import workspace_read_classes_covered

# /new(r19 小步 2)请求装配层重建 conversation 的 REPL 退出码。
# 选择 79(NR_UNRESOLVABLE 之外的未占用私人区段)只是进程内信令,不是 errno 声明。
NEW_SESSION_REQUESTED = 79
# /switch(Oracle gap2 #1,2026-10-26)请求装配层重开会话选择器的 REPL 退出码;
# 与 79 同一私人区段,只作进程内信令。
SWITCH_SESSION_REQUESTED = 78


def new_session_gate(state: ConversationState) -> str | None:
    """/new 的共享合法性判断(CLI 与 TUI 同一语义)。

    返回 None 允许显式开始新任务;返回拒绝原因字符串时不得切换。
    - active run(pending approval / takeover / EXECUTING / unknown effect)必须先处置;
    - 活跃(非终态、非暂停)Goal 必须先显式 park(/pause)或完成/取消——/new 不清空、
      不重开旧 Goal;PAUSED Goal 已在持久安全边界(leases 已撤销),允许离开;
    - Goal 终态、PAUSED 或无 Goal 时允许;旧 checkpoint 与 evidence 由装配层原样保留。
    """
    active = state.active_run
    if active is not None:
        return "Resolve the pending run or recovery state before starting a new task."
    goal = state.goal
    if (
        goal is not None
        and goal.status not in TERMINAL_GOAL_STATUSES
        and goal.status is not GoalStatus.PAUSED
    ):
        return (
            "The current goal is still active; pause it with /pause to park it, or "
            "finish or cancel it before /new."
        )
    return None


def switch_session_gate(state: ConversationState) -> str | None:
    """/switch 的合法性判断(当前为 CLI 命令;TUI 采纳时共享同一判断)。

    切换只在持久安全边界发生:active run(pending approval / takeover /
    EXECUTING / unknown effect)必须先处置。Goal 任意状态都允许——切换不清空、
    不重开、不转移任何 Goal 的 pending 决策与授权,conversation 原样保留为
    startup 候选;回切后由各自 conversation 的既有命令(/resume-goal 等)继续。
    """
    active = state.active_run
    if active is not None:
        return "Resolve the pending run or recovery state before switching tasks."
    return None


def build_complete_browser_takeover(
    state: ConversationState,
) -> CompleteBrowserTakeover:
    pending = state.browser_takeover_pending
    if pending is None:
        raise ValueError("a pending browser takeover is required")
    return CompleteBrowserTakeover(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=pending.request_id,
        session_ref=pending.session_ref,
        expected_profile_revision=pending.profile_revision,
    )


def build_cancel_browser_takeover(
    state: ConversationState,
) -> CancelBrowserTakeover:
    pending = state.browser_takeover_pending
    if pending is None:
        raise ValueError("a pending browser takeover is required")
    return CancelBrowserTakeover(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_id=pending.request_id,
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


def build_grant_provider_consent(
    state: ConversationState,
) -> GrantProviderConsent:
    """把当前屏幕上的 v2 request 翻译为范围许可；reducer 仍独立重验。

    CLI 只做可见性判断，不自行扩大 allowed set；action 绑定同一 snapshot 的
    request/scope digest，输入期间的 CAS 漂移由 Runtime fail closed。
    """

    request = state.provider_disclosure_request
    if not isinstance(request, ProviderDisclosureRequestV2):
        raise ValueError("The pending disclosure has no reusable routine scope option.")
    if not request.grant_eligible:
        raise ValueError(
            "A reusable routine scope is unavailable for this request because it "
            "contains a new or unverified source. Answer y to approve this pending "
            "content once."
        )
    if state.provider_disclosure_receipt is not None:
        raise ValueError("The pending disclosure was already acknowledged.")
    return GrantProviderConsent(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=request.request_digest,
        scope_digest=request.scope_digest,
    )


def build_grant_provider_workspace_read_consent(
    state: ConversationState,
) -> GrantProviderWorkspaceReadConsent:
    """把当前 v2 request 铸成含工作区读/命令输出的范围许可；reducer 独立重验。

    r 与 s 同一 CAS 形状；准入只看 request 自身类别（非常规部分全部为
    proof-backed 可复用来源：workspace_excerpt / command_output），CLI 不
    自行扩大 allowed set。
    """

    request = state.provider_disclosure_request
    if not isinstance(request, ProviderDisclosureRequestV2):
        raise ValueError("The pending disclosure has no workspace-read scope option.")
    if request.grant_eligible:
        raise ValueError(
            "This request is already covered by the routine scope; answer s for "
            "routine-only or y to approve this pending content once."
        )
    if not workspace_read_classes_covered(request.data_classes, request.sources):
        raise ValueError(
            "A workspace-read scope is unavailable for this request because it "
            "includes a source beyond verified workspace reads and approved "
            "command output; answer y to approve this pending content once."
        )
    if state.provider_disclosure_receipt is not None:
        raise ValueError("The pending disclosure was already acknowledged.")
    return GrantProviderWorkspaceReadConsent(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=request.request_digest,
        scope_digest=request.scope_digest,
    )


def build_revoke_provider_consent(
    state: ConversationState,
) -> RevokeProviderConsent:
    if state.provider_consent_grant is None:
        raise ValueError("No provider consent is active.")
    return RevokeProviderConsent(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
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
    defer_artifact_confirmation: bool = False,
    authorize_goal_target: bool = False,
    authorize_goal_directory: bool = False,
    authorize_obligation_rebind: bool = False,
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
        defer_artifact_confirmation=defer_artifact_confirmation,
        authorize_goal_target=authorize_goal_target,
        authorize_goal_directory=authorize_goal_directory,
        authorize_obligation_rebind=authorize_obligation_rebind,
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
            "Use /approve-artifact <64-lowercase-hex-sha256> <workspace-relative-path>."
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


def build_revoke_goal_target_authority(
    state: ConversationState,
) -> RevokeGoalTargetAuthority:
    if not state.goal_authorizations:
        raise ValueError("no active goal target authorization to revoke")
    return RevokeGoalTargetAuthority(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )
