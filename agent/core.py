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
    SHOW_REVIEW_RESULT, MAX_AUTO_RETRY, MAX_CONTINUE_ATTEMPTS,
)
from agent.logger import log_event
from agent.memory import compress_history
from agent.security import confirm_tool_call
from agent.planner import generate_plan, format_plan_for_display
from agent.review import (
    get_effective_review_request,
    truncate_for_review,
    should_review_turn,
    review_agent_output,
    print_review_summary,
    build_retry_feedback,
)
from agent.tool_registry import execute_tool, get_tool_definitions, needs_tool_confirmation
from agent.checkpoint import save_checkpoint_from_state, clear_checkpoint




# ========== 常量 ==========

MAX_TOOL_CALLS_PER_TURN = 20          # 实际工具调用上限
MAX_LOOP_ITERATIONS = 50              # 循环总次数兜底（防死循环）
MAX_CONSECUTIVE_REJECTIONS = 3        # 连续拒绝强制停止阈值
FORCE_STOP_REJECTION_THRESHOLD = 2    # 追加系统指令的拒绝阈值
REPEAT_DETECTION_WINDOW = 3           # 防循环检测窗口大小


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
    review_enabled=True,
    max_recent_messages=6,
)


# ========== 循环状态 ==========

@dataclass
class TurnState:
    """一次 chat 调用内部的循环状态。"""
    effective_review_request: bool
    system_prompt: str
    round_tool_traces: list = field(default_factory=list)
    recent_calls: list = field(default_factory=list)
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


def build_model_messages() -> list[dict]:
    """
    构造真正喂给模型的 messages。

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
                f"[当前步骤标题]：{step.title}",
                f"[当前步骤说明]：{step.description}",
                f"[步骤类型]：{step.step_type}",
            ])

            if step.suggested_tool:
                step_lines.append(f"[建议工具]：{step.suggested_tool}")

            if step.expected_outcome:
                step_lines.append(f"[预期结果]：{step.expected_outcome}")

            # [新增] 把 completion_criteria 注入给模型
            if step.completion_criteria:
                step_lines.append(f"[完成标准]：{step.completion_criteria}")

            step_lines.extend([
                "",
                "执行要求：",
                "- 只执行当前这一步，不要提前执行后续步骤",
                "- 如果当前步骤有完成标准，优先以完成标准作为收口依据",
                "- 完成当前步骤后，用自然语言明确说明“本步骤已完成”或等价表达",
                "- 如果当前步骤需要工具，就调用合适的工具",
                "- 不要重复已经完成的步骤",
            ])

            model_messages.append({
                "role": "user",
                "content": "\n".join(step_lines),
            })

    # 最近原始消息
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
    初级版 step 完成判定。

    规则：
    - 如果当前没有计划，默认视为完成
    - 如果当前 step 没有定义 completion_criteria，保持旧行为：一轮结束即完成
    - 如果定义了 completion_criteria：
        1. assistant 输出里要有“完成信号”关键词
        2. assistant 输出里最好还要体现 completion_criteria 中的部分关键信息
    - 对部分 step_type，再增加一点轻量规则
    """
    if not state.task.current_plan:
        return True

    plan = Plan.model_validate(state.task.current_plan)
    idx = state.task.current_step_index

    # 当前 step 索引不合法，默认视为完成，避免卡死
    if not (0 <= idx < len(plan.steps)):
        return True

    step = plan.steps[idx]

    # 如果没有定义 completion_criteria，保持旧逻辑
    if not step.completion_criteria:
        return True

    text = assistant_text.lower()
    criteria_text = step.completion_criteria.lower()

    # 1) 完成信号关键词
    completion_keywords = ["完成", "已完成", "done", "finished"]
    has_completion_signal = any(keyword in text for keyword in completion_keywords)

    if not has_completion_signal:
        return False

    # 2) completion_criteria 关键词匹配（非常粗粒度）
    raw_parts = re.split(r"[，。；、,;\n]+", criteria_text)
    criteria_parts = [part.strip() for part in raw_parts if part.strip()]

    criteria_matched = False
    if not criteria_parts:
        criteria_matched = True
    else:
        for part in criteria_parts:
            if len(part) >= 4 and part in text:
                criteria_matched = True
                break

    if not criteria_matched:
        return False

    # 3) step_type 的轻量附加规则
    step_type = (step.step_type or "").strip().lower()

    if step_type == "report":
        report_keywords = ["总结", "结论", "结果", "report", "summary"]
        return any(keyword in text for keyword in report_keywords)

    if step_type == "analyze":
        analyze_keywords = ["分析", "判断", "发现", "结论", "analysis"]
        return any(keyword in text for keyword in analyze_keywords)

    if step_type == "read":
        read_keywords = ["读取", "已读", "查看", "read"]
        return any(keyword in text for keyword in read_keywords)
    if step_type == "edit":
        edit_keywords = ["修改", "已修改", "更新", "edit", "changed", "patched"]
        return any(keyword in text for keyword in edit_keywords)

    if step_type == "run_command":
        cmd_keywords = ["执行", "已执行", "运行", "command", "ran", "output", "结果"]
        return any(keyword in text for keyword in cmd_keywords)

    # 其他类型先不加更强规则，通过上面的通用规则即可
    return True

