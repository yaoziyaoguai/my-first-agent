from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    Resume,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def test_invocation_limit_pauses_and_resume_gets_fresh_budget() -> None:
    spec = ToolSpec(
        name="read_fixture",
        version="1",
        description="Read fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=10,
    )
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "read_fixture", {}),)),
        ModelResponse((ModelTextBlock("final"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime((RegisteredTool(spec, lambda intent: "ok"),)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_model_calls=1),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="read",
    )

    paused = runtime.run_turn(submit, store.load())
    assert paused.status is RunStatus.LIMIT_REACHED

    resume = Resume(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
    )
    completed = runtime.run_turn(resume, store.load())

    assert completed.status is RunStatus.COMPLETED
    assert completed.message == "final"


def test_conversation_capacity_stops_before_provider_effect() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    store.capacity_available = False
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    result = runtime.run_turn(submit, store.load())

    assert result.status is RunStatus.CONVERSATION_LIMIT_REACHED
    assert provider.calls == []
    assert store.state.active_run is None


def test_tool_call_limit_pauses_before_the_next_callable() -> None:
    calls = 0

    def read_fixture(intent) -> str:
        nonlocal calls
        calls += 1
        return "ok"

    spec = ToolSpec(
        name="read_fixture",
        version="1",
        description="Read fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=10,
    )
    provider = ScriptedProvider(
        ModelResponse(
            (
                ModelToolCall("call-1", "read_fixture", {}),
                ModelToolCall("call-2", "read_fixture", {}),
            )
        )
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime((RegisteredTool(spec, read_fixture),)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_tool_calls=1),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="read twice",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "tool_call_limit"
    assert calls == 1
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_input_token_limit_pauses_before_provider_call() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_input_tokens=1),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "input_token_limit"
    assert provider.calls == []
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_output_token_limit_pauses_after_one_provider_call() -> None:
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("too much"),), output_tokens=2)
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_output_tokens=1),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "output_token_limit"
    assert len(provider.calls) == 1
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "paused_limit"


def test_missing_usage_uses_conservative_output_bound() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("x" * 100),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_output_tokens=50),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "output_token_limit"


def test_underreported_usage_cannot_bypass_conservative_output_bound() -> None:
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("x" * 100),), output_tokens=0)
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_output_tokens=50),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.LIMIT_REACHED
    assert result.error_code == "output_token_limit"
    assert len(provider.calls) == 1


def test_provider_max_tokens_stop_is_not_reported_completed() -> None:
    provider = ScriptedProvider(
        ModelResponse(
            (ModelTextBlock("truncated answer"),),
            stop_reason="max_tokens",
            output_tokens=5,
        )
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "provider_output_truncated"
    assert result.message is None
    assert store.state.active_run is None
