"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
import anthropic
from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    DisplayEvent,
    DisplayEventSink,
    RuntimeEvent,
    RuntimeEventSink,
    assistant_delta,
    control_message,
    loop_max_iterations_event,
    plan_confirmation_requested,
    render_runtime_event_for_cli,
    runtime_display_event,
    state_inconsistency_reset_event,
    tool_requested,
    unknown_stop_reason_event,
)
from agent.prompt_builder import build_system_prompt
from agent.state import create_agent_state, task_status_requires_plan
import agent.tools  # noqa: F401  触发所有工具注册



from config import (
    API_KEY, BASE_URL, MODEL_NAME, MAX_TOKENS,
    MAX_CONTINUE_ATTEMPTS,
)
from agent.memory import compress_history
from agent.planner import generate_plan, format_plan_for_display
from agent.tool_registry import get_tool_definitions
from agent.context_builder import (
    build_planning_messages as build_planning_messages_from_state,
    build_execution_messages as build_execution_messages_from_state,
)


from agent.confirm_handlers import (
    ConfirmationContext,
    handle_plan_confirmation,
    handle_step_confirmation,
    handle_user_input_step,
    handle_tool_confirmation,
    handle_feedback_intent_choice,
)

from agent.response_handlers import (
    handle_end_turn_response,
    handle_max_tokens_response,
    handle_tool_use_response,
)
from agent.runtime_events import ModelOutputKind, classify_model_output
from agent.loop_context import LoopContext
from agent.runtime_observer import log_event as log_runtime_event





# ========== 常量 ==========


MAX_LOOP_ITERATIONS = 50              # 循环总次数兜底（防死循环）；
# v0.4 Phase 2.2-c：本常量保留为**默认值来源**，由 chat() 构造 LoopContext 时
# 引用，运行时实际读取走 loop_ctx.max_loop_iterations。同时兼容现有
# `from agent.core import MAX_LOOP_ITERATIONS` 的测试（test_bug_hunting /
# test_runtime_error_recovery 等）。后续如果引入 env / config 读取，应改为：
#   MAX_LOOP_ITERATIONS = int(os.getenv("MAX_LOOP_ITERATIONS", 50))
# 然后 chat() 仍读这个常量构造 loop_ctx。


# ========== 全局 ==========

# client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)
# messages = []  # session 级消息历史

client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)

# 统一会话状态：
# 先把 system prompt 放进 runtime，
# conversation / memory / task 先用默认空值初始化。
state = create_agent_state(
    system_prompt="",
    model_name=MODEL_NAME,
    review_enabled=False,
    max_recent_messages=6,
)
def get_state():
    """获取当前会话状态。"""
    return state


# ========== 循环状态 ==========

@dataclass
class TurnState:
    """一次 chat 调用内部的循环状态。

    注意：这里只保留**本次 chat 调用内**确实 ephemeral 的字段。
    所有需要跨多次 chat 调用（例如工具确认来回）累积的计数，
    都放在 state.task 上，由 handlers 直接读写。
    """
    system_prompt: str
    round_tool_traces: list = field(default_factory=list)
    # DisplayEvent 是 Runtime 到 UI 的单向投影出口。它不写入 conversation，也不让
    # tool_executor 反向依赖 TUI；simple backend 没传 sink 时会回退到 stdout。
    on_display_event: DisplayEventSink | None = None
    # RuntimeEvent 是本轮 chat 的用户可见输出总线。它只服务 UI projection，
    # 不能混入 checkpoint、runtime_observer、conversation.messages 或 Anthropic
    # API messages；这些边界仍由各自模块负责。
    on_runtime_event: RuntimeEventSink | None = None
    # TraceEvent 是 opt-in observability sink，不是 Runtime state。默认 None，
    # 不创建 recorder、不写 agent_log/sessions/runs；只有调用方显式传 sink 时才投影。
    on_trace_event: Callable[[Any], None] | None = None
    trace_run_id: str | None = None
    trace_id: str | None = None
    print_assistant_newline: bool = False


def refresh_runtime_system_prompt() -> str:
    """
    重新生成当前运行态实际生效的 system prompt，并写回 state。

    注意：
    - 当前阶段仍然沿用 build_system_prompt() 作为 system prompt 的生成器
    - 但最终真正生效的结果，以 state.runtime.system_prompt 为准
    """
    system_prompt = build_system_prompt()
    state.set_system_prompt(system_prompt)
    return state.get_system_prompt()

refresh_runtime_system_prompt()




# ========== 对外主入口 ==========


def _build_loop_context(
    client_obj,
    *,
    model_name: str = MODEL_NAME,
    max_loop_iterations: int = MAX_LOOP_ITERATIONS,
) -> LoopContext:
    """v0.5 Phase 3 第一小步 · LoopContext 构造工厂（行为中性 helper）。

    定位（架构边界）：
        把 chat() 中字面 ``LoopContext`` 构造调用抽出为命名工厂，
        让 chat() 主体读起来不再混杂"如何构造运行时依赖"的细节。

    为什么 v0.5 第一小步选这个：
        1) Phase 2 已经把所有 helper 改成"通过 _loop_ctx 透传依赖"，但
           **构造**仍然散在 chat() 里——读 chat() 的人需要同时理解控制流
           + 依赖注入。抽 helper 后 chat() 第一步就是"拿到 loop_ctx"，
           更接近"启动 → 拿运行时依赖 → 跑业务"的清晰阶段；
        2) 是行为中性纯重构：helper 体内只是把现有 3 行构造原样包一层，
           **零**业务逻辑变化、**零**控制流变化、**零**字段变化；
        3) 为 v0.5 后续 core slimming 铺路——后续若要把 chat() 拆成
           `_initialize_turn / _route_pending_state / _begin_new_task` 等，
           每一拆都需要"先拿 loop_ctx 再传给子函数"，本 helper 让那一步
           只调用一行。

    为什么 LoopContext 仍然是 runtime dependency bundle，而不是 durable state：
        - client：LLM provider 句柄，不能 JSON 序列化、与进程绑定；
        - model_name / max_loop_iterations：当前是模块常量，未来可能改为
          env / config 读取，**但仍是启动时确定的运行配置**，不属于
          "checkpoint 应该保存的任务进度"；
        - 由 v0.4 Phase 2.4 的 4 项 checkpoint guard 钉死：runtime-only
          类型名永不出现在 checkpoint JSON / state.task / state.memory。

    为什么这**不是**完整 core.py slimming：
        - chat() 函数体仍然完整保留所有控制流（pending state 路由、
          plan/step/tool/user_input/feedback_intent 5 类 confirmation
          dispatch、main loop 启动）；
        - 不动 _run_main_loop / _call_model / _run_planning_phase 任何
          一行；
        - 不引入新依赖、新字段、新参数；
        - SSOT 仍由 test_chat_remains_unique_loop_context_construction
          _site_in_core 钉死（构造从 chat() 移到 helper，全文仍 1 次）。

    用户项目自定义入口（未来扩展点）：
        若以后要支持 chat() 多次启动用不同 model_name（多模型对比测试），
        helper 已经接受 model_name kwarg，调用点显式传入即可，无需改
        helper 签名。

    什么是 mock / demo（无）：
        helper 不含任何 mock/demo 逻辑；纯运行时依赖工厂。

    重要边界 · monkeypatch 兼容：
        chat() **必须**显式把 ``MODEL_NAME / MAX_LOOP_ITERATIONS`` 作为
        kwargs 传给本 helper，而不是依赖 helper 默认值。原因：Python
        函数默认参数在 def 时求值，monkeypatch 改写模块常量后默认值
        不会跟着变；显式传入则在 chat() 调用时重新读取。已被
        ``test_max_loop_iterations_terminal_guard_still_fires_when_double_layer_bypassed``
        钉住——任何"省掉 kwargs 让 helper 兜默认值"的简化都会破坏
        monkeypatch 测试场景。
    """
    return LoopContext(
        client=client_obj,
        model_name=model_name,
        max_loop_iterations=max_loop_iterations,
    )


