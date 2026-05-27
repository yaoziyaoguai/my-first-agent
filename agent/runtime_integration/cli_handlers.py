"""CLI meta-command handlers — thin dispatcher wrappers for CLI shortcuts.

中文学习边界：
- 这些 handler 是现有 CLI shortcut 逻辑的薄包装，不改变用户可见行为
- handler 通过 constructor injection 接收 memory_runtime / subagent_registry
- handle() 返回 RuntimeActionResult，payload 中包含原始数据供 render 函数消费
- 这不是新 runtime path——dispatch 发生在 core.chat() 的 CLI detection 阶段，
  复用已有 RuntimeActionDispatcher，不新增 branch point

Loop 4 (Runtime Entry Consolidation):
  READ_ONLY CLI commands (show memories, show subagents) 通过 dispatcher 获得
  evidence chain，不再绕过统一入口。MUTATING/DELEGATING commands 待 confirmation
  pipeline 就绪后再迁入。
"""

from __future__ import annotations

from typing import Any


class CliShowMemoriesHandler:
    """show memories CLI command 的 dispatcher handler。

    包装 _memory_runtime.list_records()，将结果放入 RuntimeActionResult.payload，
    由 core.chat() 读取后通过 cli_commands.render_memory_list() 渲染。
    """

    def __init__(self, *, memory_runtime: Any = None) -> None:
        self._memory_runtime = memory_runtime

    def handle(self, request: Any, context: Any) -> Any:
        from agent.runtime_integration.schema import RuntimeActionResult

        records = ()
        if self._memory_runtime is not None:
            try:
                records = tuple(self._memory_runtime.list_records())
            except Exception:
                records = ()
        return RuntimeActionResult(
            status="success",
            action_type="cli.show_memories",
            disposition="completed",
            payload={"records": records},
        )


class CliShowSubagentsHandler:
    """show subagents CLI command 的 dispatcher handler。

    包装 SubAgentRegistry.list_visible()，将结果放入 RuntimeActionResult.payload。
    """

    def __init__(self, *, subagent_registry: Any = None) -> None:
        self._subagent_registry = subagent_registry

    def handle(self, request: Any, context: Any) -> Any:
        from agent.runtime_integration.schema import RuntimeActionResult

        descriptors = ()
        if self._subagent_registry is not None:
            try:
                descriptors = tuple(self._subagent_registry.list_visible())
            except Exception:
                descriptors = ()
        return RuntimeActionResult(
            status="success",
            action_type="cli.show_subagents",
            disposition="completed",
            payload={"descriptors": descriptors},
        )
