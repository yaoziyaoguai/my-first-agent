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


class ToolConfirmationKind(str, Enum):
    """v0.4 Phase 1 slice 6-c（tool 子切片）：tool 确认结局的统一词汇。

    中文学习边界：
    - 这一组值描述用户确认 tool 执行后的 Runtime 意图，让
      ``handle_tool_confirmation`` 的 accept 分支不再仅靠 try/except
      的隐式分流来表达「成功 vs 异常」两种真实结局。
    - **不覆盖** reject 路径：用户拒绝执行某个工具属于 ``ToolResult`` 词
      汇（v0.1 已有的 :class:`ToolResultTransitionKind.USER_REJECTION`），
      它描述「这一次 tool_result 该如何映射」，与 plan/step confirmation
      的「Runtime 状态机该如何前进」是两个不同维度。本切片刻意保留这条
      边界：tool **确认决策** 用 ToolConfirmationKind；tool **结果映射** 用
      ToolResultTransitionKind；不强行合并以免模糊语义。
    - 与 step 不同：tool accept 有两种真实终态——
        * ``TOOL_ACCEPTED_SUCCESS``：execute_pending_tool 成功返回；
          handler 必须清 ``pending_tool`` + save_checkpoint + 继续主循环。
        * ``TOOL_ACCEPTED_FAILED``：execute_pending_tool 抛异常；handler
          **必须保留** ``pending_tool`` 以便人工排查（这是 confirm_handlers
          L444 注释明确的真实诊断需求），同时仍 save_checkpoint + 继续主
          循环让 tool_use 不再悬空。
      这两条都 should_checkpoint=True，但 ``clear_pending_tool`` 完全不
      同（success=True / failed=False），让"清不清 pending"的契约能从
      transition 层一眼看清，避免 slice 6-c 之后的人误改。
    - 不写 messages、不动 checkpoint、不调 execute_pending_tool；实际副
      作用仍由 ``handle_tool_confirmation`` 完成，pending_tool 清理仍是
      handler 的 single source of truth（已在
      ``test_tool_accept_success_path_clears_pending_tool_via_handler`` /
      ``test_tool_accept_exception_path_keeps_pending_tool_for_inspection``
      端到端钉住）。
    """

    TOOL_ACCEPTED_SUCCESS = "tool_accepted_success"
    TOOL_ACCEPTED_FAILED = "tool_accepted_failed"


def tool_confirmation_transition(kind: ToolConfirmationKind) -> TransitionResult:
    """把 tool 确认 accept 路径结局映射到轻量 :class:`TransitionResult`。

    中文学习边界：
    - 与 :func:`plan_confirmation_transition` / :func:`step_confirmation_transition`
      同形：只描述 Runtime 意图，不替 handler 写 messages、不直接调
      save_checkpoint、不调 execute_pending_tool、不清 pending_tool。
    - ``TOOL_ACCEPTED_SUCCESS``：should_checkpoint=True + clear_pending_tool=True；
      next_status="running"。
    - ``TOOL_ACCEPTED_FAILED``：should_checkpoint=True + clear_pending_tool=False
      （**关键**：保留 pending_tool 以便排查）；next_status="running"。
    - 不接受 reject kind：那条路径仍走 v0.1 已有的
      :func:`tool_result_transition` (USER_REJECTION)；本切片刻意不合并两
      套词汇以保留 ToolResult vs ToolConfirmation 的语义边界。
    """

    if kind == ToolConfirmationKind.TOOL_ACCEPTED_SUCCESS:
        return TransitionResult(
            next_status="running",
            should_checkpoint=True,
            clear_pending_tool=True,
            display_events=("tool.accepted",),
            reason=kind.value,
            notes=(
                "user approved tool; execution succeeded",
                "handler still owns the actual pending_tool clear and save_checkpoint",
            ),
        )
    if kind == ToolConfirmationKind.TOOL_ACCEPTED_FAILED:
        return TransitionResult(
            next_status="running",
            should_checkpoint=True,
            clear_pending_tool=False,
            display_events=("tool.accepted_failed",),
            reason=kind.value,
            notes=(
                "user approved tool; execution raised an exception",
                "pending_tool must be preserved for human diagnostics (handler L444)",
                "handler still writes the placeholder tool_result and saves checkpoint",
            ),
        )
    raise ValueError(f"unsupported tool confirmation kind: {kind.value}")


