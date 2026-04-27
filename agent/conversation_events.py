

"""Conversation event helpers.

This module is responsible for writing semantic events and tool results into
conversation messages. It does not control execution; execution is still driven
by state in core.py.
"""

from typing import Any


Message = dict[str, Any]


def append_control_event(messages: list[Message], event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Append a semantic control event to conversation messages.

    Raw control inputs such as y/n should not be written directly into the
    conversation. They are converted into low-ambiguity semantic events here.
    """
    payload = payload or {}
    content: list[dict[str, Any]] = []

    # ===== tool =====
    if event_type == "tool_confirm_yes":
        content.append({"type": "text", "text": "用户确认执行工具"})

    elif event_type == "tool_confirm_no":
        content.append({"type": "text", "text": "用户拒绝执行工具"})

    elif event_type == "tool_feedback":
        content.append({
            "type": "text",
            "text": f"用户对工具执行提出了补充意见：{payload.get('feedback')}",
        })

    # ===== plan =====
    elif event_type == "plan_confirm_yes":
        content.append({"type": "text", "text": "用户接受当前计划"})

    elif event_type == "plan_confirm_no":
        content.append({"type": "text", "text": "用户拒绝当前计划"})

    elif event_type == "plan_feedback":
        content.append({
            "type": "text",
            "text": f"用户对计划提出了修改意见：{payload.get('feedback')}",
        })

    # ===== step =====
    elif event_type == "step_confirm_yes":
        content.append({"type": "text", "text": "用户确认继续执行下一步"})

    elif event_type == "step_confirm_no":
        content.append({"type": "text", "text": "用户停止当前任务"})

    elif event_type == "step_feedback":
        content.append({
            "type": "text",
            "text": f"用户对后续步骤提出了补充意见：{payload.get('feedback')}",
        })

    elif event_type == "step_input":
        # 两种来源共用 step_input：
        # - collect_input/clarify 步骤的常规收尾：payload 只含 content
        # - request_user_input 触发的执行期求助回复：payload 含 question + why_needed + content
        # 这里处在 Runtime 语义事件 -> conversation.messages 的边界。它写的是给模型
        # 下一轮可读的用户事实，不是 RuntimeEvent，不是 InputIntent，也不是 Anthropic
        # tool_result。request_user_input 是元工具控制信号，元工具 tool_use 不进
        # messages，因此这里不能为了“看起来配对”伪造 tool_result；否则会破坏
        # tool_use_id 配对和 API messages 投影。
        # 区分依据是 payload 里有没有 question 字段——有就渲染更强的配对文案，
        # 让模型在下一轮上下文里把用户答复视为已收集事实。
        question = payload.get("question")
        answer = payload.get("content", "")
        if question:
            text_lines = [
                "【当前步骤用户补充信息】",
                "上一轮系统向用户询问：",
                str(question),
                "",
                "用户已经回答：",
                str(answer),
                "",
                "这条回复应视为当前步骤已经收集到的约束/事实。",
                "后续执行当前步骤时，请优先使用这些信息，不要重复追问已经由用户回答过的内容。",
                "只有在仍缺少新的关键信息，且无法通过已有回答合理推断时，才可以再次请求用户补充。",
            ]
            why_needed = payload.get("why_needed")
            if why_needed:
                text_lines.extend([
                    "",
                    "需要该信息的原因：",
                    str(why_needed),
                ])
            content.append({
                "type": "text",
                "text": "\n".join(text_lines),
            })
        else:
            content.append({
                "type": "text",
                "text": f"【当前步骤用户补充信息】\n{answer}",
            })

    else:
        content.append({"type": "text", "text": f"系统记录了未知控制事件：{event_type}"})

    messages.append({
        "role": "user",
        "content": content,
    })


def append_tool_result(messages: list[Message], tool_use_id: str, result: str) -> None:
    """Append a tool_result block to conversation messages."""
    messages.append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": result,
        }],
    })


def has_tool_result(messages: list[Message], tool_use_id: str) -> bool:
    """Return True when conversation already contains a tool_result for tool_use_id."""
    for msg in messages:
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_result"
                and block.get("tool_use_id") == tool_use_id
            ):
                return True

    return False
