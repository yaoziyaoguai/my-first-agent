from __future__ import annotations

import builtins

from agent.cli.app import run_headless
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import ConversationState, ModelResponse, ModelTextBlock, SubmitMessage
from agent.runtime.events import CollectingEventSink
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import InMemoryCheckpointStore, ScriptedProvider


def test_headless_uses_typed_action_without_terminal_io(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("headless path touched terminal IO")

    monkeypatch.setattr(builtins, "input", fail)
    monkeypatch.setattr(builtins, "print", fail)
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=ScriptedProvider(ModelResponse((ModelTextBlock("done"),))),
        context_manager=KernelContextManager(
            system_policy="policy",
                limits=ContextLimits(max_input_tokens=8_000, output_reserve=400),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingEventSink(),
        limits=InvocationLimits(),
    )
    snapshot = store.load()
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    result = run_headless(runtime, store, action)

    assert result.status.value == "completed"
    assert result.message == "done"
    assert snapshot.state.revision == 0
