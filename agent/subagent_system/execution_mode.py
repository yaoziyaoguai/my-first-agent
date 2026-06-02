"""SubAgent execution modes and stop reasons.

Mode 字符串是跨 descriptor、request、policy、executor 的 contract。默认 L0
只能使用 local_fake / local_deterministic；真实 LLM、sandbox 等高阶能力必须
通过后续 gated phase 显式开启。
"""

from __future__ import annotations

from enum import Enum


class SubAgentExecutionMode(Enum):
    LOCAL_FAKE = "local_fake"
    LOCAL_DETERMINISTIC = "local_deterministic"
    REAL_LLM_READONLY = "real_llm_readonly"
    REAL_LLM_TOOL_REQUESTING = "real_llm_tool_requesting"
    SANDBOXED_TOOL_CAPABLE = "sandboxed_tool_capable"


class SubAgentStopReason(Enum):
    TASK_COMPLETED = "task_completed"
    TASK_COMPLETED_BY_CHILD = "task_completed_by_child"
    TASK_COMPLETED_LOW_CONFIDENCE = "task_completed_low_confidence"
    MAX_ITERATIONS_EXCEEDED = "max_iterations_exceeded"
    MAX_CONTEXT_EXCEEDED = "max_context_exceeded"
    NEEDS_CLARIFICATION = "needs_clarification"
    NEEDS_CONFIRMATION = "needs_confirmation"
    TOOL_BLOCKED = "tool_blocked"
    POLICY_BLOCKED = "policy_blocked"
    ERROR = "error"
    INTERRUPTED = "interrupted"


EXECUTION_MODE_VALUES = frozenset(mode.value for mode in SubAgentExecutionMode)
STOP_REASON_VALUES = frozenset(reason.value for reason in SubAgentStopReason)
LOCAL_EXECUTION_MODES = frozenset({
    SubAgentExecutionMode.LOCAL_FAKE.value,
    SubAgentExecutionMode.LOCAL_DETERMINISTIC.value,
})