# ========== 对外主入口 ==========

def chat(user_input: str) -> str:
    """主入口：对话 + 规划 + 工具执行 + 评测 + 自动重试。"""

    # 先取出旧消息列表
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
        effective_review_request=get_effective_review_request(user_input),
        system_prompt=runtime_system_prompt,
    )

    state.conversation.messages.append({"role": "user", "content": user_input})
    log_event("user_input", {
        "content": user_input,
        "effective_review_request": turn_state.effective_review_request,
    })

    plan_result = _run_planning_phase(user_input)
    if plan_result == "cancelled":

        return "好的，已取消。"

    return _run_main_loop(turn_state)


# ========== 规划阶段 ==========

def _run_planning_phase(user_input: str) -> str:
    """任务规划 + 用户确认 + 上下文注入。返回 'cancelled' 或 'ok'。"""
    plan = generate_plan(user_input, client, MODEL_NAME, build_model_messages())
    if not plan:
        return "ok"
    
  # [新增 1] 先把 plan 和当前目标正式存入 task 状态

    state.task.current_plan = plan.model_dump()
    state.task.user_goal = user_input
    state.task.current_step_index = 0
    state.task.status = "planning"
    print(format_plan_for_display(plan))
    confirm = input("按此计划执行吗？(y/n/输入修改意见): ").strip()
    if confirm.lower() == "n":
        get_messages().append({"role": "assistant", "content": "好的，已取消。"})
        state.task.status = "idle"
        return "cancelled"
    # 空输入和 "y" 都视为同意
    if confirm and confirm.lower() != "y":
        extra_feedback = f"用户补充：{confirm}"
        get_messages().append({"role": "user", "content": extra_feedback})
        state.task.user_goal = user_input + f"\n\n{extra_feedback}"
    
    # 当前计划已经正式存入 state.task.current_plan，
    # 不再通过篡改原始 user message 来传递计划上下文。
    save_checkpoint_from_state(state)
    state.task.status = "running"
    return "ok"


# ========== 主循环 ==========

def _run_main_loop(turn_state: TurnState) -> str:
    """模型调用循环，按 stop_reason 分派处理。"""
    while True:
        turn_state.loop_iterations += 1
        if turn_state.loop_iterations > MAX_LOOP_ITERATIONS:
            print(f"\n[系统] 循环次数超过上限 {MAX_LOOP_ITERATIONS}，强制停止。")
            log_event("loop_iterations_limit", {"count": turn_state.loop_iterations})
            return "对话循环次数过多，请简化任务或分步执行。"

        response = _call_model(turn_state)
        log_event("llm_response", {"stop_reason": response.stop_reason})

        if response.stop_reason == "max_tokens":
            result = _handle_max_tokens(response, turn_state)
            if result is not None:
                return result
            continue

        if response.stop_reason == "end_turn":
            result = _handle_end_turn(response, turn_state)
            if result is not None:
                return result
            continue  # Review 触发了重试

        if response.stop_reason == "tool_use":
            result = _handle_tool_use(response, turn_state)
            if result is not None:
                return result
            continue

        print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")
        return "意外的响应"


