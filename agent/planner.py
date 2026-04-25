import json
from agent.logger import log_event
from pydantic import ValidationError
from agent.plan_schema import PlannerOutput, Plan


PLANNING_PROMPT = """你是一个任务规划器。你的任务是判断当前用户请求是否需要多步执行。

规则：
- 简单问答、闲聊、单次计算、单次解释 -> 1 步
- 单文件读取、单文件修改 -> 通常 1 步
- 涉及多个步骤、多个文件、目录级处理、先收集再分析、先规划再执行 -> 2 步及以上
- 用户明确要求“分步”“一步一步” -> 2 步及以上

请严格输出 JSON，不要输出 markdown，不要输出解释。

如果是单步任务：
{
  "steps_estimate": 1
}

如果是多步任务：
{
  "steps_estimate": 3,
  "goal": "当前任务目标",
  "thinking": "简短规划思路",
  "needs_confirmation": true,
  "steps": [
    {
      "step_id": "step-1",
      "title": "步骤标题",
      "description": "详细步骤说明",
      "step_type": "read / analyze / edit / run_command / report / collect_input / clarify",
      "suggested_tool": null,
      "expected_outcome": "该步骤完成后预期得到什么",
      "completion_criteria": "什么情况下算该步骤完成"
    }
  ]
}

要求：
- 每个步骤必须包含 step_type
- step_type 只能从以下类型中选择：read / analyze / edit / run_command / report / collect_input / clarify
- 如果任务在执行前缺少关键信息，第一步可以设为 collect_input 或 clarify，用来向用户收集必要信息后再继续
- 每个步骤尽量提供 completion_criteria，用于描述“这一步什么时候算完成”
- description 要尽量自包含，不要依赖“上一部/下一步”这种模糊描述
"""


def generate_plan(user_input, client, model_name, messages=None):
    """
    判断任务是否需要计划，如果需要则生成计划。
    返回 None（不需要计划）或 Plan 对象。
    """
    try:
        # 若调用方构造了完整的 planning messages（历史摘要 + 最近对话 + 当前输入），
        # 优先使用；否则回退为只包含当前输入的单条消息。
        plan_messages = messages if messages else [{"role": "user", "content": user_input}]
        response = client.messages.create(
            model=model_name,
            max_tokens=1024,
            system=PLANNING_PROMPT,
            messages=plan_messages,
        )

        result_text = ""
        for block in response.content:
            if block.type == "text":
                result_text = block.text
                break


        clean_text = result_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1]
        if clean_text.endswith("```"):
            clean_text = clean_text.rsplit("```", 1)[0]
        clean_text = clean_text.strip()

        raw = json.loads(clean_text)

        # 用 Pydantic 强校验模型输出
        decision = PlannerOutput.model_validate(raw)

        # 单步任务直接跳过
        if decision.steps_estimate <= 1:
            log_event("plan_skipped", {"reason": "single_step", "input": user_input[:100]})
            return None

        # 多步任务必须有 goal 和 steps
        if not decision.goal or not decision.steps:
            log_event("plan_error", {"error": "missing goal or steps", "raw": raw})
            return None

        plan = Plan(
            goal=decision.goal,
            thinking=decision.thinking,
            steps=decision.steps,
            needs_confirmation=decision.needs_confirmation,
        )

        log_event("plan_generated", {
            "goal": plan.goal,
            "steps": len(plan.steps),
            "steps_estimate": decision.steps_estimate,
        })

        return plan

    except (json.JSONDecodeError, ValidationError) as e:
        log_event("plan_error", {"error": str(e)})
        return None
    except Exception as e:
        log_event("plan_error", {"error": str(e)})
        return None


def format_plan_for_display(plan: Plan):
    lines = [f"\n📋 任务规划：{plan.goal}\n"]
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"  {i}. {step.title}：{step.description}")
    lines.append("")
    return "\n".join(lines)


def format_plan_for_context(plan: Plan):
    lines = [f"[任务计划] 目标：{plan.goal}"]
    if plan.thinking:
        lines.append(f"规划思路：{plan.thinking}")
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"步骤{i}（{step.step_id}）：{step.title}")
        lines.append(f"- 说明：{step.description}")
        if step.suggested_tool:
            lines.append(f"- 建议工具：{step.suggested_tool}")
        if step.expected_outcome:
            lines.append(f"- 预期结果：{step.expected_outcome}")
    lines.append("\n执行规则：")
    lines.append("- 严格按步骤顺序逐个执行，不要合并步骤")
    lines.append("- 每完成一个步骤后，简要说明该步骤的结果")
    lines.append("- 完成所有步骤后停止，输出最终结果")
    lines.append("- 不要执行计划之外的操作")
    lines.append("- 不要反复读取同一个文件")
    return "\n".join(lines)
