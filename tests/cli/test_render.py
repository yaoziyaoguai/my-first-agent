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


def test_renderer_deduplicates_events_and_hides_internal_approval_identity() -> None:
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
    assert "approval-full-id" not in rendered
    assert "call-1" not in rendered
    assert "/approve" not in rendered and "/reject" not in rendered
    assert "[y/N]" in rendered


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


def test_limit_result_names_the_exact_recovery_action() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.render_result(
        RunResult(RunStatus.LIMIT_REACHED, ConversationState.new("conversation-1"))
    )

    assert output == [
        "Task paused at a safe execution limit. Run /resume to continue or /cancel."
    ]


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


def test_default_renderer_hides_model_and_tool_progress_noise() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)

    renderer.emit(_event(RuntimeEventKind.MODEL_PROGRESS, event_id="model-progress"))
    renderer.emit(
        _event(
            RuntimeEventKind.TOOL_REQUESTED,
            event_id="tool-requested",
            payload={"tool_name": "list_files"},
        )
    )
    renderer.emit(
        _event(
            RuntimeEventKind.TOOL_RESULT,
            event_id="tool-result",
            payload={"tool_call_id": "internal-call-id"},
        )
    )

    assert output == []


def test_disclosure_and_recovery_are_contextual_without_protocol_ids() -> None:
    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    renderer.emit(
        _event(
            RuntimeEventKind.DISCLOSURE_REQUESTED,
            event_id="disclosure",
            payload={
                "request_digest": "internal-disclosure-digest",
                "destination": "https://provider.example/v1",
                "model": "daily-model",
                "data_classes": ["user_message"],
            },
        )
    )
    renderer.emit(
        _event(
            RuntimeEventKind.RECOVERY_REQUESTED,
            event_id="recovery",
            payload={
                "request_id": "internal-recovery-id",
                "summary": "the previous write may have completed",
            },
        )
    )

    rendered = "\n".join(output)
    assert "https://provider.example/v1" in rendered
    assert "daily-model" in rendered
    assert "[y/N]" in rendered
    assert "success" in rendered and "failed" in rendered and "stop" in rendered
    assert "internal-disclosure-digest" not in rendered
    assert "internal-recovery-id" not in rendered
    assert "/ack-provider" not in rendered
