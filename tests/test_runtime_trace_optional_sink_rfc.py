"""RFC 0002 optional trace sink first-slice tests.

这些测试继续 Runtime Trace + ToolResult gate，但只允许窄边界 opt-in wiring：
调用方显式传入 trace sink 时，工具执行边界把既有 legacy tool_result 投影成
TraceEvent；默认路径不写 trace、不创建 recorder、不改变 checkpoint/messages。
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from tests.conftest import FakeToolUseBlock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RFC_PATH = PROJECT_ROOT / "docs" / "rfcs" / "0002-runtime-trace-optional-sink.md"
EMITTER_PATH = PROJECT_ROOT / "agent" / "runtime_trace_emitter.py"
TOOL_EXECUTOR_PATH = PROJECT_ROOT / "agent" / "tool_executor.py"


def _agent_imports(path: Path) -> set[str]:
    """用 AST 守住 optional sink 的依赖方向，避免注释文本造成误判。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def test_runtime_trace_optional_sink_rfc_exists_and_is_draft() -> None:
    """RFC 0002 必须先写清楚：sink 是 opt-in，不是 runtime tracing framework。"""

    text = RFC_PATH.read_text(encoding="utf-8")

    required = (
        "RFC 0002: Runtime Trace Optional Sink",
        "Status: Draft",
        "Context",
        "Problem",
        "Goals",
        "Non-goals",
        "Current behavior",
        "Proposed design",
        "Architecture boundaries",
        "Safety boundaries",
        "First safe slice",
        "Alternatives considered",
        "Test strategy",
        "Migration plan",
        "Rollback plan",
        "Risks",
        "Open questions",
        "Required human authorization",
        "Future gates",
        "no default recorder",
        "no broad runtime rewrite",
        "no broad tool_executor rewrite",
    )
    for phrase in required:
        assert phrase in text


def test_chat_accepts_optional_trace_event_sink_without_requiring_recorder() -> None:
    """public runtime entry 只接受可选 sink，不把 LocalTraceRecorder 接进 core.py。"""

    from agent.core import chat

    signature = inspect.signature(chat)

    assert "on_trace_event" in signature.parameters
    assert signature.parameters["on_trace_event"].default is None


def test_tool_executor_emits_trace_event_to_optional_sink(monkeypatch, fresh_state) -> None:
    """工具执行完成后只向显式 sink 投影 TraceEvent，legacy messages 仍是源头。"""

    from agent.tool_executor import execute_single_tool

    events = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_display_event=None,
        on_runtime_event=None,
        on_trace_event=events.append,
        trace_run_id="run-test",
        trace_id="trace-test",
    )
    messages: list[dict] = []
    block = FakeToolUseBlock(
        id="toolu_trace_1",
        name="safe_test_tool",
        input={"value": "ok"},
    )

    monkeypatch.setattr(
        "agent.tool_executor.needs_tool_confirmation",
        lambda tool_name, tool_input: False,
    )
    monkeypatch.setattr(
        "agent.tool_executor.execute_tool",
        lambda tool_name, tool_input, context=None: "完成：api_key=sk-test-secret",
    )

    result = execute_single_tool(
        block,
        state=fresh_state,
        turn_state=turn_state,
        turn_context={},
        messages=messages,
    )

    assert result is None
    assert messages[-1]["content"][0]["content"] == "完成：api_key=sk-test-secret"
    assert len(events) == 1
    payload = events[0].to_json_dict()
    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["run_id"] == "run-test"
    assert payload["trace_id"] == "trace-test"
    assert payload["span_id"] == "tool_result:toolu_trace_1"
    assert payload["parent_span_id"] == "tool_use:toolu_trace_1"
    assert payload["status"] == "ok"
    assert payload["metadata"]["tool_name"] == "safe_test_tool"
    assert "sk-test-secret" not in encoded
    assert "[REDACTED]" in encoded


def test_execute_pending_tool_emits_trace_event_to_same_optional_sink(
    monkeypatch,
    fresh_state,
) -> None:
    """确认后执行 pending tool 也走同一窄 sink，不让 confirm handler 建 trace。"""

    from agent.tool_executor import execute_pending_tool

    events = []
    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_display_event=None,
        on_runtime_event=None,
        on_trace_event=events.append,
        trace_run_id="run-pending",
        trace_id="trace-pending",
    )
    messages: list[dict] = []
    pending = {
        "tool_use_id": "toolu_pending_1",
        "tool": "safe_pending_tool",
        "input": {"value": "ok"},
    }

    monkeypatch.setattr(
        "agent.tool_executor.execute_tool",
        lambda tool_name, tool_input, context=None: "错误：boom",
    )

    result = execute_pending_tool(
        state=fresh_state,
        turn_state=turn_state,
        messages=messages,
        pending=pending,
    )

    assert result.startswith("错误：boom")
    assert messages[-1]["content"][0]["tool_use_id"] == "toolu_pending_1"
    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].metadata["tool_result_status"] == "failed"


def test_tool_executor_without_trace_sink_preserves_legacy_messages(
    monkeypatch,
    fresh_state,
) -> None:
    """没有 sink 时默认行为不变：只写 tool_result message，不创建 trace 依赖。"""

    from agent.tool_executor import execute_single_tool

    turn_state = SimpleNamespace(
        round_tool_traces=[],
        on_display_event=None,
        on_runtime_event=None,
    )
    messages: list[dict] = []
    block = FakeToolUseBlock(
        id="toolu_no_trace",
        name="safe_test_tool",
        input={"value": "ok"},
    )
    monkeypatch.setattr(
        "agent.tool_executor.needs_tool_confirmation",
        lambda tool_name, tool_input: False,
    )
    monkeypatch.setattr(
        "agent.tool_executor.execute_tool",
        lambda tool_name, tool_input, context=None: "完成：ok",
    )

    execute_single_tool(
        block,
        state=fresh_state,
        turn_state=turn_state,
        turn_context={},
        messages=messages,
    )

    assert messages[-1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_no_trace",
        "content": "完成：ok",
    }


def test_optional_trace_sink_dependency_direction_is_narrow() -> None:
    """sink helper 可以被 executor 调用，但不能反向依赖 core/checkpoint/registry。"""

    emitter_imports = _agent_imports(EMITTER_PATH)
    executor_imports = _agent_imports(TOOL_EXECUTOR_PATH)

    assert emitter_imports == {"agent.local_trace", "agent.runtime_trace_projection"}
    assert "agent.runtime_trace_emitter" in executor_imports
    assert {
        "agent.core",
        "agent.checkpoint",
        "agent.tool_executor",
        "agent.tool_registry",
        "agent.mcp",
        "agent.memory_store",
    }.isdisjoint(emitter_imports)
