from __future__ import annotations

import pytest

from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionAuthorityClass,
    ExecutionIntent,
    InvocationOrigin,
    OutputPolicy,
    SideEffectClass,
    ToolCall,
    ToolExposure,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime, RegisteredTool


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        description="closed fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"enabled": True},
        output_limit_chars=128,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )


def _context(origin: InvocationOrigin) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=7,
        invocation_origin=origin,
    )


def test_model_definitions_never_advertise_operator_registration() -> None:
    runtime = KernelToolRuntime(
        (
            RegisteredTool(_spec("visible"), lambda intent: "ok"),
            RegisteredTool(
                _spec("hidden"),
                lambda intent: "ok",
                exposure=ToolExposure.OPERATOR,
            ),
        )
    )
    assert [definition.name for definition in runtime.definitions()] == ["visible"]


def test_guessed_operator_name_is_rejected_before_callable() -> None:
    calls = 0

    def hidden(intent: ExecutionIntent) -> str:
        nonlocal calls
        calls += 1
        return "ran"

    runtime = KernelToolRuntime(
        (RegisteredTool(_spec("hidden"), hidden, exposure=ToolExposure.OPERATOR),)
    )
    result = runtime.prepare(ToolCall("call-1", "hidden", {}), _context(InvocationOrigin.MODEL))
    assert result.executed is False
    assert result.metadata["code"] == "tool_exposure_mismatch"
    assert calls == 0


def test_operator_origin_cannot_invoke_model_registration() -> None:
    runtime = KernelToolRuntime((RegisteredTool(_spec("visible"), lambda intent: "ran"),))
    result = runtime.prepare(
        ToolCall("call-1", "visible", {}),
        _context(InvocationOrigin.OPERATOR),
    )
    assert result.executed is False
    assert result.metadata["code"] == "tool_exposure_mismatch"


def test_invoke_rechecks_origin_against_registration() -> None:
    runtime = KernelToolRuntime(
        (
            RegisteredTool(
                _spec("hidden"),
                lambda intent: "ran",
                exposure=ToolExposure.OPERATOR,
            ),
        )
    )
    intent = runtime.prepare(
        ToolCall("call-1", "hidden", {}),
        _context(InvocationOrigin.OPERATOR),
    )
    assert isinstance(intent, ExecutionIntent)
    forged = object.__new__(ExecutionIntent)
    for field in intent.__dataclass_fields__:
        object.__setattr__(forged, field, getattr(intent, field))
    object.__setattr__(forged, "invocation_origin", InvocationOrigin.MODEL)
    with pytest.raises(IntentConflictError, match="exposure"):
        runtime.invoke(forged)
