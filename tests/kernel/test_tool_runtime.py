from __future__ import annotations

import pytest

from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionIntent,
    OutputPolicy,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime, RegisteredTool


def _spec(
    name: str = "read_fixture",
    *,
    approval: ApprovalPolicy = ApprovalPolicy.NEVER,
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        description="Read a deterministic fixture",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=side_effect,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={"workspace_scoped": True},
        output_limit_chars=32,
    )


def _context() -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=2,
    )


def test_prepare_is_effect_free_and_invoke_has_one_owner() -> None:
    calls: list[str] = []

    def read_fixture(intent: ExecutionIntent) -> str:
        path = intent.arguments["path"]
        calls.append(path)
        return "fixture:" + path

    runtime = KernelToolRuntime((RegisteredTool(_spec(), read_fixture),))
    prepared = runtime.prepare(
        ToolCall(tool_call_id="call-1", name="read_fixture", arguments={"path": "a.txt"}),
        _context(),
    )

    assert isinstance(prepared, ExecutionIntent)
    assert calls == []

    result = runtime.invoke(prepared)
    assert result.content == "fixture:a.txt"
    assert calls == ["a.txt"]

    with pytest.raises(IntentConflictError, match="already invoked"):
        runtime.invoke(prepared)
    assert calls == ["a.txt"]


def test_invalid_or_unknown_tool_never_invokes() -> None:
    calls = 0

    def read_fixture(intent: ExecutionIntent) -> str:
        nonlocal calls
        calls += 1
        return intent.arguments["path"]

    runtime = KernelToolRuntime((RegisteredTool(_spec(), read_fixture),))

    unknown = runtime.prepare(
        ToolCall(tool_call_id="call-1", name="missing", arguments={"path": "a"}),
        _context(),
    )
    invalid = runtime.prepare(
        ToolCall(tool_call_id="call-2", name="read_fixture", arguments={}),
        _context(),
    )

    assert unknown.is_error is True
    assert unknown.metadata["code"] == "unknown_tool"
    assert invalid.is_error is True
    assert invalid.metadata["code"] == "invalid_arguments"
    assert calls == 0


def test_tool_exception_becomes_bounded_tool_result() -> None:
    def fail(intent: ExecutionIntent) -> str:
        raise RuntimeError("fixture failed: " + intent.arguments["path"])

    runtime = KernelToolRuntime((RegisteredTool(_spec(), fail),))
    intent = runtime.prepare(
        ToolCall(tool_call_id="call-1", name="read_fixture", arguments={"path": "a"}),
        _context(),
    )
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.is_error is True
    assert result.executed is False
    assert len(result.content) <= 32
    assert "fixture failed" not in result.content
    assert result.metadata["code"] == "tool_error"