def _call_model(turn_state: TurnState):
    """调用模型（流式）并返回最终 response。"""
    log_event("llm_call", {"message_count": len(build_model_messages())})

    with client.get_messages().stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        # 当前真正生效的 system prompt 来自运行态 state，
        # 在 chat() 里刷新后写入 TurnState.system_prompt
        system=turn_state.system_prompt,
        messages=build_model_messages(),
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
        log_event("max_tokens_limit_reached", {"attempts": turn_state.consecutive_max_tokens})
        get_messages().append({"role": "assistant", "content": response.content})
        return "内容过长，已自动截断。如需完整输出，请分步请求。"

    print(f"\n[系统] 回复被截断，自动继续（{turn_state.consecutive_max_tokens}/{MAX_CONTINUE_ATTEMPTS}）...", flush=True)
    log_event("auto_continue", {"attempt": turn_state.consecutive_max_tokens})

    get_messages().append({"role": "assistant", "content": response.content})
    get_messages().append({"role": "user", "content": "请继续你刚才的输出，不要重复已经说过的内容。"})
    return None


def _handle_end_turn(response, turn_state: TurnState) -> Optional[str]:
    """模型说完了。可能触发 Review + 自动重试。"""
    turn_state.consecutive_max_tokens = 0

    assistant_text = _extract_text(response.content)
    if not assistant_text:
        assistant_text = "[任务完成]"

    get_messages().append({"role": "assistant", "content": response.content})
    log_event("agent_reply", {"content": assistant_text})

    # 不需要 Review
    if not should_review_turn(turn_state.round_tool_traces):
        if is_current_step_completed(assistant_text):
            _advance_current_step_if_needed()
        clear_checkpoint()
        return assistant_text

    # 触发 Review
    print("\n[系统] 检测到本轮有写操作，正在进行结果评测，请稍等...", flush=True)
    review = review_agent_output(
        turn_state.effective_review_request,
        assistant_text,
        turn_state.round_tool_traces,
        client,
    )
    print("[系统] 本轮评测完成", flush=True)

    if SHOW_REVIEW_RESULT:
        print_review_summary(review)

    # Review 通过 → 清 checkpoint
    review_passed = (
        review
        and not review.get("parse_error")
        and review.get("overall") == "通过"
    )
    if review_passed:
        if is_current_step_completed(assistant_text):
            _advance_current_step_if_needed()
        clear_checkpoint()
        return assistant_text

    # Review 有 parse_error 或已达重试上限 → 不清 checkpoint
    if turn_state.auto_retry_count >= MAX_AUTO_RETRY:
        print(f"\n[系统] 已达自动重试上限（{MAX_AUTO_RETRY}次），任务保持未完成状态。")
        log_event("auto_retry_exhausted", {
            "overall": review.get("overall") if review else None,
        })
        return assistant_text

    # 可以重试：Review 未通过且还有重试次数
    if review and not review.get("parse_error") and review.get("overall") != "通过":
        turn_state.auto_retry_count += 1
        feedback_msg = build_retry_feedback(review)

        print(f"\n[系统] 评测未通过，自动重试（{turn_state.auto_retry_count}/{MAX_AUTO_RETRY}）...\n")
        log_event("auto_retry", {
            "attempt": turn_state.auto_retry_count,
            "review_overall": review.get("overall"),
        })

        get_messages().append({"role": "user", "content": feedback_msg})
        turn_state.round_tool_traces = []
        return None  # 继续循环重试

    # Review parse_error 等异常情况
    return assistant_text


