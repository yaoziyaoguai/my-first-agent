"""终态 run 记录保留模型 usage（2026-10-10 审计可观测性缺口修复）。

ActiveRun 期间 model_calls_used/input/output_tokens_used 是 durable 的，但
run 终止（complete/fail）后 active_run 清空，这些计数随 RecordedRunResult
一起丢失——真实 Dogfood 后无法从 checkpoint 复核 Token/费用。本合同要求
终态 last_safe_result 保留本次 run 的 usage。

RC-03（2026-10-11 审计）：PAUSE/CORRECT/CANCEL 走 `_poll_control` →
`apply_control_request` 时先清空 active_run，`_finish` 再读用量已无来源，
返回值 calls=0、durable 三字段=null。修复要求在 reducer 之前捕获用量并
贯穿返回值与持久化结果；下面三条控制路径的回归走真实累积路径（真实
provider 调用产生非零 usage），不手写 usage 字段。
"""

from __future__ import annotations

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    GoalProgress,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.control import (
    ControlInbox,
    ControlInboxRequest,
    ControlRequestKind,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


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


def _trusted_goal(context) -> dict | None:
    return next(
        (
            block
            for message in context.messages
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "trusted_goal"
        ),
        None,
    )


class _ControlSubmittingProvider:
    """真实累积 usage 的 provider：第一次响应后投递控制请求。

    第一次 generate 让 Runtime 走完整的 provider intent → response → usage
    入账路径（真实非零 input tokens），第二次 generate 之前把控制请求放进
    与 TUI 相同的 ControlInbox；Runtime 在安全轮询点消费它。
    """

    deadline_contract = ScriptedProvider.deadline_contract

    def __init__(self, inbox: ControlInbox, kind: ControlRequestKind) -> None:
        self.inbox = inbox
        self.kind = kind
        self.calls = 0

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        self.calls += 1
        if self.calls == 1:
            goal = _trusted_goal(context)
            assert goal is not None
            return ModelResponse(
                (ModelTextBlock("working"),),
                control=GoalProgress(
                    correlation_id=f"progress-{self.kind.value}",
                    goal_id=goal["goal_id"],
                    goal_revision=goal["goal_revision"],
                    summary="working",
                    next_step="continue",
                ),
            )
        binding = self.inbox.current("conversation-1")
        assert binding is not None, "control binding must be open at the poll point"
        self.inbox.submit(
            ControlInboxRequest(
                request_id=f"control-{self.kind.value}",
                kind=self.kind,
                conversation_id=binding.conversation_id,
                goal_id=binding.goal_id,
                goal_revision=binding.goal_revision,
                invocation_id=binding.invocation_id,
                message="switch the target to reports/brief.md"
                if self.kind is ControlRequestKind.CORRECT
                else None,
            )
        )
        return ModelResponse((ModelTextBlock("continuing"),))


@pytest.mark.parametrize(
    ("kind", "expected_status", "expected_goal_status"),
    (
        (ControlRequestKind.PAUSE, RunStatus.COMPLETED, GoalStatus.PAUSED),
        (ControlRequestKind.CORRECT, RunStatus.COMPLETED, GoalStatus.NEEDS_AUTHORITY),
        (ControlRequestKind.CANCEL, RunStatus.CANCELLED, GoalStatus.CANCELLED),
    ),
)
def test_control_terminal_result_preserves_accumulated_run_usage(
    kind: ControlRequestKind,
    expected_status: RunStatus,
    expected_goal_status: GoalStatus,
) -> None:
    """RC-03：三种控制都在清除 active_run 前保全本次 run 已累积的真实用量。

    Red（修复前）：`apply_control_request` 先清空 active_run，`_finish` 只能读到
    None → 返回值 model_calls_used=0、durable 三字段全为 null，即使本 run 已经
    真实发生过 provider 调用。Green：返回值与 durable 记录都保留累积值，且新
    store 实例（reopen）读回同一结果。
    """

    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    inbox = ControlInbox()
    provider = _ControlSubmittingProvider(inbox, kind)
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
        control_inbox=inbox,
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-usage",
            message="continue",
        ),
        store.load(),
    )

    # 控制确实在安全边界被消费（不是绕过 inbox 的假路径）。
    assert provider.calls == 2
    assert result.status is expected_status
    assert store.state.active_run is None
    assert store.state.goal is not None
    assert store.state.goal.status is expected_goal_status

    # 本次 run 在控制到达前已经真实发生过 2 次 provider 调用。
    assert result.model_calls_used == 2

    recorded = store.state.last_safe_result
    assert recorded is not None
    assert recorded.model_calls_used == 2
    assert (recorded.input_tokens_used or 0) > 0
    # reopen（新 store 实例读同一 checkpoint）后仍可读同一用量。
    reloaded = store.load().state
    assert reloaded.last_safe_result is not None
    assert reloaded.last_safe_result.model_calls_used == 2
    assert reloaded.last_safe_result.input_tokens_used == recorded.input_tokens_used


def test_control_terminal_usage_is_not_reported_as_fake_zero() -> None:
    """RC-03：已发生调用但用量来源不可用时，不得编造为真实 0。

    无 provider 调用的终态（例如 operator 释放路径）与"确实调用过"的终态在
    RecordedRunResult 上必须可区分：前者保留 None 表示未知，后者写出真实计数。
    """

    # 已知：真实调用过的 run 终态 usage 非零（上一条测试已断言）。
    # 未知：未经过任何 provider 调用的 run 终态，usage 为 None 而不是 0。
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    runtime = AgentRuntime(
        provider=ScriptedProvider(ModelResponse((ModelTextBlock("unused"),))),
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

    # PauseGoal 是纯控制 action：不进入 _drive、不发生 provider 调用。
    from agent.runtime.contracts import PauseGoal

    assert state.goal is not None
    result = runtime.run_turn(
        PauseGoal(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            goal_id=state.goal.goal_id,
            goal_revision=state.goal.revision,
        ),
        store.load(),
    )

    assert result.status is RunStatus.COMPLETED
    assert store.state.goal is not None
    assert store.state.goal.status is GoalStatus.PAUSED
    # 该路径没有 active run，因此"用量未知"必须保持 None，不能伪装成真实 0。
    recorded = store.state.last_safe_result
    assert recorded is not None
    assert recorded.model_calls_used is None
    assert recorded.input_tokens_used is None
    assert recorded.output_tokens_used is None
