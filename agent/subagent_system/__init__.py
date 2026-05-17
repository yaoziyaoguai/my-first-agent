"""Formal SubAgent System namespace.

该 package 承载生产型 SubAgent 架构，但默认只实现 L0 safe-local 基线。
Parent Agent 仍拥有 orchestration；这里的模块只提供受控 delegation contracts
和边界适配器，不接管主循环。
"""

from agent.subagent_system.context import SubAgentContextPackage
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.errors import SubAgentError
from agent.subagent_system.execution_mode import SubAgentExecutionMode, SubAgentStopReason
from agent.subagent_system.policy import SubAgentPolicy
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import SubAgentAuditRecord, SubAgentResult


# 中文学习边界：__all__ 只暴露稳定 contract 类型。这里不导出 runtime helper、
# dogfood harness、sandbox/worktree/parallel 等 gated/future 能力，避免调用方把
# package import 误当成能力开启。
__all__ = [
    "SubAgentAuditRecord",
    "SubAgentContextPackage",
    "SubAgentDescriptor",
    "SubAgentError",
    "SubAgentExecutionMode",
    "SubAgentPolicy",
    "SubAgentRequest",
    "SubAgentResult",
    "SubAgentStopReason",
]