def _handle_tool_use(response, turn_state: TurnState) -> Optional[str]:
    """处理一轮工具调用。"""
    get_messages().append({"role": "assistant", "content": response.content})
    turn_state.consecutive_max_tokens = 0

    # 真正数工具调用次数
    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    turn_state.tool_call_count += len(tool_use_blocks)

    if turn_state.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        print(f"\n[系统] 工具调用次数超过上限 {MAX_TOOL_CALLS_PER_TURN}，强制停止。")
        log_event("tool_loop_limit", {"count": turn_state.tool_call_count})
        return "工具调用次数过多，请简化任务或分步执行。"

    turn_context = {}  # 本轮所有工具共享的上下文（供钩子用）

    for block in tool_use_blocks:
        result = _execute_single_tool(block, turn_state, turn_context)

        if result == "__force_stop__":
            print("\n[系统] 用户已连续拒绝 3 次，强制停止当前任务。")
            log_event("force_stop_rejections", {"count": turn_state.consecutive_rejections})
            return "用户连续拒绝了多次操作，任务已停止。请告诉我您希望怎么调整。"

    return None


def _execute_single_tool(block, turn_state: TurnState, turn_context: dict) -> Optional[str]:
    """执行单个工具调用。返回 __force_stop__ 或 None。"""
    tool_name = block.name
    tool_input = block.input
    tool_use_id = block.id

    log_event("tool_requested", {"tool": tool_name, "input": tool_input})

    # 1. 防循环检测
    _record_tool_call(tool_name, tool_input, turn_state.recent_calls)
    if _is_repeated_recently(turn_state.recent_calls):
        result = f"检测到重复调用 {tool_name}，相同参数已调用 {REPEAT_DETECTION_WINDOW} 次。请基于已有信息继续下一步，不要重复此操作。"
        log_event("tool_repeat_blocked", {"tool": tool_name, "input": tool_input})
        turn_state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "blocked_repeat",
            "result": result,
        })
        _append_tool_result(tool_use_id, result)
        return None

    # 2. 分级确认
    confirmation = needs_tool_confirmation(tool_name, tool_input)

    if confirmation == "block":
        result = f"拒绝执行：'{tool_input.get('path', '')}' 是敏感文件，禁止 Agent 访问"
        log_event("tool_blocked_sensitive", {"tool": tool_name, "path": tool_input.get("path")})
        turn_state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "blocked_sensitive",
            "result": result,
        })
        _append_tool_result(tool_use_id, result)
        return None

    # 3. 用户确认
    if confirmation:
        approved = confirm_tool_call(tool_name, tool_input)
    else:
        print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
        approved = True

    # 4. 执行或处理拒绝
    if approved is True:
        result = execute_tool(tool_name, tool_input, context=turn_context)
        log_event("tool_executed", {"tool": tool_name, "result": result})

        if tool_name in ("write_file", "edit_file"):
            turn_context["write_file_seen"] = True

        turn_state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "executed",
            "result": truncate_for_review(result),
        })
    else:
        # 拒绝
        turn_state.consecutive_rejections += 1

        if isinstance(approved, str):
            result = f"用户拒绝了此操作，反馈如下：{approved}\n请根据用户反馈调整方案，不要重复相同的操作。"
            log_event("tool_rejected_with_feedback", {"tool": tool_name, "feedback": approved})
        else:
            result = "用户拒绝了此操作。请停下来询问用户需要什么调整，不要重复相同的操作。"
            log_event("tool_rejected", {"tool": tool_name})

        turn_state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "rejected",
            "result": result,
        })

        if turn_state.consecutive_rejections >= FORCE_STOP_REJECTION_THRESHOLD:
            result += "\n\n[系统指令] 用户已连续拒绝 2 次操作。立即停止所有工具调用，向用户询问下一步该怎么做。"
            log_event("consecutive_rejections_limit", {"count": turn_state.consecutive_rejections})

        if turn_state.consecutive_rejections >= MAX_CONSECUTIVE_REJECTIONS:
            _append_tool_result(tool_use_id, result)
            return "__force_stop__"

    _append_tool_result(tool_use_id, result)
    return None


# ========== 辅助 ==========

def _extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()


def _record_tool_call(tool_name: str, tool_input: dict, recent_calls: list) -> None:
    signature = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
    recent_calls.append(signature)


def _is_repeated_recently(recent_calls: list) -> bool:
    if len(recent_calls) < REPEAT_DETECTION_WINDOW:
        return False
    window = recent_calls[-REPEAT_DETECTION_WINDOW:]
    return len(set(window)) == 1


def _append_tool_result(tool_use_id: str, result: str) -> None:
    get_messages().append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result,
        }],
    })