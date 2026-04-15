import json
from agent.logger import log_event


PLANNING_PROMPT = """你是一个任务分析器。请估算完成用户请求需要多少个步骤。

估算规则：
- 简单问答、闲聊、单次计算 → 1 步
- 读一个文件、写一个文件 → 1 步
- 涉及一个文件夹或目录（即使用户没说"多个文件"）→ 通常 2 步以上
- 需要先收集信息再分析 → 2 步以上
- 需要多次工具调用才能完成 → 2 步以上
- 用户明确说了"一步一步"、"逐步"、"分步" → 一定是 2 步以上

请严格按 JSON 格式输出，不要有其他内容：

1 步任务：
{"steps_estimate": 1}

2 步及以上任务（附带具体计划）：
{"steps_estimate": 3, "goal": "任务目标的一句话描述", "steps": [{"id": 1, "action": "具体动作描述"}, {"id": 2, "action": "..."}]}

注意：
- 步骤数量控制在 2-6 步，不要过度拆分
- 最后一步通常是"整理并输出结果"
- 每步的 action 要具体，不要写"继续分析"这种模糊描述
- 如果有现成的命令或工具能批量完成（如 ruff check、pytest、grep），优先用命令而不是逐个读取文件
- 单个步骤内读取文件不要超过 5 个，如果需要检查更多文件，用命令行工具
"""


def generate_plan(user_input, client, model_name, messages=None):
    """
    判断任务是否需要计划，如果需要则生成计划。
    返回 None（不需要计划）或 plan 字典。
    """
    try:
        plan_messages = [{"role": "user", "content": user_input}]
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
        
        print(f"[DEBUG] plan raw response: '{result_text[:200]}'")  # ← 加这一行

        clean_text = result_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1]
        if clean_text.endswith("```"):
            clean_text = clean_text.rsplit("```", 1)[0]
        clean_text = clean_text.strip()

        plan = json.loads(clean_text)

        if plan.get("steps_estimate", 1) <= 1:
            log_event("plan_skipped", {"reason": "single_step", "input": user_input[:100]})
            return None

        log_event("plan_generated", {
            "goal": plan.get("goal", ""),
            "steps": len(plan.get("steps", [])),
            "steps_estimate": plan.get("steps_estimate"),
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
    """把计划格式化成注入上下文的文本"""
    lines = [f"[任务计划] 目标：{plan['goal']}"]
    for step in plan["steps"]:
        lines.append(f"步骤{step['id']}：{step['action']}")
    lines.append("\n执行规则：")
    lines.append("- 严格按步骤顺序逐个执行，不要合并步骤")
    lines.append("- 每完成一个步骤后，简要说明该步骤的结果")
    lines.append("- 完成所有步骤后停止，输出最终结果")
    lines.append("- 不要执行计划之外的操作")
    lines.append("- 不要反复读取同一个文件")
    return "\n".join(lines)
