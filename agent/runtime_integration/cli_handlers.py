"""CLI meta-command handlers — thin dispatcher wrappers for CLI shortcuts.

中文学习边界：
- 这些 handler 是现有 CLI shortcut 逻辑的薄包装，不改变用户可见行为
- handler 通过 constructor injection 接收 memory_runtime / subagent_registry
- handle() 通过 context.success 返回 RuntimeActionResult，payload 中包含原始数据供 render 函数消费
- 这不是新 runtime path——dispatch 发生在 core.chat() 的 CLI detection 阶段，
  复用已有 RuntimeActionDispatcher，不新增 branch point

Loop 4 (Runtime Entry Consolidation):
  READ_ONLY CLI commands (show memories, show subagents) 通过 dispatcher 获得
  evidence chain，不再绕过统一入口。MUTATING/DELEGATING commands 待 confirmation
  pipeline 就绪后再迁入。
"""

from __future__ import annotations

from typing import Any

from agent.cli_commands import (
    detect_forget_memory,
    detect_show_memories,
    detect_show_subagents,
    render_memory_forget_not_found,
    render_memory_forget_result,
    render_memory_list,
    render_subagent_list,
)
from agent.display_events import (
    memory_forgotten_event,
    memory_list_event,
    subagent_list_event,
)
from agent.runtime_event_safety import safe_emit_runtime_event
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType


class CliShowMemoriesHandler:
    """show memories CLI command 的 dispatcher handler。

    包装 _memory_runtime.list_records()，将结果放入 RuntimeActionResult.payload，
    由 core.chat() 读取后通过 cli_commands.render_memory_list() 渲染。
    """

    def __init__(self, *, memory_runtime: Any = None) -> None:
        self._memory_runtime = memory_runtime

    def handle(self, request: Any, context: Any) -> Any:
        records = ()
        if self._memory_runtime is not None:
            try:
                records = tuple(self._memory_runtime.list_records())
            except Exception:
                records = ()
        return context.success(
            handler_name=type(self).__name__,
            target_module="MemoryRuntime",
            payload={"records": records, "disposition": "completed"},
            observed_call=None,
            evidence_extra={"disposition": "completed", "record_count": len(records)},
        )


class CliShowSubagentsHandler:
    """show subagents CLI command 的 dispatcher handler。

    包装 SubAgentRegistry.list_visible()，将结果放入 RuntimeActionResult.payload。
    """

    def __init__(self, *, subagent_registry: Any = None) -> None:
        self._subagent_registry = subagent_registry

    def handle(self, request: Any, context: Any) -> Any:
        descriptors = ()
        if self._subagent_registry is not None:
            try:
                descriptors = tuple(self._subagent_registry.list_visible())
            except Exception:
                descriptors = ()
        return context.success(
            handler_name=type(self).__name__,
            target_module="SubAgentRegistry",
            payload={"descriptors": descriptors, "disposition": "completed"},
            observed_call=None,
            evidence_extra={"disposition": "completed", "descriptor_count": len(descriptors)},
        )


def handle_cli_meta_command(
    user_input: str,
    *,
    read_only_dispatcher: Any,
    mutating_dispatcher: Any,
    memory_runtime: Any,
    on_runtime_event: Any = None,
) -> str | None:
    """Handle existing CLI meta-commands outside core.py.

    Scope is intentionally limited to the three real commands that already
    existed before hardening: show memories, forget memory, and show subagents.
    This does not add update/correction commands or any Sub-agent feature work.
    """
    if detect_show_memories(user_input):
        result = read_only_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.CLI_SHOW_MEMORIES,
            source="core.chat",
            parent_trace_id="",
            payload={"user_input": user_input},
        ))
        records = result.payload.get("records", ()) if result else ()
        safe_emit_runtime_event(
            on_runtime_event,
            memory_list_event(records),
            fallback_prefix="\n",
        )
        return render_memory_list(records)

    forget_keyword = detect_forget_memory(user_input)
    if forget_keyword:
        return _handle_forget_memory_cli(
            forget_keyword,
            dispatcher=mutating_dispatcher,
            memory_runtime=memory_runtime,
            on_runtime_event=on_runtime_event,
        )

    if detect_show_subagents(user_input):
        result = read_only_dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.CLI_SHOW_SUBAGENTS,
            source="core.chat",
            parent_trace_id="",
            payload={"user_input": user_input},
        ))
        descriptors = result.payload.get("descriptors", ()) if result else ()
        safe_emit_runtime_event(
            on_runtime_event,
            subagent_list_event(descriptors),
            fallback_prefix="\n",
        )
        return render_subagent_list(descriptors)

    return None


def _handle_forget_memory_cli(
    forget_keyword: str,
    *,
    dispatcher: Any,
    memory_runtime: Any,
    on_runtime_event: Any = None,
) -> str:
    def forget_via_dispatcher(record_id: str) -> bool:
        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_FORGET,
            source="core.chat",
            parent_trace_id="",
            payload={"record_id": record_id},
        ))
        return bool(result.payload.get("forgotten")) if result else False

    if forget_keyword.lower().startswith("id:"):
        record_id = forget_keyword[3:].strip()
        if forget_via_dispatcher(record_id):
            safe_emit_runtime_event(
                on_runtime_event,
                memory_forgotten_event(1, keyword=f"id:{record_id}"),
                fallback_prefix="\n",
            )
            remaining = memory_runtime.list_records()
            safe_emit_runtime_event(
                on_runtime_event,
                memory_list_event(remaining),
                fallback_prefix="\n",
            )
            return f"已移除记忆（ID: {record_id}）。"

        records = memory_runtime.list_records()
        prefix_matches = [
            record for record in records
            if str(getattr(record, "id", "")).startswith(record_id)
        ]
        if len(prefix_matches) == 1:
            matched_id = prefix_matches[0].id
            if forget_via_dispatcher(matched_id):
                safe_emit_runtime_event(
                    on_runtime_event,
                    memory_forgotten_event(1, keyword=f"id:{record_id}"),
                    fallback_prefix="\n",
                )
                remaining = memory_runtime.list_records()
                safe_emit_runtime_event(
                    on_runtime_event,
                    memory_list_event(remaining),
                    fallback_prefix="\n",
                )
                return f"已移除记忆（ID: {record_id} → {matched_id}）。"
            return f"移除记忆失败（ID: {matched_id}）。"
        if len(prefix_matches) > 1:
            matched_ids = [
                str(getattr(record, "id", "?"))[:12] for record in prefix_matches
            ]
            return (
                f"前缀「{record_id}」匹配到 {len(prefix_matches)} 条记忆，"
                f"无法确定要删除哪一条。请使用更长的 ID 前缀重试。\n"
                f"匹配到的 ID：{', '.join(matched_ids)}"
            )
        return f"未找到 ID 为「{record_id}」的记忆。"

    records = memory_runtime.list_records()
    matched = [
        record for record in records
        if forget_keyword.lower() in getattr(record, "content", "").lower()
    ]
    if not matched:
        return render_memory_forget_not_found(forget_keyword)

    removed_count = 0
    for record in matched:
        if forget_via_dispatcher(record.id):
            removed_count += 1
    safe_emit_runtime_event(
        on_runtime_event,
        memory_forgotten_event(removed_count, keyword=forget_keyword),
        fallback_prefix="\n",
    )
    remaining = memory_runtime.list_records()
    safe_emit_runtime_event(
        on_runtime_event,
        memory_list_event(remaining),
        fallback_prefix="\n",
    )
    return render_memory_forget_result(forget_keyword, removed_count)
