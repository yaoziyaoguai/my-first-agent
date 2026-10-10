from __future__ import annotations

import threading

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    DirectResponse,
    ModelResponse,
    RunStatus,
    RuntimeEventKind,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import InMemoryCheckpointStore


class _ProgressSink:
    def __init__(self) -> None:
        self.events = []
        self.waiting_seen = threading.Event()

    def emit(self, event) -> None:  # noqa: ANN001
        self.events.append(event)
        if (
            event.kind is RuntimeEventKind.MODEL_PROGRESS
            and event.payload.get("phase") == "provider_waiting"
        ):
            self.waiting_seen.set()


class _WaitForHeartbeatProvider:
    def __init__(self, sink: _ProgressSink) -> None:
        self.sink = sink

    def generate(self, _context, *, delta_observer=None) -> ModelResponse:  # noqa: ANN001
        del delta_observer
        assert self.sink.waiting_seen.wait(timeout=1.0)
        return ModelResponse(
            (),
            control=DirectResponse("progress-done", "done"),
        )


def test_slow_nonstreaming_provider_emits_started_waiting_and_finished_advisories() -> None:
    state = ConversationState.new("conversation-progress")
    store = InMemoryCheckpointStore(state)
    sink = _ProgressSink()
    runtime = AgentRuntime(
        provider=_WaitForHeartbeatProvider(sink),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=sink,
        progress_event_sink=sink,
        limits=InvocationLimits(),
        provider_progress_interval_seconds=0.01,
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-progress",
            message="answer this",
        ),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    phases = [
        event.payload.get("phase")
        for event in sink.events
        if event.kind is RuntimeEventKind.MODEL_PROGRESS
    ]
    assert phases[0] == "provider_started"
    assert "provider_waiting" in phases
    assert phases[-1] == "provider_finished"
    assert all(
        event.advisory
        for event in sink.events
        if event.kind is RuntimeEventKind.MODEL_PROGRESS
    )


def test_transient_retry_persists_increasing_revision_between_attempts() -> None:
    """DU-14 子条件（2026-10-10 审计补证）：真实 Runtime 的 provider 重试
    必须在两次 generate 之间持久化递增的 state revision——每次前台调用前
    record_foreground_model_attempt 落盘（revision+1、model_calls_used+1），
    重试因此不可能复用旧 revision 的流式身份。前提由本测试锁定。"""

    from agent.provider.protocol import ProviderTransportError
    from agent.runtime.contracts import FactKind, ModelResponse, ModelTextBlock, SubmitMessage
    from tests.kernel.fakes import CollectingSink

    class _FlakyTransport:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
            self.calls += 1
            if self.calls == 1:
                # protocol 异常是 keyword-only 构造（不携带消息，防上游细节
                # 泄漏）；传位置参数会在 raise 处抛 TypeError 进入 generic
                # 分支——这是本测试第一次写错时实测踩到的坑。
                raise ProviderTransportError
            return ModelResponse((ModelTextBlock("recovered after retry"),))

    from agent.runtime.contracts import ConversationState

    state0 = ConversationState.new("conversation-retry")
    store = InMemoryCheckpointStore(state0)
    provider = _FlakyTransport()
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_retryable_provider_retries=1),
        invocation_id_factory=lambda: "invocation-retry",
    )
    initial_revision = state0.revision
    result = runtime.run_turn(
        SubmitMessage(
            conversation_id=state0.conversation_id,
            action_seq=state0.next_action_seq,
            expected_revision=state0.revision,
            run_id="run-retry",
            message="hello",
        ),
        store.load(),
    )

    assert result.status is not None
    assert provider.calls == 2, "bounded retry must issue exactly two provider attempts"
    final = store.state
    # 两次 generate 前各有一次 durable attempt 记录（revision 递增 ≥2）。
    assert final.revision >= initial_revision + 2, (
        final.revision,
        initial_revision,
    )
    # 重试路径的 durable 痕迹：transient-retry policy fact 落盘。
    assert any(
        fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code") == "provider_transient_retry"
        for fact in final.facts
    ), [fact.content.get("code") for fact in final.facts if fact.kind is FactKind.POLICY_RESULT]
    if result.status.value == "completed":
        assert result.message == "recovered after retry"
