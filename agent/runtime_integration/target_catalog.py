"""RuntimeAction target identity allowlist — extracted from evidence.py.

This module owns:
  * the descriptor record (``RuntimeActionTargetDescriptor``)
  * descriptor-builder helpers (``_descriptor`` and per-domain builders)
  * the per-domain adapters (catalog-owned invocation adapters)
  * the allowlist ``RuntimeActionTargetCatalog`` and its index lookups

Compatibility: ``agent.runtime_integration.evidence`` re-exports the
catalog class so existing import sites keep working.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class RuntimeActionTargetDescriptor:
    """dispatcher/catalog-owned target implementation descriptor.

    中文学习边界：`target_module` 只是报告标签，不能证明真实 target identity。
    descriptor 同时绑定 handler、action、目标标签和 catalog-owned invocation
    adapter；只有通过 descriptor adapter 执行的调用才能发行 trusted proof。
    """

    action_type: str
    handler_name: str
    handler_identity: str
    target_module: str
    operation: str
    target_catalog_id: str
    target_handle: str
    target_descriptor_id: str
    invocation_adapter_id: str
    implementation_id: str
    callable_identity: str
    function_called: str
    call_signature: str
    adapter: Callable[[Mapping[str, Any]], Any] = field(repr=False, compare=False)

    def invoke(self, payload: Mapping[str, Any]) -> Any:
        """执行 catalog-owned invocation adapter，而不是 handler 提供的 callable。"""

        return self.adapter(payload)


def _function_identity(module_name: str, qualname: str) -> str:
    return f"function:{module_name}.{qualname}"


def _bound_method_identity(class_path: str, method_name: str) -> str:
    return f"bound_method:{class_path}.{method_name}"


def _partial_identity(base_identity: str) -> str:
    return f"partial:{base_identity}"


def _callable_identity(call: Callable[[], Any]) -> str:
    """为 observer 看到的 callable 生成稳定、无参数值的实现身份。

    这里只记录函数/方法的 module + qualname，不记录闭包内容、参数值或对象
    repr，避免把 payload 或隐私数据写进 evidence。`functools.partial` 会追溯
    到它包装的真实函数/方法，用来验证 catalog-owned invocation adapter。
    """

    if isinstance(call, partial):
        return _partial_identity(_callable_identity(call.func))
    bound_function = getattr(call, "__func__", None)
    bound_owner = getattr(call, "__self__", None)
    if bound_function is not None and bound_owner is not None:
        owner_cls = bound_owner if isinstance(bound_owner, type) else type(bound_owner)
        return _bound_method_identity(
            f"{owner_cls.__module__}.{owner_cls.__qualname__}",
            str(getattr(bound_function, "__name__", "<unknown>")),
        )
    module_name = str(getattr(call, "__module__", type(call).__module__))
    qualname = str(getattr(call, "__qualname__", type(call).__qualname__))
    return _function_identity(module_name, qualname)


def _payload_value_adapter(payload: Mapping[str, Any]) -> Any:
    """test/dogfood harness 用的 catalog-owned synthetic adapter。"""

    value = payload.get("value")
    return dict(value) if isinstance(value, Mapping) else value


def _lookup_tool_registry_entry_adapter(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """ToolRegistry lookup adapter，不执行目标工具函数。"""

    from agent.tool_registry import TOOL_REGISTRY

    return TOOL_REGISTRY.get(str(payload.get("tool_name") or ""))


def _dogfood_overlay_block_adapter(payload: Mapping[str, Any]) -> dict[str, Any]:
    overlay_tool = payload.get("overlay_tool")
    if type(overlay_tool).__module__ != "agent.runtime_integration.tool_gate":
        raise TypeError("overlay_tool must be DogfoodOverlayTool")
    if type(overlay_tool).__qualname__ != "DogfoodOverlayTool":
        raise TypeError("overlay_tool must be DogfoodOverlayTool")
    return overlay_tool.block()


def _skill_loader_load_body_adapter(payload: Mapping[str, Any]) -> str:
    from agent.skill_system.loader import SkillLoader

    loader = payload.get("loader")
    if not isinstance(loader, SkillLoader):
        raise TypeError("loader must be SkillLoader")
    return str(loader.load_body(str(payload.get("skill_id") or "")))


def _skill_no_suitable_skill_adapter(payload: Mapping[str, Any]) -> str:
    """no_suitable_skill 操作适配器：返回拒绝原因字符串，不加载任何 skill body。"""
    return str(payload.get("reason") or "no suitable skill available")


def _subagent_no_suitable_subagent_adapter(payload: Mapping[str, Any]) -> str:
    """no_suitable_subagent 操作适配器：返回拒绝原因字符串，不启动任何 subagent。"""
    return str(payload.get("reason") or "no suitable subagent available")


def _memory_policy_decide_adapter(payload: Mapping[str, Any]) -> Any:
    from agent.memory_policy import DeterministicMemoryPolicy

    policy = payload.get("policy")
    if not isinstance(policy, DeterministicMemoryPolicy):
        raise TypeError("policy must be DeterministicMemoryPolicy")
    return policy.decide(str(payload.get("user_message") or ""))


def _memory_store_apply_intent_adapter(payload: Mapping[str, Any]) -> Any:
    from agent.memory_operations import MemoryAuditSummary, MemoryOperationIntent

    store = payload.get("store")
    intent = payload.get("intent")
    audit_summary = payload.get("audit_summary")
    if not _looks_like_memory_store(store):
        raise TypeError("store must implement MemoryStoreProtocol")
    if not isinstance(intent, MemoryOperationIntent):
        raise TypeError("intent must be MemoryOperationIntent")
    if not isinstance(audit_summary, MemoryAuditSummary):
        raise TypeError("audit_summary must be MemoryAuditSummary")
    return store.apply_operation_intent(intent, audit_summary)


def _memory_recall_snapshot_adapter(payload: Mapping[str, Any]) -> Any:
    """Catalog-owned adapter for memory recall snapshot generation。

    中文学习边界：这个 adapter 是 build_memory_snapshot_from_store() 的
    catalog-owned wrapper。handler 不直接调用 snapshot generator，而是通过
    context.invoke_registered_target() → 此 adapter 获取 trusted target_module_proof。
    """
    from agent.memory_snapshot_generator import (
        MemorySnapshotBuildOptions,
        build_memory_snapshot_from_store,
    )

    store = payload.get("store")
    options_dict = payload.get("options") or {}

    if not _looks_like_memory_store(store):
        raise TypeError("store must implement MemoryStoreProtocol")

    options = MemorySnapshotBuildOptions(
        selection_reason=str(options_dict.get("selection_reason") or "Memory Kernel v1 recall"),
        max_items=int(options_dict.get("max_items") or 5),
        rendered_char_budget=int(options_dict.get("rendered_char_budget") or 500),
    )
    return build_memory_snapshot_from_store(store, options)


def _looks_like_memory_store(store: Any) -> bool:
    """用公开协议方法做 duck-typing，避免 catalog adapter 绑死单个 store 实现。"""

    return all(
        callable(getattr(store, method_name, None))
        for method_name in (
            "apply_operation_intent",
            "get_record",
            "list_records",
            "remove_record",
        )
    )


def _tool_result_format_adapter(payload: Mapping[str, Any]) -> Any:
    """Catalog-owned adapter for tool result formatting。

    中文学习边界：这个 adapter 是 format_tool_result() 的
    catalog-owned wrapper。handler 不直接调用格式化函数，而是通过
    context.invoke_registered_target() → 此 adapter 获取 trusted target_module_proof。
    """
    from agent.runtime_integration.tool_result_feedback import format_tool_result

    tool_name = str(payload.get("tool_name") or "")
    tool_output = payload.get("tool_output")  # str | None
    execution_status = str(payload.get("execution_status") or "success")
    rendered_char_budget = int(payload.get("rendered_char_budget") or 500)

    return format_tool_result(
        tool_name=tool_name,
        tool_output=tool_output,
        execution_status=execution_status,
        rendered_char_budget=rendered_char_budget,
    )


def _tool_invoke_adapter(payload: Mapping[str, Any]) -> Any:
    """Catalog-owned adapter for TOOL_INVOKE evidence-only lookup。

    中文学习边界：TOOL_INVOKE 不再是工具执行入口。这个 adapter 只能读取
    TOOL_REGISTRY 元数据，不能调用 execute_tool()；真实工具执行只能通过
    ToolRuntimeMediator → tool_executor 发生。
    """
    from agent.tool_registry import TOOL_REGISTRY

    tool_name = str(payload.get("tool_name") or "")

    if tool_name not in TOOL_REGISTRY:
        return {
            "found": False,
            "tool_output": None,
            "execution_status": "not_found",
            "risk_level": "unknown",
            "capability": "",
        }

    info = TOOL_REGISTRY[tool_name]
    return {
        "found": True,
        "tool_output": None,
        "execution_status": "not_executed",
        "risk_level": info.get("risk_level", "medium"),
        "capability": info.get("capability", ""),
    }


def _checkpoint_safe_summary_adapter(payload: Mapping[str, Any]) -> str:
    from agent.runtime_integration.safe_metadata import project_safe_metadata_text

    return project_safe_metadata_text(
        str(payload.get("runtime_state_summary") or ""),
        max_length=2000,
    )


def _checkpoint_save_persist_adapter(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Catalog-owned adapter for CheckpointSave.persist invocation。"""
    return {
        "task_status": str(payload.get("task_status") or "unknown"),
        "persisted": True,
    }


