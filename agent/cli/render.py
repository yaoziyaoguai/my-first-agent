"""CLI 的唯一事件与结果渲染矩阵。"""

from __future__ import annotations

from collections.abc import Callable

from agent.runtime.contracts import RunResult, RunStatus, RuntimeEvent, RuntimeEventKind


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
            self._write(_terminal_text(message, allow_newlines=True))
        for warning in result.delivery_warnings:
            self._write(f"Warning: {_terminal_text(warning)}")

    @staticmethod
    def _event_message(event: RuntimeEvent) -> str | None:
        payload = event.payload
        if event.kind is RuntimeEventKind.APPROVAL_REQUESTED:
            request_id = _terminal_text(payload.get("request_id", ""))
            return (
                "Approval required\n"
                f"tool: {_terminal_text(payload.get('tool_name', 'unknown'))}\n"
                f"risk/effect: {_terminal_text(payload.get('risk', 'unknown'))}/"
                f"{_terminal_text(payload.get('side_effect', 'unknown'))}\n"
                f"preview: {_terminal_text(payload.get('preview', 'unavailable'))}\n"
                f"request: {request_id} (short: {request_id[:12]})\n"
                f"Use /approve {request_id} or /reject {request_id}; rejection executes nothing."
            )
        if event.kind is RuntimeEventKind.RECOVERY_REQUESTED:
            request_id = _terminal_text(payload.get("request_id", ""))
            return (
                "Unknown tool outcome: "
                f"{_terminal_text(payload.get('summary', 'classification required'))}\n"
                f"Use /resolve-success {request_id} or /resolve-failed {request_id}."
            )
        if event.kind is RuntimeEventKind.DISCLOSURE_REQUESTED:
            digest = _terminal_text(payload.get("request_digest", ""))
            classes = payload.get("data_classes", [])
            data_summary = ", ".join(classes) if isinstance(classes, list) else classes
            return (
                "Remote provider disclosure required\n"
                f"destination: {_terminal_text(payload.get('destination', 'unknown'))}\n"
                f"model: {_terminal_text(payload.get('model', 'unknown'))}\n"
                f"data: {_terminal_text(data_summary)}\n"
                f"Use /ack-provider {digest} to acknowledge this exact request."
            )
        if event.kind is RuntimeEventKind.LIMIT_REACHED:
            return "Invocation limit reached; use /resume when the run remains resumable."
        if event.kind is RuntimeEventKind.WARNING:
            return f"Warning: {_terminal_text(payload.get('message', 'runtime warning'))}"
        if event.kind is RuntimeEventKind.MODEL_PROGRESS:
            return "Model request in progress."
        if event.kind is RuntimeEventKind.TOOL_REQUESTED:
            return f"Tool requested: {_terminal_text(payload.get('tool_name', 'unknown'))}"
        if event.kind is RuntimeEventKind.TOOL_RESULT:
            return f"Tool result recorded: {_terminal_text(payload.get('tool_call_id', 'unknown'))}"
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
            return "Run paused at an invocation limit. Use /resume or /cancel."
        if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
            return "Conversation capacity reached. Start a new conversation."
        if result.status is RunStatus.FAILED_RETRYABLE:
            return "Provider failed transiently. Use /resume or /cancel."
        if result.status is RunStatus.FAILED_FATAL:
            return f"Run failed: {result.error_code or 'fatal_error'}"
        if result.status is RunStatus.CONFLICT:
            return "State conflict: restart or reload this CLI before continuing."
        return None


def _terminal_text(value: object, *, allow_newlines: bool = False) -> str:
    text = str(value)
    return "".join(
        character
        if character.isprintable() or (allow_newlines and character == "\n")
        else f"\\u{ord(character):04x}"
        for character in text
    )