def _build_confirmation_context(
    *,
    state,
    turn_state,
    loop_ctx: LoopContext,
) -> ConfirmationContext:
    """v0.5 Phase 3 第二小步 · ConfirmationContext 构造工厂（行为中性 helper）。

    定位（架构边界）：
        把 chat() 内 14 行字面 ``ConfirmationContext`` 构造抽出为命名工厂，
        与 v0.5 第一小步的 ``_build_loop_context`` 对称——chat() 头部从此变成
        清晰的"两行拿依赖"：先 _loop_ctx，再 confirmation_ctx。

    为什么 v0.5 第二小步选这个：
        1) 与第一小步同模式、同低风险的行为中性重构；
        2) ConfirmationContext 内部已经隐式依赖 _loop_ctx——continue_fn 和
           start_planning_fn 这两个 lambda 都闭包捕获 _loop_ctx——把构造抽到
           helper 让这层依赖显式（helper 签名直接吃 loop_ctx）；
        3) 同时把 client / model_name 来源从 module-level globals 切到
           ``loop_ctx.client / loop_ctx.model_name``。值等价（loop_ctx 也是
           从同一组 module globals 在 chat() 调用时构造的），但语义上更整齐：
           ConfirmationContext 是 LoopContext 的下游消费者，不再单独读
           module globals。这与 Phase 2.2-b 的"_call_model 走 loop_ctx"方向
           一致。

    为什么 ConfirmationContext 是 handler dependency bundle，不是 durable state：
        - 5 个 confirmation handler（plan/step/tool/user_input/feedback_intent）
          运行时需要：state（durable 单例的引用，不是值拷贝）+ turn_state
          （单 turn 临时态）+ client/model_name（runtime dep）+ 两个 callable
          闭包（再调用时回到主循环 / 启动新 planning）；
        - 5 个字段都不是"任务进度"——任务进度在 state.task；
        - continue_fn / start_planning_fn 是函数引用，**永不**写 checkpoint、
          **永不**进 messages、**永不**属于 schema（已被
          test_checkpoint_resume_semantics 钉死）；
        - ConfirmationContext 自身也永不进 checkpoint。

    为什么这**不是**完整 core.py slimming：
        - chat() 函数体仍然完整保留 5 类 confirmation dispatch 的 if/elif 链
          以及 main_loop 启动；
        - 不动 _run_main_loop / _call_model / _run_planning_phase /
          _start_planning_for_handler / 任何 confirm_handler 业务函数；
        - 不引入新依赖、不改 ConfirmationContext 字段集；
        - SSOT 仍由新增 source-locality 测试钉死（构造从 chat() 移到 helper，
          全文仍恰好 1 次 ``ConfirmationContext`` 字面构造）。

    用户项目自定义入口（未来扩展点）：
        若以后要支持"测试时注入 fake continue_fn"或"plan-only 模式 disable
        start_planning_fn"，helper 已经把 lambda 构造逻辑集中——可以加
        kwarg override，无需改 chat() 主体。

    什么是 mock / demo（无）：
        helper 不含任何 mock/demo 逻辑；纯运行时依赖工厂。

    重要边界 · 避免引入第二构造源：
        SSOT 测试要求 core.py 全文 ``ConfirmationContext`` 字面构造恰好
        1 次（在 helper 内）。任何 helper / handler 都不能就地重建
        ConfirmationContext，必须通过 chat() 透传。
    """
    return ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=loop_ctx.client,
        model_name=loop_ctx.model_name,
        continue_fn=lambda ts: _run_main_loop(ts, loop_ctx),
        # P1：注入"切新任务"分流路径——与正常 chat() 新任务入口完全同构。
        # 把 _run_planning_phase 后续的 awaiting/cancelled/main_loop 处理也封进
        # 这个 lambda，让 handle_feedback_intent_choice 不需要知道 chat() 的结构。
        # 函数引用只在内存中传递，不写 checkpoint、不进 messages，不属于 schema。
        start_planning_fn=lambda inp, ts: _start_planning_for_handler(
            inp, ts, loop_ctx
        ),
    )


def _dispatch_pending_confirmation(
    state,
    user_input: str,
    confirmation_ctx,
) -> str | None:
    """v0.5.1 第三小步 · pending confirmation 分发 helper（纯函数提取）。

    职责（只做一件事）：
        把"用户这次输入是否落在某个 pending 等待状态上"的路由决策从 ``chat()``
        主体里搬出来。返回值语义：

        - 返回 ``str``：5 个 pending 分支之一命中并由对应 handler 完成处理；
          调用方（``chat()``）应直接 ``return`` 这个字符串，不再走压缩 / 新
          任务路径。
        - 返回 ``None``：5 个分支都不命中（fallthrough）；调用方继续执行
          ``chat()`` 后半段的压缩历史 + 开启新任务逻辑。

    本 helper 不负责什么：
        - 不负责 5 个 handler 内部业务（plan/step/user_input/feedback_intent/
          tool 各自的 confirmation outcome、observer evidence、checkpoint
          落盘）——那些由 ``agent/confirm_handlers.py`` 各自 handler 钉死；
        - 不负责 fallthrough 之后的压缩 / 新任务开启 / 主循环；
        - 不负责 ``confirmation_ctx`` 的构造（由 ``_build_confirmation_context``
          专属，SSOT 单源）；
        - 不负责 L306 不一致 state 自愈路径（YF1 修复在 chat() 头部，独立
          于 pending 分发）；
        - 不负责 ``awaiting_feedback_intent`` / ``awaiting_tool_confirmation``
          以外其他未来可能新增的 pending 状态——新增状态须显式追加分支。

    为什么这样设计：
        v0.5.0 之前 ``chat()`` 主体连续写 5 条 ``if state.task.status == ...:
        return handler(...)``，与下方"压缩 / 新任务"逻辑混在同一函数。这导致
        两个真实风险：
        1) 任何在 chat() 主体里加新的 status 检查的提交，都会无意中影响
           pending 分发顺序；
        2) future 想做 dict-based dispatch 表 / observer hook / TUI awaitable
           分发时，必须先把这 5 个分支抽出。

        v0.5.1 第二小步 (cdd1427) 已通过 11 条 characterization tests 钉死
        了 5 分支的顺序 + 守卫 + 互斥 + fallthrough 行为；本 helper 是在那
        baseline 上做**纯函数提取**：分支顺序、守卫条件、handler 调用方式、
        参数传递与原 chat() L491-L517 字面等价。

    分支顺序与守卫（与提取前完全等价）：
        1. ``current_plan`` 非空且 status == ``awaiting_plan_confirmation``
        2. ``current_plan`` 非空且 status == ``awaiting_step_confirmation``
        3. status == ``awaiting_user_input`` 且
           （``current_plan`` 非空 或 ``pending_user_input_request`` 非空）
        4. status == ``awaiting_feedback_intent``
        5. ``pending_tool`` 非空且 status == ``awaiting_tool_confirmation``

    为什么 None 表示 fallthrough：
        所有 5 个 handler 当前的真实返回值都是非空字符串（plan_confirm_yes /
        plan_confirm_no / 各种 user-facing 文本 / "<probe:*>" 等）。用 None
        作为"未命中"哨兵不会与任何 handler 真实返回值冲突，调用方一行 if
        检查即可。

    用户项目自定义入口（未来扩展点）：
        - 若加新的 pending 状态，**必须**在本函数内追加分支并补对应的
          characterization test（参考 ``tests/test_pending_confirmation_dispatch.py``
          的 monkeypatch 5 个 handler 为 probe 的模式）；
        - 若想做 dict-based 分发表，可以把 5 条 if 换成 ``(predicate, handler)``
          列表，但必须保留顺序敏感性（前面优先）；
        - 若想加 observer hook（"哪条分支被命中"写 JSONL），加在每个
          ``return`` 之前。

    artifact 排查：
        - 用户报告"我点了 yes 但 plan 没继续"→ 看 agent_log.jsonl 是否有
          confirmation.* 事件（由 confirm_handlers 写）；本 helper 不写
          observer，所以"分发是否到位"靠 ``test_pending_confirmation_dispatch.py``
          单元层定位；
        - 用户报告"我输入文本被当成新任务"→ 检查输入时 ``state.task.status``
          + 各 pending 字段；可能命中第 3 条分支（user_input 守卫）也可能落
          fallthrough。

    什么是 mock / demo（无）：
        本 helper 是真实 production code；无 mock / demo / xfail 边界。
        ``tests/test_pending_confirmation_dispatch.py`` 中 ``dispatch_probe``
        fixture 只是测试模式下用 monkeypatch 把 5 个 handler 替换成探针，
        与本 helper 实现无关。
    """

    if state.task.current_plan and state.task.status == "awaiting_plan_confirmation":
        return handle_plan_confirmation(user_input, confirmation_ctx)

    if state.task.current_plan and state.task.status == "awaiting_step_confirmation":
        return handle_step_confirmation(user_input, confirmation_ctx)

    if (
        state.task.status == "awaiting_user_input"
        and (state.task.current_plan or state.task.pending_user_input_request)
    ):
        return handle_user_input_step(user_input, confirmation_ctx)

    if state.task.status == "awaiting_feedback_intent":
        return handle_feedback_intent_choice(user_input, confirmation_ctx)

    if (
        getattr(state.task, "pending_tool", None)
        and state.task.status == "awaiting_tool_confirmation"
    ):
        return handle_tool_confirmation(user_input, confirmation_ctx)

    return None


