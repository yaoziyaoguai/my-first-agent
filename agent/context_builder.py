
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



def build_execution_messages(state: Any) -> list[dict]:
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


def extract_text(content_blocks) -> str:
    parts = [block.text for block in content_blocks if block.type == "text"]
    return "\n".join(p for p in parts if p).strip()