class FeedbackIntentKind(str, Enum):
    """v0.4 Phase 1 slice 6-e（user-confirmation 收口切片）：feedback_intent 四路径词汇。

    中文学习边界：
    - awaiting_feedback_intent 子状态有 4 条出口：
        AS_FEEDBACK   = 用户选 [1]，把当前自由文本当作对当前 plan 的修改意见；
        AS_NEW_TASK   = 用户选 [2]，切换为新任务（reset_task + start_planning_fn）；
        CANCELLED     = 用户选 [3]，恢复 origin_status 完全无副作用；
        AMBIGUOUS     = 任何非 {1,2,3} 输入，仅重发 RuntimeEvent，不动状态。
      4 个值不可合并：AMBIGUOUS 不能省略当作"什么也不做的隐式默认"，否则未来
      容易被重构成 'CANCELLED 包含 AMBIGUOUS'，进而把"未决意图"当作"用户取消"
      持久化到 checkpoint，破坏 docs/P1_TOPIC_SWITCH_PLAN.md §3 红线。
    - 与 plan/step/tool 同形：transition 仅描述 Runtime 意图（要不要写
      checkpoint、要不要清 pending），实际 mutation / LLM 调用 / messages
      写入 / start_planning_fn 反向回调全部仍由
      :func:`agent.confirm_handlers.handle_feedback_intent_choice` 持有。
    - 这是 slice 6 中**最危险**的一块，因此本 slice 的 transition 边界刻意
      最薄：只表达 should_checkpoint / clear_pending_user_input / next_status；
      不引入任何"统一动作"（特别是禁止"任何 confirm 路径都自动 save_checkpoint"
      这种统一化重构 —— AMBIGUOUS 路径 should_checkpoint=False 是契约，
      已被 ``test_feedback_intent_ambiguous_does_not_save_checkpoint_or_mutate_state``
      钉死）。
    """

    AS_FEEDBACK = "as_feedback"
    AS_NEW_TASK = "as_new_task"
    CANCELLED = "cancelled"
    AMBIGUOUS = "ambiguous"


def feedback_intent_transition(kind: FeedbackIntentKind) -> TransitionResult:
    """把 feedback_intent 四路径映射到轻量 :class:`TransitionResult`。

    中文学习边界：
    - 与 plan/step/tool confirmation 同形：transition 是 **意图层**，不是
      行为层。本函数 **绝不** 调 save_checkpoint、绝不调 generate_plan、
      绝不调 reset_task、绝不调 start_planning_fn、绝不写 messages。
    - 4 路径意图：
        AS_FEEDBACK：should_checkpoint=True、clear_pending_user_input=True、
          next_status="awaiting_plan_confirmation"（handler 调 planner 成功
          后重新进入 plan 确认；planner 失败时 handler 走 reset 并显式覆盖）。
        AS_NEW_TASK：should_checkpoint=False（handler 通过 clear_checkpoint
          抹掉旧任务，再由 start_planning_fn 内部决定新 checkpoint 节奏）；
          clear_pending_user_input=True（reset_task 间接清掉）；
          next_status=None（由 start_planning_fn 决定）。
        CANCELLED：should_checkpoint=True（确实需要把 origin_status 落盘，
          否则下次 resume 会把 awaiting_feedback_intent 当成残留态恢复）；
          clear_pending_user_input=True；
          next_status 由 handler 用 origin_status 填，本意图层不预设具体值。
        AMBIGUOUS：should_checkpoint=False（**关键契约**：未决意图禁止持久化）、
          clear_pending_user_input=False、next_status=None；
          唯一允许的副作用是 emit feedback_intent_requested（handler 自己做）。
    - 不接受其它 kind；future-proof 通过 ValueError 显式失败而不是静默兜底。
    """

    if kind == FeedbackIntentKind.AS_FEEDBACK:
        return TransitionResult(
            next_status="awaiting_plan_confirmation",
            should_checkpoint=True,
            clear_pending_user_input=True,
            display_events=("feedback_intent.as_feedback",),
            reason=kind.value,
            notes=(
                "user chose [1] = treat free-form text as plan feedback",
                "handler owns: append plan_feedback control event, call generate_plan,"
                " write current_plan/index, save_checkpoint, emit plan_confirmation",
                "revised_goal is local input to planner only; user_goal is NEVER"
                " written back (pinned by"
                " test_feedback_intent_as_feedback_handler_source_does_not_write_revised_goal_back)",
            ),
        )
    if kind == FeedbackIntentKind.AS_NEW_TASK:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            clear_pending_user_input=True,
            display_events=("feedback_intent.as_new_task",),
            reason=kind.value,
            notes=(
                "user chose [2] = switch to a new task",
                "handler owns: reset_task, clear_checkpoint, start_planning_fn injection",
                "reset_task MUST strictly precede start_planning_fn (pinned by"
                " test_feedback_intent_as_new_task_reset_strictly_precedes_start_planning)",
            ),
        )
    if kind == FeedbackIntentKind.CANCELLED:
        return TransitionResult(
            next_status=None,
            should_checkpoint=True,
            clear_pending_user_input=True,
            display_events=("feedback_intent.cancelled",),
            reason=kind.value,
            notes=(
                "user chose [3] = cancel; restore origin_status, no messages write",
                "handler fills next_status from pending['origin_status'] then saves",
                "messages length MUST stay unchanged (P1 §3 红线，pinned by"
                " test_feedback_intent_cancel_does_not_write_messages_or_call_planner)",
            ),
        )
    if kind == FeedbackIntentKind.AMBIGUOUS:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            clear_pending_user_input=False,
            display_events=("feedback_intent.ambiguous",),
            reason=kind.value,
            notes=(
                "input outside {1,2,3}: re-emit RuntimeEvent only",
                "should_checkpoint=False is the critical contract: pending intent"
                " must NOT be persisted to checkpoint (pinned by"
                " test_feedback_intent_ambiguous_does_not_save_checkpoint_or_mutate_state)",
                "handler must not mutate state / pending / messages here",
            ),
        )
    raise ValueError(f"unsupported feedback intent kind: {kind.value}")
