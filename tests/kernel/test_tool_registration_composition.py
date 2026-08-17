from __future__ import annotations

import pytest

from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionAuthorityClass,
    ExecutionIntent,
    OutputPolicy,
    PolicyDecision,
    SideEffectClass,
    ToolCall,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import KernelToolRuntime, RegisteredTool


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name=name,
        version="1",
        description="fixture tool",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=64,
    )


def _ctx() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 1)


class _AllowPolicy:
    """每个 registration 绑定自己的 policy identity，证明不按工具名路由。"""

    def __init__(self, identity: str) -> None:
        self.identity = identity

    def evaluate(self, spec, arguments, binding):
        return PolicyDecision.ALLOW


def test_two_registrations_carry_distinct_policy_identity() -> None:
    runtime = KernelToolRuntime(
        (
            RegisteredTool(_spec("tool_a"), lambda intent: "a", policy=_AllowPolicy("policy-a-v1")),
            RegisteredTool(_spec("tool_b"), lambda intent: "b", policy=_AllowPolicy("policy-b-v1")),
        )
    )

    intent_a = runtime.prepare(ToolCall("call-a", "tool_a", {}), _ctx())
    intent_b = runtime.prepare(ToolCall("call-b", "tool_b", {}), _ctx())

    assert isinstance(intent_a, ExecutionIntent)
    assert isinstance(intent_b, ExecutionIntent)
    assert intent_a.policy_identity == "policy-a-v1"
    assert intent_b.policy_identity == "policy-b-v1"


def test_duplicate_tool_names_fail_atomically() -> None:
    with pytest.raises(ValueError, match="duplicate tool registration"):
        KernelToolRuntime(
            (
                RegisteredTool(_spec("dup"), lambda intent: "x"),
                RegisteredTool(_spec("dup"), lambda intent: "y"),
            ),
        )


def test_executor_receives_frozen_execution_intent() -> None:
    received: list[ExecutionIntent] = []

    def observe(intent: ExecutionIntent) -> str:
        received.append(intent)
        return "observed"

    runtime = KernelToolRuntime((RegisteredTool(_spec("observe"), observe),))
    intent = runtime.prepare(ToolCall("call-1", "observe", {}), _ctx())
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.executed is True
    assert result.is_error is False
    assert result.content == "observed"
    assert len(received) == 1
    assert received[0].tool_call_id == "call-1"
    # executor 拿到完整 frozen intent，可使用 idempotency identity（MCP/Memory/SubAgent 需要）
    assert received[0].idempotency_key == intent.idempotency_key
    assert received[0].intent_digest == intent.intent_digest


def test_composition_builds_single_owners_without_extension_seams() -> None:
    from agent.composition import Composition, build_composition
    from agent.runtime.context import ContextLimits, KernelContextManager
    from agent.runtime.contracts import ConversationState, ModelResponse, ModelTextBlock
    from agent.runtime.loop import AgentRuntime, InvocationLimits
    from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

    provider = ScriptedProvider(ModelResponse((ModelTextBlock("ok"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    composition = build_composition(
        provider=provider,
        checkpoint_store=store,
        tool_registrations=(),
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
    )

    assert isinstance(composition, Composition)
    assert isinstance(composition.runtime, AgentRuntime)
    assert isinstance(composition.tool_runtime, KernelToolRuntime)
    assert isinstance(composition.context_manager, KernelContextManager)
    # close_stack（MCP）与 sources（Memory）都是 composition 的显式扩展点；默认空。
    assert composition.close_stack == ()
    assert composition.sources == ()
