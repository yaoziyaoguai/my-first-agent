

"""Task runtime helpers.

This module owns task/step state transitions and step-completion checks.
It does not call the model and does not execute tools.
"""

from __future__ import annotations

from typing import Any

from agent.planner import Plan


def is_current_step_completed(state: Any, assistant_text: str) -> bool:
    """Return True when assistant_text indicates the current step is complete."""
    if not state.task.current_plan:
        return False

    text = assistant_text.strip()
    if not text:
        return False

    completion_markers = [
        "本步骤已完成",
        "当前步骤已完成",
        "步骤已完成",
        "已完成当前步骤",
    ]
    return any(marker in text for marker in completion_markers)


def advance_current_step_if_needed(state: Any) -> None:
    """Advance current task step, or mark task done when all steps are complete."""
    if not state.task.current_plan:
        state.task.status = "done"
        return

    plan = Plan.model_validate(state.task.current_plan)

    if state.task.current_step_index < len(plan.steps) - 1:
        state.task.current_step_index += 1
        state.task.status = "running"
    else:
        state.task.status = "done"