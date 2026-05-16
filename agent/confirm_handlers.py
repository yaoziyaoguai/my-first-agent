"""Confirmation handlers — backward-compatible facade.

实现已拆分到 agent.confirmation 子包（Global P3 Hardening）。
本模块保留为兼容性重导出层，所有旧 import 路径不受影响。
"""

# --- public API（与原 confirm_handlers.py 一致）---
from agent.confirmation.dispatcher import (
    ContinueFn,
    StartPlanningFn,
    ConfirmationContext,
    FEEDBACK_INTENT_OPTIONS,
    FEEDBACK_INTENT_QUESTION,
    FEEDBACK_INTENT_WHY,
)
from agent.confirmation.plan import (
    handle_feedback_intent_choice,
    handle_plan_confirmation,
    handle_step_confirmation,
)
from agent.confirmation.tool import handle_tool_confirmation
from agent.confirmation.user_input import handle_user_input_step

# --- 内部依赖重导出（测试 monkeypatch 路径兼容）---
from agent.checkpoint import save_checkpoint  # noqa: F401 (test mock path)
from agent.input_resolution import resolve_user_input  # noqa: F401 (test mock path)
from agent.runtime_observer import log_event as _log_runtime_event  # noqa: F401 (test mock path)
from agent.transitions import apply_user_replied_transition  # noqa: F401 (test mock path)

__all__ = [
    "ConfirmationContext",
    "ContinueFn",
    "StartPlanningFn",
    "FEEDBACK_INTENT_OPTIONS",
    "FEEDBACK_INTENT_QUESTION",
    "FEEDBACK_INTENT_WHY",
    "handle_feedback_intent_choice",
    "handle_plan_confirmation",
    "handle_step_confirmation",
    "handle_tool_confirmation",
    "handle_user_input_step",
]
