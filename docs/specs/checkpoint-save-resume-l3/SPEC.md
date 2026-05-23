# SPEC: Checkpoint Save/Resume L3

Date: 2026-05-24
Status: active
Parent: [First Agent Subsystem Integration Roadmap](../../plans/first-agent-subsystem-integration-roadmap.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. Branch Point 判断

Checkpoint safe summary 是 turn-end hook 上的 branch behavior。它不引入新的 capability milestone，不新增 Anchor，不新增 branch point。

归属：**已有 turn-end RuntimeAction hook**（`_try_phase1_turn_end_runtime_action` 在 `loop.py:30`）。当前 hook 已 dispatch MEMORY_TURN_END_PROPOSAL 和 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline。CHECKPOINT_SAFE_SUMMARY 是同一 hook 上的第三个 dispatch，遵循完全相同的 pattern。

## B. 当前 Behavior Scope

`agent/runtime_integration/checkpoint_summary.py`:
- `CheckpointSafeSummaryHandler.handle()` 已实现
- 产生 `safe_summary`、`secret_content_detected`、`checkpoint_boundary` 等 evidence
- 通过 `context.invoke_registered_target(target_module="CheckpointSafeSummary", operation="redact")` 调用 catalog-owned adapter

`agent/checkpoint.py`:
- `save_checkpoint(state)` / `load_checkpoint()` / `clear_checkpoint()` 是直接函数调用
- 在 `core.py` 中通过 `from agent.checkpoint import save_checkpoint` 直接调用
- 不经过 dispatcher

`agent/runtime_integration/evidence.py:467-476`:
- `checkpoint.safe_summary` 的 catalog descriptor 已注册
- `CheckpointSafeSummary.redact` adapter 指向 `agent.display_events.mask_user_visible_secrets`

`agent/runtime_integration/phase1_hook.py`:
- `build_phase1_dispatcher()` 注册了 MEMORY + TOOL_GATE/INVOKE/RESULT handler
- **未注册 CheckpointSafeSummaryHandler**

`agent/loop.py`:
- `_try_phase1_turn_end_runtime_action()` dispatch MEMORY_TURN_END_PROPOSAL 和 TOOL_GATE
- **未 dispatch CHECKPOINT_SAFE_SUMMARY**

当前 gap：
1. `CheckpointSafeSummaryHandler` 未在 `build_phase1_dispatcher()` 中注册
2. `_try_phase1_turn_end_runtime_action()` 未 dispatch `CHECKPOINT_SAFE_SUMMARY`

## C. 目标

1. 在 `build_phase1_dispatcher()` 中注册 `CheckpointSafeSummaryHandler`
2. 在 `_try_phase1_turn_end_runtime_action()` 中增加 `CHECKPOINT_SAFE_SUMMARY` dispatch
3. 验证通过 `core.chat()` → `route_from_runtime_loop()` 真实路径获得 L3 evidence
4. 验证 direct dispatcher.route 保持 L2
5. 验证不读 .env / 不调用真实 API

## D. fake/real 边界

- 使用 `FakeProvider`（不调用真实 LLM API）
- 使用 `_PipelineSpy` 包裹 dispatcher
- HOME 指向隔离路径
- 不读取 .env
- 不读取真实 sessions/runs
- 不读取 memory/episodes/*.jsonl

## E. 复用关系

| 模块 | 改动 |
|------|------|
| `agent/runtime_integration/phase1_hook.py` | 注册 CheckpointSafeSummaryHandler |
| `agent/loop.py` | 在 turn-end hook 中 dispatch CHECKPOINT_SAFE_SUMMARY |
| `agent/runtime_integration/checkpoint_summary.py` | 零改动 |
| `agent/runtime_integration/evidence.py` | 零改动 |
| `agent/runtime_integration/dispatcher.py` | 零改动 |
| `agent/runtime_integration/schema.py` | 零改动 |
| `agent/checkpoint.py` | 零改动 |
| `agent/core.py` | 零改动 |

## F. 不做什么

- 不修改 checkpoint schema
- 不修改 save_checkpoint/load_checkpoint/clear_checkpoint 函数
- 不把 save_checkpoint 调用迁移到 dispatcher
- 不新增 RuntimeActionType
- 不新增 Anchor
- 不新增 branch point
- 不新增 runtime flow
- 不实现 checkpoint migration
- 不实现跨版本 schema recovery
- 不实现 UI
- 不实现 remote store
- 不处理真实私人资料

## G. Open Questions

- Checkpoint safe summary handler 当前在 turn-end 产生 evidence 但不实际调用 save_checkpoint。save_checkpoint 仍在 core.py 中直接调用。这是设计选择——handler 证明 checkpoint boundary 被触达，而 save 由 core.py 在正确的时机执行。本轮不做改变。

## H. Review Checklist

- [x] 不需要新增 branch point
- [x] 不需要新增 Anchor
- [x] 不修改 checkpoint schema
- [x] 不涉及真实 API / .env
- [x] scope 收敛到 turn-end hook 上的单一 branch behavior
- [x] handler 和 evidence catalog 已存在，只做 wiring
- [x] 可以进入 TDD
