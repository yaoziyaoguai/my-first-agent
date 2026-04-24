"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
from agent.plan_schema import Plan
from dataclasses import dataclass, field
from typing import Optional
import anthropic
from agent.prompt_builder import build_system_prompt
from agent.state import create_agent_state
import agent.tools  # noqa: F401  触发所有工具注册



from config import (
    API_KEY, BASE_URL, MODEL_NAME, MAX_TOKENS,
    MAX_CONTINUE_ATTEMPTS,
)
from agent.memory import compress_history
from agent.planner import generate_plan, format_plan_for_display
from agent.tool_registry import get_tool_definitions
from agent.checkpoint import save_checkpoint, clear_checkpoint
from agent.context_builder import (
    build_planning_messages as build_planning_messages_from_state,
    build_execution_messages as build_execution_messages_from_state,
)


from agent.confirm_handlers import (
    handle_plan_confirmation,
    handle_step_confirmation,
    handle_tool_confirmation,
)

from agent.response_handlers import handle_tool_use_response




# ========== 常量 ==========

MAX_TOOL_CALLS_PER_TURN = 20          # 实际工具调用上限
MAX_LOOP_ITERATIONS = 50              # 循环总次数兜底（防死循环）
MAX_CONSECUTIVE_REJECTIONS = 3        # 连续拒绝强制停止阈值
FORCE_STOP_REJECTION_THRESHOLD = 2    # 追加系统指令的拒绝阈值


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


# ========== 循环状态 ==========

@dataclass
class TurnState:
    """一次 chat 调用内部的循环状态。"""
    system_prompt: str
    round_tool_traces: list = field(default_factory=list)
    auto_retry_count: int = 0
    tool_call_count: int = 0        # 真实工具调用次数
    loop_iterations: int = 0        # 循环次数
    consecutive_rejections: int = 0
    consecutive_max_tokens: int = 0


def get_state():

    """

    读取当前全局 AgentState。

    先保留全局单例写法，后面再考虑彻底去全局化。

    """

    return state

def get_messages() -> list[dict]:

    """

    兼容旧逻辑：统一从 state.conversation.messages 取消息历史。

    """

    return state.conversation.messages


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

def _advance_current_step_if_needed() -> None:
    if not state.task.current_plan:
        return

    plan = Plan.model_validate(state.task.current_plan)
    if not plan.steps:
        return

    current_index = state.task.current_step_index
    last_index = len(plan.steps) - 1

    if current_index < last_index:
        state.task.current_step_index += 1
    else:
        # ✅ 已完成最后一步
        state.task.status = "done"
        state.task.current_plan = None
        state.task.current_step_index = 0

def is_current_step_completed(assistant_text: str) -> bool:
    """
    轻量版 step 完成判定。

    当前策略：
    - 在 step confirmation 模式下，不再用 completion_criteria 作为硬门槛
    - 只要当前存在有效 step，并且模型这一轮已经正常 end_turn，
      就允许进入后续的 step confirmation / step 推进流程

    说明：
    - 真正是否进入下一步，由 awaiting_step_confirmation + 用户确认决定
    - completion_criteria 仍可作为提示信息给模型看，但不再阻断状态推进
    """
    if not state.task.current_plan:
        return True

    plan = Plan.model_validate(state.task.current_plan)
    idx = state.task.current_step_index

    # 当前 step 索引不合法，默认视为完成，避免卡死
    if not (0 <= idx < len(plan.steps)):
        return True

    return True

# ========== 对外主入口 ==========

def chat(user_input: str) -> str:
    """主入口：对话 + 规划 + 工具执行。"""

    messages = state.conversation.messages
    compressed_messages, new_summary = compress_history(
        messages,
        client,
        existing_summary=state.memory.working_summary,
        max_recent_messages=state.runtime.max_recent_messages,
    )
    
    state.conversation.messages = compressed_messages
    state.memory.working_summary = new_summary

    runtime_system_prompt = refresh_runtime_system_prompt()

    turn_state = TurnState(
        system_prompt=runtime_system_prompt,
    )

    # 先处理“等待用户确认计划”的状态：
    # 这时输入不再按普通 chat 语义解释，而是按确认协议处理。
    if state.task.current_plan and state.task.status == "awaiting_plan_confirmation":
        return handle_plan_confirmation(
            user_input,
            state=state,
            turn_state=turn_state,
            client=client,
            model_name=MODEL_NAME,
            continue_fn=_run_main_loop,
            build_planning_messages_fn=build_planning_messages_from_state,
        )

    # 处理“等待用户确认是否进入下一步”的状态。
    if state.task.current_plan and state.task.status == "awaiting_step_confirmation":
        return handle_step_confirmation(
            user_input,
            state=state,
            turn_state=turn_state,
            client=client,
            model_name=MODEL_NAME,
            continue_fn=_run_main_loop,
            advance_step_fn=_advance_current_step_if_needed,
            build_planning_messages_fn=build_planning_messages_from_state,
        )

    # 新增：处理工具确认（state 驱动）
    if getattr(state.task, "pending_tool", None) and state.task.status == "awaiting_tool_confirmation":
        return handle_tool_confirmation(
            user_input,
            state=state,
            turn_state=turn_state,
            continue_fn=_run_main_loop,
        )

    # 如果当前已有运行中的任务，则默认把这次输入视为“继续当前任务”的反馈。
    if state.task.current_plan and state.task.status == "running":
        state.conversation.messages.append({"role": "user", "content": user_input})
        return _run_main_loop(turn_state)

    plan_result = _run_planning_phase(user_input)
    if plan_result == "cancelled":
        return "好的，已取消。"

    if plan_result == "awaiting_plan_confirmation":
        return ""

    return _run_main_loop(turn_state)


