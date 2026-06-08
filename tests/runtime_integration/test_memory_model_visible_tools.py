"""Memory v0 model-visible request-only tool tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_contracts import MemoryDecisionType, MemoryScope
from agent.memory_operations import (
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_runtime import MemoryRuntime
from agent.memory_store import InMemoryMemoryStore
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.memory_forget import MemoryForgetHandler
from agent.runtime_integration.memory_retain import MemoryRetainHandler
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
from agent.tool_executor import AWAITING_USER
from agent.tool_runtime_mediator import ToolRuntimeMediator

RAW_MEMORY_TEXT = "RAW MEMORY TEXT SHOULD NOT LOG"
RAW_RECORD_ID = "memory:fake:raw-record-id"


class _ToolUseBlock:
    def __init__(self, *, name: str, input: dict[str, Any], id: str = "toolu_memory") -> None:
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = id


class _DispatcherSpy:
    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self.requests: list[Any] = []

    @property
    def action_log(self):
        return self._real.action_log

    def route(self, request):
        self.requests.append(request)
        return self._real.route(request)

    def route_from_runtime_loop(self, request, **kwargs):
        self.requests.append(request)
        return self._real.route_from_runtime_loop(request, **kwargs)

    def flush_to_event_log(self, writer):
        return self._real.flush_to_event_log(writer)


def _patch_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent.checkpoint.save_checkpoint",
        lambda *_args, **_kwargs: None,
    )


def _state() -> Any:
    return SimpleNamespace(
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
        memory=SimpleNamespace(session_id="memory-tools-test"),
    )


def _confirmation_context(*, state: Any, runtime: MemoryRuntime, dispatcher: Any) -> Any:
    from agent.confirm_handlers import ConfirmationContext

    return ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_runtime_event=lambda _event: None),
        client=None,
        model_name="test-model",
        continue_fn=lambda _turn_state: "continued",
        memory_runtime=runtime,
        dispatcher=dispatcher,
    )


def _dispatcher(runtime: MemoryRuntime) -> RuntimeActionDispatcher:
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    registry.register(RuntimeActionType.MEMORY_PROPOSE, MemoryRetainHandler(store=runtime._store))
    registry.register(RuntimeActionType.MEMORY_FORGET, MemoryForgetHandler(memory_runtime=runtime))
    return RuntimeActionDispatcher(registry=registry)


def _mediator(
    *,
    dispatcher: RuntimeActionDispatcher,
    state: Any,
    runtime: MemoryRuntime,
    messages: list[dict[str, Any]],
) -> ToolRuntimeMediator:
    return ToolRuntimeMediator(
        dispatcher,
        state=state,
        turn_state=SimpleNamespace(on_runtime_event=lambda _event: None),
        turn_context={},
        messages=messages,
        memory_runtime=runtime,
    )


def _add_memory(store: InMemoryMemoryStore, content: str, *, source: str = "test") -> str:
    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary=content,
        source_summary=source,
        scope=MemoryScope.USER,
        safety_summary="no_safety_concern",
        sensitive_redacted=False,
        user_visible_summary=content[:80],
    )
    result = store.apply_operation_intent(intent, build_memory_audit_summary(intent))
    assert result.record is not None
    return result.record.id


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _tool_result_request_payloads(dispatcher: _DispatcherSpy) -> list[Any]:
    return [
        request.payload for request in dispatcher.requests
        if request.action_type == RuntimeActionType.TOOL_RESULT
    ]


def test_memory_request_tools_are_model_visible_and_no_commit_tool() -> None:
    import agent.tools  # noqa: F401
    from agent.tool_registry import get_model_visible_tools

    visible_names = {tool["name"] for tool in get_model_visible_tools()}

    assert "MEMORY_REMEMBER_REQUEST" in visible_names
    assert "MEMORY_LIST" in visible_names
    assert "MEMORY_FORGET_REQUEST" in visible_names
    assert "MEMORY_COMMIT" not in visible_names


def test_memory_remember_request_waits_for_user_confirmation_then_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)
    state = _state()
    messages: list[dict[str, Any]] = []
    dispatcher = _dispatcher(runtime)
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_REMEMBER_REQUEST",
            input={"content": "I prefer concise Chinese replies"},
            id="toolu_remember",
        )
    )

    assert result == AWAITING_USER
    assert state.task.pending_user_input_request["awaiting_kind"] == "memory_confirmation"
    assert store.list_records() == ()
    action_types = [str(event.action_type) for event in dispatcher.action_log]
    assert "tool.gate" in action_types
    assert "tool.result" in action_types

    from agent.confirm_handlers import handle_user_input_step

    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)
    reply = handle_user_input_step("1", ctx)

    assert "已记住" in reply
    records = store.list_records()
    assert len(records) == 1
    assert records[0].content == "I prefer concise Chinese replies"


def test_memory_remember_request_rejection_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _dispatcher(runtime)
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_REMEMBER_REQUEST",
            input={"content": "Do not persist until approved"},
            id="toolu_reject",
        )
    )

    from agent.confirm_handlers import handle_user_input_step

    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)
    reply = handle_user_input_step("4", ctx)

    assert "已拒绝" in reply
    assert store.list_records() == ()


def test_memory_list_excludes_working_summary() -> None:
    store = InMemoryMemoryStore()
    _add_memory(store, "Visible explicit memory", source="explicit")
    runtime = MemoryRuntime(store=store)
    state = _state()
    state.memory.working_summary = "HIDDEN WORKING SUMMARY SHOULD NOT LIST"
    dispatcher = _dispatcher(runtime)
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    result = mediator.mediate(
        _ToolUseBlock(name="MEMORY_LIST", input={}, id="toolu_list")
    )

    assert result is None
    serialized_messages = str(messages)
    assert "Visible explicit memory" in serialized_messages
    assert "HIDDEN WORKING SUMMARY SHOULD NOT LIST" not in serialized_messages


def test_memory_list_tool_result_evidence_redacts_raw_memory_and_ids(tmp_path) -> None:
    from agent.event_log import EventLogWriter
    from agent.log_viewer import render_session_summary

    store = InMemoryMemoryStore()
    record_id = _add_memory(store, RAW_MEMORY_TEXT, source=RAW_RECORD_ID)
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _dispatcher(runtime)
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    result = mediator.mediate(
        _ToolUseBlock(name="MEMORY_LIST", input={}, id="toolu_list_safe")
    )

    assert result is None
    serialized_messages = _serialized(messages)
    assert RAW_MEMORY_TEXT in serialized_messages
    assert record_id[:8] in serialized_messages

    tool_result_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_RESULT
    ]
    assert tool_result_events
    evidence = dict(tool_result_events[-1].evidence)
    assert evidence["memory_tool_result_redacted"] is True
    assert evidence["operation"] == "list"
    assert evidence["count"] == 1
    assert evidence["redacted"] is True
    assert evidence["source_type"] == "model_visible_tool"
    assert evidence["record_id_hashes"]
    assert evidence["memory_id_hashes"]

    action_log_text = _serialized(dispatcher.action_log)
    assert RAW_MEMORY_TEXT not in action_log_text
    assert record_id not in action_log_text
    assert RAW_RECORD_ID not in action_log_text
    assert record_id[:8] not in action_log_text

    writer = EventLogWriter(tmp_path / "session")
    assert dispatcher.flush_to_event_log(writer) >= 1
    writer.close()
    event_text = (tmp_path / "session" / "events.jsonl").read_text(encoding="utf-8")
    assert "memory_tool_result_redacted" in event_text
    assert "record_id_hashes" in event_text
    assert RAW_MEMORY_TEXT not in event_text
    assert record_id not in event_text
    assert RAW_RECORD_ID not in event_text
    assert record_id[:8] not in event_text

    events = [json.loads(line) for line in event_text.splitlines()]
    rendered = render_session_summary("memory-list-safe", events)
    assert RAW_MEMORY_TEXT not in rendered
    assert record_id not in rendered
    assert RAW_RECORD_ID not in rendered


def test_memory_list_tool_result_redacts_raw_query_and_path_input(tmp_path) -> None:
    """MEMORY_LIST 即使收到多余 raw input，也只能在 TOOL_RESULT 中留下 hash metadata。"""
    from agent.event_log import EventLogWriter

    raw_path = "/Users/jinkun.wang/work_space/my-first-agent/private-memory.txt"
    store = InMemoryMemoryStore()
    record_id = _add_memory(store, RAW_MEMORY_TEXT, source=RAW_RECORD_ID)
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _DispatcherSpy(_dispatcher(runtime))
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_LIST",
            input={"query": RAW_MEMORY_TEXT, "path": raw_path},
            id="toolu_list_safe_input",
        )
    )

    assert result is None
    assert RAW_MEMORY_TEXT in _serialized(messages)
    request_text = _serialized(_tool_result_request_payloads(dispatcher))
    assert RAW_MEMORY_TEXT not in request_text
    assert raw_path not in request_text
    assert "private-memory.txt" not in request_text
    assert '"tool_input"' not in request_text
    assert "query_hash" in request_text
    assert "path_hash" in request_text

    tool_result_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_RESULT
    ]
    evidence = dict(tool_result_events[-1].evidence)
    assert evidence["operation"] == "list"
    assert evidence["count"] == 1
    assert evidence["redacted"] is True
    assert evidence["query_hash"]
    assert evidence["path_hash"]
    assert evidence["memory_tool_input_redacted"] is True
    assert evidence["memory_tool_result_redacted"] is True

    action_log_text = _serialized(dispatcher.action_log)
    assert RAW_MEMORY_TEXT not in action_log_text
    assert record_id not in action_log_text
    assert RAW_RECORD_ID not in action_log_text
    assert raw_path not in action_log_text

    writer = EventLogWriter(tmp_path / "session")
    assert dispatcher.flush_to_event_log(writer) >= 1
    writer.close()
    event_text = (tmp_path / "session" / "events.jsonl").read_text(encoding="utf-8")
    assert RAW_MEMORY_TEXT not in event_text
    assert record_id not in event_text
    assert RAW_RECORD_ID not in event_text
    assert raw_path not in event_text
    assert "query_hash" in event_text
    assert "path_hash" in event_text


def test_memory_remember_request_tool_result_redacts_raw_tool_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEMORY_REMEMBER_REQUEST 的 raw content 不能进入 TOOL_RESULT evidence/action_log。"""
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _DispatcherSpy(_dispatcher(runtime))
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=[],
    )

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_REMEMBER_REQUEST",
            input={"content": RAW_MEMORY_TEXT},
            id="toolu_remember_safe_input",
        )
    )

    assert result == AWAITING_USER
    tool_result_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_RESULT
    ]
    assert tool_result_events
    payload = dict(tool_result_events[-1].evidence)
    action_log_text = _serialized(dispatcher.action_log)
    request_text = _serialized(_tool_result_request_payloads(dispatcher))
    assert RAW_MEMORY_TEXT not in action_log_text
    assert RAW_MEMORY_TEXT not in request_text
    assert '"tool_input"' not in request_text
    assert payload["memory_tool_result_redacted"] is True
    assert payload["memory_tool_input_redacted"] is True
    assert payload["operation"] == "remember_request"
    assert payload["content_hash"]
    assert payload["content_length"] == len(RAW_MEMORY_TEXT)
    assert payload["redacted"] is True


