"""ToolRuntimeMediator child evidence redaction guardrails."""

from __future__ import annotations

from types import SimpleNamespace

from agent.runtime_integration.schema import RuntimeActionType
from agent.tool_runtime_mediator import ToolRuntimeMediator

RAW_ARGUMENT = "/tmp/raw-child-secret-path.txt"
RAW_SUMMARY = "RAW_CHILD_OUTPUT_SHOULD_NOT_ENTER_EVIDENCE"


class _Dispatcher:
    def __init__(self) -> None:
        self.requests = []

    def route_from_runtime_loop(self, request, **_kwargs):
        self.requests.append(request)
        return SimpleNamespace(status="not_supported", payload={}, evidence={})


def _mediator(dispatcher: _Dispatcher) -> ToolRuntimeMediator:
    return ToolRuntimeMediator(
        dispatcher,
        state=SimpleNamespace(task=SimpleNamespace(tool_execution_log={})),
        turn_state=SimpleNamespace(on_runtime_event=lambda _event: None),
        turn_context={},
        messages=[],
    )


def test_child_tool_request_evidence_redacts_arguments_and_path() -> None:
    dispatcher = _Dispatcher()
    mediator = _mediator(dispatcher)

    mediator._dispatch_child_tool_evidence(
        "read_file",
        {"path": RAW_ARGUMENT, "query": "raw query"},
        "delegation-1",
        "parent-1",
        gate_disposition="allowed",
    )

    payload = dispatcher.requests[-1].payload
    assert dispatcher.requests[-1].action_type == RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST
    assert "arguments_preview" not in payload
    assert RAW_ARGUMENT not in str(payload)
    assert "raw query" not in str(payload)
    assert "delegation-1" not in str(payload)
    assert payload["arguments_hash"].startswith("childargs:")
    assert payload["argument_key_count"] == 2
    assert payload["delegation_id_hash"].startswith("childdelegation:")
    assert payload["delegation_id_length"] == len("delegation-1")
    assert payload["path_hash"].startswith("path:")
    assert payload["path_kind"] in {"tmp", "absolute"}
    assert payload["redacted"] is True


def test_child_result_evidence_redacts_summary() -> None:
    dispatcher = _Dispatcher()
    mediator = _mediator(dispatcher)

    mediator._dispatch_child_result_evidence(
        delegation_id="delegation-1",
        parent_trace_id="parent-1",
        subagent_name="child",
        status="ok",
        stop_reason="end_turn",
        summary=RAW_SUMMARY,
        iterations_used=1,
    )

    payload = dispatcher.requests[-1].payload
    assert dispatcher.requests[-1].action_type == RuntimeActionType.SUBAGENT_CHILD_RESULT
    assert "summary_preview" not in payload
    assert RAW_SUMMARY not in str(payload)
    assert payload["summary_hash"].startswith("childsummary:")
    assert payload["summary_length"] == len(RAW_SUMMARY)
    assert payload["redacted"] is True
