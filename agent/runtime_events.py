"""v0.4 transition 命名草案。

这个模块只提供轻量的事件 / 结果词汇，帮助 v0.4 第一阶段先把
transition boundary 测试写清楚。它不是新的 Runtime 主流程，不接管
`core.py` / handlers，不写 checkpoint，也不承载 CLI DisplayEvent。

中文学习边界：
- RuntimeEventKind 是“发生了什么”的候选名称，当前代码仍可能由既有
  handlers 直接修改 TaskState。
- TransitionOutcome 是“未来 transition 层可以返回什么”的草案结构，
  只放 JSON 友好的基础字段，避免把 DisplayEvent / RuntimeEvent /
  InputIntent / CommandResult 这类临时 UI/协议对象混进持久状态。
- 本模块存在不代表 v0.4 完整事件驱动状态机已经实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RuntimeEventKind(str, Enum):
    """v0.4 第一阶段候选事件名，不绑定当前完整实现。"""

    USER_INPUT = "user_input"
    MODEL_OUTPUT = "model_output"
    TOOL_RESULT = "tool_result"
    POLICY_DENIAL = "policy_denial"
    USER_REJECTION = "user_rejection"
    CHECKPOINT_RESUME = "checkpoint_resume"
    HEALTH_COMMAND = "health_command"
    LOGS_COMMAND = "logs_command"


@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    """未来 transition 层的最小返回草案。

    字段都保持为基础类型或字符串 tuple，便于测试边界：这不是 checkpoint
    schema，也不是 DisplayEvent 队列。后续迁移时，handler 可以先返回这种
    结果对象，再由调用方决定是否保存 checkpoint / 渲染 UI。
    """

    next_status: str | None = None
    should_checkpoint: bool = False
    display_events: tuple[str, ...] = ()
    pending_tool_action: str | None = None
    pending_user_input_action: str | None = None
    reason: str = ""
    notes: tuple[str, ...] = ()
