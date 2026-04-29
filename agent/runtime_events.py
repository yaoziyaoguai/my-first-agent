"""v0.4 transition 命名与最小 command slice。

这个模块只提供轻量的事件 / 结果词汇，帮助 v0.4 Phase 1 先把
transition boundary 测试写清楚。它不是新的 Runtime 主流程，不接管
`core.py` / handlers，不写 checkpoint，也不承载 CLI DisplayEvent。

中文学习边界：
- RuntimeEventKind 是“发生了什么”的候选名称，当前代码仍可能由既有
  handlers 直接修改 TaskState。
- TransitionResult 是“Runtime 临时决策结果”的草案结构，只放 JSON 友好
  的基础字段，避免把 DisplayEvent / RuntimeEvent / InputIntent /
  CommandResult 这类临时 UI/协议对象混进 checkpoint 或 messages。
- command event slice 只覆盖 health/logs 维护命令的 no-op transition，
  证明维护命令可以产生输出，但不改变 task execution state。
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
class TransitionResult:
    """未来 transition 层的最小返回草案。

    字段都保持为基础类型或字符串 tuple，便于测试边界：这不是 checkpoint
    schema，也不是 DisplayEvent 队列。后续迁移时，handler 可以先返回这种
    结果对象，再由调用方决定是否保存 checkpoint / 渲染 UI。

    注意：`display_events` 目前只存临时输出事件名字符串，不存 DisplayEvent
    对象本体。这样测试能确认“可展示输出”和“持久状态”没有混线。
    """

    next_status: str | None = None
    should_checkpoint: bool = False
    clear_pending_tool: bool = False
    clear_pending_user_input: bool = False
    advance_step: bool = False
    display_events: tuple[str, ...] = ()
    reason: str = ""
    notes: tuple[str, ...] = ()


# 兼容上一轮 prep 文档和测试使用的名字。v0.4 后续正式定名时再统一收敛，
# 当前不做大范围 rename，避免把“命名准备”变成 runtime 迁移。
TransitionOutcome = TransitionResult


def command_event_transition(kind: RuntimeEventKind) -> TransitionResult:
    """把维护命令映射成 no-op transition。

    这是 v0.4 Phase 1 的第一个最小事件切片：`health` / `logs` 是 Runtime
    维护命令，可以产生 stdout/JSON/log viewer 输出，但不应该改变 TaskState、
    不应该清 pending、不应该推进 step，也不应该触发 task checkpoint。

    只接受 HealthCommand / LogsCommand，避免把业务事件误塞进这个 no-op 通道。
    """

    if kind == RuntimeEventKind.HEALTH_COMMAND:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            display_events=("health.report",),
            reason=kind.value,
            notes=("maintenance command; no task transition",),
        )
    if kind == RuntimeEventKind.LOGS_COMMAND:
        return TransitionResult(
            next_status=None,
            should_checkpoint=False,
            display_events=("logs.viewer",),
            reason=kind.value,
            notes=("maintenance command; no task transition",),
        )
    raise ValueError(f"unsupported command event kind: {kind.value}")