def _safe_emit_runtime_event(
    sink: RuntimeEventSink | None,
    event: RuntimeEvent,
    *,
    fallback_prefix: str = "",
) -> None:
    """v0.5.1 第一小步 · YF1 修复 · 安全发出 RuntimeEvent 到 sink。

    问题（v0.5.0 RELEASE_NOTES_v0.5.md / docs/V0_5_OBSERVER_AUDIT.md §8 YF1）：
    ``agent/core.py`` L306 / L670 / L789 三处 D 迁移点直接 ``sink(event)``。
    若 sink 抛异常会沿调用栈冒到 ``chat()`` 调用方，跳过下游清理（L306 的
    ``state.reset_task()`` / L670 的 ``clear_checkpoint`` + ``state.reset_task``
    + return / L789 的 ``log_runtime_event("loop.stop", ...)`` + return）。

    本 helper 把 sink 调用包成"绝不抛"契约：

    1. ``sink is None`` → print 到 stdout（保留 simple CLI fallback）；
       ``fallback_prefix`` 用于个别调用点（如 L670）需要前缀换行的场景。
    2. ``sink(event)`` 正常完成 → 直接返回，不打印（避免 stdout 双投）。
    3. ``sink(event)`` 抛任何 ``Exception``：
       a) 调用 ``log_runtime_event("runtime_event_sink.failed", ...)``
          把"原 event_type + 异常类名"写进 observer JSONL；
          payload **不含**异常栈、**不含** event.text、**不含** event.metadata
          —— 防止 user_input / tool_input 在异常路径泄漏到日志；
       b) print 到 stdout 让 simple CLI / debug 用户仍看到诊断；
       c) **不**重新抛出异常 —— 让调用方下游清理（reset_task、clear_checkpoint
          等）继续完成。
    4. observer 写入再次失败也吞掉 —— 这是兜底，避免日志层 bug 把主流程拖死；
       如果出现这种情况，stdout fallback 仍能让用户察觉异常。

    职责边界：
    - 仅吸收 sink 调用本身的异常；不吞 sink 之前 / 之后的逻辑异常。
    - 不改 ``conversation.messages`` / 不改 ``state.task`` / 不改 checkpoint /
      不改 transition 决策；这些由调用方在本 helper 之后继续负责。
    - 不增加 sink 协议字段，不与 ``DisplayEvent`` 兼容层混合。
    - 不接 TUI；TUI 自己的异常分类由前端 owner 决定。

    用户接入点：``agent/core.py`` 中 3 处带下游清理的 user-facing diagnostic
    （L306 state 自愈、L670 loop 兜底、L789 unknown stop_reason）。

    artifact 排查：
    - 若用户报告 "TUI 渲染异常后 agent 崩溃"，先看 agent_log.jsonl 是否
      含 ``event_type="runtime_event_sink.failed"`` 行；
    - 若有该行，说明 helper 已工作，问题出在 callback 实现内部；
    - 若无，说明可能 callback raise 没经过本 helper 路径，需要检查调用点
      是否仍是裸 ``sink(event)``。

    未来扩展点（不在本切片做）：
    - 把 6 个 callback 触达点统一用本 helper 包；当前只覆盖 3 处带清理的；
    - observer 失败时降级到 stderr，提供独立可观测信号；
    - 给 helper 加可注入 fallback_renderer 让 TUI 自定义错误兜底。
    """

    if sink is None:
        print(f"{fallback_prefix}{render_runtime_event_for_cli(event)}")
        return
    try:
        sink(event)
    except Exception as exc:
        try:
            log_runtime_event(
                "runtime_event_sink.failed",
                event_source="runtime",
                event_payload={
                    "original_event_type": event.event_type,
                    "exception_type": type(exc).__name__,
                },
                event_channel="display",
            )
        except Exception:
            pass
        print(f"{fallback_prefix}{render_runtime_event_for_cli(event)}")


