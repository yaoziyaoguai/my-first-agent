"""CLI 的唯一事件与结果渲染矩阵。"""

from __future__ import annotations

import threading
from collections.abc import Callable

from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalRequest,
    ConversationState,
    EgressClass,
    GoalStatus,
    RecoveryRequest,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
)
from agent.runtime.views import (
    SourceView,
    delivery_summary_message,
    project_goal_view,
    project_process_leases,
    project_visible_source_views,
    verification_scope_message,
)


class TerminalRenderer:
    """CLI 的唯一事件与结果渲染矩阵。

    S1-C（2026-10-09）：progress heartbeat 来自 provider-progress 线程，与
    delta/权威结果并发到达；对去重表、流式身份与一次输出使用窄锁，避免乱序
    覆盖。锁内不调用 Runtime/provider。
    """

    def __init__(
        self,
        write_fn: Callable[[str], None] = print,
        *,
        delta_write_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._write = write_fn
        self._delta_write = delta_write_fn
        self._seen_event_ids: set[str] = set()
        # r19 小步 3:已流式呈现的回答文本;与最终权威 message 完全一致时
        # 不再重复打印(显示可由权威结果校正,而不是双份输出)。
        self._streamed_answer = ""
        self._stream_identity: tuple[str, str | None, int, str] | None = None
        self._terminal_hints: set[tuple[str, int, str]] = set()
        # S1-C：progress 线程与 REPL 主线程并发的窄锁。
        self._lock = threading.Lock()

    def emit(self, event: RuntimeEvent) -> None:
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return
            self._seen_event_ids.add(event.event_id)
            if event.kind is RuntimeEventKind.MODEL_TEXT_DELTA:
                text = str(event.payload.get("text", ""))
                if not text:
                    return
                stream_identity = (
                    event.conversation_id,
                    event.run_id,
                    event.revision,
                    event.causation_id,
                )
                if stream_identity != self._stream_identity:
                    self._stream_identity = stream_identity
                    self._streamed_answer = ""
                self._streamed_answer += text
                display_text = terminal_text(text, allow_newlines=True)
                if self._delta_write is not None:
                    self._delta_write(display_text)
                else:
                    self._write(display_text)
                return
            message = self._event_message(event)
            if message is not None:
                self._write(message)

    def render_result(self, result: RunResult) -> None:
        with self._lock:
            self._render_result_locked(result)

    def _render_result_locked(self, result: RunResult) -> None:
        message = self._result_message(result)
        # Renderer 由整个 REPL 复用，但流式原文只属于刚结束的这次 run_turn。
        # 先完成本轮权威结果比较，再清空，避免下一轮回答与旧文本拼接。
        self._streamed_answer = ""
        self._stream_identity = None
        if message is not None:
            self._write(terminal_text(message, allow_newlines=True))
        goal_view = project_goal_view(result.state)
        if goal_view.status == GoalStatus.VERIFIED_DONE.value:
            self._write(
                terminal_text(
                    delivery_summary_message(goal_view),
                    allow_newlines=True,
                )
            )
        sources = goal_view.sources
        if sources:
            self._write(self._sources_message(sources))
        if (
            goal_view.status == GoalStatus.VERIFIED_DONE.value
            and goal_view.verification_scope
        ):
            self._write(
                terminal_text(
                    self._verification_scope_message(goal_view.verification_scope),
                    allow_newlines=True,
                )
            )
        if (
            goal_view.goal_id is not None
            and goal_view.goal_revision is not None
            and goal_view.status
            in {GoalStatus.VERIFIED_DONE.value, GoalStatus.CANCELLED.value}
        ):
            terminal_key = (
                goal_view.goal_id,
                goal_view.goal_revision,
                goal_view.status,
            )
            if terminal_key not in self._terminal_hints:
                self._terminal_hints.add(terminal_key)
                self._write(
                    "Task is closed. Use /new to start another task in this workspace."
                )
        for warning in result.delivery_warnings:
            self._write(f"Warning: {terminal_text(warning)}")

    def render_pending(self, state: ConversationState) -> None:
        """每次输入前从 authoritative state 只读投影 exact durable decision；
        不暴露内部 request identity。
        """

        active = state.active_run
        if active is None:
            return
        if (
            active.status is ActiveRunStatus.AWAITING_DISCLOSURE
            and state.provider_disclosure_request is not None
        ):
            request = state.provider_disclosure_request
            self._write(
                self._disclosure_message(
                    destination=request.canonical_destination,
                    model=request.model,
                    data_classes=request.data_classes,
                )
            )
            return
        if active.status is ActiveRunStatus.AWAITING_APPROVAL and isinstance(
            active.pending_request, ApprovalRequest
        ):
            request = active.pending_request
            requirement = request.artifact_confirmation_requirement
            self._write(
                self._approval_message(
                    tool_name=request.tool_name or "unknown",
                    risk=request.risk or "unknown",
                    side_effect=request.side_effect or "unknown",
                    preview=request.preview,
                    artifact_path=(
                        requirement.artifact_path if requirement is not None else None
                    ),
                )
            )
            return
        if active.status is ActiveRunStatus.AWAITING_RECOVERY and isinstance(
            active.pending_request, RecoveryRequest
        ):
            self._write(
                self._recovery_message(
                    active.pending_request.summary,
                    observation_unknown=(
                        active.executing_intent is not None
                        and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
                    ),
                )
            )
            return
        if active.status is ActiveRunStatus.PAUSED_LIMIT:
            self._write(self._result_message_for_limit())
        elif active.status is ActiveRunStatus.PAUSED_RETRYABLE:
            self._write(self._result_message_for_retryable())

    def render_working(self) -> None:
        """在同步 Runtime 调用前确认输入已接收，不猜测内部阶段或进度。"""

        self._write("Working...")

    @staticmethod
    def _verification_scope_message(scopes: tuple[str, ...]) -> str:
        return verification_scope_message(scopes)

    def render_sources(self, state: ConversationState, *, advanced: bool = False) -> None:
        sources = project_visible_source_views(state, advanced=advanced)
        if not sources:
            self._write("No sources recorded for the current answer or task.")
            return
        self._write(self._sources_message(sources, advanced=advanced))

    def render_leases(self, state: ConversationState, *, advanced: bool = False) -> None:
        """F5/R11：active process authority lease 的 readable 摘要（默认隐藏 digest）。"""

        leases = project_process_leases(state, advanced=advanced)
        if not leases:
            self._write("No active process lease.")
            return
        lines = ["Active process leases:"]
        for index, lease in enumerate(leases):
            lines.append(
                f"[{index}] {lease.readable_command} · profile={lease.resource_profile} "
                f"· uses left={lease.remaining_uses} "
                f"· expires={lease.expires_at}"
                + (f" · id={lease.lease_id} · digest={lease.lease_digest}" if advanced else "")
            )
        lines.append("Revoke with /revoke <lease_id> or /revoke all (ids via --advanced).")
        self._write("\n".join(lines))

    @staticmethod
    def _event_message(event: RuntimeEvent) -> str | None:
        # pending 类事件只是 advisory：可操作提示的唯一权威是每次输入前由
        # authoritative state snapshot 渲染的 render_pending，避免双权威与
        # event 丢失/延迟/重排影响正确提示。warning/informational 仍保留。
        payload = event.payload
        if event.kind in {
            RuntimeEventKind.APPROVAL_REQUESTED,
            RuntimeEventKind.RECOVERY_REQUESTED,
            RuntimeEventKind.DISCLOSURE_REQUESTED,
        }:
            return None
        if event.kind is RuntimeEventKind.LIMIT_REACHED:
            # RunResult 带 authoritative state，可投影准确 blocker/进展；事件本身不重复刷屏。
            return None
        if event.kind is RuntimeEventKind.WARNING:
            return f"Warning: {terminal_text(payload.get('message', 'runtime warning'))}"
        if (
            event.kind is RuntimeEventKind.MODEL_PROGRESS
            and payload.get("phase") == "provider_waiting"
        ):
            elapsed = payload.get("elapsed_seconds", 0)
            return f"Model is still working ({terminal_text(elapsed)}s elapsed)..."
        if event.kind in {
            RuntimeEventKind.MODEL_PROGRESS,
            RuntimeEventKind.TOOL_REQUESTED,
            RuntimeEventKind.TOOL_RESULT,
        }:
            return None
        return None

    def _result_message(self, result: RunResult) -> str | None:
        if result.status is RunStatus.COMPLETED:
            if result.message and result.message == self._streamed_answer:
                # 流式已逐字呈现同一文本;不重复打印(权威校正留给不一致时)。
                return None
            return result.message
        if result.status is RunStatus.AWAITING_APPROVAL:
            return None
        if result.status is RunStatus.AWAITING_RECOVERY:
            return None
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            return None
        if result.status is RunStatus.CANCELLED:
            if result.error_code == "approval_declined" and result.message:
                return terminal_text(result.message, allow_newlines=True)
            return "Run cancelled."
        if result.status is RunStatus.LIMIT_REACHED:
            if result.error_code == "no_progress":
                view = project_goal_view(result.state)
                lines = ["Task paused because the same next step repeated with no new evidence."]
                if view.user_outcome:
                    lines.append(f"Goal remains incomplete: {terminal_text(view.user_outcome)}")
                if view.progress_summary:
                    lines.append(f"Last verified progress: {view.progress_summary}")
                lines.append(
                    "No authority was granted implicitly; any required operation still "
                    "needs its normal approval before it can run."
                )
                lines.append("Run /resume to try a new approach or /cancel.")
                return "\n".join(lines)
            return TerminalRenderer._result_message_for_limit()
        if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
            return "Conversation capacity reached. Start a new conversation."
        if result.status is RunStatus.FAILED_RETRYABLE:
            return TerminalRenderer._result_message_for_retryable(result.error_code)
        if result.status is RunStatus.FAILED_FATAL:
            if result.error_code == "provider_auth_error":
                return (
                    "Provider authentication failed. Check the configured credential "
                    "and run first-agent again."
                )
            if result.error_code in {"invalid_provider_response", "provider_protocol_error"}:
                return (
                    "The provider response was incompatible. Check the configured model "
                    "and endpoint, then run first-agent again."
                )
            base = f"Run failed: {result.error_code or 'fatal_error'}"
            if result.message:
                # 016 真实 E3(第 19/24 轮 J8):runtime_failure 的异常细节只在
                # RunResult.message 里;只打 error_code 会丢失定诊证据(REPL 以
                # 退出码 1 结束且无 traceback)。摘要压平空白并截断;凭据按设计
                # 从不进入异常消息,E3 的 secret-free 扫描仍是兜底。
                summary = " ".join(result.message.split())[:240]
                return f"{base} ({summary})"
            return base
        if result.status is RunStatus.CONFLICT:
            return "State conflict: restart or reload this CLI before continuing."
        return None

    @staticmethod
    def _approval_message(
        *,
        tool_name: object,
        risk: object,
        side_effect: object,
        preview: object,
        artifact_path: str | None = None,
    ) -> str:
        lines = [
            "Approval required",
            f"tool: {terminal_text(tool_name)}",
            f"risk/effect: {terminal_text(risk)}/{terminal_text(side_effect)}",
            f"preview: {terminal_text(preview, allow_newlines=True)}",
        ]
        if artifact_path is None:
            lines.append("Execute this operation? [y/N]")
        else:
            lines.append(
                f"This command may generate {terminal_text(artifact_path)}. "
                "Approve generation now? [y/N] The generated file is not confirmed yet; "
                "First Agent must show its current content for a separate confirmation."
            )
        return "\n".join(lines)

    @staticmethod
    def _recovery_message(
        summary: object,
        *,
        observation_unknown: bool = False,
    ) -> str:
        if observation_unknown:
            return (
                f"Unknown public observation: {terminal_text(summary)}\n"
                "Reply with 'continue' to record no evidence and proceed, or 'stop'. "
                "The request will not retry automatically."
            )
        return (
            f"Unknown tool outcome: {terminal_text(summary)}\n"
            "Reply with 'success', 'failed', or 'stop'."
        )

    @staticmethod
    def _disclosure_message(*, destination: object, model: object, data_classes: object) -> str:
        data_summary = (
            ", ".join(str(item) for item in data_classes)
            if isinstance(data_classes, (list, tuple))
            else data_classes
        )
        return (
            "Remote provider disclosure required\n"
            f"destination: {terminal_text(destination)}\n"
            f"model: {terminal_text(model)}\n"
            f"data: {terminal_text(data_summary)}\n"
            "Allow this information to be sent? [y/N]"
        )

    @staticmethod
    def _result_message_for_limit() -> str:
        return "Task paused at a safe execution limit. Run /resume to continue or /cancel."

    @staticmethod
    def _result_message_for_retryable(error_code: str | None = None) -> str:
        if error_code == "provider_timeout":
            return "The provider timed out. Run /resume to retry or /cancel."
        if error_code == "provider_transport":
            return "The provider could not be reached. Run /resume to retry or /cancel."
        if error_code == "provider_rate_limit":
            return "The provider rate limit was reached. Run /resume later or /cancel."
        if error_code == "provider_unavailable":
            return "The provider is temporarily unavailable. Run /resume later or /cancel."
        return "The provider failed transiently. Run /resume to retry or /cancel."

    @staticmethod
    def _sources_message(sources: tuple[SourceView, ...], *, advanced: bool = False) -> str:
        lines = ["Sources:"]
        for source in sources:
            detail = (
                f"{source.source_kind} · {source.title} · {source.locator} · "
                f"{source.observed_at} · {source.status}"
            )
            if source.failure_code is not None:
                detail = f"{detail} ({source.failure_code})"
            if advanced and source.source_ref is not None:
                detail = f"{detail} · {source.source_ref}"
            lines.append(f"- {terminal_text(detail)}")
        return "\n".join(lines)


def terminal_text(value: object, *, allow_newlines: bool = False) -> str:
    text = str(value)
    return "".join(
        character
        if character.isprintable() or (allow_newlines and character == "\n")
        else f"\\u{ord(character):04x}"
        for character in text
    )
