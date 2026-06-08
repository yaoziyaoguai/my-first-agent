"""Memory v0 evidence visibility across built-in log surfaces."""

from __future__ import annotations

import json

FORBIDDEN_VALUES = (
    "RAW MEMORY TEXT SHOULD NOT LOG",
    "RAW USER PROMPT SHOULD NOT LOG",
    "RAW ASSISTANT PROMPT SHOULD NOT LOG",
    "RAW TOOL RESULT SHOULD NOT LOG",
    "RAW FILE CONTENT SHOULD NOT LOG",
    "RAW CHILD PAYLOAD SHOULD NOT LOG",
    "/Users/jinkun.wang/work_space/my-first-agent/private.txt",
    "memory:fake:raw-record-id",
    "memory:fake:raw-memory-id",
    "sk-test-secret-1234567890",
)


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def test_u2c_record_memory_evidence_writes_safe_events_jsonl(tmp_path) -> None:
    from agent.event_log import EventLogWriter
    from agent.evidence_recorder import record_memory_evidence

    writer = EventLogWriter(tmp_path / "session")
    envelope = record_memory_evidence(
        event_type="memory.recall.completed",
        operation="recall",
        phase="end",
        status="success",
        source_type="explicit_user",
        decision="allowed",
        count=1,
        memory_id="memory:fake:raw-memory-id",
        record_id="memory:fake:raw-record-id",
        raw_fields={
            "content": "RAW MEMORY TEXT SHOULD NOT LOG",
            "user_prompt": "RAW USER PROMPT SHOULD NOT LOG",
            "assistant_prompt": "RAW ASSISTANT PROMPT SHOULD NOT LOG",
            "tool_result": "RAW TOOL RESULT SHOULD NOT LOG",
            "file_content": "RAW FILE CONTENT SHOULD NOT LOG",
            "value_preview": "RAW CHILD PAYLOAD SHOULD NOT LOG",
            "path": "/Users/jinkun.wang/work_space/my-first-agent/private.txt",
            "api_key": "sk-test-secret-1234567890",
        },
        event_log_writer=writer,
    )
    writer.close()

    event_text = (tmp_path / "session" / "events.jsonl").read_text(encoding="utf-8")
    assert "memory.recall.completed" in event_text
    assert "memory_id_hash" in event_text
    assert "record_id_hash" in event_text
    assert "raw_memory" not in event_text.lower()
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in event_text
        assert forbidden not in _serialized(envelope)


def test_u2c_dispatcher_action_log_and_flush_keep_memory_evidence_safe(tmp_path) -> None:
    from agent.event_log import EventLogWriter
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.schema import RuntimeActionRequest
    from tests.runtime_integration.test_memory_recall_l3 import (
        _approved_record,
        _make_store_with_records,
    )

    store = _make_store_with_records(
        _approved_record("memory:fake:raw-record-id", "RAW MEMORY TEXT SHOULD NOT LOG"),
    )
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_RECALL, MemoryRecallHandler(store=store))
    dispatcher = RuntimeActionDispatcher(registry=registry)
    dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_RECALL,
        source="test",
        parent_trace_id="",
        payload={},
    ))

    action_log_text = str(dispatcher.action_log)
    assert "memory.recall.completed" in action_log_text
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in action_log_text

    writer = EventLogWriter(tmp_path / "session")
    assert dispatcher.flush_to_event_log(writer) == 1
    writer.close()
    event_text = (tmp_path / "session" / "events.jsonl").read_text(encoding="utf-8")
    assert "memory.recall.completed" in event_text
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in event_text


def test_u2c_log_viewer_summary_displays_memory_counts_without_raw_content() -> None:
    from agent.log_viewer import render_session_summary

    entries = [
        {
            "event": "evidence.recorded",
            "session_id": "s-memory",
            "timestamp": "2026-06-08T00:00:00Z",
            "data": {
                "subsystem": "memory",
                "operation": "recall.completed",
                "phase": "end",
                "status": "success",
                "safe_summary": "memory.recall.completed operation=recall decision=allowed count=2",
                "metadata": {
                    "event_type": "memory.recall.completed",
                    "operation": "recall",
                    "decision": "allowed",
                    "count": 2,
                    "record_id_hash": "memid:abc123",
                },
            },
        },
        {
            "event": "evidence.recorded",
            "session_id": "s-memory",
            "timestamp": "2026-06-08T00:00:01Z",
            "data": {
                "subsystem": "memory",
                "operation": "deleted",
                "phase": "end",
                "status": "success",
                "safe_summary": "memory.deleted operation=delete decision=allowed",
                "metadata": {
                    "event_type": "memory.deleted",
                    "operation": "delete",
                    "decision": "allowed",
                    "record_id_hash": "memid:def456",
                },
            },
        },
    ]

    rendered = render_session_summary("s-memory", entries)

    assert "Memory" in rendered
    assert "recall completed : 1" in rendered
    assert "deleted          : 1" in rendered
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in rendered
    assert "memid:abc123" not in rendered
    assert "memid:def456" not in rendered


