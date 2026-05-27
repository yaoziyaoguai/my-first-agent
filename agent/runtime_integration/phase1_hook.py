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

from pathlib import Path
from typing import Any

from agent.runtime_integration.checkpoint_summary import CheckpointSafeSummaryHandler
from agent.runtime_integration.dispatcher import ActionHandlerRegistry, RuntimeActionDispatcher
from agent.runtime_integration.evidence import RuntimeActionModuleObserver
from agent.runtime_integration.memory_consolidate import MemoryConsolidateHandler
from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
from agent.runtime_integration.memory_recall import MemoryRecallHandler
from agent.runtime_integration.memory_retain import MemoryRetainHandler
from agent.runtime_integration.schema import RuntimeActionType
from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
from agent.runtime_integration.streaming_provider import (
    StreamingEventHandler,
    StreamingProviderCallHandler,
)
from agent.runtime_integration.subagent_action import SubAgentDelegateL0Handler
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry
from agent.subagent_system.registry import SubAgentRegistry


def build_skill_registry() -> SkillRegistry:
    """构建 SkillRegistry，扫描 skills/ 目录。

    返回的 registry 用于两处：
    1. SkillRuntimeActionHandler——校验 available_skill_metadata 一致性
    2. LoopDependencies——填充 SKILL_SELECT payload 的 available_skill_metadata

    旧格式 skill（缺少 version/status 必填字段）进入 _load_errors，
    不会出现在 list_visible() 中，不污染模型可见 skill 列表。
    """
    return SkillRegistry(roots=[Path("skills")])


def build_phase1_dispatcher(
    *,
    memory_runtime: Any = None,
    subagent_registry: Any = None,
) -> RuntimeActionDispatcher:
    """构建 Phase 1 RuntimeActionDispatcher。

    注册 memory turn-end proposal + retain + recall + consolidate + tool pipeline +
    checkpoint + skill select + subagent delegate + streaming provider call +
    streaming event handler（共 11 个 handler）。
    Streaming 已接入（STREAMING_PROVIDER_CALL + STREAMING_EVENT），
    SubAgent 已接入（SUBAGENT_DELEGATE_L0）。

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
    # SKILL_SELECT：通过 build_skill_registry() 扫描 skills/ 目录。
    # 旧格式 skill（缺少 version/status 必填字段）进入 _load_errors，
    # 不会出现在 list_visible() 中。
    _skill_registry = build_skill_registry()
    _skill_loader = SkillLoader(_skill_registry)
    registry.register(
        RuntimeActionType.SKILL_SELECT,
        SkillRuntimeActionHandler(registry=_skill_registry, loader=_skill_loader),
    )
    # SUBAGENT_DELEGATE_L0：demo subagent registry 非空，handler 可定位已注册 subagent。
    # PF-05: 使用 agent/subagent_system/descriptors/ 而非 tests/fixtures/subagents。
    # demo descriptors（demo-stat, code-reviewer）标记为 DEMO-ONLY，不是产品能力。
    # tests/fixtures/subagents 只能被 tests 读取，不能出现在 runtime product path。
    _subagent_registry = SubAgentRegistry(roots=[Path("agent/subagent_system/descriptors")])
    registry.register(
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
        SubAgentDelegateL0Handler(registry=_subagent_registry),
    )
    # STREAMING_PROVIDER_CALL：收集 streaming provider call evidence（整轮聚合）
    registry.register(
        RuntimeActionType.STREAMING_PROVIDER_CALL,
        StreamingProviderCallHandler(),
    )
    # STREAMING_EVENT：单 event 验证和 per-event evidence 收集
    registry.register(
        RuntimeActionType.STREAMING_EVENT,
        StreamingEventHandler(),
    )
    # Loop 4: CLI meta-command handlers（READ_ONLY — show memories / show subagents）
    # MUTATING/DELEGATING commands (forget/delegate) 待 confirmation pipeline 就绪后迁入。
    if memory_runtime is not None:
        from agent.runtime_integration.cli_handlers import CliShowMemoriesHandler
        registry.register(
            RuntimeActionType.CLI_SHOW_MEMORIES,
            CliShowMemoriesHandler(memory_runtime=memory_runtime),
        )
    if subagent_registry is not None:
        from agent.runtime_integration.cli_handlers import CliShowSubagentsHandler
        registry.register(
            RuntimeActionType.CLI_SHOW_SUBAGENTS,
            CliShowSubagentsHandler(subagent_registry=subagent_registry),
        )
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())
