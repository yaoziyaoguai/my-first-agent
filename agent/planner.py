import json

from pydantic import ValidationError

from agent.logger import log_event
from agent.plan_schema import Plan, PlannerOutput

# ═══════════════════════════════════════════════════════════════════════════════
# ⛔ LEGACY: PLANNING_PROMPT / generate_plan() — 旧 Plan/PlanStep schema 路径
#
# 中文学习说明：
# 旧 planner 输出使用 Plan/PlanStep schema（step_type: read/analyze/edit/...），
# 缺少 scheduler 需要的 action_type/target/params/depends_on/recovery 等执行契约字段。
# plan_to_action_plan() 通过硬编码映射表做 schema 桥接，丢失信息且不可靠。
#
# 新正式路径：generate_action_plan() → ActionPlan schema，模型直接输出
# ActionNode 兼容 JSON（action_type/target/params/depends_on/recovery），
# 无需 heuristic 映射。ActionScheduler 只消费 ActionPlan。
#
# Sunset: v0.5+ — 所有调用方迁移到 generate_action_plan() 后移除。
# ═══════════════════════════════════════════════════════════════════════════════

PLANNING_PROMPT = """你是一个任务规划器。你的任务是判断当前用户请求是否需要多步执行。

规则：
- 简单问答、闲聊、单次计算、单次解释 -> 1 步
- 单文件读取、单文件修改 -> 通常 1 步
- 涉及多个步骤、多个文件、目录级处理、先收集再分析、先规划再执行 -> 2 步及以上
- 用户明确要求"分步""一步一步" -> 2 步及以上

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
- step_type 只能从以下类型中选择：
  read / analyze / edit / run_command / report / collect_input / clarify
- 如果任务在执行前缺少关键信息，第一步可以设为 collect_input 或 clarify
  用来向用户收集必要信息后再继续
- 每个步骤尽量提供 completion_criteria，用于描述"这一步什么时候算完成"
- description 要尽量自包含，不要依赖"上一部/下一步"这种模糊描述
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 正式规划入口：ActionPlan schema
# ═══════════════════════════════════════════════════════════════════════════════

ACTION_PLAN_PROMPT = """你是一个任务规划器，输出机器可执行的 ActionPlan JSON。

你的输出将被 ActionScheduler 直接消费，按依赖顺序逐个执行 action node。
每个 node 必须包含 action_type、target、params——这些是 scheduler 执行 node
时传给子系统 handler 的字段。

规则：
- 简单问答、闲聊、单次计算 → 不需要多步计划（返回 steps_estimate=1）
- 多步骤任务 → 输出完整 ActionPlan JSON
- 严格输出 JSON，不要 markdown，不要解释

如果是单步任务，输出：
{
  "steps_estimate": 1
}

如果是多步任务，输出：
{
  "steps_estimate": <步数>,
  "plan_id": "<唯一标识>",
  "entry_node_id": "<第一个执行的 node_id>",
  "description": "<人类可读的计划描述>",
  "nodes": [
    {
      "node_id": "step_1",
      "action_type": "TOOL_CALL",
      "target": "<工具名>",
      "params": {"<key>": "<value>"},
      "depends_on": [],
      "recovery": {"on_failure": "halt"},
      "condition": null,
      "description": "<人类可读的 node 描述>"
    }
  ]
}

字段说明：
- action_type: TOOL_CALL / MEMORY_RETAIN / MEMORY_FORGET / SKILL_SELECT / SUBAGENT_DELEGATE
- target: 工具名（TOOL_CALL）/ 记忆 key（MEMORY_RETAIN/MEMORY_FORGET）
  / skill 名（SKILL_SELECT）/ subagent 名（SUBAGENT_DELEGATE）
- params: 传给 target 的参数字典
- depends_on: 前置依赖 node_id 列表——前置全部完成后才能执行当前 node
- recovery.on_failure: "halt"（停止计划）/ "skip"（跳过继续）/ "fallback"（执行 fallback_node_id）
- condition: 可选 condition flag 名——前置 node 设置此 flag=true 时跳过当前 node；不需要则为 null
- description: 人类可读的 node 描述

要求：
- 每个 node 必须有 node_id / action_type / target
- params 根据 action_type 合理填充（TOOL_CALL 需要工具参数，MEMORY_RETAIN 需要 content 等）
- depends_on 数组即使为空也要输出 []
- recovery 即使为默认值也要输出 {"on_failure": "halt"}
- 顺序依赖的 node 必须显式声明 depends_on（如 step_2 depends_on ["step_1"]）
"""


# ⛔ LEGACY: generate_plan() 返回旧 Plan 对象（PlanStep schema），
# 不含 scheduler 需要的 action_type/target/params/depends_on/recovery。
# 新代码请用 generate_action_plan()。Sunset: v0.5+。
def generate_plan(user_input, client, model_name, messages=None):
    """[LEGACY] 判断任务是否需要计划，返回 None 或旧 Plan 对象。

    新代码应使用 generate_action_plan()——直接输出 ActionPlan schema，
    无需 plan_to_action_plan() heuristic 映射。
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


