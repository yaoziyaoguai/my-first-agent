"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
import json
import re
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
from agent.tool_registry import execute_tool, get_tool_definitions, needs_tool_confirmation
from agent.checkpoint import save_checkpoint, clear_checkpoint




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



def build_planning_messages(current_user_input: str) -> list[dict]:
    """
    构造给 planner 使用的轻量 messages。

    规则：
    - 只提供历史摘要 + 最近原始消息
    - 不注入 current_plan / current_step / completion_criteria
    - 避免让 planner 被执行态上下文污染
    - 当前轮输入只在这里临时加入，不提前写回 conversation state
    """
    model_messages: list[dict] = []

    if state.memory.working_summary:
        model_messages.append({
            "role": "user",
            "content": f"[以下是之前对话的摘要]\n{state.memory.working_summary}",
        })
        model_messages.append({
            "role": "assistant",
            "content": "好的，我了解了之前的对话内容。请继续。",
        })

    model_messages.extend(state.conversation.messages)
    model_messages.append({"role": "user", "content": current_user_input})
    return model_messages



def build_execution_messages() -> list[dict]:
    """
    构造真正喂给执行阶段模型的 messages。

    规则：
    - summary 不存到 conversation.messages
    - current_plan 不存到 conversation.messages
    - 只在这里临时拼接
    - 只给模型当前步骤，而不是整份计划
    """
    model_messages: list[dict] = []

    # 历史摘要
    if state.memory.working_summary:
        model_messages.append({
            "role": "user",
            "content": f"[以下是之前对话的摘要]\n{state.memory.working_summary}",
        })
        model_messages.append({
            "role": "assistant",
            "content": "好的，我了解了之前的对话内容。请继续。",
        })

    # 当前任务步骤
    if state.task.current_plan:
        plan = Plan.model_validate(state.task.current_plan)
        current_step = state.task.current_step_index

        if 0 <= current_step < len(plan.steps):
            step = plan.steps[current_step]

            step_lines = [
                f"[当前任务] {plan.goal}",
            ]

            if plan.thinking:
                step_lines.append(f"规划思路：{plan.thinking}")

            step_lines.extend([
                f"[当前执行进度]：正在执行第 {current_step + 1} 步 / 共 {len(plan.steps)} 步",
            ])
            # Step Memory（已完成步骤注入）
            completed_steps = plan.steps[:current_step]
            if completed_steps:
                step_lines.append("\n【已完成步骤】")
                for i, s in enumerate(completed_steps):
                    step_lines.append(f"{i+1}. {s.title}（已完成）")

            step_lines.extend([
                f"[当前步骤标题]：{step.title}",
                f"[当前步骤说明]：{step.description}",
                f"[步骤类型]：{step.step_type}",
            ])

            if step.suggested_tool:
                step_lines.append(f"[建议工具]：{step.suggested_tool}")

            if step.expected_outcome:
                step_lines.append(f"[预期结果]：{step.expected_outcome}")

            if step.completion_criteria:
                step_lines.append(f"[完成标准]：{step.completion_criteria}")

            step_lines.extend([
                "",
                "【执行上下文】",
                f"- 当前任务：{plan.goal}",
                f"- 当前步骤：第 {current_step + 1} 步 / 共 {len(plan.steps)} 步",
                f"- 步骤名称：{step.title}",
                "",
                "【执行目标】",
                f"{step.description}",
                "",
                "【执行约束（必须严格遵守）】",
                "- 你只能执行当前步骤",
                "- 不允许执行已完成步骤的内容",
                "- 不允许执行与当前步骤无关的行为",
                "- 不要重复【已完成步骤】中的任何行为",
                "",
                "【行为判断规则】",
                "- 如果你的行为与当前步骤目标不一致，这是错误",
                "- 如果重复之前步骤，这是错误",
                "- 如果偏离当前步骤目标，这是错误",
                "",
                "【完成要求】",
                "- 完成后必须明确说明：本步骤已完成",
            ])

            model_messages.append({
                "role": "user",
                "content": "\n".join(step_lines),
            })

    model_messages.extend(state.conversation.messages)
    return model_messages

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
        return _handle_plan_confirmation(user_input, turn_state)

    # 处理“等待用户确认是否进入下一步”的状态。
    if state.task.current_plan and state.task.status == "awaiting_step_confirmation":
        return _handle_step_confirmation(user_input, turn_state)

    # 新增：处理工具确认（state 驱动）
    if getattr(state.task, "pending_tool", None) and state.task.status == "awaiting_tool_confirmation":
        return _handle_tool_confirmation(user_input, turn_state)

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
    plan = generate_plan(user_input, client, MODEL_NAME, build_planning_messages(user_input))
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


