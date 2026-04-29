"""v0.4 transition 命名与最小 command slice。

这个模块只提供轻量的事件 / 结果词汇，帮助 v0.4 Phase 1 先把
transition boundary 测试写清楚。它不是新的 Runtime 主流程，不接管
`core.py` / handlers，不写 checkpoint，也不承载 CLI DisplayEvent。

中文学习边界：
- RuntimeEventKind 是“发生了什么”的候选名称，当前代码仍可能由既有
  handlers 直接修改 TaskState。
- TransitionResult 是“Runtime 临时决策结果”的草案结构，只放 JSON 友好
  的基础字段，避免把 DisplayEvent / RuntimeEvent / InputIntent /
  CommandResult 这类临时 UI/协议对象混进 checkpoint 或 messages。
- command event slice 只覆盖 health/logs 维护命令的 no-op transition，
  证明维护命令可以产生输出，但不改变 task execution state。
- ToolResult slice 先覆盖 policy denial / user rejection / tool failure 的
  transition 意图，不接管完整工具执行，也不改变 tool_result 消息协议。
- 本模块存在不代表 v0.4 完整事件驱动状态机已经实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RuntimeEventKind(str, Enum):
    """v0.4 第一阶段候选事件名，不绑定当前完整实现。"""

    USER_INPUT = "user_input"
    MODEL_OUTPUT = "model_output"
    TOOL_RESULT = "tool_result"
    POLICY_DENIAL = "policy_denial"
    USER_REJECTION = "user_rejection"
    CHECKPOINT_RESUME = "checkpoint_resume"
    HEALTH_COMMAND = "health_command"
    LOGS_COMMAND = "logs_command"


class ToolResultTransitionKind(str, Enum):
    """ToolResult 边界的最小 transition 词汇。

    中文学习边界：这些值只描述“工具调用之后 Runtime 应该怎么处理状态”，
    不描述 Anthropic `tool_result` 消息本身，也不应该被写入 checkpoint。
    v0.4 Phase 1 先用它统一 policy denial / user rejection / tool failure
    这类低风险切片，tool success 的完整迁移后续再逐步收敛。
    """

    TOOL_SUCCESS = "tool_success"
    TOOL_FAILURE = "tool_failure"
    POLICY_DENIAL = "policy_denial"
    USER_REJECTION = "user_rejection"


@dataclass(frozen=True, slots=True)
class TransitionResult:
    """未来 transition 层的最小返回草案。

    字段都保持为基础类型或字符串 tuple，便于测试边界：这不是 checkpoint
    schema，也不是 DisplayEvent 队列。后续迁移时，handler 可以先返回这种
    结果对象，再由调用方决定是否保存 checkpoint / 渲染 UI。

    注意：`display_events` 目前只存临时输出事件名字符串，不存 DisplayEvent
    对象本体。这样测试能确认“可展示输出”和“持久状态”没有混线。
    """

    next_status: str | None = None
    should_checkpoint: bool = False
    clear_pending_tool: bool = False
    clear_pending_user_input: bool = False
    advance_step: bool = False
    display_events: tuple[str, ...] = ()
    reason: str = ""
    notes: tuple[str, ...] = ()


# 兼容上一轮 prep 文档和测试使用的名字。v0.4 后续正式定名时再统一收敛，
# 当前不做大范围 rename，避免把“命名准备”变成 runtime 迁移。
TransitionOutcome = TransitionResult


def command_event_transition(kind: RuntimeEventKind) -> TransitionResult:
    """把维护命令映射成 no-op transition。

    这是 v0.4 Phase 1 的第一个最小事件切片：`health` / `logs` 是 Runtime
    维护命令，可以产生 stdout/JSON/log viewer 输出，但不应该改变 TaskState、
    不应该清 pending、不应该推进 step，也不应该触发 task checkpoint。

    只接受 HealthCommand / LogsCommand，避免把业务事件误塞进这个 no-op 通道。
    """

    if kind == RuntimeEventKind.HEALTH_COMMAND:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            display_events=("health.report",),
            reason=kind.value,
            notes=("maintenance command; no task transition",),
        )
    if kind == RuntimeEventKind.LOGS_COMMAND:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            display_events=("logs.viewer",),
            reason=kind.value,
            notes=("maintenance command; no task transition",),
        )
    raise ValueError(f"unsupported command event kind: {kind.value}")


def tool_result_transition(
    kind: ToolResultTransitionKind,
    *,
    from_pending_tool: bool = False,
) -> TransitionResult:
    """把工具结局映射到轻量 TransitionResult。

    这是 v0.4 Phase 1 的 ToolResult 最小切片入口：返回值只告诉既有 handler
    “是否清 pending / 是否 checkpoint / 是否推进 step / 用哪个临时 display event”。
    它不写 messages、不保存 checkpoint、不执行工具，也不替代 `tool_result`
    协议配对。调用方仍然负责按现有流程写 durable facts。

    `from_pending_tool` 用来表达真实语义差异：直接执行的 tool failure 没有
    pending_tool 可清；用户确认后执行的 tool failure 则由 confirmation handler
    在执行完成后清 pending。本 helper 只描述意图，不替调用方猜上下文。
    """

    if kind == ToolResultTransitionKind.TOOL_SUCCESS:
        return TransitionResult(
            should_checkpoint=True,
            clear_pending_tool=from_pending_tool,
            advance_step=False,
            display_events=("tool.completed",),
            reason=kind.value,
            notes=("tool result message remains the durable protocol fact",),
        )
    if kind == ToolResultTransitionKind.TOOL_FAILURE:
        return TransitionResult(
            should_checkpoint=True,
            clear_pending_tool=from_pending_tool,
            advance_step=False,
            display_events=("tool.failed",),
            reason=kind.value,
            notes=(
                "tool failure is observable but does not complete a step directly",
                "tool result message remains the durable protocol fact",
            ),
        )
    if kind == ToolResultTransitionKind.POLICY_DENIAL:
        return TransitionResult(
            should_checkpoint=True,
            clear_pending_tool=True,
            advance_step=False,
            display_events=("tool.rejected",),
            reason=kind.value,
            notes=("policy denial is not user rejection and is not tool failure",),
        )
    if kind == ToolResultTransitionKind.USER_REJECTION:
        return TransitionResult(
            should_checkpoint=True,
            clear_pending_tool=True,
            advance_step=False,
            display_events=("tool.user_rejected",),
            reason=kind.value,
            notes=("user rejection is explicit human choice, not security policy",),
        )
    raise ValueError(f"unsupported tool transition kind: {kind.value}")


class ModelOutputKind(str, Enum):
    """v0.4 Phase 1 slice 5：模型输出分类的统一词汇。

    中文学习边界：
    - 这一组值用于把 Anthropic SDK 返回的 ``stop_reason`` 收敛成
      Runtime 自己的分类标签，让 ``agent/core.py`` 的循环 dispatch
      不再用四处散落的 inline 字符串比较来决定走哪个 handler。
    - 它**不是**新的状态机、**不是**新的事件总线，也**不**接管
      ``response_handlers.py`` 里的 state mutation / messages 写入 /
      checkpoint / `consecutive_*` 计数器——这些仍由原 handler 各自负责，
      slice 5 只把"是哪一种模型输出"这一条边界提取出来。
    - ``UNKNOWN`` 必须显式存在：未知 stop_reason 不能被静默归到 end_turn /
      tool_use / max_tokens 任何一类，否则会把 LLM SDK 的协议变更或异常
      响应伪装成"正常完成"——本切片的核心防回归点。
    - 后续 slice 6 用户确认 transition、Phase 2 主循环瘦身才会基于这个
      分类层进一步把 dispatch 集中；本切片不做这些扩展。
    """

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    UNKNOWN = "unknown"


def classify_model_output(stop_reason: str | None) -> ModelOutputKind:
    """把 ``response.stop_reason`` 收敛成 :class:`ModelOutputKind`。

    中文学习边界：
    - 纯函数：不读 state、不写 messages、不发 RuntimeEvent、不动 checkpoint。
      调用方拿到结果再决定 dispatch / 日志 / display；分类与副作用解耦。
    - 任何不在已知白名单内的 stop_reason（包括 ``None`` / 空串 / 大小写
      变体 / SDK 未来新增字段）一律返回 :attr:`ModelOutputKind.UNKNOWN`，
      避免"静默成功"——下游必须显式处理 UNKNOWN 才能继续。
    - 不接管 stop_reason 之外的细节（比如 ``stop_sequence`` / ``refusal``）；
      那些在未来 slice 中独立判断，本切片只覆盖当前 ``core.py`` dispatcher
      已经在用的 4 个分支。
    """

    if stop_reason == "end_turn":
        return ModelOutputKind.END_TURN
    if stop_reason == "tool_use":
        return ModelOutputKind.TOOL_USE
    if stop_reason == "max_tokens":
        return ModelOutputKind.MAX_TOKENS
    return ModelOutputKind.UNKNOWN


class PlanConfirmationKind(str, Enum):
    """v0.4 Phase 1 slice 6（plan 子切片）：plan 确认结局的统一词汇。

    中文学习边界：
    - 这一组值描述用户对**已生成的 plan** 的最终决定（接受 / 拒绝），
      让 ``handle_plan_confirmation`` 的两条分支不再仅靠 inline 字符串
      （``"accept"`` / ``"reject"``）和散落的 ``state.task.status = "running"``
      赋值来表达意图。
    - 它**不**覆盖 step 确认（涉及 ``advance_current_step_if_needed``）、
      也**不**覆盖 tool 确认（涉及 ``pending_tool``）、也**不**覆盖
      user_input / feedback_intent 确认（涉及 ``pending_user_input_request``）；
      这些 confirmation 各自有不同的 mutation 语义，强行用同一枚举会把
      slice 6 的边界模糊化。后续每个 confirmation 走自己的 *Kind 是为了
      让 transition 词汇直接对应真实状态变更。
    - 「feedback 三选一」分支（用户既不接受也不直接拒绝，要求修改 plan）
      不在这里映射：那条路径是切到 ``awaiting_feedback_intent`` 子状态，
      不属于 plan 本身的最终结局；本切片刻意不抽象它，留给后续 slice。
    - 不写 messages、不动 checkpoint、不调 planner、不 reset task；
      实际副作用仍由 ``handle_plan_confirmation`` 完成。
    """

    PLAN_ACCEPTED = "plan_accepted"
    PLAN_REJECTED = "plan_rejected"


def plan_confirmation_transition(kind: PlanConfirmationKind) -> TransitionResult:
    """把 plan 确认结局映射到轻量 :class:`TransitionResult`。

    中文学习边界：
    - 与 :func:`tool_result_transition` 同形：只描述「Runtime 应该如何
      处理这次 plan 确认」的意图，不替 handler 写 messages、不直接调
      ``save_checkpoint`` / ``clear_checkpoint`` / ``state.reset_task``。
    - ``PLAN_ACCEPTED``：should_checkpoint=True，下一状态是 ``"running"``，
      让循环继续按 plan 推进；display 事件用 ``plan.accepted``，与现有
      ``plan_confirm_yes`` control event 命名意图一致但属于 transition 层
      命名，不冲突。
    - ``PLAN_REJECTED``：用户主动取消任务。Runtime 应该清掉 task 状态
      （``state.reset_task()``）并删除 checkpoint，因此 ``should_checkpoint``
      保持 False（**不**写新的 checkpoint），但 notes 里明确指出 handler
      仍需要 ``clear_checkpoint``——这一点目前由 handler 自己执行，等后续
      slice 把这种「负向落盘」也统一时，再扩展 :class:`TransitionResult`
      字段，避免本切片就引入新字段污染语义。
    - 不接受其他枚举值；任何未来扩展（plan 修改 / plan 重生成 / feedback
      三选一）都应另起新 kind，而不是在这里加分支，避免「一个 helper 决
      策一切」的反模式。
    """

    if kind == PlanConfirmationKind.PLAN_ACCEPTED:
        return TransitionResult(
            next_status="running",
            should_checkpoint=True,
            display_events=("plan.accepted",),
            reason=kind.value,
            notes=(
                "user explicitly approved the generated plan",
                "handler still owns messages append and save_checkpoint call",
            ),
        )
    if kind == PlanConfirmationKind.PLAN_REJECTED:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            display_events=("plan.rejected",),
            reason=kind.value,
            notes=(
                "user explicitly cancelled the task; not a feedback request",
                "handler still owns reset_task and clear_checkpoint",
            ),
        )
    raise ValueError(f"unsupported plan confirmation kind: {kind.value}")


class StepConfirmationKind(str, Enum):
    """v0.4 Phase 1 slice 6-b（step 子切片）：step 确认结局的统一词汇。

    中文学习边界：
    - 这一组值描述用户对**当前 step 完成提示**的最终决定，让
      ``handle_step_confirmation`` 不再仅靠 inline ``state.task.status ==
      "done"`` 这种"事后读 status 来分流"的写法表达 Runtime 意图。
    - 与 plan 不同：plan accept 只有一种结局（→ running + save_checkpoint），
      而 step accept 有两种真实终态——
        * ``STEP_ACCEPTED_CONTINUE``：还有下一步，handler 仍 save_checkpoint
          并继续主循环；
        * ``STEP_ACCEPTED_TASK_DONE``：当前 step 是计划最后一步，
          ``advance_current_step_if_needed`` 把 status 置成 ``"done"``，
          handler 必须 reset_task + clear_checkpoint，**不能** save_checkpoint
          （否则会把 done 状态落盘 → resume 复活已结束的任务）。
      正因为终态分裂，本切片**刻意不复用** :class:`PlanConfirmationKind`；
      让每种 confirmation 走自己的边界，比共享一个泛 ``UserConfirmationKind``
      更能让"transition 命名 ↔ 真实状态变更"一一对应。
    - ``STEP_REJECTED``：用户主动停止任务，与 plan reject 同形。
    - 不覆盖 step 的 feedback 三选一分支（切到 ``awaiting_feedback_intent``
      子状态），原因同 plan slice：那条路径不属于 step 本身的最终结局。
    - 不写 messages、不动 checkpoint、不调 advance_current_step_if_needed；
      实际副作用仍由 ``handle_step_confirmation`` 完成。
    """

    STEP_ACCEPTED_CONTINUE = "step_accepted_continue"
    STEP_ACCEPTED_TASK_DONE = "step_accepted_task_done"
    STEP_REJECTED = "step_rejected"


def step_confirmation_transition(kind: StepConfirmationKind) -> TransitionResult:
    """把 step 确认结局映射到轻量 :class:`TransitionResult`。

    中文学习边界：
    - 与 :func:`plan_confirmation_transition` 同形：只描述 Runtime 意图，
      不替 handler 写 messages、不直接调 save_checkpoint / clear_checkpoint /
      reset_task / advance_current_step_if_needed。
    - ``STEP_ACCEPTED_CONTINUE``：should_checkpoint=True；下一状态由
      ``advance_current_step_if_needed`` 决定（通常仍是 ``"running"``），
      因此 ``next_status`` 留空避免与 advance 结果冲突；display 用
      ``step.accepted``。advance_step=True 是**意图标记**，不代表 transition
      自己推进 step——handler 仍负责调用 advance。
    - ``STEP_ACCEPTED_TASK_DONE``：用户接受了最后一步。should_checkpoint=False
      （task 即将清空），display 用 ``step.task_done``；handler 必须 reset +
      clear，**不能** save。这条与 PLAN_REJECTED 形状相似但语义完全不同：
      用户没有拒绝，是任务自然结束。
    - ``STEP_REJECTED``：用户主动停止。should_checkpoint=False，handler
      reset + clear；display 用 ``step.rejected``。
    - 任何未来扩展（step 跳过 / step 重试 / step 编辑）都应另起新 kind，
      不在这里加分支。
    """

    if kind == StepConfirmationKind.STEP_ACCEPTED_CONTINUE:
        return TransitionResult(
            next_status=None,
            should_checkpoint=True,
            advance_step=True,
            display_events=("step.accepted",),
            reason=kind.value,
            notes=(
                "user approved current step; more steps remain",
                "handler still owns advance_current_step_if_needed and save_checkpoint",
            ),
        )
    if kind == StepConfirmationKind.STEP_ACCEPTED_TASK_DONE:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            advance_step=True,
            display_events=("step.task_done",),
            reason=kind.value,
            notes=(
                "user approved the final step; task naturally completes",
                "handler still owns reset_task and clear_checkpoint",
                "no positive checkpoint here: persisting 'done' would resurrect on resume",
            ),
        )
    if kind == StepConfirmationKind.STEP_REJECTED:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            display_events=("step.rejected",),
            reason=kind.value,
            notes=(
                "user explicitly stopped the task at this step",
                "handler still owns reset_task and clear_checkpoint",
            ),
        )
    raise ValueError(f"unsupported step confirmation kind: {kind.value}")
