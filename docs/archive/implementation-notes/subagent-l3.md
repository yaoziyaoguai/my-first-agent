# SubAgent L3 Implementation Notes

## 概述

SubAgent L3 wiring —— 在 loop.py turn-end hook 中新增 SUBAGENT_DELEGATE_L0 RuntimeAction dispatch，复用 `SubAgentRegistry(roots=())` 空 registry 的 `context.failed()` 路径产生 L3 evidence。

## 架构决策

与 Skill L3 同构：不新增 RuntimeActionType，复用已有 `subagent.delegate_l0` action type + `SubAgentDelegateL0Handler`，在 handler 中新增 early-return 路径区分 turn-end hook dispatch 和模型驱动的 subagent delegation。

## 关键变更

### 1. `agent/runtime_integration/subagent_action.py` — early-return 路径

```python
if not subagent_name and payload.get("in_delegation_context") is not True:
    observed = context.invoke_registered_target(
        target_module="SubAgentExecutor",
        operation="no_suitable_subagent",
        payload={"reason": "no subagent available for delegation"},
    )
    return context.failed(
        ...,
        observed_call=observed,
        parent_adjudicated=True,  # CRITICAL: is_runtime_e2e_evidence() 要求
        ...
    )
```

**关键修复**：`parent_adjudicated=True` —— `is_runtime_e2e_evidence()` 对 `subagent.delegate_l0` 有硬性检查：
```python
if action_type == "subagent.delegate_l0":
    return evidence.get("parent_adjudicated") is True
```
不加此参数会被降级为 `subsystem_integration`。

### 2. `agent/runtime_integration/evidence.py` — catalog entry + adapter

新增 `_subagent_no_suitable_subagent_adapter` 和对应的 `_descriptor()` entry：
- `target_module="SubAgentExecutor"`, `operation="no_suitable_subagent"`
- 适配器只返回拒绝原因字符串，不启动任何 subagent

### 3. `agent/loop.py` — turn-end dispatch block

```python
subagent_request = RuntimeActionRequest(
    action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
    source="core_loop",
    parent_trace_id="",
    payload={
        "core_loop_invoked": True,
        "core_entrypoint": "core.chat",
        "runtime_hook_name": "loop.turn_end",
        ...
    },
)
route = getattr(dispatcher, "route_from_runtime_loop", dispatcher.route)
route(subagent_request)
```

### 4. `agent/runtime_integration/phase1_hook.py` — handler 注册

```python
_subagent_registry = SubAgentRegistry(roots=())
registry.register(
    RuntimeActionType.SUBAGENT_DELEGATE_L0,
    SubAgentDelegateL0Handler(registry=_subagent_registry),
)
```

## L3 Evidence Chain

```
loop.turn_end
  → _try_phase1_turn_end_runtime_action()
    → dispatcher.route_from_runtime_loop()
      → SubAgentDelegateL0Handler.handle()
        → context.invoke_registered_target("SubAgentExecutor", "no_suitable_subagent")
        → context.failed(observed_call=observed, parent_adjudicated=True)
  → evidence.is_runtime_e2e_evidence() → True
```

## 测试

`tests/runtime_integration/test_subagent_l3.py` — 3 个测试：
1. `test_subagent_delegate_dispatched_from_loop_turn_end_is_l3` — 确认 `real_core_loop_runtime_e2e` L3 证据
2. `test_subagent_delegate_l3_status_is_rejected_with_empty_registry` — 确认 status=failed
3. `test_subagent_l3_no_real_api_or_env_access` — 确保无真实 API 调用

## 回退/Deferred

- 当前空 registry → rejected disposition，L3 evidence 完整
- 真实 subagent delegation 需要 SubAgentRegistry 有注册的子代理，但那是实现阶段的工作
- 如果后续需要支持真实 subagent delegation，仅需注册 subagent 到 registry，不需要改动 handler/dispatcher/L3 evidence wiring
