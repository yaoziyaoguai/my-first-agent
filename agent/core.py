"""Agent 主循环：流程编排 + 模型调用 + stop_reason 分派。"""
import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from config import (
    API_KEY, BASE_URL, MODEL_NAME, MAX_TOKENS,
    SHOW_REVIEW_RESULT, MAX_AUTO_RETRY, MAX_CONTINUE_ATTEMPTS,
)
from agent.logger import log_event
from agent.context import compress_history
from agent.security import confirm_tool_call
from agent.planner import generate_plan, format_plan_for_display, format_plan_for_context
from agent.review import (
    get_effective_review_request,
    truncate_for_review,
    should_review_turn,
    review_agent_output,
    print_review_summary,
    build_retry_feedback,
)
from agent.tool_registry import execute_tool, get_tool_definitions, needs_tool_confirmation
from agent.checkpoint import save_checkpoint, clear_checkpoint
from agent.prompt_builder import build_system_prompt
import agent.tools  # noqa: F401  触发所有工具注册


# ========== 常量 ==========

MAX_TOOL_CALLS_PER_TURN = 20          # 实际工具调用上限
MAX_LOOP_ITERATIONS = 50              # 循环总次数兜底（防死循环）
MAX_CONSECUTIVE_REJECTIONS = 3        # 连续拒绝强制停止阈值
FORCE_STOP_REJECTION_THRESHOLD = 2    # 追加系统指令的拒绝阈值
REPEAT_DETECTION_WINDOW = 3           # 防循环检测窗口大小


# ========== 全局 ==========

client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL)
messages = []  # session 级消息历史


# ========== 循环状态 ==========

@dataclass
class TurnState:
    """一次 chat 调用内部的循环状态。"""
    effective_review_request: str
    system_prompt: str
    round_tool_traces: list = field(default_factory=list)
    recent_calls: list = field(default_factory=list)
    auto_retry_count: int = 0
    tool_call_count: int = 0        # 真实工具调用次数
    loop_iterations: int = 0        # 循环次数
    consecutive_rejections: int = 0
    consecutive_max_tokens: int = 0


# ========== 对外主入口 ==========

def chat(user_input: str) -> str:
    """主入口：对话 + 规划 + 工具执行 + 评测 + 自动重试。"""
    global messages
    messages = compress_history(messages, client)
    
    state = TurnState(
        effective_review_request=get_effective_review_request(user_input),
        system_prompt=build_system_prompt(),
    )
    
    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {
        "content": user_input,
        "effective_review_request": state.effective_review_request,
    })
    
    plan_result = _run_planning_phase(user_input)
    if plan_result == "cancelled":
        return "好的，已取消。"
    
    return _run_main_loop(state)


# ========== 规划阶段 ==========

def _run_planning_phase(user_input: str) -> str:
    """任务规划 + 用户确认 + 上下文注入。返回 'cancelled' 或 'ok'。"""
    plan = generate_plan(user_input, client, MODEL_NAME, messages)
    if not plan:
        return "ok"
    
    print(format_plan_for_display(plan))
    confirm = input("按此计划执行吗？(y/n/输入修改意见): ").strip()
    
    if confirm.lower() == "n":
        messages.append({"role": "assistant", "content": "好的，已取消。"})
        return "cancelled"
    
    # 空输入和 "y" 都视为同意
    if confirm and confirm.lower() != "y":
        updated = user_input + f"\n\n用户补充：{confirm}"
        messages[-1] = {"role": "user", "content": updated}
    
    plan_context = format_plan_for_context(plan)
    messages[-1] = {
        "role": "user",
        "content": messages[-1]["content"] + f"\n\n{plan_context}"
    }
    
    save_checkpoint(user_input, plan, messages)
    return "ok"


# ========== 主循环 ==========

def _run_main_loop(state: TurnState) -> str:
    """模型调用循环，按 stop_reason 分派处理。"""
    while True:
        state.loop_iterations += 1
        if state.loop_iterations > MAX_LOOP_ITERATIONS:
            print(f"\n[系统] 循环次数超过上限 {MAX_LOOP_ITERATIONS}，强制停止。")
            log_event("loop_iterations_limit", {"count": state.loop_iterations})
            return "对话循环次数过多，请简化任务或分步执行。"
        
        response = _call_model(state)
        log_event("llm_response", {"stop_reason": response.stop_reason})
        
        if response.stop_reason == "max_tokens":
            result = _handle_max_tokens(response, state)
            if result is not None:
                return result
            continue
        
        if response.stop_reason == "end_turn":
            result = _handle_end_turn(response, state)
            if result is not None:
                return result
            continue  # Review 触发了重试
        
        if response.stop_reason == "tool_use":
            result = _handle_tool_use(response, state)
            if result is not None:
                return result
            continue
        
        print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")
        return "意外的响应"


def _call_model(state: TurnState):
    """调用模型（流式）并返回最终 response。"""
    log_event("llm_call", {"message_count": len(messages)})
    
    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=state.system_prompt,
        messages=messages,
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

def _handle_max_tokens(response, state: TurnState) -> Optional[str]:
    """输出被截断。返回字符串表示结束，None 表示继续循环。"""
    state.consecutive_max_tokens += 1
    
    if state.consecutive_max_tokens >= MAX_CONTINUE_ATTEMPTS:
        print(f"\n[系统] 已连续 {state.consecutive_max_tokens} 次触发输出上限，强制停止。")
        log_event("max_tokens_limit_reached", {"attempts": state.consecutive_max_tokens})
        messages.append({"role": "assistant", "content": response.content})
        return "内容过长，已自动截断。如需完整输出，请分步请求。"
    
    print(f"\n[系统] 回复被截断，自动继续（{state.consecutive_max_tokens}/{MAX_CONTINUE_ATTEMPTS}）...", flush=True)
    log_event("auto_continue", {"attempt": state.consecutive_max_tokens})
    
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": "请继续你刚才的输出，不要重复已经说过的内容。"})
    return None


