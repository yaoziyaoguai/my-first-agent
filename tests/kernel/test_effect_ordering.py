from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ApprovalPolicy,
    ConversationState,
    ExecutionAuthorityClass,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _runtime(store, provider, callable_):
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_fixture",
        version="1",
        description="Write fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={},
        output_limit_chars=20,
    )
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime((RegisteredTool(spec, callable_),)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )


def _action(state: ConversationState) -> SubmitMessage:
    # 从当前状态派生序列,兼容 seeded(带 Goal)与全新会话两种起点。
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=f"run-{state.next_action_seq}",
        message="write",
    )


def test_cas_failure_before_executing_invokes_zero_callables() -> None:
    calls = 0

    def effect(intent) -> str:
        nonlocal calls
        calls += 1
        return "done"

    # 有 Goal 时 save#4 才是 EXECUTING checkpoint;否则会在 goal guard 处早退,
    # 注入点永远打不中 mark_executing,断言只会空洞地通过。
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    store.fail_on_save = 4
    provider = ScriptedProvider(ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)))

    result = _runtime(store, provider, effect).run_turn(_action(store.state), store.load())

    assert result.status is RunStatus.FAILED_FATAL
    assert calls == 0


def test_result_save_failure_enters_unknown_outcome_recovery() -> None:
    calls = 0

    def effect(intent) -> str:
        nonlocal calls
        calls += 1
        return "done"

    store = InMemoryCheckpointStore(conversation_with_active_goal())
    store.fail_on_save = 5
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not auto retry"),)),
    )

    result = _runtime(store, provider, effect).run_turn(_action(store.state), store.load())

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == 1
    assert len(provider.calls) == 1
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "awaiting_recovery"


def test_write_callable_exception_enters_unknown_outcome_recovery() -> None:
    calls = 0

    def effect_then_fail(intent) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("failure after possible effect")

    store = InMemoryCheckpointStore(conversation_with_active_goal())
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not auto retry"),)),
    )

    result = _runtime(store, provider, effect_then_fail).run_turn(
        _action(store.state),
        store.load(),
    )

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == 1
    assert len(provider.calls) == 1
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "awaiting_recovery"


def test_terminal_and_replay_result_commit_atomically() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    store.fail_on_save = 3
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    action = _action(store.state)

    failed = runtime.run_turn(action, store.load())
    replayed = runtime.run_turn(action, store.load())

    assert failed.status is RunStatus.FAILED_FATAL
    assert failed.error_code == "runtime_failure"
    assert store.state.active_run is None
    assert store.state.replay_records[-1].result is not None
    assert replayed.status is RunStatus.FAILED_FATAL
    assert replayed.replayed is True
    assert len(provider.calls) == 1
