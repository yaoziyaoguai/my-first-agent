# MEMORY_PROPOSE L3 Wiring — Implementation Notes

Date: 2026-05-24
SPEC: [docs/specs/memory-propose-l3/SPEC.md](../specs/memory-propose-l3/SPEC.md)
TDD: [docs/specs/memory-propose-l3/TDD.md](../specs/memory-propose-l3/TDD.md)

## 架构决策

Normal Capability Loop — 复用已有 turn-end hook branch point，不断增 RuntimeActionType。

MEMORY_PROPOSE 是 retain execution 的正式路径：已确认的 proposal 在 `state.task.pending_retain_proposals` 中排队，turn-end hook 中 dispatch MEMORY_PROPOSE → MemoryRetainHandler → store.write()。

## 变更文件

### `agent/state.py`

- 新增 `TaskState.pending_retain_proposals: list[dict[str, Any]]` 字段
- `reset_task()` 不再清空 `pending_retain_proposals`——它是跨 turn 的确认 memory proposal 队列，由 turn-end hook 消费后清空

### `agent/memory_interaction.py`

- `handle_inline_confirmation_reply` 中 accept/edit_accept 路径改为入队 `pending_retain_proposals`，不再直接调用 `apply_inline_confirmation_response`
- 新增 `_now_iso()` helper

### `agent/loop.py`

- 在 turn-end hook 中 MEMORY_TURN_END_PROPOSAL 之后、TOOL_GATE 之前，新增 MEMORY_PROPOSE dispatch block
- 独立 try/except——失败不阻断 TOOL_GATE

## 数据流

```
用户确认 (accept/edit_accept)
  → handle_inline_confirmation_reply()
  → state.task.pending_retain_proposals.append(confirmed_proposal)
  → 下一轮 chat() → turn-end hook
  → 遍历 pending_retain_proposals
  → 构造 RuntimeActionRequest(MEMORY_PROPOSE)
  → dispatcher.route_from_runtime_loop()
  → MemoryRetainHandler
  → store.write()
  → pending_retain_proposals.clear()
```

## 测试

`tests/runtime_integration/test_memory_propose_l3.py` — 4 个 L3 测试：

- T1: turn-end hook dispatch MEMORY_PROPOSE，验证 evidence chain（L3 + route_from_runtime_loop + stored=True）
- T2: 空队列不 dispatch
- T3: rejected confirmation → dispatched but not_retained, stored=False
- T4: FakeProvider only，无真实 API

## 关键发现

`reset_task()` 最初清空了 `pending_retain_proposals`，导致 `chat()` 在 `status != "running"` 且无 plan 时调用 `reset_task()` 清空队列，turn-end hook 永远看不到排队的 proposal。修复：`pending_retain_proposals` 不在 `reset_task()` 中清空——它是跨 turn 状态，只由 turn-end hook 消费后清空。
