from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ApprovalPolicy,
    ConversationFact,
    ExecuteOperatorTool,
    ExecutionAuthorityClass,
    FactKind,
    InvocationOrigin,
    OutputPolicy,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    RunStatus,
    SideEffectClass,
    ToolExposure,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import accept_action, record_nonexecuted_tool_result
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import (
    RecordingCheckpointStore,
    RecordingEventSink,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _operator_action(state) -> ExecuteOperatorTool:
    return ExecuteOperatorTool(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        action_id="operator-action-1",
        tool_name="skill_package_stage",
        arguments={
            "source": {"kind": "local", "path": "owner/private/source.skillpkg"}
        },
        submitted_at="2026-08-30T12:00:00Z",
    )


def _operator_state():
    state = _operator_ready_state()
    transition = accept_action(state, _operator_action(state))
    assert transition.reason is None
    return transition.state


def _operator_ready_state():
    return replace(
        conversation_with_active_goal(),
        active_run=ActiveRun(run_id="run-operator"),
    )


def _completed_operator_state(*, private_argument: str, result_text: str):
    state = _operator_state()
    call = state.active_run.tool_calls[0]
    state = replace(
        state,
        active_run=replace(
            state.active_run,
            tool_calls=(replace(call, arguments={"source": private_argument}),),
        ),
    )
    result = ConversationFact(
        fact_id="run:run-operator:tool-result:operator-action-1:7",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "operator-action-1",
            "text": result_text,
            "is_error": False,
            "executed": False,
            "metadata": {},
            "invocation_origin": InvocationOrigin.OPERATOR.value,
        },
    )
    return record_nonexecuted_tool_result(state, result)


def _context_manager() -> KernelContextManager:
    return KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
    )


def _operator_runtime_fixture(*, approval: ApprovalPolicy, callable_):
    calls: list[str] = []
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="skill_package_stage",
        version="1",
        description="Stage an operator-owned package",
        input_schema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["kind", "path"],
                    "additionalProperties": False,
                }
            },
            "required": ["source"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval,
        safety_policy={},
        output_limit_chars=128,
    )
    store = RecordingCheckpointStore(_operator_ready_state())
    provider = ScriptedProvider()
    events = RecordingEventSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=_context_manager(),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    spec,
                    lambda intent: calls.append(intent.tool_call_id) or callable_(intent),
                    exposure=ToolExposure.OPERATOR,
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=events,
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    return runtime, store, calls, events, provider


def test_operator_facts_never_project_arguments_or_result_to_model_context() -> None:
    private = "owner/private/source.skillpkg"
    state = _completed_operator_state(
        private_argument=private,
        result_text="private result",
    )
    pack = _context_manager().build(
        state,
        Resume(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
        ),
        (),
    )
    wire = repr(pack.messages)
    assert private not in wire
    assert "private result" not in wire
    assert "operator" not in wire


def test_operator_rejection_and_recovery_results_remain_private() -> None:
    runtime, store, calls, _events, provider = _operator_runtime_fixture(
        approval=ApprovalPolicy.ALWAYS,
        callable_=lambda intent: "private result",
    )
    rejected = runtime.run_turn(_operator_action(store.state), store.load())
    assert rejected.request is not None
    pending = store.load()
    result = runtime.run_turn(
        ResolveApproval(
            conversation_id=pending.state.conversation_id,
            action_seq=pending.state.next_action_seq,
            expected_revision=pending.state.revision,
            request_id=rejected.request.request_id,
            binding_digest=rejected.request.binding_digest,
            approved=False,
        ),
        pending,
    )
    assert result.status is RunStatus.COMPLETED
    assert calls == []
    assert provider.calls == []
    context = _context_manager().build(
        store.state,
        Resume(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        (),
    )
    rejection_wire = repr(context.messages)
    assert "owner/private/source.skillpkg" not in rejection_wire
    assert "User rejected the requested tool action." not in rejection_wire

    recovering_runtime, recovering_store, recovering_calls, _events, recovering_provider = (
        _operator_runtime_fixture(
            approval=ApprovalPolicy.NEVER,
            callable_=lambda intent: (_ for _ in ()).throw(RuntimeError("possible effect")),
        )
    )
    awaiting = recovering_runtime.run_turn(
        _operator_action(recovering_store.state), recovering_store.load()
    )
    assert awaiting.status is RunStatus.AWAITING_RECOVERY
    assert awaiting.request is not None
    recovery_state = recovering_store.load()
    recovered = recovering_runtime.run_turn(
        ResolveUnknownToolOutcome(
            conversation_id=recovery_state.state.conversation_id,
            action_seq=recovery_state.state.next_action_seq,
            expected_revision=recovery_state.state.revision,
            request_id=awaiting.request.request_id,
            binding_digest=awaiting.request.binding_digest,
            resolution=RecoveryResolution.MARK_FAILED,
        ),
        recovery_state,
    )
    assert recovered.status is RunStatus.COMPLETED
    assert recovering_calls == ["operator-action-1"]
    assert recovering_provider.calls == []
    recovery_context = _context_manager().build(
        recovering_store.state,
        Resume(
            conversation_id=recovering_store.state.conversation_id,
            action_seq=recovering_store.state.next_action_seq,
            expected_revision=recovering_store.state.revision,
        ),
        (),
    )
    recovery_wire = repr(recovery_context.messages)
    assert "owner/private/source.skillpkg" not in recovery_wire
    assert "Operator classified the previous tool effect as failed." not in recovery_wire
