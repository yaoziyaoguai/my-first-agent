from __future__ import annotations

from pathlib import Path

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    AbandonUnknownModelOutcome,
    ActiveRunStatus,
    ApprovalPolicy,
    BackgroundOccurrenceBindingV1,
    BeginAnswer,
    ContinuationPhase,
    ConversationState,
    ExecutionAuthorityClass,
    FactKind,
    KnownExecutedError,
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
from agent.scheduler.caller import ScheduledOccurrenceCaller, create_or_load_occurrence_store
from agent.scheduler.contracts import ScheduledOccurrence
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


class _CrashLocalCheckpointStore(LocalCheckpointStore):
    def __init__(self, path: Path, predicate) -> None:  # noqa: ANN001
        super().__init__(path)
        self._predicate = predicate
        self._crashed = False

    def compare_and_swap(self, snapshot, new_state):  # noqa: ANN001
        updated = super().compare_and_swap(snapshot, new_state)
        if not self._crashed and self._predicate(new_state):
            self._crashed = True
            raise _SimulatedProcessCrash
        return updated


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


def _runtime(
    store,
    provider,
    *,
    invocation_id: str = "invocation:one",
    tools: tuple[RegisteredTool, ...] = (),
) -> AgentRuntime:  # noqa: ANN001
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(tools),
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


def _occurrence() -> ScheduledOccurrence:
    return ScheduledOccurrence(
        schedule_id="automation:nightly-report",
        occurrence_id=_binding().occurrence_id,
        scheduled_for_utc=_binding().scheduled_for_utc,
        message="Give the bounded nightly status.",
        workspace_scope_digest="workspace:fixture",
        background_binding=_binding(),
    )


def _read_registration(
    invocations: list[str],
    *,
    fail_path: str | None = None,
    name: str = "read_recovery_fixture",
    approval_policy: ApprovalPolicy = ApprovalPolicy.NEVER,
) -> RegisteredTool:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name=name,
        version="1",
        description="Read a benign recovery fixture",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH if approval_policy is ApprovalPolicy.ALWAYS else ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=approval_policy,
        safety_policy={"fixture": True},
        output_limit_chars=100,
    )

    def read_fixture(intent) -> str | KnownExecutedError:  # noqa: ANN001
        path = intent.arguments["path"]
        invocations.append(path)
        if path == fail_path:
            return KnownExecutedError(
                code="fixture_read_failed",
                message=f"could not read {path}",
            )
        return f"content:{path}"

    return RegisteredTool(spec, read_fixture)


def _crash_occurrence_store(
    tmp_path: Path,
    predicate,
) -> tuple[ScheduledOccurrence, _CrashLocalCheckpointStore, Path]:  # noqa: ANN001
    occurrence = _occurrence()
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    create_or_load_occurrence_store(occurrence, state_root=state_root)
    checkpoint_path = state_root / occurrence.checkpoint_relative_path
    return (
        occurrence,
        _CrashLocalCheckpointStore(checkpoint_path, predicate),
        checkpoint_path,
    )


def _scheduled_caller(
    runtime: AgentRuntime,
    store: LocalCheckpointStore,
    occurrence: ScheduledOccurrence,
) -> ScheduledOccurrenceCaller:
    return ScheduledOccurrenceCaller(runtime, store, store.load(), occurrence)