def _handle_end_turn(response, state: TurnState) -> Optional[str]:
    """模型说完了。可能触发 Review + 自动重试。"""
    state.consecutive_max_tokens = 0
    
    assistant_text = _extract_text(response.content)
    if not assistant_text:
        assistant_text = "[任务完成]"
    
    messages.append({"role": "assistant", "content": response.content})
    log_event("agent_reply", {"content": assistant_text})
    
    # 不需要 Review
    if not should_review_turn(state.round_tool_traces):
        clear_checkpoint()
        return assistant_text
    
    # 触发 Review
    print("\n[系统] 检测到本轮有写操作，正在进行结果评测，请稍等...", flush=True)
    review = review_agent_output(
        state.effective_review_request,
        assistant_text,
        state.round_tool_traces,
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
        clear_checkpoint()
        return assistant_text
    
    # Review 有 parse_error 或已达重试上限 → 不清 checkpoint
    if state.auto_retry_count >= MAX_AUTO_RETRY:
        print(f"\n[系统] 已达自动重试上限（{MAX_AUTO_RETRY}次），任务保持未完成状态。")
        log_event("auto_retry_exhausted", {
            "overall": review.get("overall") if review else None,
        })
        return assistant_text
    
    # 可以重试：Review 未通过且还有重试次数
    if review and not review.get("parse_error") and review.get("overall") != "通过":
        state.auto_retry_count += 1
        feedback_msg = build_retry_feedback(review)
        
        print(f"\n[系统] 评测未通过，自动重试（{state.auto_retry_count}/{MAX_AUTO_RETRY}）...\n")
        log_event("auto_retry", {
            "attempt": state.auto_retry_count,
            "review_overall": review.get("overall"),
        })
        
        messages.append({"role": "user", "content": feedback_msg})
        state.round_tool_traces = []
        return None  # 继续循环重试
    
    # Review parse_error 等异常情况
    return assistant_text


def _handle_tool_use(response, state: TurnState) -> Optional[str]:
    """处理一轮工具调用。"""
    messages.append({"role": "assistant", "content": response.content})
    state.consecutive_max_tokens = 0
    
    # 真正数工具调用次数
    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    state.tool_call_count += len(tool_use_blocks)
    
    if state.tool_call_count > MAX_TOOL_CALLS_PER_TURN:
        print(f"\n[系统] 工具调用次数超过上限 {MAX_TOOL_CALLS_PER_TURN}，强制停止。")
        log_event("tool_loop_limit", {"count": state.tool_call_count})
        return "工具调用次数过多，请简化任务或分步执行。"
    
    turn_context = {}  # 本轮所有工具共享的上下文（供钩子用）
    
    for block in tool_use_blocks:
        result = _execute_single_tool(block, state, turn_context)
        
        if result == "__force_stop__":
            print("\n[系统] 用户已连续拒绝 3 次，强制停止当前任务。")
            log_event("force_stop_rejections", {"count": state.consecutive_rejections})
            return "用户连续拒绝了多次操作，任务已停止。请告诉我您希望怎么调整。"
    
    return None


def _execute_single_tool(block, state: TurnState, turn_context: dict) -> Optional[str]:
    """执行单个工具调用。返回 __force_stop__ 或 None。"""
    tool_name = block.name
    tool_input = block.input
    tool_use_id = block.id
    
    log_event("tool_requested", {"tool": tool_name, "input": tool_input})
    
    # 1. 防循环检测
    _record_tool_call(tool_name, tool_input, state.recent_calls)
    if _is_repeated_recently(state.recent_calls):
        result = f"检测到重复调用 {tool_name}，相同参数已调用 {REPEAT_DETECTION_WINDOW} 次。请基于已有信息继续下一步，不要重复此操作。"
        log_event("tool_repeat_blocked", {"tool": tool_name, "input": tool_input})
        state.round_tool_traces.append({
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
        state.round_tool_traces.append({
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
        
        state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "executed",
            "result": truncate_for_review(result),
        })
    else:
        # 拒绝
        state.consecutive_rejections += 1
        
        if isinstance(approved, str):
            result = f"用户拒绝了此操作，反馈如下：{approved}\n请根据用户反馈调整方案，不要重复相同的操作。"
            log_event("tool_rejected_with_feedback", {"tool": tool_name, "feedback": approved})
        else:
            result = "用户拒绝了此操作。请停下来询问用户需要什么调整，不要重复相同的操作。"
            log_event("tool_rejected", {"tool": tool_name})
        
        state.round_tool_traces.append({
            "tool_use_id": tool_use_id,
            "tool": tool_name,
            "input": tool_input,
            "status": "rejected",
            "result": result,
        })
        
        if state.consecutive_rejections >= FORCE_STOP_REJECTION_THRESHOLD:
            result += "\n\n[系统指令] 用户已连续拒绝 2 次操作。立即停止所有工具调用，向用户询问下一步该怎么做。"
            log_event("consecutive_rejections_limit", {"count": state.consecutive_rejections})
        
        if state.consecutive_rejections >= MAX_CONSECUTIVE_REJECTIONS:
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
    messages.append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result,
        }],
    })