"""TUI 渲染：literal safe-display 与 authoritative projection matrix。

所有外部可控文本统一 literal rendering（Textual/Rich 用 ``markup=False``），不解析
markup/link；ANSI、C0/C1 与 Unicode bidi control 以可见且无歧义的 escape 表示。
escape 后的完整 preview 超过 cap 时，调用方必须在 effect 前拒绝（不截断、不隐藏）。
projection 由 authoritative state/RunResult 驱动；events 只作 advisory。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.runtime.contracts import (
    ActiveRunStatus,
    ContinuationPhase,
    ConversationState,
    RunResult,
    RunStatus,
)
from agent.runtime.views import GoalView, project_goal_view

if TYPE_CHECKING:
    from agent.runtime.contracts import ApprovalRequest, RecoveryRequest

# Unicode bidi / format controls that must always render as visible escapes.
_BIDI_CONTROLS = frozenset(
    [0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x061C]
)
_KEEP_CONTROL = frozenset({0x0A, 0x09, 0x0D})  # \n \t \r 保留为布局


class SafeDisplayTooLargeError(RuntimeError):
    """escape 后的完整文本超过 cap；调用方必须在 effect 前拒绝，不能截断。"""


def safe_display(text: str, *, cap: int | None = None) -> str:
    out: list[str] = []
    for char in text:
        cp = ord(char)
        if cp in _BIDI_CONTROLS:
            out.append(_visible(cp))
        elif cp < 0x20:
            if cp in _KEEP_CONTROL:
                out.append(char)
            else:
                out.append(_visible(cp))
        elif 0x7F <= cp <= 0x9F:
            out.append(_visible(cp))
        else:
            out.append(char)
    escaped = "".join(out)
    if cap is not None and len(escaped) > cap:
        raise SafeDisplayTooLargeError("escaped preview exceeds the display cap")
    return escaped


def _visible(cp: int) -> str:
    return f"<U+{cp:04X}>"


@dataclass(frozen=True, slots=True)
class TuiProjection:
    main_text: str
    form_kind: str | None  # approval | recovery | None
    # submit | approve | reject | mark_succeeded | mark_failed | resume | cancel
    actions: tuple[str, ...]
    focus: str
    terminal_message: str | None
    # approval/recovery 表单的真实 pending-request 字段（label, value）；events 不参与。
    form_fields: tuple[tuple[str, str], ...] = ()
    goal: GoalView | None = None


def project(state: ConversationState, result: RunResult | None = None) -> TuiProjection:
    active = state.active_run
    goal_view = project_goal_view(state)
    if active is None:
        terminal = None
        if state.last_safe_result is not None:
            terminal = state.last_safe_result.message
        elif result is not None and result.message is not None:
            terminal = result.message
        actions = goal_view.legal_actions if goal_view.goal_id is not None else ("submit",)
        return TuiProjection(
            main_text=terminal or "ready",
            form_kind=None,
            actions=actions,
            focus="input" if "submit" in actions or "correct_goal" in actions else "goal",
            terminal_message=terminal,
            goal=goal_view,
        )
    if active.status is ActiveRunStatus.AWAITING_APPROVAL:
        return TuiProjection(
            main_text="awaiting approval",
            form_kind="approval",
            actions=("approve", "reject"),
            focus="approval",
            terminal_message=None,
            form_fields=_approval_fields(active.pending_request),
            goal=goal_view,
        )
    if active.status is ActiveRunStatus.AWAITING_RECOVERY:
        return TuiProjection(
            main_text="awaiting recovery",
            form_kind="recovery",
            actions=("mark_succeeded", "mark_failed"),
            focus="recovery",
            terminal_message=None,
            form_fields=_recovery_fields(active.pending_request),
            goal=goal_view,
        )
    if active.status is ActiveRunStatus.AWAITING_DISCLOSURE:
        request = state.provider_disclosure_request
        fields = ()
        if request is not None:
            fields = (
                ("destination", request.canonical_destination),
                ("model", request.model),
                ("data", ", ".join(request.data_classes)),
                ("binding", request.request_digest),
            )
        return TuiProjection(
            main_text="remote provider disclosure required",
            form_kind="disclosure",
            actions=("ack_provider",),
            focus="disclosure",
            terminal_message=None,
            form_fields=fields,
            goal=goal_view,
        )
    if active.phase is ContinuationPhase.EXECUTING:
        # 重开 EXECUTING checkpoint：工具 effect 可能已发生（unknown），只能 Resume
        # 重新进入工具发现真实结果；Cancel 会绕过未知 effect，故不提供。
        return TuiProjection(
            main_text="interrupted unknown effect",
            form_kind=None,
            actions=("resume",),
            focus="resume",
            terminal_message=None,
            goal=goal_view,
        )
    # PAUSED_LIMIT / PAUSED_RETRYABLE / RUNNABLE（MODEL/TOOL phase）：worker 已返回的 paused 状态。
    return TuiProjection(
        main_text=_status_label(active.status),
        form_kind=None,
        actions=("resume", "cancel"),
        focus="resume",
        terminal_message=None,
        goal=goal_view,
    )


def _approval_fields(req: ApprovalRequest | None) -> tuple[tuple[str, str], ...]:
    """ApprovalRequest 的真实字段；不伪造 ApprovalRequest 没有的字段。"""
    if req is None:
        return ()
    fields: list[tuple[str, str]] = [("request", req.request_id)]
    if req.tool_name:
        fields.append(("tool", req.tool_name))
    fields.append(("preview", req.preview))
    fields.append(("risk", req.risk if req.risk else "unknown"))
    fields.append(("side effect", req.side_effect if req.side_effect else "unknown"))
    fields.append(("binding", req.binding_digest))
    return tuple(fields)


def _recovery_fields(req: RecoveryRequest | None) -> tuple[tuple[str, str], ...]:
    """RecoveryRequest 当前合同只有 request/tool/binding/summary；只展示这些真实字段。"""
    if req is None:
        return ()
    return (
        ("request", req.request_id),
        ("tool", req.tool_call_id),
        ("summary", req.summary),
        ("binding", req.binding_digest),
    )


def _status_label(status: ActiveRunStatus) -> str:
    return {
        ActiveRunStatus.PAUSED_LIMIT: "limit reached",
        ActiveRunStatus.PAUSED_RETRYABLE: "retryable failure",
        ActiveRunStatus.RUNNABLE: "paused",
    }.get(status, status.value)


def run_status_label(status: RunStatus) -> str:
    return {
        RunStatus.COMPLETED: "completed",
        RunStatus.AWAITING_APPROVAL: "needs approval",
        RunStatus.AWAITING_RECOVERY: "needs recovery",
        RunStatus.AWAITING_DISCLOSURE: "needs provider disclosure",
        RunStatus.LIMIT_REACHED: "limit reached",
        RunStatus.CONVERSATION_LIMIT_REACHED: "conversation limit reached",
        RunStatus.FAILED_RETRYABLE: "retryable failure",
        RunStatus.FAILED_FATAL: "fatal failure",
        RunStatus.CONFLICT: "conflict; reload",
        RunStatus.CANCELLED: "cancelled",
    }.get(status, status.value)
