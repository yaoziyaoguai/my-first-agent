
from typing import Any

from agent.planner import Plan



def build_planning_messages(state: Any, current_user_input: str) -> list[dict]:
    """
    构造给 planner 使用的轻量 messages。

    规则：
    - 只提供历史摘要 + 最近原始消息
    - 不注入 current_plan / current_step / completion_criteria
    - 避免让 planner 被执行态上下文污染
    - 当前轮输入只在这里临时加入，不提前写回 conversation state
    - 过滤 tool_use / tool_result 块：planner 的 system prompt 只教它输出 JSON，
      不懂工具语义，带着工具块会成为噪声，干扰 steps_estimate 判断
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

    for msg in state.conversation.messages:
        cleaned = _strip_tool_blocks(msg)
        if cleaned is not None:
            model_messages.append(cleaned)

    model_messages.append({"role": "user", "content": current_user_input})
    return model_messages


def _strip_tool_blocks(msg: dict) -> dict | None:
    """把 messages 里的 tool_use / tool_result 块过滤掉，只保留纯文本。

    返回 None 表示这条消息整条被过滤（全是工具块，没有 text）。
    """
    content = msg.get("content")
    role = msg.get("role")

    # 纯文本消息直接保留
    if isinstance(content, str):
        return {"role": role, "content": content}

    if not isinstance(content, list):
        return None

    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text")
            if t:
                text_parts.append(t)
        # tool_use / tool_result 整块忽略

    if not text_parts:
        return None

    return {"role": role, "content": "\n".join(text_parts)}



def build_execution_messages(state: Any) -> list[dict]:
    """
    构造真正喂给执行阶段模型的 messages。

    规则：
    - summary 不存到 conversation.messages
    - current_plan 不存到 conversation.messages
    - 只在这里临时拼接
    - 只给模型当前步骤，而不是整份计划

    关键点：「当前步骤指令块」必须放在 messages **末尾**。
    注意力衰减下最近的消息影响最大，如果放在最前面，模型在经过
    多轮 tool_use / tool_result 之后会遗忘当前步骤的约束。
    但是——如果 messages 最后一条是 tool_result（user 消息），
    再追加一条 user 消息会连续出现两条 user（Anthropic 允许但语义混乱）；
    同时在 awaiting_tool_confirmation 期间也不应打扰 pending。
    这里采取折中：把指令块作为最末 user 消息追加，不和 tool_result 合并。
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

    # 先放历史对话
    model_messages.extend(state.conversation.messages)

    # 再把当前步骤指令块追加到末尾（靠近模型注意力）
    # 防御：task.status == "done" 时不应该再拼 step 块，即使 current_plan 还没被清空。
    if state.task.current_plan and state.task.status != "done":
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

            # 判断末尾是否为 user 消息，如果是则不连着再追加 user（某些后端不支持）
            # Anthropic 允许连续 user，但避免和 tool_result 同属一个 user 条目混淆：
            # 这里始终作为独立 user 消息追加。
            model_messages.append({
                "role": "user",
                "content": "\n".join(step_lines),
            })

    return model_messages


def extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()