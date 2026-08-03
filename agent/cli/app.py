"""把终端输入或 headless typed action 交给同一个 Runtime。"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from agent.cli.actions import build_cancel_goal, build_pause_goal, build_resume_goal
from agent.cli.render import TerminalRenderer
from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    Action,
    ActiveRunStatus,
    ApprovalRequest,
    CancelRun,
    ConversationState,
    GoalStatus,
    RecoveryRequest,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    RunResult,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime
from agent.runtime.ports import CheckpointStore
from agent.runtime.views import GoalView, project_goal_view

_AFFIRMATIVE = frozenset({"y", "yes", "是", "允许"})
_NEGATIVE = frozenset({"n", "no", "否", "不允许"})
_RECOVERY_SUCCEEDED = frozenset({"已成功", "成功", "succeeded", "success"})
_RECOVERY_FAILED = frozenset({"未成功", "失败", "failed", "failure"})
_RECOVERY_STOP = frozenset({"先停止", "停止", "stop"})


def run_headless(
    runtime: AgentRuntime,
    store: CheckpointStore,
    action: Action,
) -> RunResult:
    """无隐式 I/O 地加载一次 snapshot 并执行一个 typed action。"""

    return runtime.run_turn(action, store.load())


def load_headless_view(store: CheckpointStore) -> GoalView:
    """headless/CLI 共用的只读状态投影；load 不会推进产品循环。"""

    return project_goal_view(store.load().state)


def run_repl(
    runtime: AgentRuntime,
    store: CheckpointStore,
    *,
    input_fn: Callable[[str], str] = input,
    write_fn: Callable[[str], None] = print,
    run_id_factory: Callable[[], str] | None = None,
    renderer: TerminalRenderer | None = None,
) -> int:
    make_run_id = run_id_factory or (lambda: str(uuid4()))
    renderer = renderer or TerminalRenderer(write_fn)
    while True:
        try:
            raw = input_fn("> ")
        except (EOFError, KeyboardInterrupt, StopIteration):
            return 0
        if raw == "/exit":
            return 0
        if not raw.strip():
            continue

        snapshot = store.load()
        contextual_exit = _contextual_exit_message(raw, snapshot.state)
        if contextual_exit is not None:
            write_fn(contextual_exit)
            return 0
        action, error = _parse_action(raw, snapshot.state, make_run_id)
        if error is not None:
            write_fn(error)
            continue
        if action is None:
            continue

        result = runtime.run_turn(action, snapshot)
        renderer.render_result(result)
        if result.status is RunStatus.CONFLICT:
            return 2
        if result.status is RunStatus.FAILED_FATAL:
            return 1
        if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
            return 2


def _parse_action(
    raw: str,
    state: ConversationState,
    make_run_id: Callable[[], str],
) -> tuple[Action | None, str | None]:
    common = {
        "conversation_id": state.conversation_id,
        "action_seq": state.next_action_seq,
        "expected_revision": state.revision,
    }
    command, separator, argument = raw.partition(" ")
    normalized = raw.strip().casefold()

    disclosure = state.provider_disclosure_request
    if (
        disclosure is not None
        and state.active_run is not None
        and state.active_run.status is ActiveRunStatus.AWAITING_DISCLOSURE
        and normalized in _AFFIRMATIVE
    ):
        return (
            AcknowledgeProviderDisclosure(
                **common,
                request_digest=disclosure.request_digest,
                acknowledged_at="operator-confirmed",
            ),
            None,
        )

    approval = _approval_request(state)
    if approval is not None and normalized in _AFFIRMATIVE | _NEGATIVE:
        return (
            ResolveApproval(
                **common,
                request_id=approval.request_id,
                binding_digest=approval.binding_digest,
                approved=normalized in _AFFIRMATIVE,
            ),
            None,
        )

    recovery = _recovery_request(state)
    if recovery is not None:
        resolution = None
        if normalized in _RECOVERY_SUCCEEDED:
            resolution = RecoveryResolution.MARK_SUCCEEDED
        elif normalized in _RECOVERY_FAILED:
            resolution = RecoveryResolution.MARK_FAILED
        if resolution is not None:
            return (
                ResolveUnknownToolOutcome(
                    **common,
                    request_id=recovery.request_id,
                    binding_digest=recovery.binding_digest,
                    resolution=resolution,
                ),
                None,
            )
        if not command.startswith("/"):
            return (
                None,
                "The previous operation has an unknown outcome. "
                "Reply with 'success', 'failed', or 'stop'.",
            )

    if command == "/ack-provider":
        request = state.provider_disclosure_request
        if request is None:
            return None, "No provider disclosure is pending."
        if not separator or argument != request.request_digest:
            return None, "Use the exact pending disclosure digest."
        return (
            AcknowledgeProviderDisclosure(
                **common,
                request_digest=request.request_digest,
                acknowledged_at="operator-confirmed",
            ),
            None,
        )

    if command in {"/approve", "/reject"}:
        request = _approval_request(state)
        if request is None:
            return None, "No approval request is pending."
        if not separator or argument != request.request_id:
            return None, "Use the exact pending request ID."
        return (
            ResolveApproval(
                **common,
                request_id=request.request_id,
                binding_digest=request.binding_digest,
                approved=command == "/approve",
            ),
            None,
        )

    if command in {"/resolve-success", "/resolve-failed"}:
        request = _recovery_request(state)
        if request is None:
            return None, "No recovery request is pending."
        if not separator or argument != request.request_id:
            return None, "Use the exact pending request ID."
        return (
            ResolveUnknownToolOutcome(
                **common,
                request_id=request.request_id,
                binding_digest=request.binding_digest,
                resolution=(
                    RecoveryResolution.MARK_SUCCEEDED
                    if command == "/resolve-success"
                    else RecoveryResolution.MARK_FAILED
                ),
            ),
            None,
        )

    if command == "/resume":
        if separator:
            return None, "/resume does not accept arguments."
        if (
            state.goal is not None
            and state.goal.status in {GoalStatus.PAUSED, GoalStatus.BLOCKED}
            and state.active_run is None
        ):
            return build_resume_goal(state), None
        if state.active_run is None:
            return None, "No run is paused."
        return Resume(**common), None

    if command == "/pause":
        if separator:
            return None, "/pause does not accept arguments."
        if state.goal is None:
            return None, "No goal is active."
        return build_pause_goal(state), None

    if command == "/cancel":
        if separator:
            return None, "/cancel does not accept arguments."
        if state.goal is not None and state.goal.status not in {
            GoalStatus.CANCELLED,
            GoalStatus.VERIFIED_DONE,
        }:
            return build_cancel_goal(state), None
        if state.active_run is None:
            return None, "No run is paused."
        return CancelRun(**common), None

    if command.startswith("/"):
        return None, "Unknown command."
    if state.active_run is not None:
        status = state.active_run.status.value
        return None, f"A run is paused ({status}); use its matching reserved command."
    return SubmitMessage(**common, run_id=make_run_id(), message=raw), None


def _approval_request(state: ConversationState) -> ApprovalRequest | None:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.AWAITING_APPROVAL:
        return None
    return active.pending_request if isinstance(active.pending_request, ApprovalRequest) else None


def _recovery_request(state: ConversationState) -> RecoveryRequest | None:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.AWAITING_RECOVERY:
        return None
    return active.pending_request if isinstance(active.pending_request, RecoveryRequest) else None


def _contextual_exit_message(raw: str, state: ConversationState) -> str | None:
    """拒绝 disclosure 或停止 unknown-outcome 时安全退出，且不伪造状态变更。"""

    normalized = raw.strip().casefold()
    active = state.active_run
    if (
        state.provider_disclosure_request is not None
        and active is not None
        and active.status is ActiveRunStatus.AWAITING_DISCLOSURE
        and normalized in _NEGATIVE
    ):
        return "Nothing was sent."
    if _recovery_request(state) is not None and normalized in _RECOVERY_STOP:
        return "Stopped without classifying or retrying the previous operation."
    return None
