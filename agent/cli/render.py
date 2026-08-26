"""CLI 的唯一事件与结果渲染矩阵。"""

from __future__ import annotations

from collections.abc import Callable

from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalRequest,
    ConversationState,
    EgressClass,
    RecoveryRequest,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
)
from agent.runtime.views import (
    SourceView,
    project_goal_view,
    project_process_leases,
    project_visible_source_views,
)


class TerminalRenderer:
    def __init__(self, write_fn: Callable[[str], None] = print) -> None:
        self._write = write_fn
        self._seen_event_ids: set[str] = set()

    def emit(self, event: RuntimeEvent) -> None:
        if event.event_id in self._seen_event_ids:
            return
        self._seen_event_ids.add(event.event_id)
        message = self._event_message(event)
        if message is not None:
            self._write(message)

    def render_result(self, result: RunResult) -> None:
        message = self._result_message(result)
        if message is not None:
            self._write(terminal_text(message, allow_newlines=True))
        sources = project_goal_view(result.state).sources
        if sources:
            self._write(self._sources_message(sources))
        for warning in result.delivery_warnings:
            self._write(f"Warning: {terminal_text(warning)}")

    def render_pending(self, state: ConversationState) -> None:
        """重启时只读重放 exact durable decision；绝不暴露内部 request identity。"""

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
            self._write(
                self._approval_message(
                    tool_name=request.tool_name or "unknown",
                    risk=request.risk or "unknown",
                    side_effect=request.side_effect or "unknown",
                    preview=request.preview,
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
        payload = event.payload
        if event.kind is RuntimeEventKind.APPROVAL_REQUESTED:
            return TerminalRenderer._approval_message(
                tool_name=payload.get("tool_name", "unknown"),
                risk=payload.get("risk", "unknown"),
                side_effect=payload.get("side_effect", "unknown"),
                preview=payload.get("preview", "unavailable"),
            )
        if event.kind is RuntimeEventKind.RECOVERY_REQUESTED:
            return TerminalRenderer._recovery_message(
                payload.get("summary", "classification required"),
                observation_unknown=payload.get("egress") == "public_network",
            )
        if event.kind is RuntimeEventKind.DISCLOSURE_REQUESTED:
            classes = payload.get("data_classes", [])
            return TerminalRenderer._disclosure_message(
                destination=payload.get("destination", "unknown"),
                model=payload.get("model", "unknown"),
                data_classes=classes,
            )
        if event.kind is RuntimeEventKind.LIMIT_REACHED:
            # RunResult 带 authoritative state，可投影准确 blocker/进展；事件本身不重复刷屏。
            return None
        if event.kind is RuntimeEventKind.WARNING:
            return f"Warning: {terminal_text(payload.get('message', 'runtime warning'))}"
        if event.kind in {
            RuntimeEventKind.MODEL_PROGRESS,
            RuntimeEventKind.TOOL_REQUESTED,
            RuntimeEventKind.TOOL_RESULT,
        }:
            return None
        return None

    @staticmethod
    def _result_message(result: RunResult) -> str | None:
        if result.status is RunStatus.COMPLETED:
            return result.message
        if result.status is RunStatus.AWAITING_APPROVAL:
            return None
        if result.status is RunStatus.AWAITING_RECOVERY:
            return None
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            return None
        if result.status is RunStatus.CANCELLED:
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
        *, tool_name: object, risk: object, side_effect: object, preview: object
    ) -> str:
        return (
            "Approval required\n"
            f"tool: {terminal_text(tool_name)}\n"
            f"risk/effect: {terminal_text(risk)}/{terminal_text(side_effect)}\n"
            f"preview: {terminal_text(preview)}\n"
            "Execute this operation? [y/N]"
        )

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
