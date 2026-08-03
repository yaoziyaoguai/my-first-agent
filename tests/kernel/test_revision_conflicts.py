from __future__ import annotations

from dataclasses import replace

from agent.runtime.checkpoint import InMemoryCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.events import CollectingEventSink
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import ScriptedProvider


def test_stale_initial_snapshot_returns_current_conflict_without_effect() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("must not run"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    stale = store.load()
    lease = store.try_acquire("conversation-1")
    assert lease is not None
    store.compare_and_swap(stale, replace(stale.state, revision=1))
    lease.release()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=1_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingEventSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
        stale,
    )

    assert result.status is RunStatus.CONFLICT
    assert result.error_code == "checkpoint_conflict"
    assert result.state.revision == 1
    assert provider.calls == []
