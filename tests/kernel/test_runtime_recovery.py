from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ContinuationPhase,
    ConversationState,
    ExecutingIntentRecord,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RecoveryResolution,
    ResolveUnknownToolOutcome,
    Resume,
    RunStatus,
    SubmitMessage,
    ToolCall,
    ToolResult,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


class ExplodingToolRuntime:
    def definitions(self):
        from agent.runtime.contracts import ToolDefinition

        return (ToolDefinition("explode", "explode after persist", {"type": "object"}),)

    def prepare(self, call, context, approval=None):
        from agent.runtime.contracts import ExecutionIntent, SideEffectClass

        return ExecutionIntent(
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
        )

    def invoke(self, intent):
        raise RuntimeError("unknown after external boundary")


def test_unknown_tool_outcome_never_retries_automatically() -> None:
    provider = ScriptedProvider(
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
    assert len(provider.calls) == 1

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
    assert len(provider.calls) == 2
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