def _dispatch_model_output(
    response,
    *,
    turn_state: "TurnState",
) -> str | None:
    """v0.5.1 第五小步 · _run_main_loop 模型输出分发 helper（行为中性提取）。

    职责（架构边界）
    ----------------
    把 ``_run_main_loop`` 中"按 :class:`ModelOutputKind` 把 response 路由到
    对应 handler"的 4 个 if-branch 抽出为单一函数：

        MAX_TOKENS  → handle_max_tokens_response
        END_TURN    → handle_end_turn_response
        TOOL_USE    → handle_tool_use_response
        UNKNOWN     → fallback: 发 unknown_stop_reason RuntimeEvent，
                       记 loop.stop(reason_for_stop=unknown_stop_reason)，
                       返回 ``"意外的响应"``

    返回语义（与原 inline 逻辑完全等价）：
    - **str** = handler 已产生最终结果，调用方应 ``return result`` 退出循环；
    - **None** = handler 返回 None（典型如 max_tokens continue 路径），
      调用方应 ``continue`` 进入下一轮 ``while``。

    本 helper **不负责**的事
    ------------------------
    - ❌ ``_call_model`` 调用：仍由 ``_run_main_loop`` 在主循环顶部执行；
    - ❌ ``state.task.loop_iterations += 1`` / ``loop.iteration_start`` log /
      ``loop.guard_triggered`` log / max_iter guard 内 ``clear_checkpoint`` +
      ``state.reset_task`` + return —— 这些是 *循环控制*，与"输出分发"是两层
      不同关注点；
    - ❌ ``loop.start`` log（属循环启动一次性事件，不进 helper）；
    - ❌ handler 内部的 messages 写入 / state mutation / checkpoint / 工具
      执行 / consecutive 计数器 —— 全部仍由 ``response_handlers.py`` 各自
      handler 负责；
    - ❌ pending confirmation 路由（那是 :func:`_dispatch_pending_confirmation`
      的职责，按 *用户输入* + *task.status* 派发，与本 helper 完全正交）。

    与 :func:`_dispatch_pending_confirmation` 的区别（请勿混用）
    -----------------------------------------------------------
    - 输入来源不同：confirmation dispatch 拿到的是**用户输入字符串** +
      ``task.status``；本 helper 拿到的是**模型 response 对象** +
      ``stop_reason``；
    - 触发时机不同：confirmation dispatch 在 ``chat()`` 顶层用户进入时；
      本 helper 在 ``_run_main_loop`` 每轮模型调用之后；
    - 失败 fallback 不同：confirmation dispatch 落到"开启全新任务"路径；
      本 helper 落到 UNKNOWN fallback 文案。

    为什么仍留在 ``agent/core.py``（不新建模块）
    --------------------------------------------
    - 4 个 handler 已 ``from agent.response_handlers import ...`` 集中在
      ``core.py`` 顶部；新模块只会让 import 重新分散；
    - 与 :func:`_dispatch_pending_confirmation`（bf49a84 抽出）保持对称布局，
      便于未来读者一次看完两类 dispatch；
    - 本切片是**函数提取**，不是新状态机、不是 callback framework、不是
      新 API；不需要独立模块边界。

    为什么先有 characterization tests 再抽 helper
    ----------------------------------------------
    - 605196c（``tests/test_model_output_dispatch.py`` 9 条）已经钉死：
      4 分支路由 + None / continue 语义 + 互斥 + classify_model_output 唯一
      truth source + UNKNOWN fallback return value + ModelOutputKind 词表稳定；
    - 如果没有这层网，本次提取若不慎调整 ``loop.iteration_end`` log 字段顺序、
      或把 UNKNOWN 文案改成 ``"未知响应"``，很可能在 production agent 跑出
      silent-success 才被发现；
    - 与 cdd1427→bf49a84 的 confirmation dispatch 提取完全同模式：
      先 char baseline、再纯函数提取、helper-level 单测兜底 None 边界。

    用户项目自定义入口（未来扩展点）
    --------------------------------
    - 若未来新增第 5 类 ``ModelOutputKind``（例如 ``REFUSAL``），应：
      1) 在 ``classify_model_output`` 加映射；2) 在本 helper 的 if-chain
      新增分支；3) 同步在 ``test_model_output_dispatch`` 加路由测试与词表
      断言更新；不要绕过 helper 直接在 ``_run_main_loop`` 加分支。
    - 若未来要支持"按 ModelOutputKind 注入自定义 handler"（例如插件化），
      可以让本 helper 接受 ``handlers: dict[ModelOutputKind, Callable]``
      参数；当前是常量 import，不接 plugin 抽象。

    artifact 排查
    -------------
    - 用户报告"循环吃掉异常输出"时，先 grep agent_log.jsonl 中
      ``event_type="loop.stop"`` 行的 ``reason_for_stop`` 字段：
      * ``handler_returned`` → 走了已知分支；
      * ``unknown_stop_reason`` → 走了 UNKNOWN fallback；
      * 缺失 ``loop.stop`` → 可能在 max_iter guard 触发了，看
        ``loop.guard_triggered`` 行（属 ``_run_main_loop`` 直接发，不经
        本 helper）。
    - 若用户报告 "tool_use 没执行"，看 ``loop.iteration_end`` 行的
      ``stop_reason`` 是否真是 ``"tool_use"``——若不是，说明 SDK 返回的
      stop_reason 漂移了（未来需要在 classify 层兜底新映射）。

    什么是 mock / demo（无）
    ------------------------
    helper 不含任何 mock / demo 逻辑；纯运行时分发。测试用 fake response +
    handler probe 见 ``tests/test_model_output_dispatch.py``。

    重要边界 · 行为中性证明
    -----------------------
    - 本 helper 体内的 4 个分支**字面**等价于原 ``_run_main_loop`` 的
      L860-L969 区段；唯一差别是把"if result is not None: log + return"
      模式收敛成：handler 返回 None → helper 返回 None；handler 返回 str
      → helper 记 ``loop.stop(reason_for_stop=handler_returned)`` 后返回
      str。
    - 调用方 ``_run_main_loop`` 据此 ``return``/``continue``，与原行为
      逐字节等价；这一点由 605196c 9 条 + 本切片 1 条 helper-level None
      fallthrough 测试共同钉死。
    """
    model_kind = classify_model_output(response.stop_reason)
    log_runtime_event(
        "loop.iteration_end",
        event_source="runtime",
        event_payload={
            **_runtime_loop_fields(),
            "stop_reason": response.stop_reason,
        },
        event_channel="loop",
    )

    if model_kind is ModelOutputKind.MAX_TOKENS:
        result = handle_max_tokens_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=state.conversation.messages,
            extract_text_fn=_extract_text,
            max_consecutive_max_tokens=MAX_CONTINUE_ATTEMPTS,
        )
        if result is not None:
            log_runtime_event(
                "loop.stop",
                event_source="runtime",
                event_payload={
                    **_runtime_loop_fields(),
                    "stop_reason": response.stop_reason,
                    "reason_for_stop": "handler_returned",
                },
                event_channel="loop",
            )
            return result
        return None

    if model_kind is ModelOutputKind.END_TURN:
        result = handle_end_turn_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=state.conversation.messages,
            extract_text_fn=_extract_text,
        )
        if result is not None:
            log_runtime_event(
                "loop.stop",
                event_source="runtime",
                event_payload={
                    **_runtime_loop_fields(),
                    "stop_reason": response.stop_reason,
                    "reason_for_stop": "handler_returned",
                },
                event_channel="loop",
            )
            return result
        return None

    if model_kind is ModelOutputKind.TOOL_USE:
        result = handle_tool_use_response(
            response,
            state=state,
            turn_state=turn_state,
            messages=state.conversation.messages,
            extract_text_fn=_extract_text,
        )
        if result is not None:
            log_runtime_event(
                "loop.stop",
                event_source="runtime",
                event_payload={
                    **_runtime_loop_fields(),
                    "stop_reason": response.stop_reason,
                    "reason_for_stop": "handler_returned",
                },
                event_channel="loop",
            )
            return result
        return None

    # ModelOutputKind.UNKNOWN：未知 stop_reason 走显式分支，不能被
    # 上面任何一类静默吸收。这里保留原 "[系统] 未知的 stop_reason: …"
    # 文案与 reason_for_stop=unknown_stop_reason 日志，行为与提取前
    # 完全一致；分类层只是让 "unknown 是一类独立结果" 在测试里可以
    # 直接钉死，避免未来 SDK 协议漂移把异常静默吞掉。
    # B2 契约：诊断信息用户必须能看到，不能用 [DEBUG] 前缀（会被
    # main.DEBUG_OUTPUT_PREFIXES 兜底过滤吞掉）。详见
    # docs/CLI_OUTPUT_CONTRACT.md "允许直接 print 的 prefix 白名单"。
    # v0.5 第七小步 D · L769 print 迁移到 RuntimeEvent。
    # 优先 ``turn_state.on_runtime_event``；callback 缺失回退 stdout
    # 保留 simple CLI 诊断可见性。
    # v0.5.1 YF1：用 _safe_emit_runtime_event 包住 sink 调用，
    # 防止 callback raise 跳过下面的 log_runtime_event("loop.stop") + return。
    _evt = unknown_stop_reason_event(response.stop_reason)
    _safe_emit_runtime_event(turn_state.on_runtime_event, _evt)
    log_runtime_event(
        "loop.stop",
        event_source="runtime",
        event_payload={
            **_runtime_loop_fields(),
            "stop_reason": response.stop_reason,
            "reason_for_stop": "unknown_stop_reason",
        },
        event_channel="loop",
    )
    return "意外的响应"