# 新增：处理“等待用户确认计划”阶段的输入
def _handle_plan_confirmation(user_input: str, turn_state: TurnState) -> str:
    """
    处理“等待用户确认计划”阶段的输入。

    规则：
    - y：接受当前计划，进入 running 并开始执行
    - n：取消当前计划，回到 idle
    - 其他任意输入：视为对当前计划的修改意见，重新生成计划
    """
    confirm = user_input.strip()

    if confirm.lower() == "y":
        _append_control_event("plan_confirm_yes", {})
        state.task.status = "running"
        save_checkpoint(state)
        return _run_main_loop(turn_state)

    if confirm.lower() == "n":
        _append_control_event("plan_confirm_no", {})
        state.reset_task()
        return "好的，已取消。"

    # 其他任何输入都视为对计划的修改意见：
    # 基于原始目标 + 修改意见重新生成计划，而不是继续执行。
    revised_goal = f"{state.task.user_goal}\n\n用户对计划的修改意见：{confirm}"
    state.task.user_goal = revised_goal

    plan = generate_plan(revised_goal, client, MODEL_NAME, build_planning_messages(revised_goal))
    if not plan:
        state.reset_task()
        return "未能根据你的修改意见重新生成计划，请重新描述你的需求。"

    state.task.current_plan = plan.model_dump()
    state.task.current_step_index = 0
    state.task.status = "awaiting_plan_confirmation"

    print(format_plan_for_display(plan))
    print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
    return ""


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
            result = _handle_tool_use(response, turn_state)
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
        messages=build_execution_messages(),
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
    """模型说完了，按当前步骤完成情况决定是否进入 step confirmation。"""
    turn_state.consecutive_max_tokens = 0

    assistant_text = _extract_text(response.content)
    if not assistant_text:
        assistant_text = "[任务完成]"

    get_messages().append({"role": "assistant", "content": response.content})

    if is_current_step_completed(assistant_text):
        print("[DEBUG] current task status before end_turn:", state.task.status)

        # 如果当前任务还有后续步骤，则先进入 step confirmation，
        # 不立即推进 current_step_index，等待用户确认“继续下一步”。
        if state.task.current_plan:
            plan = Plan.model_validate(state.task.current_plan)
            current_index = state.task.current_step_index
            last_index = len(plan.steps) - 1

            if current_index < last_index:
                print("[DEBUG] entering awaiting_step_confirmation")
                state.task.status = "awaiting_step_confirmation"
                save_checkpoint(state)
                return (
                    assistant_text
                    + "\n\n本步骤已完成。回复 y 继续下一步，回复 n 停止当前任务，"
                      "或输入补充信息以调整后续计划。"
                )

        # 已经是最后一步：直接收口为 done
        _advance_current_step_if_needed()

    # 只有当任务真正完成时才清理 checkpoint
    if state.task.status == "done":
        clear_checkpoint()

    return assistant_text


