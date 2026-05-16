"""confirmation 子包：plan / step / tool / user_input / memory 确认 handler。

本包通过 dispatcher.py 提供共享基础设施（ConfirmationContext、observer 入口、
feedback intent 常量），各 handler 模块按职责独立但共享同一份 ConfirmationContext
签名——确保拆分后 handler 签名一致、core.py 无需感知内部分层。
"""

from agent.confirmation.dispatcher import (
    FEEDBACK_INTENT_OPTIONS,
    FEEDBACK_INTENT_QUESTION,
    FEEDBACK_INTENT_WHY,
    ConfirmationContext,
)
from agent.confirmation.memory import dispatch_memory_confirmation
from agent.confirmation.plan import (
    handle_feedback_intent_choice,
    handle_plan_confirmation,
    handle_step_confirmation,
)
from agent.confirmation.tool import handle_tool_confirmation
from agent.confirmation.user_input import handle_user_input_step

__all__ = [
    "ConfirmationContext",
    "FEEDBACK_INTENT_OPTIONS",
    "FEEDBACK_INTENT_QUESTION",
    "FEEDBACK_INTENT_WHY",
    "dispatch_memory_confirmation",
    "handle_feedback_intent_choice",
    "handle_plan_confirmation",
    "handle_step_confirmation",
    "handle_tool_confirmation",
    "handle_user_input_step",
]