def generate_action_plan(user_input, client, model_name, messages=None, *, clean_text=None):
    """正式规划入口：让模型直接输出 ActionPlan schema JSON。

    与 generate_plan() 的关键区别：
    - 模型输出 ActionNode 兼容 JSON（action_type/target/params/depends_on/recovery），
      而非旧 PlanStep JSON（step_type/suggested_tool）
    - 解析通过 build_action_plan_from_model_output() 完成，无需 heuristic 映射
    - 返回 ActionPlan（可被 ActionScheduler 直接消费），而非旧 Plan

    Args:
        user_input: 用户原始输入
        client: 模型 client（clean_text 非空时仅用于签名兼容，不调用 API）
        model_name: 模型名（clean_text 非空时仅用于签名兼容）
        messages: 可选的完整 messages 列表
        clean_text: 可选——当调用方（_run_planning_phase）已完成 API 调用和
                    文本清洗后传入。此时跳过 client.messages.create()，
                    直接解析 JSON。这是 planner ↔ runtime 的统一委托解析入口，
                    消除 core.py 中重复的 markdown 剥离/JSON 解析逻辑。

    Returns:
        ActionPlan on success, None on single-step task or error.
    """
    # 延迟 import 避免循环依赖
    from agent.action_scheduler import build_action_plan_from_model_output

    try:
        if clean_text is not None:
            # ── 委托路径：API 调用已由 _run_planning_phase() 完成 ──
            # clean_text 已剥离 markdown fence 并 strip，直接解析 JSON。
            raw = json.loads(clean_text)
        else:
            # ── 独立路径：自行完成 API 调用 ──
            plan_messages = messages if messages else [{"role": "user", "content": user_input}]
            response = client.messages.create(
                model=model_name,
                max_tokens=1024,
                system=ACTION_PLAN_PROMPT,
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

        # 单步任务直接跳过
        steps_estimate = raw.get("steps_estimate", 0)
        if isinstance(steps_estimate, (int, float)) and int(steps_estimate) <= 1:
            log_event("plan_skipped", {"reason": "single_step", "input": user_input[:100]})
            return None

        # 多步任务：必须有 plan_id / nodes / entry_node_id
        if not raw.get("plan_id") or not raw.get("nodes"):
            log_event(
                "plan_error",
                {"error": "missing plan_id or nodes", "raw_keys": list(raw.keys())},
            )
            return None

        action_plan = build_action_plan_from_model_output(clean_text)

        log_event("action_plan_generated", {
            "plan_id": action_plan.plan_id,
            "nodes": len(action_plan.nodes),
            "entry_node_id": action_plan.entry_node_id,
        })

        return action_plan

    except (json.JSONDecodeError, KeyError) as e:
        log_event("plan_error", {"error": str(e), "phase": "generate_action_plan"})
        return None
    except ValueError as e:
        log_event("plan_error", {"error": str(e), "phase": "generate_action_plan_parse"})
        return None
    except Exception as e:
        log_event("plan_error", {"error": str(e), "phase": "generate_action_plan"})
        return None


# ⛔ LEGACY: format_plan_for_display() — 格式化旧 Plan 对象用于终端展示。
# 新代码请用 format_action_plan_for_display()。Sunset: v0.5+。
def format_plan_for_display(plan: Plan):
    lines = [f"\n📋 任务规划：{plan.goal}\n"]
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"  {i}. {step.title}：{step.description}")
    lines.append("")
    return "\n".join(lines)


# ⛔ LEGACY: format_plan_for_context() — 格式化旧 Plan 为模型上下文。
# 新代码请用 format_action_plan_for_context()。Sunset: v0.5+。
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


def format_action_plan_for_display(action_plan) -> str:
    """格式化 ActionPlan 为终端可读展示。

    与旧 format_plan_for_display() 的关键区别——ActionPlan 使用
    action_type/target/params/depends_on 字段，而非 step_type/suggested_tool。
    depends_on 非空时显示依赖关系。
    """
    lines = [f"\n📋 任务规划：{action_plan.description or action_plan.plan_id}\n"]
    for i, node in enumerate(action_plan.nodes, 1):
        deps = f" [依赖: {', '.join(node.depends_on)}]" if node.depends_on else ""
        cond = f" [条件: {node.condition}]" if node.condition else ""
        recovery = ""
        if node.recovery.on_failure != "halt":
            recovery = f" [失败: {node.recovery.on_failure}]"
        lines.append(
            f"  {i}. {node.description or node.node_id} "
            f"({node.action_type}:{node.target}{deps}{cond}{recovery})"
        )
    lines.append("")
    return "\n".join(lines)


def format_action_plan_for_context(action_plan) -> str:
    """格式化 ActionPlan 为模型上下文（注入 conversation.messages）。

    ActionScheduler 在 main loop 中按 depends_on 拓扑顺序推进 node，
    模型只需知道当前正在执行哪个 node、之前完成了哪些 node。
    与旧 format_plan_for_context() 不同，这里不注入"执行规则"——
    调度逻辑由 ActionScheduler 在 loop.py preprocessing block 中承载。
    """
    lines = [f"[任务计划] 目标：{action_plan.description or action_plan.plan_id}"]
    lines.append(f"计划包含 {len(action_plan.nodes)} 个步骤：")
    for node in action_plan.nodes:
        deps = f"，依赖: {', '.join(node.depends_on)}" if node.depends_on else ""
        lines.append(f"- {node.node_id}：{node.description or node.target}{deps}")
    return "\n".join(lines)
