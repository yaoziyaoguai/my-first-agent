from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ApprovalPolicy,
    ConversationState,
    ExecuteOperatorTool,
    ExecutionAuthorityClass,
    InvocationOrigin,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    OutputPolicy,
    ResolveApproval,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolExposure,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    RecordingCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
    goal_noop_response,
)


def _runtime(
    store,
    provider,
    callable_,
    *,
    approval: ApprovalPolicy = ApprovalPolicy.NEVER,
    exposure: ToolExposure = ToolExposure.MODEL,
    event_sink=None,
):
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="write_fixture",
        version="1",
        description="Write fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={},
        output_limit_chars=20,
    )
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(
            (RegisteredTool(spec, callable_, exposure=exposure),)
        ),
        checkpoint_store=store,
        event_sink=event_sink or CollectingSink(),
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

    # 已有 Goal 的用户补充先由 no-op delta 消费并记录 replan；save#6 才是
    # EXECUTING checkpoint。注入点必须命中 mark_executing，断言才不空洞。
    store = InMemoryCheckpointStore(conversation_with_active_goal())
    store.fail_on_save = 6
    provider = ScriptedProvider(
        goal_noop_response("effect-cas-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
    )

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
    store.fail_on_save = 7
    provider = ScriptedProvider(
        goal_noop_response("effect-save-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not auto retry"),)),
    )

    result = _runtime(store, provider, effect).run_turn(_action(store.state), store.load())

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == 1
    assert len(provider.calls) == 2
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
        goal_noop_response("effect-exception-user-supplement"),
        ModelResponse((ModelToolCall("call-1", "write_fixture", {}),)),
        ModelResponse((ModelTextBlock("must not auto retry"),)),
    )

    result = _runtime(store, provider, effect_then_fail).run_turn(
        _action(store.state),
        store.load(),
    )

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == 1
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.status.value == "awaiting_recovery"


def test_operator_tool_uses_same_approval_executing_result_order() -> None:
    calls: list[str] = []
    state = replace(
        conversation_with_active_goal(),
        active_run=ActiveRun(run_id="run-existing"),
    )
    store = RecordingCheckpointStore(state)
    provider = ScriptedProvider()
    events = CollectingSink()
    runtime = _runtime(
        store,
        provider,
        lambda intent: calls.append(intent.tool_call_id) or "private result",
        approval=ApprovalPolicy.ALWAYS,
        exposure=ToolExposure.OPERATOR,
        event_sink=events,
    )
    action = ExecuteOperatorTool(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        action_id="operator-action-1",
        tool_name="write_fixture",
        arguments={},
        submitted_at="2026-08-30T12:00:00Z",
    )

    first = runtime.run_turn(action, store.load())

    assert first.status is RunStatus.AWAITING_APPROVAL
    assert calls == []
    pending = store.load()
    assert pending.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    assert first.request is not None
    second = runtime.run_turn(
        ResolveApproval(
            conversation_id=pending.state.conversation_id,
            action_seq=pending.state.next_action_seq,
            expected_revision=pending.state.revision,
            request_id=first.request.request_id,
            binding_digest=first.request.binding_digest,
            approved=True,
        ),
        pending,
    )

    assert second.status is RunStatus.COMPLETED
    assert calls == ["operator-action-1"]
    assert store.saved_phases.index("executing") < store.saved_fact_kinds.index(
        "tool_result"
    )
    assert provider.calls == []
    assert "private result" not in repr(events.events)


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