def test_restart_after_durable_tool_batch_reclaims_and_executes_once(
    tmp_path: Path,
) -> None:
    occurrence, crash_store, checkpoint_path = _crash_occurrence_store(
        tmp_path,
        lambda item: (
            item.active_run is not None
            and item.active_run.status is ActiveRunStatus.RUNNABLE
            and item.active_run.phase is ContinuationPhase.TOOL
            and item.active_run.batch_cursor == 0
        ),
    )
    invocations: list[str] = []
    registration = _read_registration(invocations)
    first_provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-background-read")),
        ModelResponse(
            (
                ModelToolCall("call-a", "read_recovery_fixture", {"path": "a.txt"}),
                ModelToolCall("call-b", "read_recovery_fixture", {"path": "b.txt"}),
            )
        ),
    )
    first_runtime = _runtime(crash_store, first_provider, tools=(registration,))

    with pytest.raises(_SimulatedProcessCrash):
        _scheduled_caller(first_runtime, crash_store, occurrence).run_once()

    durable = LocalCheckpointStore(checkpoint_path).load().state
    assert durable.active_run is not None
    assert durable.active_run.status is ActiveRunStatus.RUNNABLE
    assert durable.active_run.phase is ContinuationPhase.TOOL
    assert durable.active_run.batch_cursor == 0
    assert durable.active_run.executing_intent is None
    assert len(durable.active_run.tool_calls) == 2
    assert invocations == []

    reopened = LocalCheckpointStore(checkpoint_path)
    resumed_provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    resumed_runtime = _runtime(
        reopened,
        resumed_provider,
        invocation_id="invocation:restart",
        tools=(registration,),
    )
    report = _scheduled_caller(resumed_runtime, reopened, occurrence).run_once()

    assert report.run_status is RunStatus.COMPLETED
    assert invocations == ["a.txt", "b.txt"]
    assert len(first_provider.calls) == 2
    assert len(resumed_provider.calls) == 1

    duplicate = _scheduled_caller(resumed_runtime, reopened, occurrence).run_once()
    assert duplicate.replayed is True
    assert invocations == ["a.txt", "b.txt"]
    assert len(resumed_provider.calls) == 1


def test_reclaimed_tool_suffix_still_stops_at_approval(
    tmp_path: Path,
) -> None:
    occurrence, crash_store, checkpoint_path = _crash_occurrence_store(
        tmp_path,
        lambda item: (
            item.active_run is not None
            and item.active_run.status is ActiveRunStatus.RUNNABLE
            and item.active_run.phase is ContinuationPhase.TOOL
            and item.active_run.batch_cursor == 1
        ),
    )
    ordinary_invocations: list[str] = []
    gated_invocations: list[str] = []
    ordinary = _read_registration(
        ordinary_invocations,
        name="read_recovery_fixture",
    )
    gated = _read_registration(
        gated_invocations,
        name="read_gated_recovery_fixture",
        approval_policy=ApprovalPolicy.ALWAYS,
    )
    first_provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-background-approval")),
        ModelResponse(
            (
                ModelToolCall(
                    "call-prefix",
                    "read_recovery_fixture",
                    {"path": "prefix.txt"},
                ),
                ModelToolCall(
                    "call-gated",
                    "read_gated_recovery_fixture",
                    {"path": "gated.txt"},
                ),
            )
        ),
    )

    with pytest.raises(_SimulatedProcessCrash):
        _scheduled_caller(
            _runtime(crash_store, first_provider, tools=(ordinary, gated)),
            crash_store,
            occurrence,
        ).run_once()

    assert ordinary_invocations == ["prefix.txt"]
    assert gated_invocations == []

    reopened = LocalCheckpointStore(checkpoint_path)
    resumed_provider = ScriptedProvider(AssertionError("provider must not be called"))
    resumed_runtime = _runtime(
        reopened,
        resumed_provider,
        invocation_id="invocation:restart",
        tools=(ordinary, gated),
    )
    report = _scheduled_caller(
        resumed_runtime,
        reopened,
        occurrence,
    ).run_once()

    assert report.run_status is RunStatus.AWAITING_APPROVAL
    assert report.occurrence_status == "needs_human"
    assert ordinary_invocations == ["prefix.txt"]
    assert gated_invocations == []
    assert len(resumed_provider.calls) == 0

    duplicate = _scheduled_caller(
        resumed_runtime,
        reopened,
        occurrence,
    ).run_once()
    assert duplicate.run_status is RunStatus.AWAITING_APPROVAL
    assert duplicate.replayed is True
    assert ordinary_invocations == ["prefix.txt"]
    assert gated_invocations == []
    assert len(resumed_provider.calls) == 0