def test_tool_result_summary_redacts_raw_filesystem_path() -> None:
    from agent.evidence_recorder import record_tool_result_summary

    raw_path = "/Users/jinkun.wang/work_space/my-first-agent/private.txt"
    envelope = record_tool_result_summary(
        tool_name="read_file",
        path=raw_path,
        content="RAW TOOL RESULT SHOULD NOT LOG",
        status="blocked",
        reason_code="sensitive_path",
    )

    serialized = _serialized(envelope)
    assert raw_path not in serialized
    assert "private.txt" not in serialized
    assert "path_hash" in serialized
    assert "path_kind" in serialized
    assert envelope["metadata"]["redacted"] is True


def test_tool_runtime_mediator_path_evidence_uses_hashes_not_raw_path(
    tmp_path,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    import agent.tools  # noqa: F401 - ensure tool registry is populated
    from agent.event_log import EventLogWriter
    from agent.log_viewer import render_session_summary
    from agent.runtime_integration import (
        ActionHandlerRegistry,
        RuntimeActionDispatcher,
        RuntimeActionType,
    )
    from agent.runtime_integration.tool_gate import ToolGateHandler
    from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    class DispatcherSpy:
        def __init__(self, real):
            self._real = real
            self.requests = []

        @property
        def action_log(self):
            return self._real.action_log

        def route_from_runtime_loop(self, request, **kwargs):
            self.requests.append(request)
            return self._real.route_from_runtime_loop(request, **kwargs)

        def flush_to_event_log(self, writer):
            return self._real.flush_to_event_log(writer)

    monkeypatch.setattr(
        "agent.checkpoint.save_checkpoint",
        lambda *_args, **_kwargs: None,
    )
    raw_path = "/Users/jinkun.wang/work_space/my-first-agent/private.txt"
    state = SimpleNamespace(
        task=SimpleNamespace(
            status="running",
            pending_user_input_request=None,
            pending_tool=None,
            tool_execution_log={},
            current_step_index=0,
            current_plan=None,
            tool_call_count=0,
            loop_iterations=0,
            consecutive_end_turn_without_progress=0,
        ),
        conversation=SimpleNamespace(messages=[]),
        memory=SimpleNamespace(session_id="path-redaction-test"),
    )
    turn_state = SimpleNamespace(
        on_runtime_event=lambda _event: None,
        on_display_event=lambda _event: None,
        round_tool_traces=[],
    )
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    dispatcher = DispatcherSpy(RuntimeActionDispatcher(registry=registry))
    mediator = ToolRuntimeMediator(
        dispatcher,
        state=state,
        turn_state=turn_state,
        turn_context={},
        messages=[],
    )
    block = SimpleNamespace(
        type="tool_use",
        id="toolu_path_redaction",
        name="mark_step_complete",
        input={
            "completion_score": 100,
            "summary": "path redaction test",
            "outstanding": "none",
            "path": raw_path,
        },
    )

    mediator.mediate(block)

    tool_result_payloads = [
        request.payload for request in dispatcher.requests
        if request.action_type == RuntimeActionType.TOOL_RESULT
    ]
    assert tool_result_payloads
    request_text = _serialized(tool_result_payloads)
    assert raw_path not in request_text
    assert "private.txt" not in request_text
    assert '"tool_input"' not in request_text
    assert "path_hash" in request_text
    assert "path_kind" in request_text

    action_log_text = _serialized(dispatcher.action_log)
    assert raw_path not in action_log_text
    assert "private.txt" not in action_log_text
    assert "path_hash" in action_log_text
    assert "path_kind" in action_log_text
    assert "redacted" in action_log_text

    writer = EventLogWriter(tmp_path / "session")
    dispatcher.flush_to_event_log(writer)
    writer.close()
    event_text = (tmp_path / "session" / "events.jsonl").read_text(encoding="utf-8")
    assert raw_path not in event_text
    assert "private.txt" not in event_text
    assert "path_hash" in event_text
    assert "path_kind" in event_text

    events = [json.loads(line) for line in event_text.splitlines()]
    rendered = render_session_summary("path-redaction-test", events)
    assert raw_path not in rendered
    assert "private.txt" not in rendered
