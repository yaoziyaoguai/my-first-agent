from __future__ import annotations

import hashlib
from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalPolicy,
    ApprovalRequest,
    BlockedClaim,
    CompletionClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EgressClass,
    ExecuteOperatorTool,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalStatus,
    InvocationOrigin,
    ModelResponse,
    OutputPolicy,
    RecoverUnknownObservation,
    RecoveryRequest,
    RecoveryResolution,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolExposure,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import accept_action, record_nonexecuted_tool_result
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.continuity.test_contracts import _goal
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


def _operator_runtime_fixture(
    *,
    approval: ApprovalPolicy,
    callable_,
    initial_state=None,
    provider=None,
):
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
    store = RecordingCheckpointStore(initial_state or _operator_ready_state())
    provider = provider or ScriptedProvider()
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


def test_operator_rejection_does_not_block_later_model_completion() -> None:
    content = "verified report\n"
    goal = _goal()
    criterion = replace(
        goal.admitted_criteria[0],
        predicate={
            "path": "reports/final.md",
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        },
    )
    state = ConversationState(
        conversation_id="conversation-operator-completion",
        facts=(
            ConversationFact(
                fact_id="fact:user:1",
                kind=FactKind.USER_MESSAGE,
                content={"text": "write the exact verified report"},
            ),
            ConversationFact(
                fact_id="fact:calls:1",
                kind=FactKind.TOOL_CALLS,
                content={
                    "calls": [
                        {
                            "tool_call_id": "read-1",
                            "name": "read_file",
                            "arguments": {"path": "reports/final.md"},
                        }
                    ]
                },
            ),
            ConversationFact(
                fact_id="fact:read-result:1",
                kind=FactKind.TOOL_RESULT,
                content={
                    "tool_call_id": "read-1",
                    "text": content,
                    "is_error": False,
                    "executed": True,
                    "metadata": {},
                },
            ),
        ),
        goal=replace(goal, admitted_criteria=(criterion,), status=GoalStatus.GOAL_READY),
        active_run=ActiveRun(run_id="run-verify"),
    )
    evidence_id = f"evidence:{goal.goal_id}:{goal.revision}:{criterion.criterion_id}"
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-operator-rejection",
                goal_id=goal.goal_id,
                goal_revision=goal.revision,
                blocker="the private operator request was rejected",
                safe_attempts=(),
                resume_condition="approve the private operator request",
            ),
        ),
        ModelResponse(
            (),
            control=CompletionClaim(
                correlation_id="complete-after-operator-rejection",
                goal_id=goal.goal_id,
                goal_revision=goal.revision,
                criterion_evidence_refs=(evidence_id,),
            ),
        ),
    )
    runtime, store, calls, _events, _provider = _operator_runtime_fixture(
        approval=ApprovalPolicy.ALWAYS,
        callable_=lambda intent: "must not run",
        initial_state=state,
        provider=provider,
    )

    pending = runtime.run_turn(_operator_action(store.state), store.load())
    assert pending.request is not None
    rejected = runtime.run_turn(
        ResolveApproval(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
            request_id=pending.request.request_id,
            binding_digest=pending.request.binding_digest,
            approved=False,
        ),
        store.load(),
    )
    assert rejected.status is RunStatus.COMPLETED
    assert calls == []

    completed = runtime.run_turn(
        Resume(
            conversation_id=store.state.conversation_id,
            action_seq=store.state.next_action_seq,
            expected_revision=store.state.revision,
        ),
        store.load(),
    )

    assert completed.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.VERIFIED_DONE
    assert len(provider.calls) == 2


def test_operator_unknown_observation_fact_stays_private() -> None:
    state = _operator_state()
    active = state.active_run
    assert active is not None
    recovering = replace(
        state,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            pending_request=RecoveryRequest(
                request_id="recovery-operator-observation",
                run_id=active.run_id,
                tool_call_id="operator-action-1",
                binding_digest="operator-public-intent",
                summary="public observation outcome unknown",
            ),
            executing_intent=ExecutingIntentRecord(
                tool_call_id="operator-action-1",
                intent_digest="operator-public-intent",
                idempotency_key="operator-public-request",
                side_effect=SideEffectClass.READ_ONLY,
                egress=EgressClass.PUBLIC_NETWORK,
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
        ),
    )
    action = RecoverUnknownObservation(
        conversation_id=recovering.conversation_id,
        action_seq=recovering.next_action_seq,
        expected_revision=recovering.revision,
        tool_call_id="operator-action-1",
        intent_digest="operator-public-intent",
    )

    transition = accept_action(recovering, action)

    assert transition.reason is None
    observation = transition.state.facts[-1]
    assert observation.content["invocation_origin"] == InvocationOrigin.OPERATOR.value
    pack = _context_manager().build(
        transition.state,
        Resume(
            conversation_id=transition.state.conversation_id,
            action_seq=transition.state.next_action_seq,
            expected_revision=transition.state.revision,
        ),
        (),
    )
    wire = repr(pack.messages)
    assert "owner/private/source.skillpkg" not in wire
    assert "public-network observation outcome is unknown" not in wire


def test_operator_correction_supersession_fact_stays_private() -> None:
    state = _operator_state()
    active = state.active_run
    assert active is not None
    pending = ApprovalRequest(
        request_id="approval-operator-correction",
        run_id=active.run_id,
        tool_call_id="operator-action-1",
        binding_digest="operator-correction-binding",
        preview="stage private skill package",
        tool_name="skill_package_stage",
    )
    awaiting = replace(
        state,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_APPROVAL,
            pending_request=pending,
        ),
    )
    correction = SubmitMessage(
        conversation_id=awaiting.conversation_id,
        action_seq=awaiting.next_action_seq,
        expected_revision=awaiting.revision,
        run_id="run-corrected",
        message="use a different package",
    )

    transition = accept_action(awaiting, correction)

    assert transition.reason is None
    superseded = next(
        fact for fact in transition.state.facts if fact.content.get("superseded") is True
    )
    assert superseded.content["invocation_origin"] == InvocationOrigin.OPERATOR.value
    pack = _context_manager().build(transition.state, correction, ())
    wire = repr(pack.messages)
    assert "owner/private/source.skillpkg" not in wire
    assert "Tool call was not executed because the user corrected the Goal." not in wire