def _checkpoint_resume_restore_adapter(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Catalog-owned adapter for CheckpointResume.restore invocation。"""
    return {
        "resume_mode": str(payload.get("resume_mode") or "interactive"),
        "restored": True,
    }


def _mcp_bridge_lifecycle_initialize_adapter(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Catalog-owned adapter for MCPBridgeLifecycle.initialize invocation。"""
    return {
        "mode": str(payload.get("mode") or "disabled"),
        "dry_run": bool(payload.get("dry_run", True)),
        "servers_configured": int(payload.get("servers_configured") or 0),
        "servers_evaluated": int(payload.get("servers_evaluated") or 0),
        "tools_discovered": int(payload.get("tools_discovered") or 0),
        "tools_registered": int(payload.get("tools_registered") or 0),
    }


def _memory_consolidation_adapter(payload: Mapping[str, Any]) -> Any:
    """Catalog-owned adapter for consolidation pipeline invocation.

    The underlying pipeline module is FROZEN (2026-05-25). This adapter
    is a compatibility shim: MEMORY_CONSOLIDATE is dispatched in
    ``MemoryConsolidateHandler``, which calls back into the frozen
    pipeline via this adapter. The dispatcher-bound handler itself is
    NOT frozen, so the product path remains alive while the legacy
    pipeline implementation stays frozen.
    """
    from agent.memory_consolidation_pipeline import run_consolidation_pipeline
    from agent.memory_store import InMemoryMemoryStore

    store = payload.get("store")
    if not isinstance(store, InMemoryMemoryStore):
        raise TypeError("store must be InMemoryMemoryStore or its subclass")
    return run_consolidation_pipeline(store, llm_generator=None)


def _streaming_collect_response_adapter(payload: Mapping[str, Any]) -> Any:
    from agent.provider.streaming import ProviderStreamEvent, collect_stream_response

    events = payload.get("events") or ()
    if not all(isinstance(event, ProviderStreamEvent) for event in events):
        raise TypeError("events must be ProviderStreamEvent instances")
    return collect_stream_response(list(events))


def _streaming_validate_event_adapter(payload: Mapping[str, Any]) -> Any:
    from agent.provider.streaming import ProviderStreamEvent
    from agent.runtime_integration.streaming_provider import validate_stream_event

    event = payload.get("event")
    if not isinstance(event, ProviderStreamEvent):
        raise TypeError("event must be a ProviderStreamEvent instance")
    return validate_stream_event(event)


def _subagent_delegate_once_adapter(payload: Mapping[str, Any]) -> Any:
    from agent.subagent_system.delegation import delegate_once
    from agent.subagent_system.registry import SubAgentRegistry
    from agent.subagent_system.request import SubAgentRequest

    subagent_request = payload.get("subagent_request")
    registry = payload.get("registry")
    if not isinstance(subagent_request, SubAgentRequest):
        raise TypeError("subagent_request must be SubAgentRequest")
    if not isinstance(registry, SubAgentRegistry):
        raise TypeError("registry must be SubAgentRegistry")
    return delegate_once(subagent_request, registry)


def _cli_show_memories_list_records_adapter(payload: Mapping[str, Any]) -> Any:
    from agent.memory_runtime import MemoryRuntime

    store = payload.get("store")
    if store is not None:
        runtime = MemoryRuntime(store=store)
        return runtime.list_records()
    return ()


def _memory_store_remove_record_adapter(payload: Mapping[str, Any]) -> Any:
    """Catalog-owned adapter for memory store remove_record。

    Loop 2.1: MEMORY_FORGET handler 通过此 adapter 获得 trusted target_module_proof。
    """
    store = payload.get("store")
    record_id = str(payload.get("record_id") or "")
    if store is not None and record_id:
        return store.remove_record(record_id)
    return False


def _cli_show_subagents_list_visible_adapter(payload: Mapping[str, Any]) -> Any:
    from pathlib import Path as _Path

    from agent.subagent_system.registry import SubAgentRegistry

    registry = SubAgentRegistry(roots=[_Path("agent/subagent_system/descriptors")])
    return registry.list_visible()


def _descriptor(
    action_type: str,
    handler_identity: str,
    target_module: str,
    *,
    operation: str,
    invocation_adapter_id: str,
    adapter: Callable[[Mapping[str, Any]], Any],
    function_called: str,
    call_signature: str,
    implementation_id: str | None = None,
) -> RuntimeActionTargetDescriptor:
    handler_name = handler_identity.rsplit(".", 1)[-1]
    catalog_id = f"{action_type}:{handler_identity}:{target_module}:{operation}"
    callable_identity = _callable_identity(adapter)
    return RuntimeActionTargetDescriptor(
        action_type=action_type,
        handler_name=handler_name,
        handler_identity=handler_identity,
        target_module=target_module,
        operation=operation,
        target_catalog_id=catalog_id,
        target_handle=f"target:{catalog_id}",
        target_descriptor_id=f"descriptor:{catalog_id}:{invocation_adapter_id}",
        invocation_adapter_id=invocation_adapter_id,
        implementation_id=implementation_id or invocation_adapter_id,
        callable_identity=callable_identity,
        function_called=function_called,
        call_signature=call_signature,
        adapter=adapter,
    )


def _test_descriptors(
    module_name: str,
    handler_name: str,
    action_type: str,
    targets: tuple[str, ...],
    *,
    operation: str,
    invocation_adapter_id: str,
    function_called: str | None = None,
    call_signature: str = "run()",
) -> tuple[RuntimeActionTargetDescriptor, ...]:
    """为 runtime_integration harness 测试声明静态 target 身份。

    中文学习边界：这些 test-only descriptor 仍是代码内置 catalog，不是 public
    API。它们允许 harness 生成合法 synthetic target proof，但任意 handler
    通过 `invoke_registered_target()` 才能使用 `_payload_value_adapter`。handler
    传入 lambda 的兼容路径不会解析 descriptor，仍不能伪造成可信 target。
    """

    return tuple(
        _descriptor(
            action_type,
            f"{module_name}.{handler_name}",
            target,
            operation=operation,
            invocation_adapter_id=invocation_adapter_id,
            adapter=_payload_value_adapter,
            function_called=function_called or f"{target}.run",
            call_signature=call_signature,
        )
        for target in targets
    )


def _scheduler_descriptors() -> tuple[RuntimeActionTargetDescriptor, ...]:
    """Loop 3.4: Advanced Scheduler 的 5 个 action type 的 catalog descriptors。

    中文学习边界：
    Scheduler handler 不执行真实业务逻辑——它只是验证 payload 结构完整性。
    这些 descriptor 使用 _payload_value_adapter（identity pass-through），
    因为 scheduler evidence 的 value 已经在 payload 中，不需要 adapter 转换。
    """
    _scheduler_action_types = (
        "scheduler.action_plan_start",
        "scheduler.node_enter",
        "scheduler.node_exit",
        "scheduler.node_failure",
        "scheduler.action_plan_complete",
    )
    _handler = "agent.runtime_integration.action_scheduler_handler.ActionSchedulerHandler"
    _operations = (
        "action_plan_start",
        "node_enter",
        "node_exit",
        "node_failure",
        "action_plan_complete",
    )
    return tuple(
        _descriptor(
            at,
            _handler,
            "ActionScheduler",
            operation=op,
            invocation_adapter_id=f"ActionScheduler.{op}",
            implementation_id=f"agent.action_scheduler.ActionScheduler.{op}",
            adapter=_payload_value_adapter,
            function_called=f"ActionScheduler.{op}",
            call_signature=f"{op}(payload: dict)",
        )
        for at, op in zip(_scheduler_action_types, _operations, strict=True)
    )


class RuntimeActionTargetCatalog:
    """RuntimeAction target identity allowlist.

    route/result/proof/call 绑定只能证明“一次调用被观测”；它不能证明 handler
    声称的 `target_module` 就是真实生产 target。target catalog 是 dispatcher
    可查询、classifier 可复核的受控 trust boundary：只有这里声明的
    action_type + handler identity + target_module + operation + descriptor adapter
    组合才能获得 target_handle。
    """

    _bindings: ClassVar[tuple[RuntimeActionTargetDescriptor, ...]] = (
        _descriptor(
            "skill.select",
            "agent.runtime_integration.skill_action.SkillRuntimeActionHandler",
            "SkillLoader",
            operation="load_body",
            invocation_adapter_id="SkillLoader.load_body",
            implementation_id="agent.skill_system.loader.SkillLoader.load_body",
            adapter=_skill_loader_load_body_adapter,
            function_called="SkillLoader.load_body",
            call_signature="load_body(skill_id: str)",
        ),
        _descriptor(
            "skill.select",
            "agent.runtime_integration.skill_action.SkillRuntimeActionHandler",
            "SkillLoader",
            operation="no_suitable_skill",
            invocation_adapter_id="SkillLoader.no_suitable_skill",
            implementation_id="agent.skill_system.loader.SkillLoader.no_suitable_skill",
            adapter=_skill_no_suitable_skill_adapter,
            function_called="SkillLoader.no_suitable_skill",
            call_signature="no_suitable_skill(reason: str)",
        ),
        _descriptor(
            "tool.request",
            "agent.runtime_integration.tool_gate.ToolGateHandler",
            "ToolRegistry",
            operation="lookup_and_risk_check",
            invocation_adapter_id="ToolRegistry.lookup_and_risk_check",
            implementation_id="agent.tool_registry.TOOL_REGISTRY.lookup",
            adapter=_lookup_tool_registry_entry_adapter,
            function_called="ToolRegistry.lookup_and_risk_check",
            call_signature="lookup_and_risk_check(tool_name: str)",
        ),
        _descriptor(
            "tool.gate",
            "agent.runtime_integration.tool_gate.ToolGateHandler",
            "ToolRegistry",
            operation="lookup_and_risk_check",
            invocation_adapter_id="ToolRegistry.lookup_and_risk_check",
            implementation_id="agent.tool_registry.TOOL_REGISTRY.lookup",
            adapter=_lookup_tool_registry_entry_adapter,
            function_called="ToolRegistry.lookup_and_risk_check",
            call_signature="lookup_and_risk_check(tool_name: str)",
        ),
        _descriptor(
            "tool.invoke",
            "agent.runtime_integration.tool_invoke.ToolInvokeHandler",
            "ToolRegistry",
            operation="lookup_invoke_metadata",
            invocation_adapter_id="ToolRegistry.lookup_invoke_metadata",
            implementation_id="agent.tool_registry.TOOL_REGISTRY.lookup",
            adapter=_tool_invoke_adapter,
            function_called="ToolRegistry.lookup_invoke_metadata",
            call_signature="lookup_invoke_metadata(tool_name: str)",
        ),
        _descriptor(
            "tool.request",
            "agent.runtime_integration.tool_gate.ToolGateHandler",
            "DogfoodFakeToolOverlay",
            operation="block",
            invocation_adapter_id="DogfoodFakeToolOverlay.block",
            implementation_id="agent.runtime_integration.tool_gate.DogfoodOverlayTool.block",
            adapter=_dogfood_overlay_block_adapter,
            function_called="DogfoodOverlayTool.block",
            call_signature="block()",
        ),
        _descriptor(
            "tool.gate",
            "agent.runtime_integration.tool_gate.ToolGateHandler",
            "DogfoodFakeToolOverlay",
            operation="block",
            invocation_adapter_id="DogfoodFakeToolOverlay.block",
            implementation_id="agent.runtime_integration.tool_gate.DogfoodOverlayTool.block",
            adapter=_dogfood_overlay_block_adapter,
            function_called="DogfoodOverlayTool.block",
            call_signature="block()",
        ),
        _descriptor(
            "memory.turn_end_proposal",
            "agent.runtime_integration.memory_hook.MemoryTurnEndProposalHandler",
            "MemoryPolicy",
            operation="decide",
            invocation_adapter_id="MemoryPolicy.decide",
            implementation_id="agent.memory_policy.DeterministicMemoryPolicy.decide",
            adapter=_memory_policy_decide_adapter,
            function_called="DeterministicMemoryPolicy.decide",
            call_signature="decide(text: str)",
        ),
        _descriptor(
            "memory.propose",
            "agent.runtime_integration.memory_hook.MemoryTurnEndProposalHandler",
            "MemoryPolicy",
            operation="decide",
            invocation_adapter_id="MemoryPolicy.decide",
            implementation_id="agent.memory_policy.DeterministicMemoryPolicy.decide",
            adapter=_memory_policy_decide_adapter,
            function_called="DeterministicMemoryPolicy.decide",
            call_signature="decide(text: str)",
        ),
        _descriptor(
            "memory.propose",
            "agent.runtime_integration.memory_retain.MemoryRetainHandler",
            "MemoryStore",
            operation="apply_operation_intent",
            invocation_adapter_id="MemoryStore.apply_operation_intent",
            implementation_id="agent.memory_store.MemoryStoreProtocol.apply_operation_intent",
            adapter=_memory_store_apply_intent_adapter,
            function_called="MemoryStoreProtocol.apply_operation_intent",
            call_signature="apply_operation_intent(intent, audit_summary)",
        ),
        _descriptor(
            "memory.recall",
            "agent.runtime_integration.memory_recall.MemoryRecallHandler",
            "MemoryRuntime",
            operation="build_memory_snapshot",
            invocation_adapter_id="MemoryRuntime.build_memory_snapshot",
            implementation_id="agent.memory_snapshot_generator.build_memory_snapshot_from_store",
            adapter=_memory_recall_snapshot_adapter,
            function_called="build_memory_snapshot_from_store",
            call_signature="build_memory_snapshot_from_store(store, options)",
        ),
        _descriptor(
            "tool.result",
            "agent.runtime_integration.tool_result_feedback.ToolResultFeedbackHandler",
            "ToolRuntime",
            operation="format_tool_result",
            invocation_adapter_id="ToolRuntime.format_tool_result",
            implementation_id="agent.runtime_integration.tool_result_feedback.format_tool_result",
            adapter=_tool_result_format_adapter,
            function_called="format_tool_result",
            call_signature="format_tool_result(tool_name, tool_output,"
            " execution_status, rendered_char_budget)",
        ),
        _descriptor(
            "checkpoint.safe_summary",
            "agent.runtime_integration.checkpoint_summary.CheckpointSafeSummaryHandler",
            "CheckpointSafeSummary",
            operation="redact",
            invocation_adapter_id="CheckpointSafeSummary.redact",
            implementation_id="agent.display_events.mask_user_visible_secrets",
            adapter=_checkpoint_safe_summary_adapter,
            function_called="CheckpointSafeSummary.redact",
            call_signature="redact(runtime_state_summary: str)",
        ),
        _descriptor(
            "checkpoint.save",
            "agent.runtime_integration.checkpoint_save.CheckpointSaveHandler",
            "CheckpointSave",
            operation="persist",
            invocation_adapter_id="CheckpointSave.persist",
            implementation_id="agent.checkpoint.save_checkpoint",
            adapter=_checkpoint_save_persist_adapter,
            function_called="CheckpointSave.persist",
            call_signature="persist(task_status: str)",
        ),
        _descriptor(
            "checkpoint.resume",
            "agent.runtime_integration.checkpoint_resume.CheckpointResumeHandler",
            "CheckpointResume",
            operation="restore",
            invocation_adapter_id="CheckpointResume.restore",
            implementation_id="agent.checkpoint.load_checkpoint_to_state",
            adapter=_checkpoint_resume_restore_adapter,
            function_called="CheckpointResume.restore",
            call_signature="restore(resume_mode: str)",
        ),
        _descriptor(
            "mcp.bridge_lifecycle",
            "agent.runtime_integration.mcp_bridge_lifecycle.MCPBridgeLifecycleHandler",
            "MCPBridgeLifecycle",
            operation="initialize",
            invocation_adapter_id="MCPBridgeLifecycle.initialize",
            implementation_id="agent.mcp_bridge.run_mcp_bridge",
            adapter=_mcp_bridge_lifecycle_initialize_adapter,
            function_called="MCPBridgeLifecycle.initialize",
            call_signature="initialize(mode: str, dry_run: bool, tools_registered: int)",
        ),
        _descriptor(
            "streaming.provider_call",
            "agent.runtime_integration.streaming_provider.StreamingProviderCallHandler",
            "StreamingProtocol",
            operation="collect_stream_response",
            invocation_adapter_id="StreamingProtocol.collect_stream_response",
            implementation_id="agent.provider.streaming.collect_stream_response",
            adapter=_streaming_collect_response_adapter,
            function_called="collect_stream_response",
            call_signature="collect_stream_response(events)",
        ),
        _descriptor(
            "streaming.event",
            "agent.runtime_integration.streaming_provider.StreamingEventHandler",
            "StreamingProtocol",
            operation="validate_stream_event",
            invocation_adapter_id="StreamingProtocol.validate_stream_event",
            implementation_id="agent.runtime_integration.streaming_provider.validate_stream_event",
            adapter=_streaming_validate_event_adapter,
            function_called="validate_stream_event",
            call_signature="validate_stream_event(event)",
        ),
        _descriptor(
            "subagent.delegate_l0",
            "agent.runtime_integration.subagent_action.SubAgentDelegateL0Handler",
            "SubAgentExecutor",
            operation="delegate_once",
            invocation_adapter_id="SubAgentExecutor.delegate_once",
            implementation_id="agent.subagent_system.delegation.delegate_once",
            adapter=_subagent_delegate_once_adapter,
            function_called="delegate_once",
            call_signature="delegate_once(SubAgentRequest, SubAgentRegistry)",
        ),
        _descriptor(
            "subagent.delegate_l0",
            "agent.runtime_integration.subagent_action.SubAgentDelegateL0Handler",
            "SubAgentExecutor",
            operation="no_suitable_subagent",
            invocation_adapter_id="SubAgentExecutor.no_suitable_subagent",
            implementation_id="agent.subagent_system.delegation.SubAgentExecutor.no_suitable_subagent",
            adapter=_subagent_no_suitable_subagent_adapter,
            function_called="SubAgentExecutor.no_suitable_subagent",
            call_signature="no_suitable_subagent(reason: str)",
        ),
        _descriptor(
            "memory.consolidate",
            "agent.runtime_integration.memory_consolidate.MemoryConsolidateHandler",
            "MemoryConsolidation",
            operation="run_pipeline",
            invocation_adapter_id="MemoryConsolidation.run_pipeline",
            implementation_id="agent.memory_consolidation_pipeline.run_consolidation_pipeline",
            adapter=_memory_consolidation_adapter,
            function_called="run_consolidation_pipeline",
            call_signature="run_consolidation_pipeline(store, llm_generator=None)",
        ),
        _descriptor(
            "cli.show_memories",
            "agent.runtime_integration.cli_handlers.CliShowMemoriesHandler",
            "MemoryRuntime",
            operation="list_records",
            invocation_adapter_id="MemoryRuntime.list_records",
            implementation_id="agent.memory_runtime.MemoryRuntime.list_records",
            adapter=_cli_show_memories_list_records_adapter,
            function_called="MemoryRuntime.list_records",
            call_signature="list_records()",
        ),
        _descriptor(
            "memory.forget",
            "agent.runtime_integration.memory_forget.MemoryForgetHandler",
            "MemoryStore",
            operation="remove_record",
            invocation_adapter_id="MemoryStore.remove_record",
            implementation_id="agent.memory_store.InMemoryMemoryStore.remove_record",
            adapter=_memory_store_remove_record_adapter,
            function_called="InMemoryMemoryStore.remove_record",
            call_signature="remove_record(record_id)",
        ),
        _descriptor(
            "cli.show_subagents",
            "agent.runtime_integration.cli_handlers.CliShowSubagentsHandler",
            "SubAgentRegistry",
            operation="list_visible",
            invocation_adapter_id="SubAgentRegistry.list_visible",
            implementation_id="agent.subagent_system.registry.SubAgentRegistry.list_visible",
            adapter=_cli_show_subagents_list_visible_adapter,
            function_called="SubAgentRegistry.list_visible",
            call_signature="list_visible()",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_ObservedHandler",
            "tool.request",
            ("FakeTargetModule",),
            operation="run",
            invocation_adapter_id="FakeTargetModule.test_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_ObservedHandler",
            "tool.request",
            ("FakeTargetModule",),
            operation="run",
            invocation_adapter_id="FakeTargetModule.test_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_ObservedHandler",
            "tool.request",
            ("FakeTargetModule",),
            operation="run",
            invocation_adapter_id="FakeTargetModule.test_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_TwoIssuedResultsSameRouteHandler",
            "tool.request",
            ("FakeTargetModule",),
            operation="run",
            invocation_adapter_id="FakeTargetModule.test_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_TwoIssuedResultsSameRouteHandler",
            "tool.request",
            ("FakeTargetModule",),
            operation="run",
            invocation_adapter_id="FakeTargetModule.test_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_TwoIssuedResultsSameRouteHandler",
            "tool.request",
            ("FakeTargetModule",),
            operation="run",
            invocation_adapter_id="FakeTargetModule.test_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "tool.request",
            ("ToolRegistry",),
            operation="test_catalog_adapter",
            invocation_adapter_id="ToolRegistry.test_catalog_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "tool.request",
            ("ToolRegistry",),
            operation="test_catalog_adapter",
            invocation_adapter_id="ToolRegistry.test_catalog_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "tool.request",
            ("ToolRegistry",),
            operation="test_catalog_adapter",
            invocation_adapter_id="ToolRegistry.test_catalog_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "skill.select",
            ("SkillLoader", "SkillRegistry"),
            operation="test_catalog_adapter",
            invocation_adapter_id="SkillRuntime.test_catalog_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "skill.select",
            ("SkillLoader", "SkillRegistry"),
            operation="test_catalog_adapter",
            invocation_adapter_id="SkillRuntime.test_catalog_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "skill.select",
            ("SkillLoader", "SkillRegistry"),
            operation="test_catalog_adapter",
            invocation_adapter_id="SkillRuntime.test_catalog_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.safe_summary",
            ("CheckpointSafeSummary",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointSafeSummary.test_catalog_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.safe_summary",
            ("CheckpointSafeSummary",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointSafeSummary.test_catalog_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.safe_summary",
            ("CheckpointSafeSummary",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointSafeSummary.test_catalog_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.save",
            ("CheckpointSave",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointSave.test_catalog_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.save",
            ("CheckpointSave",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointSave.test_catalog_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.save",
            ("CheckpointSave",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointSave.test_catalog_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.resume",
            ("CheckpointResume",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointResume.test_catalog_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.resume",
            ("CheckpointResume",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointResume.test_catalog_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "checkpoint.resume",
            ("CheckpointResume",),
            operation="test_catalog_adapter",
            invocation_adapter_id="CheckpointResume.test_catalog_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "streaming.provider_call",
            ("StreamingProtocol",),
            operation="test_catalog_adapter",
            invocation_adapter_id="StreamingProtocol.test_catalog_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "streaming.provider_call",
            ("StreamingProtocol",),
            operation="test_catalog_adapter",
            invocation_adapter_id="StreamingProtocol.test_catalog_adapter",
        ),
        *_test_descriptors(
            "test_runtime_action_contract",
            "_CatalogAllowedForgedCallableHandler",
            "streaming.provider_call",
            ("StreamingProtocol",),
            operation="test_catalog_adapter",
            invocation_adapter_id="StreamingProtocol.test_catalog_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_capability_matrix",
            "_MatrixObservedHandler",
            "skill.select",
            ("SkillLoader",),
            operation="run",
            invocation_adapter_id="MatrixHarness.test_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_capability_matrix",
            "_MatrixObservedHandler",
            "skill.select",
            ("SkillLoader",),
            operation="run",
            invocation_adapter_id="MatrixHarness.test_adapter",
        ),
        *_test_descriptors(
            "test_capability_matrix",
            "_MatrixObservedHandler",
            "skill.select",
            ("SkillLoader",),
            operation="run",
            invocation_adapter_id="MatrixHarness.test_adapter",
        ),
        *_test_descriptors(
            "tests.runtime_integration.test_capability_matrix",
            "_MatrixObservedHandler",
            "tool.request",
            ("ToolRegistry", "DogfoodFakeToolOverlay"),
            operation="run",
            invocation_adapter_id="MatrixHarness.test_adapter",
        ),
        *_test_descriptors(
            "runtime_integration.test_capability_matrix",
            "_MatrixObservedHandler",
            "tool.request",
            ("ToolRegistry", "DogfoodFakeToolOverlay"),
            operation="run",
            invocation_adapter_id="MatrixHarness.test_adapter",
        ),
        *_test_descriptors(
            "test_capability_matrix",
            "_MatrixObservedHandler",
            "tool.request",
            ("ToolRegistry", "DogfoodFakeToolOverlay"),
            operation="run",
            invocation_adapter_id="MatrixHarness.test_adapter",
        ),
        # Loop 3.4: Advanced Scheduler — 5 action types, 共用一个 identity adapter
        *_scheduler_descriptors(),
    )
    _by_key: ClassVar[dict[tuple[str, str, str, str, str], RuntimeActionTargetDescriptor]] = {
        (
            binding.action_type,
            binding.handler_name,
            binding.handler_identity,
            binding.target_module,
            binding.operation,
        ): binding
        for binding in _bindings
    }
    _by_descriptor_id: ClassVar[dict[str, RuntimeActionTargetDescriptor]] = {
        binding.target_descriptor_id: binding
        for binding in _bindings
    }

    @classmethod
    def resolve(
        cls,
        *,
        action_type: str,
        handler_name: str,
        handler_identity: str,
        target_module: str,
        operation: str,
    ) -> RuntimeActionTargetDescriptor | None:
        key = (action_type, handler_name, handler_identity, target_module, operation)
        return cls._by_key.get(key)

    @classmethod
    def is_allowed_descriptor(
        cls,
        *,
        action_type: str,
        handler_name: str,
        handler_identity: str,
        target_module: str,
        target_catalog_id: str,
        target_handle: str,
        target_descriptor_id: str,
        invocation_adapter_id: str,
        implementation_id: str,
        callable_identity: str,
    ) -> bool:
        binding = cls._by_descriptor_id.get(target_descriptor_id)
        return (
            binding is not None
            and binding.action_type == action_type
            and binding.handler_name == handler_name
            and binding.handler_identity == handler_identity
            and binding.target_module == target_module
            and binding.target_catalog_id == target_catalog_id
            and binding.target_handle == target_handle
            and binding.target_descriptor_id == target_descriptor_id
            and binding.invocation_adapter_id == invocation_adapter_id
            and binding.implementation_id == implementation_id
            and binding.callable_identity == callable_identity
        )
