from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import ConversationState, ModelResponse, RunStatus, SubmitMessage
from agent.runtime.loop import AgentRuntime, InvocationLimits, RetryableProviderError
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def _run(provider, *, repairs=1):
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
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
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
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
