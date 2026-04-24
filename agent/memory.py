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


def _collect_tool_use_ids(messages) -> set:
    """收集 messages 里 assistant 端声明过的 tool_use id。"""
    ids = set()
    for m in messages:
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                bid = block.get("id")
                if bid:
                    ids.add(bid)
    return ids


def _collect_tool_result_ids(messages) -> set:
    """收集 messages 里 user 端回传的 tool_result 对应的 tool_use_id。"""
    ids = set()
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                bid = block.get("tool_use_id")
                if bid:
                    ids.add(bid)
    return ids


def _find_safe_split_index(messages, preferred_recent: int) -> int:
    """计算一个不切断 tool_use/tool_result 配对的切分点。

    返回 split_index：messages[:split_index] 归摘要，messages[split_index:]
    保留为 recent。若找不到合法切点（例如所有 tool_use/result 穿插太深），
    返回 0，表示本次不做压缩。
    """
    n = len(messages)
    if preferred_recent >= n:
        return 0

    split = n - preferred_recent

    # 把 split 向前推，直到 recent 部分里不存在「对应 tool_use 不在 recent 里」的孤悬 tool_result，
    # 也不存在「对应 tool_result 不在 recent 里」的孤悬 tool_use。
    max_iter = n  # 防止死循环
    for _ in range(max_iter):
        if split <= 0:
            return 0

        recent = messages[split:]
        recent_tool_uses = _collect_tool_use_ids(recent)
        recent_tool_results = _collect_tool_result_ids(recent)

        # recent 里有 tool_result 但对应 tool_use 不在 recent —— 需要把 tool_use 也拉进 recent
        orphan_results = recent_tool_results - recent_tool_uses
        # recent 里有 tool_use 但对应 tool_result 不在 recent —— 同样要扩大 recent
        orphan_uses = recent_tool_uses - recent_tool_results

        if not orphan_results and not orphan_uses:
            return split

        split -= 1  # 把 split 再向前一步，把更多消息纳入 recent

    return 0  # 兜底：放弃压缩


def compress_history(messages, client, existing_summary: str | None = None, max_recent_messages: int = 6):
    """
    检查并压缩消息历史。

    参数:
        messages: 当前原始对话消息
        client: LLM client
        existing_summary: 之前已有的摘要，可为空
        max_recent_messages: 最近保留多少条原始消息不压缩

    返回:
        (new_messages, new_summary)
        - new_messages: 压缩后保留的原始消息（只保留最近消息）
        - new_summary: 最新摘要（单独存，不再塞回 messages）
    """
    total_size = estimate_messages_size(messages)

    if len(messages) <= MAX_MESSAGES and total_size <= MAX_MESSAGE_CHARS:
        return messages, existing_summary

    print(
        f"\n[系统] 上下文较长，正在压缩历史记录..."
        f"（message_count={len(messages)}, total_chars={total_size}）"
    )
    log_event("context_compression_start", {
        "message_count": len(messages),
        "total_chars": total_size,
    })

    recent = messages[-max_recent_messages:]
    old = messages[:-max_recent_messages]

    # 防护：切分点不能切断 tool_use / tool_result 的配对。
    # 否则压缩后 recent 里会留下孤悬 tool_result（对应 tool_use 已进摘要），
    # 或孤悬 tool_use（对应 tool_result 已进摘要），下次调用 API 必然报错。
    safe_split = _find_safe_split_index(messages, max_recent_messages)
    if safe_split == 0:
        print("[系统] 压缩放弃：找不到不切断 tool_use/tool_result 的切点。")
        return messages, existing_summary
    old = messages[:safe_split]
    recent = messages[safe_split:]

    old_for_summary = make_serializable(old)
    old_for_summary = _truncate_tool_result_content(
        old_for_summary, threshold=200, keep_prefix=200
    )

    if existing_summary:
        summary_prompt = (
            "下面有两部分内容：\n"
            "1. 之前的历史摘要\n"
            "2. 新增的旧消息\n\n"
            "请把它们整合成一份新的中文摘要，保留关键信息，包括："
            "完成了什么任务、重要结论、用户偏好、当前进度。\n"
            "只输出摘要，不要多余的话。\n\n"
            f"【之前的历史摘要】\n{existing_summary}\n\n"
            f"【新增的旧消息】\n{json.dumps(old_for_summary, ensure_ascii=False)}"
        )
    else:
        summary_prompt = (
            "请用中文简要总结以下对话历史的关键信息，包括："
            "完成了什么任务、重要的结论、用户的偏好、当前进度。"
            "只输出总结，不要多余的话。\n\n"
            f"对话历史：\n{json.dumps(old_for_summary, ensure_ascii=False)}"
        )

    summary_response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": summary_prompt,
            }
        ],
    )

    summary_text = existing_summary
    for block in summary_response.content:
        if block.type == "text":
            summary_text = block.text
            break

    new_total_size = estimate_messages_size(recent)

    print(
        f"[系统] 压缩完成：{len(messages)} 条 → {len(recent)} 条，"
        f"{total_size} 字符 → {new_total_size} 字符\n"
    )

    return recent, summary_text


def build_memory_section() -> str:
    """
    构造 system prompt 中使用的 memory section。

    当前先只提供一个最小可用版本：
    - 不把 working_summary 混进这里
    - 只返回一个稳定、静态的 memory 说明占位

    后续如果要接长期记忆，再在这里扩展。
    """
    return "[Memory]\n当前未注入长期记忆。"


def init_memory() -> None:
    """
    初始化 memory 模块。

    当前先保留最小兼容实现：
    - 不做额外初始化
    - 只保证 session 启动链路可运行
    """
    return None



def cleanup_old_episodes() -> None:
    """
    清理旧的记忆片段。

    当前先保留最小兼容实现：
    - 不做实际清理
    - 后续如果接长期记忆再扩展
    """
    return None



def extract_memories_from_session(messages, client, model_name) -> None:
    """
    从本次会话中提取长期记忆。

    当前先保留最小兼容实现：
    - 不把 working_summary 混入长期记忆
    - 不做实际提取
    - 只保证退出流程可运行
    """
    return None