# ========== 规划阶段 ==========

def _run_planning_phase(user_input: str) -> str:
    """任务规划阶段。返回 'cancelled' / 'awaiting_plan_confirmation' / 'ok'。"""
    plan = generate_plan(user_input, client, MODEL_NAME, build_planning_messages_from_state(state,user_input))
    if not plan:
        get_messages().append({"role": "user", "content": user_input})
        return "ok"

    state.task.current_plan = plan.model_dump()
    state.task.user_goal = user_input
    state.task.current_step_index = 0
    state.task.status = "awaiting_plan_confirmation"

    # 计划展示给用户，但此时还没有正式接受执行。
    print(format_plan_for_display(plan))
    print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
    return "awaiting_plan_confirmation"




# ========== 主循环 ==========

def _run_main_loop(turn_state: TurnState) -> str:
    """模型调用循环，按 stop_reason 分派处理。"""
    while True:
        turn_state.loop_iterations += 1
        if turn_state.loop_iterations > MAX_LOOP_ITERATIONS:
            print(f"\n[系统] 循环次数超过上限 {MAX_LOOP_ITERATIONS}，强制停止。")
            return "对话循环次数过多，请简化任务或分步执行。"

        response = _call_model(turn_state)

        if response.stop_reason == "max_tokens":
            result = _handle_max_tokens(response, turn_state)
            if result is not None:
                return result
            continue

        if response.stop_reason == "end_turn":
            result = _handle_end_turn(response, turn_state)
            if result is not None:
                return result
            continue

        if response.stop_reason == "tool_use":
            result = handle_tool_use_response(
                response,
                state=state,
                turn_state=turn_state,
                messages=get_messages(),
                extract_text_fn=_extract_text,
            )
            if result is not None:
                return result
            continue

        print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")
        return "意外的响应"


def _call_model(turn_state: TurnState):
    """调用模型（流式）并返回最终 response。"""
    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=turn_state.system_prompt,
        messages=build_execution_messages_from_state(state),
        tools=get_tool_definitions(),
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", None)

            if event_type == "content_block_start":
                block_type = getattr(event.content_block, "type", None)
                if block_type == "tool_use":
                    print("\n🔧 正在规划工具调用...", flush=True)

            elif event_type == "content_block_delta":
                delta_text = getattr(event.delta, "text", None)
                if delta_text:
                    print(delta_text, end="", flush=True)

        response = stream.get_final_message()
        print()

    return response


# ========== stop_reason 处理器 ==========

def _handle_max_tokens(response, turn_state: TurnState) -> Optional[str]:
    """输出被截断。返回字符串表示结束，None 表示继续循环。"""
    turn_state.consecutive_max_tokens += 1

    if turn_state.consecutive_max_tokens >= MAX_CONTINUE_ATTEMPTS:
        print(f"\n[系统] 已连续 {turn_state.consecutive_max_tokens} 次触发输出上限，强制停止。")
        get_messages().append({"role": "assistant", "content": response.content})
        return "内容过长，已自动截断。如需完整输出，请分步请求。"

    print(f"\n[系统] 回复被截断，自动继续（{turn_state.consecutive_max_tokens}/{MAX_CONTINUE_ATTEMPTS}）...", flush=True)

    get_messages().append({"role": "assistant", "content": response.content})
    get_messages().append({"role": "user", "content": "请继续你刚才的输出，不要重复已经说过的内容。"})
    return None


def _handle_end_turn(response, turn_state: TurnState) -> Optional[str]:
    turn_state.consecutive_max_tokens = 0

    assistant_text = _extract_text(response.content)
    if not assistant_text:
        assistant_text = "[任务完成]"

    # ✅ 不再塞 response.content
    get_messages().append({
        "role": "assistant",
        "content": assistant_text
    })

    if is_current_step_completed(assistant_text):
        if state.task.current_plan:
            plan = Plan.model_validate(state.task.current_plan)
            idx = state.task.current_step_index

            if idx < len(plan.steps) - 1:
                state.task.status = "awaiting_step_confirmation"
                save_checkpoint(state)
                return (
                    assistant_text
                    + "\n\n本步骤已完成。回复 y 继续下一步，回复 n 停止任务。"
                )

        _advance_current_step_if_needed()

    if state.task.status == "done":
        clear_checkpoint()

    return assistant_text




# ========== 辅助 ==========

def _extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()


