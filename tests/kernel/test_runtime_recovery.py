from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActionDisposition,
    ActiveRun,
    ActiveRunStatus,
    BeginAnswer,
    ContinuationPhase,
    ConversationState,
    EgressClass,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RecoverUnknownObservation,
    RecoveryRequest,
    RecoveryResolution,
    ResolveUnknownToolOutcome,
    Resume,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    ToolResult,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


class ExplodingToolRuntime:
    def definitions(self):
        from agent.runtime.contracts import ToolDefinition

        return (
            ToolDefinition(
                "explode",
                "explode after persist",
                {"type": "object"},
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
        )

    def prepare(self, call, context, approval=None):
        from agent.runtime.contracts import (
            ExecutionIntent,
            InvocationOrigin,
            SideEffectClass,
        )

        return ExecutionIntent(
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            tool_identity="fixture-tool",
            arguments=call.arguments,
            arguments_digest="arguments",
            intent_digest="intent",
            idempotency_key="key",
            policy_identity="fixture-policy",
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            side_effect=SideEffectClass.WRITE,
            invocation_origin=InvocationOrigin.MODEL,
        )

    def invoke(self, intent):
        raise RuntimeError("unknown after external boundary")


class ExplodingPublicObservationRuntime:
    def definitions(self):
        from agent.runtime.contracts import ToolDefinition

        return (
            ToolDefinition(
                "web_search",
                "read public information",
                {"type": "object"},
                egress=EgressClass.PUBLIC_NETWORK,
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
        )

    def prepare(self, call, context, approval=None):
        from agent.runtime.contracts import ExecutionIntent, InvocationOrigin

        return ExecutionIntent(
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            tool_call_id=call.tool_call_id,
            tool_name=call.name,
            tool_identity="fixture-web-tool",
            arguments=call.arguments,
            arguments_digest="arguments",
            intent_digest="public-intent",
            idempotency_key="public-request-1",
            policy_identity="fixture-policy",
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            side_effect=SideEffectClass.READ_ONLY,
            invocation_origin=InvocationOrigin.MODEL,
            egress=EgressClass.PUBLIC_NETWORK,
            operation="search",
            request_identity="public-request-1",
            approval_basis_revision=context.approval_basis_revision,
        )

    def invoke(self, intent):
        raise RuntimeError("unknown after public send")


def test_unknown_tool_outcome_never_retries_automatically() -> None:
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-unknown-outcome")),
        ModelResponse((ModelToolCall("call-1", "explode", {}),)),
        ModelResponse((ModelTextBlock("continued"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=ExplodingToolRuntime(),
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
        message="do it",
    )

    paused = runtime.run_turn(submit, store.load())

    assert paused.status is RunStatus.AWAITING_RECOVERY
    assert paused.request is not None
    assert len(provider.calls) == 2

    resolved = ResolveUnknownToolOutcome(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_id=paused.request.request_id,
        binding_digest=paused.request.binding_digest,
        resolution=RecoveryResolution.MARK_FAILED,
    )
    completed = runtime.run_turn(resolved, store.load())

    assert completed.status is RunStatus.COMPLETED
    assert len(provider.calls) == 3
    assert store.state.last_safe_result is not None
    assert store.state.last_safe_result.status is RunStatus.COMPLETED
    assert store.state.last_safe_result.run_id == "run-1"
    recovery_facts = [fact for fact in store.state.facts if fact.content.get("synthetic")]
    assert len(recovery_facts) == 1
    assert recovery_facts[0].content["is_error"] is True
    assert not isinstance(completed, ToolResult)


def test_resume_of_crashed_executing_checkpoint_enters_recovery() -> None:
    state = ConversationState(
        conversation_id="conversation-1",
        revision=7,
        next_action_seq=2,
        active_run=ActiveRun(
            run_id="run-1",
            status=ActiveRunStatus.RUNNABLE,
            phase=ContinuationPhase.EXECUTING,
            owner_invocation_id="dead-invocation",
            executing_intent=ExecutingIntentRecord(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                tool_call_id="call-1",
                intent_digest="intent-digest",
                idempotency_key="idempotency-1",
            ),
            tool_calls=(ToolCall("call-1", "explode", {}),),
        ),
    )
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=ExplodingToolRuntime(),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-2",
    )
    resume = Resume(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=7,
    )

    result = runtime.run_turn(resume, store.load())

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert result.request is not None
    assert result.request.binding_digest == "intent-digest"
    assert provider.calls == []
    assert store.state.active_run is not None
    assert store.state.active_run.status is ActiveRunStatus.AWAITING_RECOVERY


def test_public_observation_recovery_is_typed_exactly_once_and_never_resends() -> None:
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-public-observation")),
        ModelResponse((ModelToolCall("call-1", "web_search", {}),)),
        ModelResponse((ModelTextBlock("continued without retry"),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=ExplodingPublicObservationRuntime(),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-public",
    )
    paused = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="search",
        ),
        store.load(),
    )
    assert paused.status is RunStatus.AWAITING_RECOVERY
    assert len(provider.calls) == 2
    assert store.state.active_run is not None
    assert store.state.active_run.executing_intent is not None

    generic = ResolveUnknownToolOutcome(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_id=paused.request.request_id,
        binding_digest=paused.request.binding_digest,
        resolution=RecoveryResolution.MARK_FAILED,
    )
    generic_result = runtime.run_turn(generic, store.load())
    assert generic_result.status is RunStatus.CONFLICT
    assert generic_result.error_code == "typed_observation_recovery_required"

    action = RecoverUnknownObservation(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        tool_call_id="call-1",
        intent_digest="public-intent",
    )
    completed = runtime.run_turn(action, store.load())

    assert completed.status is RunStatus.COMPLETED
    assert len(provider.calls) == 3
    observations = [
        fact
        for fact in store.state.facts
        if fact.content.get("metadata", {}).get("code") == "observation_unknown"
    ]
    assert len(observations) == 1
    assert observations[0].content["metadata"]["source_receipts"] == []
    assert store.state.evidence_records == ()

    replayed = runtime.run_turn(action, store.load())
    assert replayed.status is RunStatus.COMPLETED
    assert replayed.replayed is True
    assert len(provider.calls) == 3
    assert len(
        [
            fact
            for fact in store.state.facts
            if fact.content.get("metadata", {}).get("code") == "observation_unknown"
        ]
    ) == 1


def test_public_observation_recovery_rejects_stale_or_cross_identity() -> None:
    state = ConversationState(
        conversation_id="conversation-1",
        revision=7,
        next_action_seq=2,
        active_run=ActiveRun(
            run_id="run-1",
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            executing_intent=ExecutingIntentRecord(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                tool_call_id="call-1",
                intent_digest="public-intent",
                idempotency_key="public-request-1",
                side_effect=SideEffectClass.READ_ONLY,
                egress=EgressClass.PUBLIC_NETWORK,
                operation="search",
                request_identity="public-request-1",
            ),
            tool_calls=(ToolCall("call-1", "web_search", {}),),
            pending_request=RecoveryRequest(
                request_id="recovery-public",
                run_id="run-1",
                tool_call_id="call-1",
                binding_digest="public-intent",
                summary="observation outcome unknown",
            ),
        ),
    )
    from agent.runtime.state import accept_action

    wrong_intent = accept_action(
        state,
        RecoverUnknownObservation(
            conversation_id="conversation-1",
            action_seq=2,
            expected_revision=7,
            tool_call_id="call-1",
            intent_digest="other-intent",
        ),
    )
    assert wrong_intent.disposition is ActionDisposition.CONFLICT
    assert wrong_intent.reason == "observation_recovery_mismatch"

    cross_conversation = accept_action(
        state,
        RecoverUnknownObservation(
            conversation_id="conversation-2",
            action_seq=2,
            expected_revision=7,
            tool_call_id="call-1",
            intent_digest="public-intent",
        ),
    )
    assert cross_conversation.disposition is ActionDisposition.CONFLICT
    assert cross_conversation.reason == "conversation_mismatch"
