from __future__ import annotations

from agent.cli.render import TerminalRenderer
from agent.runtime.contracts import (
    ConversationState,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
)


def _event(kind: RuntimeEventKind, *, event_id: str = "event-1", payload=None):
    return RuntimeEvent(
        event_id=event_id,
        kind=kind,
        conversation_id="conversation-1",
        run_id="run-1",
        revision=3,
        causation_id="action:1",
        payload=payload or {},
    )


def test_renderer_deduplicates_events_and_events_own_approval_view() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    event = _event(
        RuntimeEventKind.APPROVAL_REQUESTED,
        payload={
            "request_id": "approval-full-id",
            "tool_call_id": "call-1",
            "tool_name": "write_file",
            "preview": "write note.txt (5 bytes)",
            "risk": "high",
            "side_effect": "write",
        },
    )

    renderer.emit(event)
    renderer.emit(event)

    rendered = "\n".join(output)
    assert output and len(output) == 1
    assert "write_file" in rendered
    assert "write note.txt" in rendered
    assert "high" in rendered
    assert "approval-full-id" in rendered
    assert "/reject" in rendered


def test_run_result_owns_final_text_and_terminal_status() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    state = ConversationState.new("conversation-1")

    renderer.emit(_event(RuntimeEventKind.COMPLETED))
    renderer.render_result(
        RunResult(RunStatus.COMPLETED, state, run_id="run-1", message="final answer")
    )

    assert output == ["final answer"]


def test_conflict_and_retryable_results_give_operator_guidance() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    state = ConversationState.new("conversation-1")

    renderer.render_result(RunResult(RunStatus.CONFLICT, state, error_code="revision"))
    renderer.render_result(RunResult(RunStatus.FAILED_RETRYABLE, state))

    assert "restart" in output[0].lower() or "reload" in output[0].lower()
    assert "/resume" in output[1]


def test_renderer_escapes_terminal_control_characters_in_event_fields() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    renderer.emit(
        _event(
            RuntimeEventKind.APPROVAL_REQUESTED,
            event_id="event-unsafe",
            payload={
                "request_id": "request-1",
                "tool_name": "write_file",
                "risk": "high",
                "side_effect": "write",
                "preview": "write note\n\x1b[2J.txt",
            },
        )
    )

    assert len(output) == 1
    assert "\x1b" not in output[0]
    assert "\\u000a" in output[0]
    assert "\\u001b" in output[0]