def test_memory_forget_request_tool_result_redacts_raw_tool_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEMORY_FORGET_REQUEST 的 raw record_id 不能进入 TOOL_RESULT evidence/action_log。"""
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _DispatcherSpy(_dispatcher(runtime))
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=[],
    )

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_FORGET_REQUEST",
            input={"record_id": RAW_RECORD_ID},
            id="toolu_forget_safe_input",
        )
    )

    assert result == AWAITING_USER
    action_log_text = _serialized(dispatcher.action_log)
    request_text = _serialized(_tool_result_request_payloads(dispatcher))
    assert RAW_RECORD_ID not in action_log_text
    assert RAW_RECORD_ID not in request_text
    assert '"tool_input"' not in request_text
    tool_result_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_RESULT
    ]
    evidence = dict(tool_result_events[-1].evidence)
    assert evidence["operation"] == "forget_request"
    assert evidence["memory_id_hash"]
    assert evidence["record_id_hash"]
    assert evidence["memory_id_hashes"]
    assert evidence["redacted"] is True


def test_filesystem_backend_memory_remember_commits_reopens_and_recalls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """env filesystem backend 下 request-only remember 经确认后必须 durable commit。"""
    _patch_checkpoint(monkeypatch)
    from agent.memory_fs_store import FilesystemMemoryStore
    from agent.memory_runtime import create_memory_runtime
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.schema import RuntimeActionRequest

    raw_content = "FS MODEL TOOL MEMORY SHOULD REOPEN AND RECALL"
    root = tmp_path / "memory-root"
    monkeypatch.setenv("MEMORY_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("MEMORY_STORE_ROOT", str(root))
    runtime = create_memory_runtime()
    assert isinstance(runtime._store, FilesystemMemoryStore)

    state = _state()
    dispatcher = _dispatcher(runtime)
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=[],
    )

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_REMEMBER_REQUEST",
            input={"content": raw_content},
            id="toolu_fs_remember",
        )
    )
    assert result == AWAITING_USER

    from agent.confirm_handlers import handle_user_input_step

    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)
    reply = handle_user_input_step("1", ctx)

    assert "已记住" in reply
    assert [record.content for record in runtime._store.list_records()] == [raw_content]
    commit_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.MEMORY_PROPOSE
    ]
    assert commit_events
    commit_evidence = dict(commit_events[-1].evidence)
    assert "memory_commit_failed" not in commit_evidence
    assert commit_evidence["memory_committed"]["event_type"] == "memory.committed"
    assert commit_evidence["memory_committed"]["backend"] == "filesystem"
    assert raw_content not in _serialized(commit_evidence)
    assert str(root) not in _serialized(commit_evidence)

    reopened_runtime = create_memory_runtime()
    assert [record.content for record in reopened_runtime._store.list_records()] == [raw_content]
    recall_registry = ActionHandlerRegistry()
    recall_registry.register(
        RuntimeActionType.MEMORY_RECALL,
        MemoryRecallHandler(store=reopened_runtime._store),
    )
    recall_dispatcher = RuntimeActionDispatcher(registry=recall_registry)

    recall_result = recall_dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_RECALL,
        source="test",
        parent_trace_id="",
        payload={},
    ))

    assert recall_result.status == "success"
    assert raw_content in recall_result.payload["prompt_section"]
    assert "memory_recall_failed" not in recall_result.evidence
    assert (
        recall_result.evidence["memory_recall_requested"]["event_type"]
        == "memory.recall.requested"
    )
    assert (
        recall_result.evidence["memory_recall_completed"]["event_type"]
        == "memory.recall.completed"
    )
    recall_evidence_text = _serialized(recall_result.evidence)
    assert raw_content not in recall_evidence_text
    assert str(root) not in recall_evidence_text


def test_filesystem_backend_recall_logs_safe_evidence_surfaces(
    tmp_path,
) -> None:
    """filesystem recall 允许 prompt 注入正文，但日志面只能保留安全 evidence。"""
    from agent.event_log import EventLogWriter
    from agent.log_viewer import render_session_summary
    from agent.memory_fs_store import FilesystemMemoryStore
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.schema import RuntimeActionRequest

    raw_content = "FS RECALL RAW MEMORY SHOULD ONLY ENTER PROMPT"
    root = tmp_path / "durable-memory-root"
    store = FilesystemMemoryStore(root)
    _add_memory(store, raw_content, source="fs-recall-safe")

    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_RECALL,
        MemoryRecallHandler(store=store),
    )
    dispatcher = RuntimeActionDispatcher(registry=registry)

    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_RECALL,
        source="test",
        parent_trace_id="",
        payload={},
    ))

    assert result.status == "success"
    assert raw_content in result.payload["prompt_section"]
    assert result.evidence["memory_recall_completed"]["event_type"] == (
        "memory.recall.completed"
    )
    assert "memory_recall_failed" not in result.evidence

    action_log_text = _serialized(dispatcher.action_log)
    assert raw_content not in action_log_text
    assert str(root) not in action_log_text

    writer = EventLogWriter(tmp_path / "session")
    assert dispatcher.flush_to_event_log(writer) == 1
    writer.close()
    event_text = (tmp_path / "session" / "events.jsonl").read_text(encoding="utf-8")
    assert "memory.recall.completed" in event_text
    assert raw_content not in event_text
    assert str(root) not in event_text

    raw_events = [json.loads(line) for line in event_text.splitlines()]
    summary_entries = [
        {
            "event": "evidence.recorded",
            "session_id": event.get("session_id", ""),
            "timestamp": event.get("timestamp", ""),
            "data": event.get("evidence", {}),
        }
        for event in raw_events
    ]
    rendered = render_session_summary("fs-recall-safe", summary_entries)
    assert raw_content not in rendered
    assert str(root) not in rendered


def test_memory_forget_request_waits_for_user_confirmation_then_deletes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    record_id = _add_memory(store, "Memory to delete", source="delete-me")
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _dispatcher(runtime)
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_FORGET_REQUEST",
            input={"record_id": record_id},
            id="toolu_forget",
        )
    )

    assert result == AWAITING_USER
    assert state.task.pending_user_input_request["awaiting_kind"] == "memory_forget_confirmation"
    assert len(store.list_records()) == 1

    from agent.confirm_handlers import handle_user_input_step

    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)
    reply = handle_user_input_step("1", ctx)

    assert "已移除记忆" in reply
    assert store.list_records() == ()
    delete_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.MEMORY_FORGET
    ]
    assert delete_events[-1].evidence["memory_delete_completed"]["event_type"] == "memory.deleted"
    assert record_id not in _serialized(delete_events[-1].evidence)


def test_memory_forget_request_missing_record_does_not_report_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _dispatcher(runtime)
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )
    missing_id = "memory:fake:missing-raw-record-id"

    result = mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_FORGET_REQUEST",
            input={"record_id": missing_id},
            id="toolu_forget_missing",
        )
    )
    assert result == AWAITING_USER

    from agent.confirm_handlers import handle_user_input_step

    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)
    reply = handle_user_input_step("1", ctx)

    assert "未找到" in reply or "不存在" in reply
    assert "已移除记忆" not in reply
    assert state.task.pending_user_input_request is None
    delete_events = [
        event for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.MEMORY_FORGET
    ]
    assert delete_events
    evidence = dict(delete_events[-1].evidence)
    assert evidence["memory_delete_completed"]["event_type"] == "memory.delete_failed"
    assert evidence["memory_delete_completed"]["reason"] == "record_not_found"
    assert missing_id not in _serialized(evidence)


def test_memory_forget_request_no_handler_does_not_report_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    from agent import evidence_recorder
    from agent.confirm_handlers import handle_user_input_step

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    state = _state()
    state.task.status = "awaiting_user_input"
    raw_id = "memory:fake:no-handler-raw-record-id"
    state.task.pending_user_input_request = {
        "awaiting_kind": "memory_forget_confirmation",
        "_record_id": raw_id,
        "_origin_status": "running",
    }
    dispatcher = RuntimeActionDispatcher(registry=ActionHandlerRegistry())
    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)

    reply = handle_user_input_step("1", ctx)

    assert "删除失败" in reply
    assert "已移除记忆" not in reply
    assert state.task.pending_user_input_request is None
    assert any(
        call.get("metadata", {}).get("event_type") == "memory.delete_failed"
        and call.get("metadata", {}).get("reason") == "dispatcher_no_handler"
        for call in calls
    )
    assert raw_id not in _serialized(calls)


def test_memory_forget_request_dispatcher_failure_does_not_report_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    from agent import evidence_recorder
    from agent.confirm_handlers import handle_user_input_step
    from agent.runtime_integration.schema import RuntimeActionResult

    class BrokenForgetHandler:
        def handle(self, _request, _context) -> RuntimeActionResult:
            raise RuntimeError("RAW RECORD DELETE FAILURE SHOULD NOT LOG")

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    state = _state()
    state.task.status = "awaiting_user_input"
    raw_id = "memory:fake:dispatcher-failed-raw-record-id"
    state.task.pending_user_input_request = {
        "awaiting_kind": "memory_forget_confirmation",
        "_record_id": raw_id,
        "_origin_status": "running",
    }
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_FORGET, BrokenForgetHandler())
    dispatcher = RuntimeActionDispatcher(registry=registry)
    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)

    reply = handle_user_input_step("1", ctx)

    assert "删除失败" in reply
    assert "已移除记忆" not in reply
    assert state.task.pending_user_input_request is None
    assert any(
        call.get("metadata", {}).get("event_type") == "memory.delete_failed"
        and call.get("metadata", {}).get("reason") == "dispatcher_failed"
        for call in calls
    )
    serialized = _serialized({"calls": calls, "action_log": dispatcher.action_log})
    assert raw_id not in serialized
    assert "RAW RECORD DELETE FAILURE SHOULD NOT LOG" not in serialized


def test_memory_forget_request_cancel_keeps_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkpoint(monkeypatch)
    store = InMemoryMemoryStore()
    record_id = _add_memory(store, "Memory to keep", source="keep-me")
    runtime = MemoryRuntime(store=store)
    state = _state()
    dispatcher = _dispatcher(runtime)
    messages: list[dict[str, Any]] = []
    mediator = _mediator(
        dispatcher=dispatcher,
        state=state,
        runtime=runtime,
        messages=messages,
    )

    mediator.mediate(
        _ToolUseBlock(
            name="MEMORY_FORGET_REQUEST",
            input={"record_id": record_id},
            id="toolu_forget_cancel",
        )
    )

    from agent.confirm_handlers import handle_user_input_step

    ctx = _confirmation_context(state=state, runtime=runtime, dispatcher=dispatcher)
    reply = handle_user_input_step("2", ctx)

    assert "已取消" in reply
    records = store.list_records()
    assert len(records) == 1
    assert records[0].id == record_id