def chat(
    user_input: str,
    *,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
    on_trace_event: Callable[[Any], None] | None = None,
) -> str:
    """主入口：对话 + 规划 + 工具执行。

    `on_runtime_event` 是 Runtime -> UI 用户可见输出的主路径。`on_output_chunk` 和
    `on_display_event` 只作为 deprecated compatibility bridge 保留，分别兼容旧调用方
    接收 assistant delta 和 DisplayEvent；新调用方不应继续把它们当入口。这个函数
    只迁移 UI projection，不改变 checkpoint、runtime_observer、conversation.messages、
    Anthropic API messages 或 TaskState 状态机本体。

    `on_trace_event` 是 RFC 0002 的显式 opt-in observability seam：调用方如果需要
    本地 TraceEvent，可以传 sink；默认不创建 recorder，也不把 trace 写入 durable
    Runtime/checkpoint state。
    """

    # 空输入守卫：strip 后为空串的输入直接过滤掉。
    # 这是 chat() 内部的第二层守卫（main.py::main_loop 已有第一层），
    # 目的是让任何直接调 chat() 的前端也不会因空串触发：
    #   - 不必要的 LLM 调用（浪费 token）
    #   - awaiting 分支把空串当 feedback 触发重规划
    if not user_input or not user_input.strip():
        return ""

    # 状态一致性自愈：是否必须有 current_plan 统一交给 state helper 判断。
    # 这避免 core.py 继续散落硬编码 status tuple；更细的 plan/tool/user-input
    # 维度未来再拆 schema，当前阶段只收口 invariant。
    _inconsistent = (
        task_status_requires_plan(state.task)
        and state.task.current_plan is None
    )
    if _inconsistent:
        # v0.5 第七小步 D · L306 print 迁移到 RuntimeEvent。
        # 优先走调用方传入的 ``on_runtime_event`` callback；callback 缺失时
        # 回退到 stdout，保证 simple CLI 用户仍能看到诊断（characterization
        # baseline 在 tests/test_core_loop_terminal_prints.py 钉死双向行为）。
        # 注意：本处早于 ``_emit_runtime_event`` 闭包定义、早于 ``turn_state``
        # 构造，所以不能复用闭包；只能直接拿 chat() 参数。
        _evt = state_inconsistency_reset_event(state.task.status)
        # v0.5.1 YF1：用 _safe_emit_runtime_event 包住 sink 调用，
        # 防止 callback raise 跳过下面的 state.reset_task()。
        _safe_emit_runtime_event(on_runtime_event, _evt)
        state.reset_task()

    # 注意：不要在这里无条件压缩历史。
    # 当处于 awaiting_tool_confirmation 时，上一条 assistant 里有未闭合的
    # tool_use 块，它必须与稍后的 tool_result 配对。若此刻压缩，可能把该
    # tool_use 丢进摘要，留下悬空 tool_result，下次调用 API 会直接报错。

    runtime_system_prompt = refresh_runtime_system_prompt()

    def _emit_runtime_event(event: RuntimeEvent) -> None:
        """统一投递本轮用户可见输出，并集中兼容旧 callback。

        这是 core.py 内 RuntimeEvent 的唯一投递出口：Runtime 内部先生成
        RuntimeEvent，再由这里决定发给新主路径、deprecated 旧 callback，或无 sink 的
        simple CLI print fallback。旧 `on_output_chunk` / `on_display_event` 的转发必须
        保持集中，不能散落到模型流、工具执行或状态处理里；这个兼容层不能继续扩大成
        新协议，也不能承载 checkpoint、runtime_observer、conversation.messages、
        Anthropic API messages、TaskState 状态机本体、debug print 或 terminal observer
        log。
        """

        if on_runtime_event is not None:
            on_runtime_event(event)
            return

        if event.event_type == EVENT_ASSISTANT_DELTA:
            if on_output_chunk is not None:
                on_output_chunk(event.text)
                return
            print(render_runtime_event_for_cli(event), end="", flush=True)
            return

        if event.display_event is not None:
            if on_display_event is not None:
                on_display_event(event.display_event)
                return
            print(f"\n{render_runtime_event_for_cli(event)}", flush=True)
            return

        rendered = render_runtime_event_for_cli(event)
        if rendered:
            print(f"\n{rendered}", flush=True)

    def _emit_display_event(event: DisplayEvent) -> None:
        """把旧 DisplayEvent sink 收口到 RuntimeEvent，再交给统一投递桥。"""

        _emit_runtime_event(runtime_display_event(event))

    turn_state = TurnState(
        system_prompt=runtime_system_prompt,
        on_display_event=_emit_display_event,
        on_runtime_event=_emit_runtime_event,
        on_trace_event=on_trace_event,
        trace_run_id=(f"run:{uuid4().hex}" if on_trace_event is not None else None),
        trace_id=(f"trace:{uuid4().hex}" if on_trace_event is not None else None),
        print_assistant_newline=(
            on_runtime_event is None and on_output_chunk is None
        ),
    )

    # v0.4 Phase 2.1/2.2-a/2.2-b/2.2-c：构造一次 LoopContext 实例作为运行时
    # 依赖注入锚点，**整个调用链唯一构造点**。
    # - Phase 2.2-a：_run_planning_phase / _start_planning_for_handler 吃；
    # - Phase 2.2-b：_run_main_loop / _call_model 吃；
    # - Phase 2.2-c：_run_main_loop 开始消费 loop_ctx.max_loop_iterations
    #   （client / model_name 仍只在 _call_model 消费）。
    # confirm_handlers / response_handlers 仍走 ConfirmationContext，未迁移
    # （评估属未来切片）。严禁在任何 helper 内重建 LoopContext——SSOT 单源
    # 由 test_chat_remains_unique_loop_context_construction_site_in_core 钉死。
    # 模块级 MAX_LOOP_ITERATIONS 仍保留作为默认值，并兼容现有测试 import。
    #
    # v0.5 Phase 3 第一小步：构造调用走 _build_loop_context() 工厂（行为
    # 中性 helper），让 chat() 主体只剩"拿到运行时依赖"一行。SSOT 测试
    # 用 src.count 在 core.py 全文上检查 LoopContext 字面构造，构造从
    # chat() 移到 helper 后仍恰好 1 次（在 helper 内）。详见
    # _build_loop_context 顶部 docstring。
    #
    # 注意：这里**显式**把 MODEL_NAME / MAX_LOOP_ITERATIONS 作为 kwargs
    # 传入，而不是依赖 helper 的 def-time 默认值——否则
    # monkeypatch.setattr(core, "MAX_LOOP_ITERATIONS", N) 这类测试场景
    # 拿不到运行时被 patch 的值（Python 函数默认参数在 def 时求值，仅一次）。
    # 这一行写法保证 chat() 调用时**重新**读取模块级常量。
    _loop_ctx = _build_loop_context(
        client,
        model_name=MODEL_NAME,
        max_loop_iterations=MAX_LOOP_ITERATIONS,
    )

    # v0.5 Phase 3 第二小步：ConfirmationContext 构造走 _build_confirmation_context()
    # 工厂（行为中性 helper），与 _loop_ctx 抽 helper 形成对称结构——chat() 头部
    # 现在是清晰的"两行拿依赖"。client / model_name 来源从 module globals 切到
    # loop_ctx 字段（值等价：loop_ctx 也是由同一组 module globals 构造的）。
    # SSOT 测试 ``test_chat_remains_unique_confirmation_context_construction_site_in_core``
    # 钉死全文 ``ConfirmationContext`` 恰好 1 次。详见 _build_confirmation_context
    # 顶部 docstring。
    confirmation_ctx = _build_confirmation_context(
        state=state,
        turn_state=turn_state,
        loop_ctx=_loop_ctx,
    )

    # v0.5.1 第三小步：5 条 pending confirmation 分支抽进
    # ``_dispatch_pending_confirmation`` helper（纯函数提取，行为与提取前
    # 字面等价）。helper 返回 None 表示 fallthrough 到下方"压缩 + 新任务"
    # 路径；返回 str 表示已被某个 confirmation handler 接管。
    # baseline 由 tests/test_pending_confirmation_dispatch.py 11 条
    # characterization tests 钉死（cdd1427）。详见 helper docstring。
    _dispatched = _dispatch_pending_confirmation(state, user_input, confirmation_ctx)
    if _dispatched is not None:
        return _dispatched

    _compress_history_and_sync_checkpoint(_loop_ctx)

    # 如果当前已有运行中的任务，则默认把这次输入视为"继续当前任务"的反馈。
    if state.task.current_plan and state.task.status == "running":
        state.conversation.messages.append({"role": "user", "content": user_input})
        return _run_main_loop(turn_state, _loop_ctx)

    # 到这里意味着要开启一轮全新的任务。
    # 用 state.reset_task() 一次性清干净 task 层所有字段，避免"单步任务收尾
    # 不触发 done 路径、tool_execution_log / pending_tool 残留到下一个任务"
    # 这种 bug。之前这里只重置 4 个计数字段，其他字段（log/pending/user_goal
    # 等）都有可能带着旧值进新任务。
    state.reset_task()

    plan_result = _run_planning_phase(user_input, turn_state, _loop_ctx)
    return _handle_planning_phase_result(plan_result, turn_state, _loop_ctx)


