"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
from collections.abc import Callable
from dataclasses import dataclass, field
import anthropic
from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    DisplayEvent,
    DisplayEventSink,
    RuntimeEvent,
    RuntimeEventSink,
    assistant_delta,
    control_message,
    plan_confirmation_requested,
    render_runtime_event_for_cli,
    runtime_display_event,
    tool_requested,
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
)

from agent.response_handlers import (
    handle_end_turn_response,
    handle_max_tokens_response,
    handle_tool_use_response,
)
from agent.runtime_observer import log_event as log_runtime_event





# ========== 常量 ==========


MAX_LOOP_ITERATIONS = 50              # 循环总次数兜底（防死循环）


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

def chat(
    user_input: str,
    *,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
) -> str:
    """主入口：对话 + 规划 + 工具执行。

    `on_runtime_event` 是 Runtime -> UI 用户可见输出的主路径。`on_output_chunk` 和
    `on_display_event` 只作为 deprecated compatibility bridge 保留，分别兼容旧调用方
    接收 assistant delta 和 DisplayEvent；新调用方不应继续把它们当入口。这个函数
    只迁移 UI projection，不改变 checkpoint、runtime_observer、conversation.messages、
    Anthropic API messages 或 TaskState 状态机本体。
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
        print(
            f"[系统] 检测到不一致状态（status={state.task.status}, plan=None），已重置。"
        )
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
        print_assistant_newline=(
            on_runtime_event is None and on_output_chunk is None
        ),
    )

    confirmation_ctx = ConfirmationContext(
        state=state,
        turn_state=turn_state,
        client=client,
        model_name=MODEL_NAME,
        continue_fn=lambda ts: _run_main_loop(
            ts,
        ),
    )

    # 先处理"等待用户确认计划"的状态：
    # 这时输入不再按普通 chat 语义解释，而是按确认协议处理。
    if state.task.current_plan and state.task.status == "awaiting_plan_confirmation":
        return handle_plan_confirmation(user_input, confirmation_ctx)

    # 处理"等待用户确认是否进入下一步"的状态。
    if state.task.current_plan and state.task.status == "awaiting_step_confirmation":
        return handle_step_confirmation(user_input, confirmation_ctx)

    # 处理"等待用户补充信息"的状态。
    if (
        state.task.status == "awaiting_user_input"
        and (state.task.current_plan or state.task.pending_user_input_request)
    ):
        return handle_user_input_step(user_input, confirmation_ctx)

    # 新增：处理工具确认（state 驱动）
    if getattr(state.task, "pending_tool", None) and state.task.status == "awaiting_tool_confirmation":
        return handle_tool_confirmation(user_input, confirmation_ctx)

    # 到这里才是真正的「新一轮对话」：可以安全做压缩。
    messages = state.conversation.messages
    compressed_messages, new_summary = compress_history(
        messages,
        client,
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

    # 如果当前已有运行中的任务，则默认把这次输入视为"继续当前任务"的反馈。
    if state.task.current_plan and state.task.status == "running":
        state.conversation.messages.append({"role": "user", "content": user_input})
        return _run_main_loop(turn_state)

    # 到这里意味着要开启一轮全新的任务。
    # 用 state.reset_task() 一次性清干净 task 层所有字段，避免"单步任务收尾
    # 不触发 done 路径、tool_execution_log / pending_tool 残留到下一个任务"
    # 这种 bug。之前这里只重置 4 个计数字段，其他字段（log/pending/user_goal
    # 等）都有可能带着旧值进新任务。
    state.reset_task()

    plan_result = _run_planning_phase(user_input, turn_state)
    if plan_result == "cancelled":
        return "好的，已取消。"

    if plan_result == "awaiting_plan_confirmation":
        return ""

    return _run_main_loop(turn_state)


# ========== 规划阶段 ==========


def _run_planning_phase(user_input: str, turn_state: TurnState) -> str:
    """任务规划阶段。返回 'cancelled' / 'awaiting_plan_confirmation' / 'ok'。

    这里仍然只负责规划状态推进；计划展示属于 Runtime -> UI projection，所以通过
    RuntimeEvent 发出。不要为了让 TUI 看到计划而把展示文本写进 conversation.messages，
    也不要改变 checkpoint schema 或 TaskState 结构。
    """
    plan = generate_plan(user_input, client, MODEL_NAME, build_planning_messages_from_state(state,user_input))

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
) -> str:
    """模型调用循环，按 stop_reason 分派处理。"""
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
        if state.task.loop_iterations > MAX_LOOP_ITERATIONS:
            log_runtime_event(
                "loop.guard_triggered",
                event_source="runtime",
                event_payload={
                    **_runtime_loop_fields(),
                    "reason_for_stop": "max_loop_iterations",
                },
                event_channel="loop",
            )
            print(f"\n[系统] 循环次数超过上限 {MAX_LOOP_ITERATIONS}，强制停止。")
            from agent.checkpoint import clear_checkpoint as _clear_checkpoint
            _clear_checkpoint()
            state.reset_task()
            return "对话循环次数过多，请简化任务或分步执行。"

        response = _call_model(turn_state)
        log_runtime_event(
            "loop.iteration_end",
            event_source="runtime",
            event_payload={
                **_runtime_loop_fields(),
                "stop_reason": response.stop_reason,
            },
            event_channel="loop",
        )

        if response.stop_reason == "max_tokens":
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
            continue

        if response.stop_reason == "end_turn":
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
            continue

        if response.stop_reason == "tool_use":
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
            continue

        print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")
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


def _call_model(
    turn_state: TurnState,
):
    """调用模型（流式）并返回最终 response。

    模型 SDK 已经给出 content_block_delta。这里不再直接 print/callback，而是先
    生成 RuntimeEvent；chat() 的兼容桥再决定送给 TUI、旧 callback 还是 simple CLI。
    这样 assistant.delta 和 tool lifecycle 属于同一条 UI projection 流，仍然不进入
    checkpoint、conversation.messages、runtime_observer 或 Anthropic API messages。
    """
    # ===== 协议观察：构造 request payload 并打印 =====
    request_messages = build_execution_messages_from_state(state)
    # _debug_print_request(turn_state.system_prompt, request_messages, get_tool_definitions())

    with client.messages.stream(
        model=MODEL_NAME,
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

DEBUG_PROTOCOL = True   # 想关闭把这里改成 False


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
    if not DEBUG_PROTOCOL:
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
    if not DEBUG_PROTOCOL:
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
