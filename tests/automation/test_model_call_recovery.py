from __future__ import annotations

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    AbandonUnknownModelOutcome,
    ActiveRunStatus,
    BackgroundOccurrenceBindingV1,
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


class _SimulatedProcessCrash(BaseException):
    pass


class _CrashStore(InMemoryCheckpointStore):
    def __init__(self, state, predicate, *, after_persist: bool) -> None:  # noqa: ANN001
        super().__init__(state)
        self._predicate = predicate
        self._after_persist = after_persist
        self._crashed = False

    def compare_and_swap(self, snapshot, new_state):  # noqa: ANN001
        should_crash = not self._crashed and self._predicate(new_state)
        if should_crash and not self._after_persist:
            self._crashed = True
            raise _SimulatedProcessCrash
        updated = super().compare_and_swap(snapshot, new_state)
        if should_crash:
            self._crashed = True
            raise _SimulatedProcessCrash
        return updated


class _CrashAfterSendProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, _context):  # noqa: ANN001
        self.calls += 1
        raise _SimulatedProcessCrash


def _binding() -> BackgroundOccurrenceBindingV1:
    return BackgroundOccurrenceBindingV1.create(
        automation_id="automation:nightly-report",
        automation_revision=1,
        occurrence_id="occurrence:0000",
        occurrence_index=0,
        scheduled_for_utc="2026-08-28T00:00:00Z",
        definition_digest="1" * 64,
        grant_digest="2" * 64,
        claim_authority_digest="3" * 64,
        claim_capability_digest="4" * 64,
        checkpoint_identity_digest="5" * 64,
        deadline_utc="2026-08-28T00:10:00Z",
        model_call_limit=4,
        tool_call_limit=8,
        sandbox_command_limit=2,
        browser_action_limit=3,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
    )


def _action(state: ConversationState) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=1,
        expected_revision=0,
        run_id="run:background",
        message="Give the bounded nightly status.",
    )


def _runtime(store, provider, *, invocation_id: str = "invocation:one") -> AgentRuntime:  # noqa: ANN001
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: invocation_id,
    )


def _fresh_state() -> ConversationState:
    return ConversationState.new(
        "conversation:background",
        background_occurrence_binding=_binding(),
    )


def _response() -> ModelResponse:
    return ModelResponse((ModelTextBlock("background ok"),))


def test_restart_before_provider_intent_save_safely_sends_once() -> None:
    state = _fresh_state()
    store = _CrashStore(
        state,
        lambda item: (
            item.active_run is not None
            and item.active_run.status is ActiveRunStatus.MODEL_EXECUTING
        ),
        after_persist=False,
    )
    first_provider = ScriptedProvider(_response())
    with pytest.raises(_SimulatedProcessCrash):
        _runtime(store, first_provider).run_turn(_action(state), store.load())
    assert len(first_provider.calls) == 0

    resumed_provider = ScriptedProvider(_response())
    result = _runtime(
        store, resumed_provider, invocation_id="invocation:restart"
    ).run_turn(_action(state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert len(resumed_provider.calls) == 1


def test_restart_with_only_provider_intent_is_unknown_and_never_resends() -> None:
    state = _fresh_state()
    store = InMemoryCheckpointStore(state)
    first_provider = _CrashAfterSendProvider()
    with pytest.raises(_SimulatedProcessCrash):
        _runtime(store, first_provider).run_turn(_action(state), store.load())
    assert first_provider.calls == 1
    assert store.load().state.active_run.status is ActiveRunStatus.MODEL_EXECUTING

    resumed_provider = ScriptedProvider(_response())
    result = _runtime(
        store, resumed_provider, invocation_id="invocation:restart"
    ).run_turn(_action(state), store.load())

    assert result.status is RunStatus.FAILED_RETRYABLE
    assert result.error_code == "model_outcome_unknown"
    assert len(resumed_provider.calls) == 0
    assert store.load().state.active_run.status is ActiveRunStatus.MODEL_OUTCOME_UNKNOWN


def test_restart_consumes_durable_model_response_without_provider_resend() -> None:
    state = _fresh_state()
    store = _CrashStore(
        state,
        lambda item: (
            item.active_run is not None
            and item.active_run.persisted_model_response is not None
        ),
        after_persist=True,
    )
    first_provider = ScriptedProvider(_response())
    with pytest.raises(_SimulatedProcessCrash):
        _runtime(store, first_provider).run_turn(_action(state), store.load())
    assert len(first_provider.calls) == 1

    resumed_provider = ScriptedProvider(AssertionError("provider must not be called"))
    result = _runtime(
        store, resumed_provider, invocation_id="invocation:restart"
    ).run_turn(_action(state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert len(resumed_provider.calls) == 0


def test_restart_after_consumed_response_replays_terminal_result() -> None:
    state = _fresh_state()
    store = _CrashStore(
        state,
        lambda item: any(record.result is not None for record in item.replay_records),
        after_persist=True,
    )
    first_provider = ScriptedProvider(_response())
    with pytest.raises(_SimulatedProcessCrash):
        _runtime(store, first_provider).run_turn(_action(state), store.load())
    assert len(first_provider.calls) == 1

    resumed_provider = ScriptedProvider(AssertionError("provider must not be called"))
    result = _runtime(store, resumed_provider).run_turn(_action(state), store.load())

    assert result.status is RunStatus.COMPLETED
    assert result.replayed is True
    assert len(resumed_provider.calls) == 0


def test_exact_abandon_terminalizes_only_unknown_occurrence() -> None:
    state = _fresh_state()
    store = InMemoryCheckpointStore(state)
    with pytest.raises(_SimulatedProcessCrash):
        _runtime(store, _CrashAfterSendProvider()).run_turn(_action(state), store.load())
    _runtime(store, ScriptedProvider(_response())).run_turn(_action(state), store.load())
    unknown = store.load().state
    active = unknown.active_run
    assert active is not None and active.provider_call_intent is not None

    abandon = AbandonUnknownModelOutcome(
        conversation_id=unknown.conversation_id,
        action_seq=unknown.next_action_seq,
        expected_revision=unknown.revision,
        occurrence_id=_binding().occurrence_id,
        background_binding_digest=_binding().binding_digest,
        provider_call_intent_digest=active.provider_call_intent.intent_digest,
    )
    result = _runtime(store, ScriptedProvider(_response())).run_turn(abandon, store.load())

    assert result.status is RunStatus.FAILED_FATAL
    assert result.error_code == "model_outcome_abandoned"
    assert store.load().state.active_run is None


def test_abandon_rejects_another_occurrence_binding() -> None:
    state = _fresh_state()
    store = InMemoryCheckpointStore(state)
    with pytest.raises(_SimulatedProcessCrash):
        _runtime(store, _CrashAfterSendProvider()).run_turn(_action(state), store.load())
    _runtime(store, ScriptedProvider(_response())).run_turn(_action(state), store.load())
    unknown = store.load().state
    active = unknown.active_run
    assert active is not None and active.provider_call_intent is not None

    forged = AbandonUnknownModelOutcome(
        conversation_id=unknown.conversation_id,
        action_seq=unknown.next_action_seq,
        expected_revision=unknown.revision,
        occurrence_id="occurrence:another",
        background_binding_digest=_binding().binding_digest,
        provider_call_intent_digest=active.provider_call_intent.intent_digest,
    )
    provider = ScriptedProvider(AssertionError("provider must not be called"))
    result = _runtime(store, provider).run_turn(forged, store.load())

    assert result.status is RunStatus.CONFLICT
    assert len(provider.calls) == 0
    assert store.load().state.active_run == active
