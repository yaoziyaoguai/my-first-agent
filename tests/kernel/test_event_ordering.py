from __future__ import annotations

from pathlib import Path

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
    SubmitMessage,
)
from agent.runtime.events import CallbackEventSink, CollectingEventSink, EventReentryError
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink as FailingCollectingSink
from tests.kernel.fakes import InMemoryCheckpointStore, ScriptedProvider


def _event() -> RuntimeEvent:
    return RuntimeEvent(
        event_id="event-1",
        kind=RuntimeEventKind.WARNING,
        conversation_id="conversation-1",
        run_id="run-1",
        revision=2,
        causation_id="action:1",
        payload={"message": "fixture"},
    )


def test_collecting_sink_keeps_zero_or_more_contract_simple() -> None:
    sink = CollectingEventSink()
    sink.emit(_event())
    sink.emit(_event())

    assert [event.event_id for event in sink.events] == ["event-1", "event-1"]


def test_callback_sink_rejects_synchronous_reentry() -> None:
    holder = {}

    def callback(event):
        holder["sink"].emit(event)

    sink = CallbackEventSink(callback)
    holder["sink"] = sink

    with pytest.raises(EventReentryError):
        sink.emit(_event())


def test_state_referential_event_observes_committed_revision(tmp_path: Path) -> None:
    store = LocalCheckpointStore.initialize(
        tmp_path / "state" / "conversation.json",
        ConversationState.new("conversation-1"),
    )
    observations: list[tuple[int | None, int]] = []

    def observe(event: RuntimeEvent) -> None:
        observations.append((event.revision, store.load().state.revision))

    runtime = AgentRuntime(
        provider=ScriptedProvider(ModelResponse((ModelTextBlock("done"),))),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CallbackEventSink(observe),
        limits=InvocationLimits(durable_effect_reserve_bytes=100),
        invocation_id_factory=lambda: "invocation-1",
    )
    snapshot = store.load()
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    runtime.run_turn(action, snapshot)

    assert observations
    assert all(
        event_revision == stored_revision
        for event_revision, stored_revision in observations
    )


def test_event_callbacks_run_after_checkpoint_lease_release() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    lock_observations: list[bool] = []

    def observe(_event: RuntimeEvent) -> None:
        lock_observations.append(store.locked)

    runtime = AgentRuntime(
        provider=ScriptedProvider(ModelResponse((ModelTextBlock("done"),))),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CallbackEventSink(observe),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status.value == "completed"
    assert lock_observations
    assert lock_observations == [False]


def test_sink_failure_is_warning_and_committed_result_remains_authoritative() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=ScriptedProvider(ModelResponse((ModelTextBlock("done"),))),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=FailingCollectingSink(fail=True),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status.value == "completed"
    assert result.delivery_warnings
    assert store.state.active_run is None


def test_event_callback_cannot_submit_a_nested_action() -> None:
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("first"),)),
        ModelResponse((ModelTextBlock("nested must not run"),)),
    )
    nested_results = []
    holder = {}

    def observe(_event: RuntimeEvent) -> None:
        snapshot = store.load()
        nested_results.append(
            holder["runtime"].run_turn(
                SubmitMessage(
                    conversation_id="conversation-1",
                    action_seq=snapshot.state.next_action_seq,
                    expected_revision=snapshot.state.revision,
                    run_id="run-nested",
                    message="nested",
                ),
                snapshot,
            )
        )

    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CallbackEventSink(observe),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    holder["runtime"] = runtime

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

    assert result.status is RunStatus.COMPLETED
    assert len(nested_results) == 1
    assert nested_results[0].status is RunStatus.CONFLICT
    assert nested_results[0].error_code == "event_reentry_denied"
    assert store.state.next_action_seq == 2
    assert len(provider.calls) == 1
