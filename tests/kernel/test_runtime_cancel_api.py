"""Runtime.request_active_cancel 公开投递入口（Oracle #4，2026-10-25 审计）。

CLI 的 SIGINT 守卫与 TUI 的 request_control 共用同一条 control-inbox 通道；
本合同钉住三件事：
- 只有 run 期间 open 的 binding 可收 CANCEL（无 inbox / 无 binding → False，
  调用方退化到各自 fail-closed 路径，不部分成功）；
- 投递成功即排在 inbox，Runtime 在安全轮询点消费并写 CANCELLED 终态
  （端到端：provider 调用中投递 → run_turn 返回 CANCELLED）；
- request 只进 process-local inbox，不改 durable state。
"""

from __future__ import annotations

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ControlBinding,
    ConversationState,
    GoalProgress,
    ModelResponse,
    ModelTextBlock,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.control import ControlInbox, ControlRequestKind
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
    conversation_with_active_goal,
)


def _runtime(store, provider, inbox):  # noqa: ANN001, ANN202
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-cancel-api",
        control_inbox=inbox,
    )


def test_request_active_cancel_requires_inbox_and_open_binding() -> None:
    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    inbox = ControlInbox()
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("unused"),)))
    runtime = _runtime(store, provider, inbox)

    # binding 未 open：goal-less 会话、run 未开始、或已收尾。
    assert runtime.request_active_cancel(state.conversation_id) is False

    inbox.open(
        ControlBinding(
            conversation_id=state.conversation_id,
            goal_id=state.goal.goal_id,
            goal_revision=state.goal.revision,
            invocation_id="invocation-cancel-api",
        )
    )
    assert runtime.request_active_cancel(state.conversation_id) is True

    # 投递成功即排在 inbox：Runtime 的安全轮询点会取出 CANCEL。
    binding = inbox.current(state.conversation_id)
    request = inbox.poll(binding)
    assert request is not None
    assert request.kind is ControlRequestKind.CANCEL
    assert request.invocation_id == "invocation-cancel-api"


def test_request_active_cancel_without_inbox_returns_false() -> None:
    state = ConversationState.new("conversation-goalless")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(ModelResponse((ModelTextBlock("unused"),)))
    runtime = _runtime(store, provider, inbox=None)
    assert runtime.request_active_cancel(state.conversation_id) is False


def _trusted_goal(context) -> dict | None:  # noqa: ANN001, ANN202
    return next(
        (
            block
            for message in context.messages
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "trusted_goal"
        ),
        None,
    )


class _CancelDuringGenerateProvider:
    """在 provider 调用中模拟界面投递：generate 时 binding 已 open。

    等价于 CLI SIGINT 守卫/TUI 控件在 run_turn 阻塞期间调用
    request_active_cancel；返回合法非终态 GoalProgress 让 Runtime 走到
    下一个安全轮询点消费该请求。
    """

    deadline_contract = ScriptedProvider.deadline_contract

    def __init__(self, runtime_ref, conversation_id: str) -> None:  # noqa: ANN001
        self._runtime_ref = runtime_ref
        self._conversation_id = conversation_id

    def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
        goal = _trusted_goal(context)
        assert goal is not None
        runtime = self._runtime_ref[0]
        assert runtime.request_active_cancel(self._conversation_id) is True
        # 同一 invocation 的重复投递也必须可收（每次 request_id 唯一）。
        assert runtime.request_active_cancel(self._conversation_id) is True
        return ModelResponse(
            (ModelTextBlock("working"),),
            control=GoalProgress(
                correlation_id="progress-cancel-api",
                goal_id=goal["goal_id"],
                goal_revision=goal["goal_revision"],
                summary="working",
                next_step="continue",
            ),
        )


def test_request_active_cancel_flows_to_cancelled_terminal() -> None:
    """端到端：provider 调用中投递 CANCEL → run_turn 以 CANCELLED 终态返回。"""

    state = conversation_with_active_goal()
    store = InMemoryCheckpointStore(state)
    inbox = ControlInbox()
    provider_box: list = []
    provider = _CancelDuringGenerateProvider(provider_box, state.conversation_id)
    runtime = _runtime(store, provider, inbox)
    provider_box.append(runtime)

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            run_id="run-cancel-api",
            message="do the work",
        ),
        store.load(),
    )
    assert result.status is RunStatus.CANCELLED
    assert result.message == "goal cancelled at a safe boundary"
    # 投递只进 process-local inbox；终态由 Runtime 在安全边界写入 durable
    # state（goal 终态 CANCELLED），不存在绕过 reducer 的路径。
    assert store.state.goal is not None
    from agent.runtime.contracts import GoalStatus

    assert store.state.goal.status is GoalStatus.CANCELLED
