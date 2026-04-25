

"""Task runtime helpers.

This module owns task/step state transitions and step-completion checks.
It does not call the model and does not execute tools.
"""

from __future__ import annotations

from typing import Any

from agent.planner import Plan
from config import STEP_COMPLETION_THRESHOLD


def get_latest_step_completion(state: Any) -> dict | None:
    """返回当前步骤**最近一次** mark_step_complete 的 input（如果有）。

    返回值形态（由 meta.py 的工具参数定义）：
        {"completion_score": int, "summary": str, "outstanding": str}

    若当前步骤没有任何 mark_step_complete 记录，返回 None。

    实现：遍历 tool_execution_log（dict，Python 3.7+ 保留插入顺序），
    找出 tool == 'mark_step_complete' 且 step_index == 当前步骤索引 的**最后一条**
    ——模型可能先报低分、之后又改口打高分，"后来居上"是想要的语义。
    """
    if not state.task.current_plan:
        return None

    current_idx = state.task.current_step_index
    latest = None
    for entry in state.task.tool_execution_log.values():
        if entry.get("tool") != "mark_step_complete":
            continue
        if entry.get("step_index") != current_idx:
            continue
        latest = entry

    if latest is None:
        return None
    return latest.get("input")


def is_current_step_completed(state: Any) -> bool:
    """当前步骤是否被模型"合法地"声明完成。

    判定规则：当前步骤至少有一条 mark_step_complete 记录，
    且**最近一条**的 completion_score ≥ STEP_COMPLETION_THRESHOLD。

    单步任务（无 plan）不走本流程——核心循环在无 plan 时本来就靠 end_turn
    结束，不需要"步骤完成"概念。
    """
    if not state.task.current_plan:
        return False

    latest = get_latest_step_completion(state)
    if latest is None:
        return False

    score = latest.get("completion_score")
    if not isinstance(score, int):
        return False
    return score >= STEP_COMPLETION_THRESHOLD


def advance_current_step_if_needed(state: Any) -> None:
    """Advance current task step, or mark task done when all steps are complete.

    任何让 status 跨状态跳变（done / running with new step_index）的 mutate
    都必须立刻 save_checkpoint，否则重启后会进入"旧步骤已过、新步骤未记录"的
    不一致态。
    """
    from agent.checkpoint import save_checkpoint

    if not state.task.current_plan:
        state.task.status = "done"
        save_checkpoint(state)
        return

    plan = Plan.model_validate(state.task.current_plan)

    if state.task.current_step_index < len(plan.steps) - 1:
        state.task.current_step_index += 1
        state.task.status = "running"
    else:
        state.task.status = "done"

    save_checkpoint(state)