import json
from agent.logger import log_event


PLANNING_PROMPT = """判断用户的请求是否需要多步骤执行计划。

判断标准：
- 如果是简单问答、闲聊、单次计算、读一个文件、写一个文件等一步能完成的操作 → 不需要计划
- 如果需要先收集信息再分析、需要读多个文件、需要多次工具调用才能完成 → 需要计划

请严格按 JSON 格式输出，不要有其他内容：

不需要计划时：
{"needs_plan": false}

需要计划时：
{"needs_plan": true, "goal": "任务目标的一句话描述", "steps": [{"id": 1, "action": "具体动作描述"}, {"id": 2, "action": "..."}]}

注意：
- 步骤数量控制在 2-6 步，不要过度拆分
- 最后一步通常是"整理并输出结果"
- 每步的 action 要具体，不要写"继续分析"这种模糊描述
"""


def generate_plan(user_input, client, model_name, messages=None):
    """
    判断任务是否需要计划，如果需要则生成计划。
    返回 None（不需要计划）或 plan 字典。
    """
    try:
        plan_messages = []
        if messages and len(messages) > 1:
            plan_messages = messages[-6:]

        plan_messages.append({"role": "user", "content": user_input})

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

        plan = json.loads(clean_text)

        if not plan.get("needs_plan", False):
            log_event("plan_skipped", {"reason": "simple_task", "input": user_input[:100]})
            return None

        log_event("plan_generated", {
            "goal": plan.get("goal", ""),
            "steps": len(plan.get("steps", [])),
        })

        return plan

    except Exception as e:
        log_event("plan_error", {"error": str(e)})
        return None


def format_plan_for_display(plan):
    """把计划格式化成用户可读的文本"""
    lines = [f"\n📋 任务规划：{plan['goal']}\n"]
    for step in plan["steps"]:
        lines.append(f"  {step['id']}. {step['action']}")
    lines.append("")
    return "\n".join(lines)


def format_plan_for_context(plan):
    lines = [f"[任务计划] 目标：{plan['goal']}"]
    for step in plan["steps"]:
        lines.append(f"步骤{step['id']}：{step['action']}")
    lines.append("\n执行规则：")
    lines.append("- 严格按步骤顺序逐个执行，不要合并步骤")
    lines.append("- 每完成一个步骤后，简要说明该步骤的结果")
    lines.append("- 完成所有步骤后停止，输出最终结果")
    lines.append("- 不要执行计划之外的操作")
    return "\n".join(lines)
