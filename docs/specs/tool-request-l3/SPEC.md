# TOOL_REQUEST L3 Architecture Decision

## Architecture Decision

TOOL_REQUEST RuntimeActionType 的 L3 evidence wiring 复用现有 turn-end hook branch point，遵循与 Skill L3 / SubAgent L3 完全同构的 Architecture Extension Loop 模式。

## 动机

- `RuntimeActionType.TOOL_REQUEST` ("tool.request") 已在 schema 中定义，evidence catalog 中已有两个 descriptor entry（`ToolRegistry.lookup_and_risk_check` 和 `DogfoodFakeToolOverlay.block`）
- `ToolGateHandler` 已实现完整的 tool.request payload 处理逻辑
- 但 TOOL_REQUEST 未在 `phase1_hook.py` 中注册 handler，也未在 `loop.py` turn-end hook 中 dispatch
- 这导致 13 个 RuntimeActionType 中只有 10 个有 L3 evidence（完成本项后为 11 个）

## 为什么现有 branch point 可以承载

TOOL_REQUEST 不需要新的 dispatch timing（如 streaming 需要 mid-model-call dispatch）。它可以像其他 10 个 RuntimeActionType 一样通过 turn-end hook dispatch：

```
loop.turn_end
  → _try_phase1_turn_end_runtime_action()
    → dispatcher.route_from_runtime_loop()
      → ToolGateHandler.handle()
        → context.invoke_registered_target("ToolRegistry", "lookup_and_risk_check")
        → context.failed(observed_call=observed)
  → evidence.is_runtime_e2e_evidence() → True
```

## 为什么它有限、稳定、必要

- **有限**：仅新增 ~30 行 handler early-return 路径 + 标准 dispatch block + 注册行
- **稳定**：不改变 ToolGateHandler 现有 tool.gate 处理逻辑；early-return 仅当 `action_type == "tool.request" and not tool_name` 时触发
- **必要**：完成 evidence catalog 覆盖，13 个 RuntimeActionType 中 11 个有 L3 evidence

## 它在统一主流程中的位置

turn-end hook（与 TOOL_GATE, TOOL_INVOKE, TOOL_RESULT 等处于同一 dispatch phase）

## L1/L2/L3 evidence plan

- **L1**：ToolGateHandler 响应 tool.request action type 并返回正确 disposition
- **L2**：Handler 通过 `invoke_registered_target()` 调用 catalog adapter，生成 `target_module_proof`
- **L3**：`route_from_runtime_loop()` → `dispatcher_origin="runtime_loop"` → `real_core_loop_runtime_e2e`

## Fake/real boundary

- Fake-first：turn-end hook dispatch 使用空 tool_name
- Handler early-return 调用 `invoke_registered_target(operation="lookup_and_risk_check")` 查找空 tool_name → 返回 None → failed disposition
- 不执行真实工具，不读取真实 registry entry
- 证据链完整

## Stop conditions

无 — 纯增量变更，不影响现有 tool.gate 行为。

## Rollback/deferred plan

如需回退：删除 loop.py 中的 dispatch block、phase1_hook.py 中的注册行、handler 中的 early-return 路径即可。
不影响任何其他 RuntimeActionType。
