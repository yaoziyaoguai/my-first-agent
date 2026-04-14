import json
import anthropic
from config import API_KEY, BASE_URL, MODEL_NAME, MAX_TOKENS, SYSTEM_PROMPT, SHOW_REVIEW_RESULT, MAX_AUTO_RETRY
from agent.logger import log_event
from agent.context import compress_history
from agent.security import  confirm_tool_call
from agent.review import (
    get_effective_review_request,
    truncate_for_review,
    should_review_turn,
    review_agent_output,
    print_review_summary,
    build_retry_feedback,
)
from agent.tool_registry import execute_tool, get_tool_definitions, needs_tool_confirmation
import agent.tools  # noqa: F401  # 触发所有工具注册
from agent.memory import build_memory_prompt

# API 客户端
client = anthropic.Anthropic(
    api_key=API_KEY,
    base_url=BASE_URL,
)

# 消息历史
messages = []


def chat(user_input):
    global messages
    messages = compress_history(messages, client)
    memory_prompt = build_memory_prompt()

    effective_review_request = get_effective_review_request(user_input)

    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {
        "content": user_input,
        "effective_review_request": effective_review_request,
    })

    round_tool_traces = []
    tool_call_count = 0          # ← 加这一行
    MAX_TOOL_CALLS_PER_TURN = 20  # ← 加这一行
    auto_retry_count = 0

    while True:
        log_event("llm_call", {"message_count": len(messages)})
        tool_call_count += 1
        if tool_call_count > MAX_TOOL_CALLS_PER_TURN:
            print("\n[系统] 工具调用次数超过上限，强制停止。")
            log_event("tool_loop_limit", {"count": tool_call_count})
            return "工具调用次数超过上限，请简化任务或分步执行。"
        
        with client.messages.stream(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT + "\n\n" + memory_prompt,
            messages=messages,
            tools=get_tool_definitions(),
        ) as stream:
            for event in stream:
                if hasattr(event, "type") and event.type == "content_block_start":
                    if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                        print("\n🔧 正在规划工具调用...", flush=True)
                if hasattr(event, "type") and event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        print(event.delta.text, end="", flush=True)
            response = stream.get_final_message()
            print()

        log_event("llm_response", {"stop_reason": response.stop_reason})

        # ========== end_turn：模型说完了 ==========
        if response.stop_reason == "end_turn":
            assistant_text_parts = []
            for block in response.content:
                if block.type == "text":
                    assistant_text_parts.append(block.text)
            assistant_text = "\n".join(part for part in assistant_text_parts if part).strip()

            messages.append({"role": "assistant", "content": response.content})
            log_event("agent_reply", {"content": assistant_text})

            # 推理型 Sensor
            if should_review_turn(round_tool_traces):
                print("\n[系统] 检测到本轮有写操作，正在进行结果评测，请稍等...", flush=True)

                review = review_agent_output(
                    effective_review_request,
                    assistant_text,
                    round_tool_traces,
                    client,
                )

                print("[系统] 本轮评测完成", flush=True)

                if SHOW_REVIEW_RESULT:
                    print_review_summary(review)

                # 自动重试
                if (review
                    and not review.get("parse_error")
                    and review.get("overall") != "通过"
                    and auto_retry_count < MAX_AUTO_RETRY):

                    auto_retry_count += 1
                    feedback_msg = build_retry_feedback(review)

                    print(f"\n[系统] 评测未通过，自动重试（{auto_retry_count}/{MAX_AUTO_RETRY}）...\n")
                    log_event("auto_retry", {
                        "attempt": auto_retry_count,
                        "review_overall": review.get("overall"),
                    })

                    messages.append({"role": "user", "content": feedback_msg})
                    round_tool_traces = []
                    continue

            return assistant_text

        # ========== tool_use：模型想用工具 ==========
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            # 构建执行上下文，供钩子使用
            turn_context = {}

            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                log_event("tool_requested", {"tool": tool_name, "input": tool_input})

                # 分级确认
                confirmation = needs_tool_confirmation(tool_name, tool_input)

                if confirmation == "block":
                    result = f"拒绝执行：'{tool_input.get('path', '')}' 是敏感文件，禁止 Agent 访问"
                    log_event("tool_blocked_sensitive", {"tool": tool_name, "path": tool_input.get("path")})
                    round_tool_traces.append({
                        "tool_use_id": tool_use_id,
                        "tool": tool_name,
                        "input": tool_input,
                        "status": "blocked_sensitive",
                        "result": result,
                    })
                    messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                    })
                    continue
                elif confirmation:
                    approved = confirm_tool_call(tool_name, tool_input)
                else:
                    print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
                    approved = True

                if approved:
                    result = execute_tool(tool_name, tool_input, context=turn_context)
                    log_event("tool_executed", {"tool": tool_name, "result": result})

                    # 更新上下文（供后续工具的钩子使用）
                    if tool_name == "write_file":
                        turn_context["write_file_seen"] = True

                    round_tool_traces.append({
                        "tool_use_id": tool_use_id,
                        "tool": tool_name,
                        "input": tool_input,
                        "status": "executed",
                        "result": truncate_for_review(result),
                    })
                else:
                    result = "用户拒绝了此操作"
                    log_event("tool_rejected", {"tool": tool_name})

                    round_tool_traces.append({
                        "tool_use_id": tool_use_id,
                        "tool": tool_name,
                        "input": tool_input,
                        "status": "rejected_by_user",
                        "result": result,
                    })

                messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                })

            continue

        print(f"[DEBUG] 未知的 stop_reason: {response.stop_reason}")
        return "意外的响应"