# ========== 规划阶段 ==========


def _compress_history_and_sync_checkpoint(loop_ctx: LoopContext) -> None:
    """在进入新对话分支前压缩历史，并保持 active task checkpoint 同步。

    这是 Architecture Debt 第二刀的最小 behavior-preserving helper extraction：
    `chat()` 仍然决定何时进入"真正的新一轮对话"，本 helper 只封装原地已有的
    compression + active-task checkpoint sync 时机。它不改变 checkpoint schema、
    不改变 pending confirmation / Ask User / TUI contract，也不处理 XFAIL-1 /
    XFAIL-2；checkpoint ownership 仍留在 `agent.core` runtime 层。
    """

    # 到这里才是真正的「新一轮对话」：可以安全做压缩。
    messages = state.conversation.messages
    compressed_messages, new_summary = compress_history(
        messages,
        loop_ctx.client,
        existing_summary=state.memory.working_summary,
        max_recent_messages=state.runtime.max_recent_messages,
    )
    compression_happened = (
        compressed_messages is not messages or new_summary != state.memory.working_summary
    )
    state.conversation.messages = compressed_messages
    state.memory.working_summary = new_summary
    # 压缩真实发生且当前存在运行中任务时，立刻落盘，避免 summary 与 checkpoint 不一致。
    if compression_happened and state.task.current_plan:
        from agent.checkpoint import save_checkpoint as _save_checkpoint

        _save_checkpoint(state)


def _run_planning_phase(
    user_input: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
) -> str:
    """任务规划阶段。返回 'cancelled' / 'awaiting_plan_confirmation' / 'ok'。

    这里仍然只负责规划状态推进；计划展示属于 Runtime -> UI projection，所以通过
    RuntimeEvent 发出。不要为了让 TUI 看到计划而把展示文本写进 conversation.messages，
    也不要改变 checkpoint schema 或 TaskState 结构。

    v0.4 Phase 2.2-a 依赖注入边界
    -----------------------------
    本函数 LLM provider 依赖（``client`` / ``model_name``）从 ``loop_ctx`` 读取，
    不再隐式引用 ``agent.core`` 的模块级 ``client`` / ``MODEL_NAME``。但 **durable
    state**（``state.task`` / ``state.conversation.messages`` / ``state.task.
    current_plan`` / ``current_step_index``）仍通过模块级 ``state`` 单例读写——
    Phase 2.2-a 故意不把 state 塞进 LoopContext，否则 LoopContext 会从 runtime
    dependency container 退化成 god-object，并污染 checkpoint schema 边界。

    保持不变的契约：
    - ``state.conversation.messages.append({"role": "user", ...})`` 的写入时机；
    - ``state.task.user_goal / current_plan / current_step_index / confirm_each_step``
      的赋值时机；
    - ``save_checkpoint(state)`` 在 ``awaiting_plan_confirmation`` 切换后立即触发；
    - ``plan_confirmation_requested`` RuntimeEvent 发射时机；
    - ``confirm_each_step`` 关键词列表完全不动（产品契约）。
    """
    plan = generate_plan(
        user_input,
        loop_ctx.client,
        loop_ctx.model_name,
        build_planning_messages_from_state(state, user_input),
    )

    # 无论走哪条分支，用户原始输入都必须归档到 conversation.messages。
    # 否则「多步计划 → y 确认 → 执行」路径里，执行阶段模型看不到用户原话，
    # 只能依赖 planner 的二次总结 plan.goal，丢失细节。
    state.conversation.messages.append({"role": "user", "content": user_input})

    if not plan:
        # 这里可能是：planner 判定单步任务，或 planner 自身出错。
        # 单步分支是预期路径；但出错也会走这里，给用户一行轻量提示以便察觉。
        if turn_state.on_runtime_event is not None:
            turn_state.on_runtime_event(control_message("[系统] 未生成多步计划，按单步处理。"))
        return "ok"

    state.task.current_plan = plan.model_dump()
    state.task.user_goal = user_input
    state.task.current_step_index = 0
    state.task.confirm_each_step = any(
        marker in user_input
        for marker in (
            "每步确认",
            "每一步确认",
            "每一步都确认",
            "每步都确认",
            "每一步都让我确认",
            "每步都让我确认",
            "做完一步问我",
            "每做完一步问我",
            "一步一确认",
            "每步推理",
            "每一步推理",
            "逐步推理",
            "一步一步推理",
            "不要自动下一步",
            "不要自动继续",
            "先别自动执行下一步",
        )
    )
    state.task.status = "awaiting_plan_confirmation"

    # 一旦计划生成完毕且状态切到 awaiting_plan_confirmation，必须立刻落盘。
    # 否则用户此时 Ctrl+C，计划会完全丢失、重启后无感。
    from agent.checkpoint import save_checkpoint as _save_checkpoint
    _save_checkpoint(state)

    # 计划展示给用户，但此时还没有正式接受执行。RuntimeEvent 只投影 UI，不改变
    # current_plan / checkpoint / conversation.messages 的业务边界。
    if turn_state.on_runtime_event is not None:
        turn_state.on_runtime_event(
            plan_confirmation_requested(
                f"{format_plan_for_display(plan)}\n按此计划执行吗？(y/n/输入修改意见):",
                metadata={"source": "planning_phase"},
            )
        )
    return "awaiting_plan_confirmation"


