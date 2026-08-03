from __future__ import annotations

from dataclasses import replace

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    AdmittedCriterion,
    CompletionClaim,
    ControlReceipt,
    ConversationState,
    EvidenceOracleKind,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.evidence import ClosedEvidenceRegistry
from agent.runtime.loop import AgentRuntime, InvocationLimits, RetryableProviderError
from agent.runtime.ports import InvalidProviderResponseError
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _run(provider, *, repairs=1, state: ConversationState | None = None):
    initial = state or ConversationState.new("conversation-1")
    store = InMemoryCheckpointStore(initial)
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_invalid_repairs=repairs),
        invocation_id_factory=lambda: "invocation-1",
    )
    action = SubmitMessage(
        conversation_id=initial.conversation_id,
        action_seq=initial.next_action_seq,
        expected_revision=initial.revision,
        run_id="run-1",
        message="hello",
    )
    return runtime.run_turn(action, store.load()), store


def test_transient_provider_error_is_retryable_pause() -> None:
    result, store = _run(ScriptedProvider(RetryableProviderError("timeout")))

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert store.state.active_run is not None


def test_invalid_provider_output_has_bounded_repair_then_fails_fatal() -> None:
    result, store = _run(
        ScriptedProvider(ModelResponse(()), ModelResponse(())),
        repairs=1,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert store.state.active_run is None


def test_invalid_provider_response_can_recover_once_without_tool_effect() -> None:
    result, store = _run(
        ScriptedProvider(
            InvalidProviderResponseError("malformed_tool_call"),
            ModelResponse((ModelTextBlock("recovered"),)),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.message == "recovered"
    assert [
        fact.content["code"]
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_provider_response"
    ] == ["invalid_provider_response"]
    repair_fact = next(
        fact
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_provider_response"
    )
    assert "malformed_tool_call" in repair_fact.content["text"]


def test_repeated_invalid_provider_response_fails_closed() -> None:
    result, store = _run(
        ScriptedProvider(
            InvalidProviderResponseError("malformed_control"),
            InvalidProviderResponseError("malformed_control"),
        ),
        repairs=1,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_provider_response"
    assert store.state.active_run is None


def test_repeated_invalid_completion_control_exhausts_shared_repair_budget() -> None:
    seed = conversation_with_active_goal()
    assert seed.goal is not None
    criterion = AdmittedCriterion(
        criterion_id="criterion-confirmed",
        description="owner confirms the bounded result",
        source_fact_id="action:1:user",
        oracle_kind=EvidenceOracleKind.USER_CONFIRMATION,
        predicate={"confirmed": True},
        required_evidence_class="user_confirmation",
        admission_digest="runtime-admission-confirmed",
    )
    source = replace(
        seed.facts[0],
        content={
            "text": "please persist the fixture note",
            "criterion_id": criterion.criterion_id,
            "confirmed": True,
        },
    )
    correlation_id = "already-used-completion"
    seed = replace(
        seed,
        facts=(source,),
        goal=replace(seed.goal, admitted_criteria=(criterion,)),
        control_receipts=(
            ControlReceipt.create(
                correlation_id=correlation_id,
                control_kind="goal_progress",
                goal_id=seed.goal.goal_id,
                goal_revision=seed.goal.revision,
                accepted_state_revision=seed.revision,
                payload_digest="prior-control-payload",
            ),
        ),
    )
    claim = CompletionClaim(
        correlation_id=correlation_id,
        goal_id=seed.goal.goal_id,
        goal_revision=seed.goal.revision,
        criterion_evidence_refs=(
            ClosedEvidenceRegistry.evidence_id(
                seed.goal.goal_id,
                seed.goal.revision,
                criterion.criterion_id,
            ),
        ),
    )

    result, store = _run(
        ScriptedProvider(
            ModelResponse((), control=claim),
            ModelResponse((), control=claim),
        ),
        repairs=1,
        state=seed,
    )

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "invalid_model_control"
    assert store.state.active_run is None
    assert [
        fact.content.get("code")
        for fact in store.state.facts
        if fact.content.get("code") == "invalid_model_control"
    ] == ["invalid_model_control"]
