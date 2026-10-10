"""终态 run 记录保留模型 usage（2026-10-10 审计可观测性缺口修复）。

ActiveRun 期间 model_calls_used/input/output_tokens_used 是 durable 的，但
run 终止（complete/fail）后 active_run 清空，这些计数随 RecordedRunResult
一起丢失——真实 Dogfood 后无法从 checkpoint 复核 Token/费用。本合同要求
终态 last_safe_result 保留本次 run 的 usage。
"""

from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider


def _runtime_and_store():
    state = ConversationState.new("conversation-usage")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(
        ModelResponse((ModelTextBlock("usage recorded"),)),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-usage",
    )
    return runtime, store, state


def test_completed_run_result_retains_model_usage() -> None:
    runtime, store, state = _runtime_and_store()
    runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-usage",
            message="hello",
        ),
        store.load(),
    )

    final = store.state
    recorded = final.last_safe_result
    assert recorded is not None
    # 终态记录保留本次 run 的 usage（Red：旧实现这些字段不存在/为 None）。
    assert recorded.model_calls_used == 1
    assert (recorded.input_tokens_used or 0) > 0
    # reopen（新 store 实例读同一 checkpoint）后仍可读。
    reloaded = store.load().state
    assert reloaded.last_safe_result is not None
    assert reloaded.last_safe_result.model_calls_used == 1