def _handle_planning_phase_result(
    plan_result: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
) -> str:
    """统一处理规划阶段后的三种控制流结果。

    这是 v0.6.2 后 Architecture Debt 第一刀的行为保持型 helper extraction：
    `chat()` 主入口和 feedback-intent 切新任务入口都依赖同一套
    cancelled / awaiting_plan_confirmation / ok 分流。把这段逻辑收口到一个
    helper，避免两个入口未来漂移；helper 不写 checkpoint、不改 state、不碰 TUI
    或 Ask User，只把既有结果映射到既有返回值或主循环。
    """

    if plan_result == "cancelled":
        return "好的，已取消。"
    if plan_result == "awaiting_plan_confirmation":
        return ""
    return _run_main_loop(turn_state, loop_ctx)


def _start_planning_for_handler(
    user_input: str,
    turn_state: TurnState,
    loop_ctx: LoopContext,
) -> str:
    """与 chat() 主分支共用的"启动新任务"出口，供 confirm_handlers 注入。

    P1 中 awaiting_feedback_intent 选 [2] 切新任务时调用。它复用 chat() 在
    `_run_planning_phase` 后的三种路径处理（cancelled / awaiting_plan_confirmation /
    继续主循环），保证"用户主动开新任务"和"模糊反馈分流为新任务"走完全相同的
    后续路径——不会因为入口不同而出现 plan 展示、checkpoint 落盘、主循环触发
    时机的微妙差异。该函数只做路由，不修改任何 task 字段（`_run_planning_phase`
    自己负责赋值 user_goal/current_plan）。

    v0.4 Phase 2.2-a/2.2-b：``loop_ctx`` 既向下传给 ``_run_planning_phase``，
    也（在 Phase 2.2-b 后）向下传给 ``_run_main_loop`` 作为兜底执行入口。本
    函数自己不读 ``loop_ctx`` 任何字段——它只做控制流路由，把上层 chat() 构造
    的同一个 LoopContext 单源转发到下游，避免主循环出现第二个 LoopContext
    构造点。
    """

    plan_result = _run_planning_phase(user_input, turn_state, loop_ctx)
    return _handle_planning_phase_result(plan_result, turn_state, loop_ctx)


# ========== 主循环 ==========

def _runtime_loop_fields() -> dict:
    """提取主循环观测字段，只用于日志，不参与业务判断。"""

    fields = {
        "task_status": state.task.status,
        "current_step_index": state.task.current_step_index,
        "loop_iterations": state.task.loop_iterations,
        "has_pending_tool": bool(state.task.pending_tool),
        "has_pending_user_input": bool(state.task.pending_user_input_request),
    }
    plan = state.task.current_plan or {}
    steps = plan.get("steps") or []
    idx = state.task.current_step_index
    if 0 <= idx < len(steps):
        step = steps[idx]
        fields["current_step_title"] = step.get("title")
        fields["current_step_type"] = step.get("step_type")
    return fields

def _run_main_loop(
    turn_state: TurnState,
    loop_ctx: LoopContext,
) -> str:
    """模型调用循环，按 stop_reason 分派处理。

    v0.4 Phase 2.2-b/2.2-c 依赖注入边界
    -----------------------------------
    本函数签名增加 ``loop_ctx`` 后承担两个最小职责：
    1. **转发**给 ``_call_model``（Phase 2.2-b）：让 LLM provider 边界
       (``client`` / ``model_name``) 显式吃 LoopContext，不再隐式引用模块级。
    2. **消费 ``loop_ctx.max_loop_iterations``**（Phase 2.2-c）：循环兜底次数
       归为 runtime configuration，与 client/model_name 同级，由 chat() 单源
       构造。模块级 ``MAX_LOOP_ITERATIONS = 50`` 仍保留作为**默认值**，供
       chat() 构造 LoopContext 时引用，并兼容现有 ``from agent.core import
       MAX_LOOP_ITERATIONS`` 的测试。

    本切片**严格不做的事**：
    - ❌ 不在函数体内构造 LoopContext（已有 chat() 唯一构造点）；
    - ❌ 不读 ``loop_ctx.client`` / ``loop_ctx.model_name`` 自己使用——这些
      通过 ``_call_model`` 间接消费，保持"主循环不知道 LLM provider 细节"
      的边界；
    - ❌ 不动主循环控制流（while/guard/iteration log/dispatch 全部不变）；
    - ❌ 不动 ``state.task.loop_iterations`` 自增逻辑；
    - ❌ 不动 ``save_checkpoint`` / ``clear_checkpoint`` / ``state.reset_task``
      调用时机；
    - ❌ 不动 ``classify_model_output`` 分类与 4 个 dispatch 分支。
    """
    log_runtime_event(
        "loop.start",
        event_source="runtime",
        event_payload=_runtime_loop_fields(),
        event_channel="loop",
    )
    while True:
        state.task.loop_iterations += 1
        log_runtime_event(
            "loop.iteration_start",
            event_source="runtime",
            event_payload=_runtime_loop_fields(),
            event_channel="loop",
        )
        if state.task.loop_iterations > loop_ctx.max_loop_iterations:
            log_runtime_event(
                "loop.guard_triggered",
                event_source="runtime",
                event_payload={
                    **_runtime_loop_fields(),
                    "reason_for_stop": "max_loop_iterations",
                },
                event_channel="loop",
            )
            # v0.5 第七小步 D · L670 print 迁移到 RuntimeEvent。
            # 在 ``_run_main_loop`` 内部通过 ``turn_state.on_runtime_event``
            # 投递；callback 缺失时回退 stdout，保留 simple CLI 诊断可见性。
            # 注意：本事件**只**替换原 print，**不**改：
            #   - 上方 ``log_runtime_event("loop.guard_triggered", ...)`` observer 写入；
            #   - 下方 ``clear_checkpoint`` / ``state.reset_task`` / return value。
            _evt = loop_max_iterations_event(loop_ctx.max_loop_iterations)
            # v0.5.1 YF1：用 _safe_emit_runtime_event 包住 sink 调用，
            # 防止 callback raise 跳过下面的 clear_checkpoint / reset_task / return。
            _safe_emit_runtime_event(
                turn_state.on_runtime_event, _evt, fallback_prefix="\n"
            )
            from agent.checkpoint import clear_checkpoint as _clear_checkpoint
            _clear_checkpoint()
            state.reset_task()
            return "对话循环次数过多，请简化任务或分步执行。"

        response = _call_model(turn_state, loop_ctx)
        # v0.5.1 第五小步：4 个 ModelOutputKind 分支已抽到 _dispatch_model_output。
        # 本调用点**只**做：拿 response → 交给 helper → 据返回值 return / continue。
        # 行为与提取前完全等价，由 tests/test_model_output_dispatch.py 9 条
        # characterization tests + 同文件 helper-level None fallthrough 测试
        # 双层保护。**不**在此处再读 stop_reason / 调 classify_model_output /
        # 写 loop.iteration_end log——那些已搬入 helper，重复会导致双发。
        result = _dispatch_model_output(response, turn_state=turn_state)
        if result is not None:
            return result
        continue