def _handle_step_confirmation(user_input: str, turn_state: TurnState) -> str:
    """
    处理“等待用户确认是否进入下一步”的状态。

    协议：
    - y：推进到下一步并继续执行
    - n：停止当前任务
    - 其他任意输入：视为对后续步骤的修改意见，重新生成计划
    """
    confirm = user_input.strip()

    if confirm.lower() == "y":
        _append_control_event("step_confirm_yes", {})
        _advance_current_step_if_needed()
        state.task.status = "running"
        save_checkpoint(state)
        return _run_main_loop(turn_state)

    if confirm.lower() == "n":
        _append_control_event("step_confirm_no", {})
        state.reset_task()
        clear_checkpoint()
        return "好的，当前任务已停止。"

    # 其他输入：视为对后续步骤的修改意见，重新生成计划
    get_messages().append({"role": "user", "content": user_input})
    _append_control_event("step_feedback", {"feedback": confirm})
    revised_goal = (
        f"{state.task.user_goal}\n\n"
        f"用户在步骤确认阶段的补充意见：{confirm}"
    )
    state.task.user_goal = revised_goal
    _append_control_event("plan_feedback", {"feedback": confirm})
    plan = generate_plan(revised_goal, client, MODEL_NAME, build_planning_messages(revised_goal))
    if not plan:
        state.reset_task()
        clear_checkpoint()
        return "未能根据你的补充意见重新生成计划，请重新描述你的需求。"

    state.task.current_plan = plan.model_dump()
    state.task.current_step_index = 0
    state.task.status = "awaiting_plan_confirmation"
    save_checkpoint(state)

    print(format_plan_for_display(plan))
    print("按此计划执行吗？(y/n/输入修改意见): ", end="", flush=True)
    return ""


def _handle_tool_use(response, turn_state: TurnState) -> Optional[str]:
    """处理一轮工具调用。"""
    get_messages().append({"role": "assistant", "content": response.content})
    turn_state.consecutive_max_tokens = 0

    # 真正数工具调用次数
    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    turn_state.tool_call_count += len(tool_use_blocks)

    if turn_state.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        print(f"\n[系统] 工具调用次数超过上限 {MAX_TOOL_CALLS_PER_TURN}，强制停止。")
        return "工具调用次数过多，请简化任务或分步执行。"

    turn_context = {}  # 本轮所有工具共享的上下文（供钩子用）

    for block in tool_use_blocks:
        result = _execute_single_tool(block, turn_state, turn_context)

        if result == "__force_stop__":
            print("\n[系统] 用户已连续拒绝 3 次，强制停止当前任务。")
            return "用户连续拒绝了多次操作，任务已停止。请告诉我您希望怎么调整。"

    return None


def _has_tool_result(tool_use_id: str) -> bool:
    """Check whether the current conversation already contains a tool_result for this tool_use_id."""
    for msg in state.conversation.messages:
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") == tool_use_id:
                    return True
    return False

def _execute_single_tool(block, turn_state: TurnState, turn_context: dict) -> Optional[str]:
    """执行单个工具调用。返回 __force_stop__ 或 None。"""
    tool_name = block.name
    tool_input = block.input
    tool_use_id = block.id

    # 幂等检查：同一个 tool_use_id 只执行一次
    execution_log = state.task.tool_execution_log
    if tool_use_id in execution_log:
        cached = execution_log[tool_use_id]["result"]
        print(f"\n[系统] 工具 {tool_name} 已执行过，跳过执行")
        if not _has_tool_result(tool_use_id):
            _append_tool_result(tool_use_id, cached)
        return None

    # 1. 分级确认
    confirmation = needs_tool_confirmation(tool_name, tool_input)

    if confirmation == "block":
        result = f"拒绝执行：'{tool_input.get('path', '')}' 是敏感文件，禁止 Agent 访问"
        turn_state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "blocked_sensitive",
            "result": result,
        })
        _append_tool_result(tool_use_id, result)
        return None

    # 2. 工具确认改为 state 驱动（不再直接 input）
    if confirmation:
        # 记录待确认工具
        state.task.pending_tool = {
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
        }
        state.task.status = "awaiting_tool_confirmation"
        save_checkpoint(state)
        print(f"\n⚠️ 需要确认执行工具：{tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
        print("是否执行？(y/n/输入反馈意见): ", end="", flush=True)
        return None
    else:
        print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")

    # 3. 执行工具（confirmation 已在上方处理）
    result = execute_tool(tool_name, tool_input, context=turn_context)

    # 写入执行记录（用于幂等执行）
    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "input": tool_input,
        "result": result,
    }
    save_checkpoint(state)

    if tool_name in ("write_file", "edit_file"):
        turn_context["write_file_seen"] = True

    turn_state.round_tool_traces.append({
        "tool_use_id": tool_use_id,
        "tool": tool_name,
        "input": tool_input,
        "status": "executed",
        "result": result,
    })

    _append_tool_result(tool_use_id, result)
    return None


