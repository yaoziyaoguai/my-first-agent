import json
import anthropic
from config import API_KEY, BASE_URL, MODEL_NAME, MAX_TOKENS, SYSTEM_PROMPT, ENABLE_REVIEW, SHOW_REVIEW_RESULT, MAX_AUTO_RETRY
from agent.logger import log_event
from agent.security import is_protected_source_file, needs_confirmation, confirm_tool_call
from agent.tools import execute_tool, TOOL_DEFINITIONS
from agent.context import compress_history
from agent.review import (
    get_effective_review_request,
    truncate_for_review,
    should_review_turn,
    review_agent_output,
    print_review_summary,
    build_retry_feedback,
)

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

    effective_review_request = get_effective_review_request(user_input)

    messages.append({"role": "user", "content": user_input})
    log_event("user_input", {
        "content": user_input,
        "effective_review_request": effective_review_request,
    })

    round_tool_traces = []
    auto_retry_count = 0

    while True:
        log_event("llm_call", {"message_count": len(messages)})

        with client.messages.stream(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOL_DEFINITIONS,
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
            write_file_seen_in_this_turn = False

            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                log_event("tool_requested", {"tool": tool_name, "input": tool_input})

                # 同一轮只允许一次 write_file
                if tool_name == "write_file":
                    if write_file_seen_in_this_turn:
                        result = "拒绝执行：同一轮响应中只允许执行一个 write_file，请先等待用户确认后再继续下一个文件。"
                        log_event("tool_blocked_multiple_write_same_turn", {
                            "tool": tool_name,
                            "path": tool_input.get("path"),
                        })
                        round_tool_traces.append({
                            "tool_use_id": tool_use_id,
                            "tool": tool_name,
                            "input": tool_input,
                            "status": "blocked_multiple_write_same_turn",
                            "result": truncate_for_review(result),
                        })
                        messages.append({
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                        })
                        continue
                    write_file_seen_in_this_turn = True

                # 源码保护
                if tool_name == "write_file" and is_protected_source_file(tool_input["path"]):
                    result = f"拒绝执行：'{tool_input['path']}' 属于受保护源码文件（.py），不允许 Agent 修改"
                    log_event("tool_blocked_protected_source", {
                        "tool": tool_name,
                        "path": tool_input["path"],
                    })
                    round_tool_traces.append({
                        "tool_use_id": tool_use_id,
                        "tool": tool_name,
                        "input": tool_input,
                        "status": "blocked_protected_source",
                        "result": truncate_for_review(result),
                    })
                    messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": result}],
                    })
                    continue

                # 分级确认
                if needs_confirmation(tool_name, tool_input):
                    approved = confirm_tool_call(tool_name, tool_input)
                else:
                    print(f"  [自动执行] {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
                    approved = True

                if approved:
                    result = execute_tool(tool_name, tool_input)
                    log_event("tool_executed", {"tool": tool_name, "result": result})

                    round_tool_traces.append({
                        "tool_use_id": tool_use_id,
                        "tool": tool_name,
                        "input": tool_input,
                        "status": "executed",
                        "result": truncate_for_review(result),
                    })

                    # 写文件成功后注入停止指令
                    if tool_name == "write_file" and not result.startswith("拒绝"):
                        if ENABLE_REVIEW:
                            result += "\n\n[系统指令] 文件已写入。请停止当前操作，向用户报告本次操作的结果。不要询问用户是否继续，不要自行继续创建更多文件。"
                        else:
                            result += "\n\n[系统指令] 文件已写入。请停止当前操作，将结果报告给用户，并询问用户是否继续下一步。不要自行继续创建更多文件。"

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
