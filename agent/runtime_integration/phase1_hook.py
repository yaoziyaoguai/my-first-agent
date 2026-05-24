"""Phase 1 real core loop RuntimeAction hook factory.

中文学习边界：
这个模块是 Phase 1 的 dispatcher 构建工厂，只负责组装 RuntimeActionDispatcher
并注册 memory turn-end proposal handler、memory retain handler 和 tool gate handler。
它不导入 core.py、loop.py 或 state.py，保持单向依赖：core.py → phase1_hook →
dispatcher/memory_hook/memory_retain/tool_gate。

为什么独立文件：
- 避免 core.py 直接依赖 RuntimeActionDispatcher 构造细节
- 避免 core.py 变成 dispatcher builder 巨石
- 保持 runtime_integration 内聚：所有 dispatcher build 变体都在这一层
"""

from __future__ import annotations

from agent.runtime_integration.checkpoint_summary import CheckpointSafeSummaryHandler
from agent.runtime_integration.dispatcher import ActionHandlerRegistry, RuntimeActionDispatcher
from agent.runtime_integration.evidence import RuntimeActionModuleObserver
from agent.runtime_integration.memory_consolidate import MemoryConsolidateHandler
from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
from agent.runtime_integration.memory_recall import MemoryRecallHandler
from agent.runtime_integration.memory_retain import MemoryRetainHandler
from agent.runtime_integration.schema import RuntimeActionType
from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
from agent.runtime_integration.subagent_action import SubAgentDelegateL0Handler
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry
from agent.subagent_system.registry import SubAgentRegistry
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler


def build_phase1_dispatcher() -> RuntimeActionDispatcher:
    """构建 Phase 1 RuntimeActionDispatcher。

    注册 memory turn-end proposal + retain + recall + consolidate + tool pipeline +
    checkpoint + skill select handler（共 9 个 handler）。
    Streaming、SubAgent 不在当前范围，不注册。

    Phase 1 dispatcher 特征：
    - MemoryTurnEndProposalHandler（pending_review only，proposal generation）
    - MemoryRetainHandler（confirmed proposal retain execution）
    - ToolGateHandler（_safe_noop / _confirmable_noop explicit internal allowlist only；
      其他 "_" 前缀工具仍被 blocked，不走 allowlist 路径）
    - 不在 core loop 中自动 approved
    - dispatcher.route() 在 loop.turn_end 时由 loop.py 触发
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    registry.register(
        RuntimeActionType.MEMORY_PROPOSE,
        MemoryRetainHandler(),
    )
    registry.register(
        RuntimeActionType.MEMORY_RECALL,
        MemoryRecallHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_GATE,
        ToolGateHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_REQUEST,
        ToolGateHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_INVOKE,
        ToolInvokeHandler(),
    )
    registry.register(
        RuntimeActionType.TOOL_RESULT,
        ToolResultFeedbackHandler(),
    )
    registry.register(
        RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
        CheckpointSafeSummaryHandler(),
    )
    registry.register(
        RuntimeActionType.MEMORY_CONSOLIDATE,
        MemoryConsolidateHandler(),
    )
    # SKILL_SELECT：空 registry → handler 总是 rejected（no skills available）
    # 但 evidence chain 仍然完整——L3 关注 dispatch 路径，不关注 disposition
    _skill_registry = SkillRegistry(roots=[])
    _skill_loader = SkillLoader(_skill_registry)
    registry.register(
        RuntimeActionType.SKILL_SELECT,
        SkillRuntimeActionHandler(registry=_skill_registry, loader=_skill_loader),
    )
    # SUBAGENT_DELEGATE_L0：空 registry → handler 总是 rejected（no subagent available）
    _subagent_registry = SubAgentRegistry(roots=())
    registry.register(
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
        SubAgentDelegateL0Handler(registry=_subagent_registry),
    )
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())
