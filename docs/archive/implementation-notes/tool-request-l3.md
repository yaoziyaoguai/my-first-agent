# TOOL_REQUEST L3 Implementation Notes

## 概述

TOOL_REQUEST L3 wiring —— 在 loop.py turn-end hook 中新增 `tool.request` RuntimeAction dispatch，复用 `ToolGateHandler` 的 early-return 路径产生 L3 evidence。

## 架构决策

与 Skill/SubAgent L3 同构：不复用不同的 dispatch timing（token streaming），而是在 turn-end hook 中 dispatch TOOL_REQUEST，handler early-return 路径处理空 tool_name → `context.invoke_registered_target("ToolRegistry", "lookup_and_risk_check")` → `context.failed(observed_call=observed)`。

## 关键变更

### 1. `agent/runtime_integration/tool_gate.py` — early-return 路径

在现有 `if not tool_name:` 检查之前，新增 tool.request 专用 early-return：

```python
if not tool_name:
    # tool.request L3 evidence dispatch（非模型驱动的 tool request）
    if str(request.action_type) == "tool.request":
        observed = context.invoke_registered_target(
            target_module="ToolRegistry",
            operation="lookup_and_risk_check",
            payload={"tool_name": ""},
        )
        return context.failed(
            ...,
            observed_call=observed,
            evidence_extra={"decision": "failed", "no_tool_requested": True},
        )
    # 原有 tool.gate 空 tool_name 错误路径（无 L3 evidence）
    return context.failed(...)
```

### 2. `agent/runtime_integration/phase1_hook.py` — handler 注册

```python
registry.register(RuntimeActionType.TOOL_REQUEST, ToolGateHandler())
```

### 3. `agent/loop.py` — turn-end dispatch block

```python
tool_request_dispatch = RuntimeActionRequest(
    action_type=RuntimeActionType.TOOL_REQUEST,
    source="core_loop",
    payload={"core_loop_invoked": True, "core_entrypoint": "core.chat", ...},
)
route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
route(tool_request_dispatch)
```

## L3 Evidence Chain

```
loop.turn_end
  → _try_phase1_turn_end_runtime_action()
    → dispatcher.route_from_runtime_loop()
      → ToolGateHandler.handle()
        → action_type == "tool.request" and not tool_name → early-return
        → context.invoke_registered_target("ToolRegistry", "lookup_and_risk_check")
        → context.failed(observed_call=observed)
  → evidence.is_runtime_e2e_evidence() → True
```

## 测试

`tests/runtime_integration/test_tool_request_l3.py` — 3 个测试：
1. `test_tool_request_dispatched_from_loop_turn_end_is_l3` — 确认 `real_core_loop_runtime_e2e` L3 证据
2. `test_tool_request_l3_status_is_failed_with_empty_tool_name` — 确认 status=failed, no_tool_requested=True
3. `test_tool_request_l3_no_real_api_or_env_access` — 确保无真实 API 调用

## 影响面

- 现有 TOOL_GATE 行为完全不受影响（early-return 仅在 `action_type == "tool.request"` 时触发）
- 11/13 RuntimeActionType 现在有 L3 evidence（仅剩 STREAMING_PROVIDER_CALL 和 STREAMING_EVENT）
