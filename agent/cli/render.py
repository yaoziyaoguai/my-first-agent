"""CLI 的唯一事件与结果渲染矩阵。"""

from __future__ import annotations

from collections.abc import Callable

from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalRequest,
    ConversationState,
    RecoveryRequest,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
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
        if (
            active.status is ActiveRunStatus.AWAITING_APPROVAL
            and isinstance(active.pending_request, ApprovalRequest)
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
        if (
            active.status is ActiveRunStatus.AWAITING_RECOVERY
            and isinstance(active.pending_request, RecoveryRequest)
        ):
            self._write(self._recovery_message(active.pending_request.summary))
            return
        if active.status is ActiveRunStatus.PAUSED_LIMIT:
            self._write(self._result_message_for_limit())
        elif active.status is ActiveRunStatus.PAUSED_RETRYABLE:
            self._write(self._result_message_for_retryable())

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
                payload.get("summary", "classification required")
            )
        if event.kind is RuntimeEventKind.DISCLOSURE_REQUESTED:
            classes = payload.get("data_classes", [])
            return TerminalRenderer._disclosure_message(
                destination=payload.get("destination", "unknown"),
                model=payload.get("model", "unknown"),
                data_classes=classes,
            )
        if event.kind is RuntimeEventKind.LIMIT_REACHED:
            return TerminalRenderer._result_message_for_limit()
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
            return TerminalRenderer._result_message_for_limit()
        if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
            return "Conversation capacity reached. Start a new conversation."
        if result.status is RunStatus.FAILED_RETRYABLE:
            return TerminalRenderer._result_message_for_retryable()
        if result.status is RunStatus.FAILED_FATAL:
            return f"Run failed: {result.error_code or 'fatal_error'}"
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
    def _recovery_message(summary: object) -> str:
        return (
            f"Unknown tool outcome: {terminal_text(summary)}\n"
            "Reply with 'success', 'failed', or 'stop'."
        )

    @staticmethod
    def _disclosure_message(
        *, destination: object, model: object, data_classes: object
    ) -> str:
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
    def _result_message_for_retryable() -> str:
        return "The provider failed transiently. Run /resume to retry or /cancel."


def terminal_text(value: object, *, allow_newlines: bool = False) -> str:
    text = str(value)
    return "".join(
        character
        if character.isprintable() or (allow_newlines and character == "\n")
        else f"\\u{ord(character):04x}"
        for character in text
    )
