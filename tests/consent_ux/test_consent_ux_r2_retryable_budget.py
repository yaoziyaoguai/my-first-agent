"""oracle r2 §F-4：retryable 计数跨 resume 重置反例（红则修）。

`retryable_provider_retries` 是 `_drive` 局部变量且在 run_turn 内不复位
（累计语义）。consent/审批/暂停会拆分 run_turn——若每次恢复都归零，调用方
只要反复 Resume，就能在同一个 durable run 上无限获得新的瞬态重试额度，
突破 `max_retryable_provider_retries`（SPEC S1/S6：不提升既有执行预算）。

修复模式与 `_run_invalid_repairs` 相同：从 durable 的 run 级
`provider_transient_retry` policy facts **累计**重建（该计数器在 run 内
不被有效响应复位，不能用尾部连续语义）。
"""

from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    Resume,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.ports import RetryableProviderError as _PortRetryable
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore


class _AlwaysTransientProvider:
    """每次 generate 都抛可安全重试的瞬态错误。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        error = _PortRetryable("simulated transient timeout")
        error.code = "provider_timeout"  # noqa: B010
        raise error


def _runtime(store, provider) -> AgentRuntime:
    return AgentRuntime(
        provider=provider,
        provider_descriptor=None,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(max_retryable_provider_retries=1),
        invocation_id_factory=lambda: "inv-r2d",
    )


def _submit(state: ConversationState) -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-1",
        message="hello",
    )


def _resume(state: ConversationState) -> Resume:
    return Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )


def test_consent_ux_r2_retryable_budget_survives_resume() -> None:
    state = ConversationState.new("conversation-1")
    store = InMemoryCheckpointStore(state)
    provider = _AlwaysTransientProvider()
    runtime = _runtime(store, provider)

    first = runtime.run_turn(_submit(store.state), store.load())
    assert first.status is RunStatus.FAILED_RETRYABLE
    # run_turn 内：1 次尝试 + 1 次重试 = 2 次派发，之后额度用尽失败。
    in_turn_calls = provider.calls
    assert in_turn_calls == 2

    # 跨 resume：额度必须从 durable facts 重建——同一个 run 不得再获得
    # 新的重试预算（恢复只允许 1 次终试，绝不能回到 3 次/每次恢复）。
    second = runtime.run_turn(_resume(store.state), store.load())
    assert second.status is RunStatus.FAILED_RETRYABLE
    assert provider.calls - in_turn_calls <= 1, (
        "retryable budget reset across resume: "
        f"{provider.calls - in_turn_calls} extra sends after resume"
    )

    third = runtime.run_turn(_resume(store.state), store.load())
    assert third.status is RunStatus.FAILED_RETRYABLE
    assert provider.calls - in_turn_calls <= 2