def test_background_replay_never_retries_an_executing_tool(
    tmp_path: Path,
) -> None:
    occurrence, crash_store, checkpoint_path = _crash_occurrence_store(
        tmp_path,
        lambda item: (
            item.active_run is not None
            and item.active_run.status is ActiveRunStatus.RUNNABLE
            and item.active_run.phase is ContinuationPhase.EXECUTING
            and item.active_run.executing_intent is not None
        ),
    )
    invocations: list[str] = []
    registration = _read_registration(invocations)
    first_provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-background-executing")),
        ModelResponse(
            (
                ModelToolCall(
                    "call-executing",
                    "read_recovery_fixture",
                    {"path": "uncertain.txt"},
                ),
            )
        ),
    )

    with pytest.raises(_SimulatedProcessCrash):
        _scheduled_caller(
            _runtime(crash_store, first_provider, tools=(registration,)),
            crash_store,
            occurrence,
        ).run_once()

    durable = LocalCheckpointStore(checkpoint_path).load().state
    assert durable.active_run is not None
    assert durable.active_run.phase is ContinuationPhase.EXECUTING
    assert durable.active_run.executing_intent is not None
    assert invocations == []

    reopened = LocalCheckpointStore(checkpoint_path)
    resumed_provider = ScriptedProvider(AssertionError("provider must not be called"))
    report = _scheduled_caller(
        _runtime(
            reopened,
            resumed_provider,
            invocation_id="invocation:restart",
            tools=(registration,),
        ),
        reopened,
        occurrence,
    ).run_once()

    assert report.run_status is RunStatus.AWAITING_RECOVERY
    assert report.occurrence_status == "needs_human"
    assert invocations == []
    assert len(resumed_provider.calls) == 0


def test_restart_after_durable_tool_prefix_executes_only_remaining_suffix(
    tmp_path: Path,
) -> None:
    occurrence, crash_store, checkpoint_path = _crash_occurrence_store(
        tmp_path,
        lambda item: (
            item.active_run is not None
            and item.active_run.status is ActiveRunStatus.RUNNABLE
            and item.active_run.phase is ContinuationPhase.TOOL
            and item.active_run.batch_cursor == 2
        ),
    )
    invocations: list[str] = []
    registration = _read_registration(invocations, fail_path="b.txt")
    first_provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-background-prefix")),
        ModelResponse(
            tuple(
                ModelToolCall(
                    f"call-{name}",
                    "read_recovery_fixture",
                    {"path": f"{name}.txt"},
                )
                for name in ("a", "b", "c")
            )
        ),
    )

    with pytest.raises(_SimulatedProcessCrash):
        _scheduled_caller(
            _runtime(crash_store, first_provider, tools=(registration,)),
            crash_store,
            occurrence,
        ).run_once()

    durable = LocalCheckpointStore(checkpoint_path).load().state
    assert durable.active_run is not None
    assert durable.active_run.phase is ContinuationPhase.TOOL
    assert durable.active_run.batch_cursor == 2
    assert invocations == ["a.txt", "b.txt"]
    prefix = tuple(fact for fact in durable.facts if fact.kind is FactKind.TOOL_RESULT)
    assert [fact.content["tool_call_id"] for fact in prefix] == ["call-a", "call-b"]
    assert [fact.content["is_error"] for fact in prefix] == [False, True]

    reopened = LocalCheckpointStore(checkpoint_path)
    resumed_provider = ScriptedProvider(ModelResponse((ModelTextBlock("done"),)))
    report = _scheduled_caller(
        _runtime(
            reopened,
            resumed_provider,
            invocation_id="invocation:restart",
            tools=(registration,),
        ),
        reopened,
        occurrence,
    ).run_once()

    assert report.run_status is RunStatus.COMPLETED
    assert invocations == ["a.txt", "b.txt", "c.txt"]
    completed = reopened.load().state
    results = tuple(fact for fact in completed.facts if fact.kind is FactKind.TOOL_RESULT)
    assert results[:2] == prefix
    assert [fact.content["tool_call_id"] for fact in results] == [
        "call-a",
        "call-b",
        "call-c",
    ]
    assert sum(fact.kind is FactKind.TOOL_CALLS for fact in completed.facts) == 1
    assert len(first_provider.calls) == 2
    assert len(resumed_provider.calls) == 1


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
