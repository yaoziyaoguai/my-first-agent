import json
from config import MAX_MESSAGES, MAX_MESSAGE_CHARS, MODEL_NAME
from agent.logger import log_event, make_serializable


def estimate_messages_size(messages):
    try:
        serializable = make_serializable(messages)
        return len(json.dumps(serializable, ensure_ascii=False))
    except Exception as e:
        print(f"[系统] 估算 messages 大小时出错: {e}")
        return 0


def _truncate_tool_result_content(obj, threshold=200, keep_prefix=200):
    if isinstance(obj, list):
        return [_truncate_tool_result_content(item, threshold, keep_prefix) for item in obj]
    if isinstance(obj, dict):
        new_obj = {}
        is_tool_result = obj.get("type") == "tool_result"
        for k, v in obj.items():
            if is_tool_result and k == "content":
                if isinstance(v, str):
                    content_text = v
                else:
                    content_text = json.dumps(v, ensure_ascii=False)
                if len(content_text) > threshold:
                    content_text = content_text[:keep_prefix] + "...(已截断)"
                new_obj[k] = content_text
            else:
                new_obj[k] = _truncate_tool_result_content(v, threshold, keep_prefix)
        return new_obj
    return obj


def compress_history(messages, client):
    """
    检查并压缩消息历史。
    返回压缩后的 messages 列表。
    """
    total_size = estimate_messages_size(messages)

    if len(messages) <= MAX_MESSAGES and total_size <= MAX_MESSAGE_CHARS:
        return messages

    print(
        f"\n[系统] 上下文较长，正在压缩历史记录..."
        f"（message_count={len(messages)}, total_chars={total_size}）"
    )
    log_event("context_compression_start", {
        "message_count": len(messages),
        "total_chars": total_size,
    })

    recent = messages[-6:]
    old = messages[:-6]

    old_for_summary = make_serializable(old)
    old_for_summary = _truncate_tool_result_content(
        old_for_summary, threshold=200, keep_prefix=200
    )

    summary_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "请用中文简要总结以下对话历史的关键信息，包括："
                    "完成了什么任务、重要的结论、用户的偏好。"
                    "只输出总结，不要多余的话。\n\n"
                    f"对话历史：\n{json.dumps(old_for_summary, ensure_ascii=False)}"
                )
            }
        ],
    )

    summary_text = ""
    for block in summary_response.content:
        if block.type == "text":
            summary_text = block.text
            break

    new_messages = [
        {"role": "user", "content": f"[以下是之前对话的摘要]\n{summary_text}"},
        {"role": "assistant", "content": "好的，我了解了之前的对话内容。请继续。"},
    ] + recent

    new_total_size = estimate_messages_size(new_messages)

    log_event("context_compression_done", {
        "old_count": len(old) + len(recent),
        "new_count": len(new_messages),
        "summary": summary_text,
        "old_total_chars": total_size,
        "new_total_chars": new_total_size,
    })

    print(
        f"[系统] 压缩完成：{len(old) + len(recent)} 条 → {len(new_messages)} 条，"
        f"{total_size} 字符 → {new_total_size} 字符\n"
    )

    return new_messages