# ========== 辅助 ==========

def _extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()




# 新增：控制事件注入
def _append_control_event(event_type: str, payload: dict) -> None:
    content = []

    # ===== tool =====
    if event_type == "tool_confirm_yes":
        content.append({"type": "text", "text": "用户确认执行工具"})

    elif event_type == "tool_confirm_no":
        content.append({"type": "text", "text": "用户拒绝执行工具"})

    elif event_type == "tool_feedback":
        content.append({
            "type": "text",
            "text": f"用户对工具执行提出了补充意见：{payload.get('feedback')}"
        })

    # ===== plan =====
    elif event_type == "plan_confirm_yes":
        content.append({"type": "text", "text": "用户接受当前计划"})

    elif event_type == "plan_confirm_no":
        content.append({"type": "text", "text": "用户拒绝当前计划"})

    elif event_type == "plan_feedback":
        content.append({
            "type": "text",
            "text": f"用户对计划提出了修改意见：{payload.get('feedback')}"
        })

    # ===== step =====
    elif event_type == "step_confirm_yes":
        content.append({"type": "text", "text": "用户确认继续执行下一步"})

    elif event_type == "step_confirm_no":
        content.append({"type": "text", "text": "用户停止当前任务"})

    elif event_type == "step_feedback":
        content.append({
            "type": "text",
            "text": f"用户对后续步骤提出了补充意见：{payload.get('feedback')}"
        })

    get_messages().append({
        "role": "user",
        "content": content
    })
def _append_tool_result(tool_use_id: str, result: str) -> None:
    get_messages().append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result,
        }],
    })
# 新增：处理工具确认（state 驱动）
def _handle_tool_confirmation(user_input: str, turn_state: TurnState) -> str:
    """
    处理工具确认（state 驱动）

    协议：
    - y：执行工具
    - n：拒绝执行
    - 其他输入：作为反馈
    """
    confirm = user_input.strip()

    pending = state.task.pending_tool
    if not pending:
        return "[系统] 未找到待确认的工具。"

    tool_use_id = pending["tool_use_id"]
    tool_name = pending["tool"]
    tool_input = pending["input"]

    # 清理 pending
    state.task.pending_tool = None

    if confirm.lower() == "y":
        _append_control_event("tool_confirm_yes", pending)
        result = execute_tool(tool_name, tool_input, context=turn_state.round_tool_traces)

        # 幂等记录
        state.task.tool_execution_log[tool_use_id] = {
            "tool": tool_name,
            "input": tool_input,
            "result": result,
        }
        # 工具 trace logging
        turn_state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "executed",
            "result": result,
        })

        state.task.status = "running"
        save_checkpoint(state)

        _append_tool_result(tool_use_id, result)
        return _run_main_loop(turn_state)

    if confirm.lower() == "n":
        _append_control_event("tool_confirm_no", pending)
        state.task.status = "running"
        save_checkpoint(state)
        return _run_main_loop(turn_state)

    # 其他输入：作为反馈
    _append_control_event("tool_feedback", {
        "feedback": confirm,
        "tool": tool_name,
        "input": tool_input,
    })
    result = f"用户反馈：{confirm}"
    _append_tool_result(tool_use_id, result)
    state.task.status = "running"
    save_checkpoint(state)
    return _run_main_loop(turn_state)