from __future__ import annotations

from agent.cli.app import run_repl
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import ConversationState, ModelResponse, ModelTextBlock
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def test_fake_provider_walking_skeleton_prints_final_once() -> None:
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("final answer"),)))
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    sink = CollectingSink()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
                limits=ContextLimits(max_input_tokens=8_000, output_reserve=400),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=sink,
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )
    inputs = iter(("hello", "/exit"))
    output: list[str] = []

    exit_code = run_repl(
        runtime,
        store,
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        run_id_factory=lambda: "run-1",
    )

    assert exit_code == 0
    assert output.count("final answer") == 1