def _call_model(
    turn_state: TurnState,
    loop_ctx: LoopContext,
):
    """调用模型（流式）并返回最终 response。

    模型 SDK 已经给出 content_block_delta。这里不再直接 print/callback，而是先
    生成 RuntimeEvent；chat() 的兼容桥再决定送给 TUI、旧 callback 还是 simple CLI。
    这样 assistant.delta 和 tool lifecycle 属于同一条 UI projection 流，仍然不进入
    checkpoint、conversation.messages、runtime_observer 或 Anthropic API messages。

    v0.4 Phase 2.2-b 依赖注入边界
    -----------------------------
    - LLM provider 依赖（``client`` / ``model_name``）从 ``loop_ctx`` 显式读取，
      不再隐式引用 ``agent.core`` 的模块级 ``client`` / ``MODEL_NAME``；
    - ``MAX_TOKENS`` 仍读模块级常量——本切片不扩张 LoopContext 字段集合（详见
      ``agent/loop_context.py`` "MVP / mock / demo 边界"），未来如需 per-turn 调
      max_tokens 再单独评估是否进 LoopContext；
    - **绝不**通过 ``loop_ctx`` 取 ``request_messages`` / ``system_prompt`` /
      ``tools``：messages 是 durable state 的派生（来自 ``state.conversation``），
      system_prompt 是 per-turn 信息（在 ``turn_state``），tools 是 registry
      singleton（``get_tool_definitions()``）——三者都不属于 runtime dependency。
    """
    # ===== 协议观察：构造 request payload 并打印 =====
    request_messages = build_execution_messages_from_state(state)
    # _debug_print_request(turn_state.system_prompt, request_messages, get_tool_definitions())

    with loop_ctx.client.messages.stream(
        model=loop_ctx.model_name,
        max_tokens=MAX_TOKENS,
        system=turn_state.system_prompt,
        messages=request_messages,
        tools=get_tool_definitions(),
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", None)

            if event_type == "content_block_start":
                block_type = getattr(event.content_block, "type", None)
                if block_type == "tool_use" and turn_state.on_runtime_event is not None:
                    turn_state.on_runtime_event(tool_requested())

            elif event_type == "content_block_delta":
                delta_text = getattr(event.delta, "text", None)
                if delta_text and turn_state.on_runtime_event is not None:
                    turn_state.on_runtime_event(assistant_delta(delta_text))

        response = stream.get_final_message()
        if turn_state.print_assistant_newline:
            print()

    # ===== 协议观察：打印返回结构 =====
    # _debug_print_response(response)

    return response




# ========== 辅助 ==========

def _extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()


# ========== 协议观察（调试用，稳定后可关）==========

# B2 契约：DEBUG_PROTOCOL 默认 False。
# 历史上这里默认 True，且 _debug_print_request / _debug_print_response 会在
# 每轮模型调用时打印巨量 REQUEST / RESPONSE dump，是普通 CLI 下"看不清
# Agent 在做什么"的潜在回归源（虽然当前 545/572 行调用点已注释掉，但只要
# 任何人取消注释，污染就会立刻回归）。
# 现在把开关收到环境变量 MY_FIRST_AGENT_PROTOCOL_DUMP，普通 CLI 永远不会
# 触发；函数体逻辑不动，方便临时排查。详见 docs/CLI_OUTPUT_CONTRACT.md。
DEBUG_PROTOCOL = False


def _protocol_dump_enabled() -> bool:
    """协议 dump 开关：普通 CLI 永远不打印，仅排查时开。

    打开方式：MY_FIRST_AGENT_PROTOCOL_DUMP=1。这里独立于 DEBUG_PROTOCOL
    常量，让函数级 guard 与模块级常量一起决定是否输出，避免任何一侧
    被误改成 True 时直接污染普通 CLI。
    """

    if not DEBUG_PROTOCOL:
        return False
    import os
    return os.getenv("MY_FIRST_AGENT_PROTOCOL_DUMP", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _truncate(s: str, n: int = 200) -> str:
    if len(s) <= n:
        return s
    return s[:n] + f"...(共 {len(s)} 字，截 {n})"


def _summarize_content(content) -> str:
    """把一条 message 的 content 压成一行人类可读的描述。"""
    if isinstance(content, str):
        return f"text: {_truncate(content, 150)!r}"
    if not isinstance(content, list):
        return f"<未知形态 {type(content).__name__}>"
    parts = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(f"<非 dict 块 {type(block).__name__}>")
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(f"text {_truncate(block.get('text',''), 120)!r}")
        elif btype == "tool_use":
            parts.append(
                f"tool_use(id={block.get('id')}, "
                f"name={block.get('name')}, "
                f"input={_truncate(str(block.get('input')), 120)})"
            )
        elif btype == "tool_result":
            content_text = block.get("content", "")
            if not isinstance(content_text, str):
                content_text = str(content_text)
            parts.append(
                f"tool_result(tool_use_id={block.get('tool_use_id')}, "
                f"content={_truncate(content_text, 120)!r})"
            )
        else:
            parts.append(f"{btype}(...)")
    return " | ".join(parts)


def _debug_print_request(system_prompt: str, messages: list, tools: list) -> None:
    if not _protocol_dump_enabled():
        return
    print("\n" + "=" * 12 + " REQUEST → Anthropic " + "=" * 12)
    print(f"model:  {MODEL_NAME}")
    print(f"system: {_truncate(system_prompt, 200)}")
    print(f"tools:  {[t['name'] for t in tools]}")
    print(f"messages ({len(messages)} 条):")
    for i, msg in enumerate(messages):
        role = msg.get("role")
        summary = _summarize_content(msg.get("content"))
        print(f"  [{i}] role={role}")
        print(f"       {summary}")
    print("=" * 45 + "\n")


def _debug_print_response(response) -> None:
    if not _protocol_dump_enabled():
        return
    print("\n" + "=" * 12 + " RESPONSE ← Anthropic " + "=" * 11)
    print(f"stop_reason: {response.stop_reason}")
    print("content blocks:")
    for i, block in enumerate(response.content):
        btype = getattr(block, "type", "?")
        if btype == "text":
            print(f"  [{i}] text: {_truncate(block.text, 150)!r}")
        elif btype == "tool_use":
            print(
                f"  [{i}] tool_use: {block.name}"
                f"(id={block.id}, input={_truncate(str(block.input), 150)})"
            )
        else:
            print(f"  [{i}] {btype}: ...")
    usage = getattr(response, "usage", None)
    if usage is not None:
        print(
            f"usage: input_tokens={usage.input_tokens}, "
            f"output_tokens={usage.output_tokens}"
            + (
                f", cache_read={getattr(usage, 'cache_read_input_tokens', 0)}, "
                f"cache_create={getattr(usage, 'cache_creation_input_tokens', 0)}"
                if hasattr(usage, "cache_read_input_tokens") else ""
            )
        )
    print("=" * 45 + "\n")
