"""SubAgent execution mode policy."""

from __future__ import annotations

from dataclasses import dataclass

from agent.subagent_system.errors import SubAgentModeError
from agent.subagent_system.execution_mode import SubAgentExecutionMode


@dataclass(frozen=True)
class SubAgentPolicy:
    """Parent-controlled execution boundaries.

    默认值表达 L0：本地、确定性、无外部进程、无 nested delegation。高阶能力
    只通过 gated phase 显式打开。
    """

    local_only: bool = True
    real_llm_readonly_allowed: bool = False
    real_llm_tool_requesting_allowed: bool = False
    sandboxed_tool_capable_allowed: bool = False
    external_process_allowed: bool = False
    worktree_isolation_allowed: bool = False
    autonomous_tool_execution_allowed: bool = False
    max_nested_depth: int = 0
    max_context_chars: int = 100_000
    max_revisions: int = 1
    default_mode: str = "local_fake"


def select_execution_mode(
    request: object,
    descriptor: object,
    policy: SubAgentPolicy,
) -> SubAgentExecutionMode:
    """Select a parent-requested mode if descriptor and policy both allow it."""

    requested = getattr(request, "execution_mode", policy.default_mode)
    if requested not in getattr(descriptor, "supported_modes", ()):
        raise SubAgentModeError(
            code="MODE_NOT_SUPPORTED",
            message="Requested execution mode is outside descriptor.supported_modes",
            safe_preview="Requested execution mode is not supported by SubAgent",
        )
    if requested == SubAgentExecutionMode.REAL_LLM_READONLY.value and not policy.real_llm_readonly_allowed:
        raise _gate_closed("REAL_LLM_READONLY_GATE_CLOSED")
    if requested == SubAgentExecutionMode.REAL_LLM_TOOL_REQUESTING.value and not policy.real_llm_tool_requesting_allowed:
        raise _gate_closed("REAL_LLM_TOOL_REQUESTING_GATE_CLOSED")
    if requested == SubAgentExecutionMode.SANDBOXED_TOOL_CAPABLE.value and not policy.sandboxed_tool_capable_allowed:
        raise _gate_closed("SANDBOX_GATE_CLOSED")
    return SubAgentExecutionMode(requested)


def _gate_closed(code: str) -> SubAgentModeError:
    return SubAgentModeError(
        code=code,
        message="Execution mode config gate is closed",
        safe_preview="Execution mode is gated off",
    )

