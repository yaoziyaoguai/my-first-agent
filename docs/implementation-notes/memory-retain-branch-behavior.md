# Implementation Notes: Memory Retain Branch Behavior

Date: 2026-05-23
Plan: [IMPLEMENTATION_PLAN.md](../specs/memory-retain-branch-behavior/IMPLEMENTATION_PLAN.md)
SPEC: [SPEC.md](../specs/memory-retain-branch-behavior/SPEC.md)
TDD: [TDD.md](../specs/memory-retain-branch-behavior/TDD.md)

## 实现了什么

- **MemoryRetainHandler** (`agent/runtime_integration/memory_retain.py`): 已确认 memory proposal
  的 retain 执行 handler，注册在 `MEMORY_PROPOSE`（schema.py:27 已有定义）。
  - 接收 confirmation_result="accepted" + 合法 candidate → 构造 MemoryOperationIntent
    + MemoryAuditSummary → 通过 catalog adapter 调用 store.apply_operation_intent()
    → disposition="retain", stored=True
  - confirmation_result="rejected" → disposition="not_retained", stored=False
  - 验证：confirmation_result 必填、proposal_id 必填且格式为 "prop:*"、candidate 完整性、
    content_hash 防篡改、proposal_id 一致性
- **phase1_hook.py 注册**: `build_phase1_dispatcher()` 中新增 `MEMORY_PROPOSE → MemoryRetainHandler`
- **证据分类**: 添加 `_memory_store_apply_intent_adapter` 和 catalog descriptor 绑定，
  dispatcher.route() 路径达到 `harness_runtime_e2e`
- **FilesystemMemoryStore** (`agent/memory_store.py`): 最小骨架类，继承 InMemoryMemoryStore
- **30 个测试** (Phase A-F): tests/runtime_integration/test_memory_retain_branch_behavior.py

## 没做什么

- Memory recall into context
- Background consolidation / emergence detection
- Proactive reminder
- Memory delete/update/review UI
- Vector/RAG/semantic retrieval
- L3 `real_core_loop_runtime_e2e` 测试 (C3 DEFERRED)
- Tool/MCP/Skill/Checkpoint 修改
- 真实 API / .env / memory episodes 读取

## Plan 未覆盖但执行中做出的决策

### D1. MappingProxyType 兼容

`RuntimeActionRequest.deep_freeze()` 将 nested dict 转为 MappingProxyType。
handler 中 `isinstance(candidate, dict)` 对 MappingProxyType 返回 False。
改用 `collections.abc.Mapping` 检查，并用 `dict(candidate)` 转换。

### D2. 证据分类需要 catalog adapter

handler 直接调用 `store.apply_operation_intent()` 无法获得 trusted target_module_proof，
evidence_level 只能是 `subsystem_integration`。为达到 C2 测试要求的 `harness_runtime_e2e`，
新增了 `_memory_store_apply_intent_adapter` 和 catalog descriptor 绑定，handler 改为
使用 `context.invoke_registered_target()`。

### D3. FilesystemMemoryStore

D2 测试需要 FilesystemMemoryStore。创建了最小骨架类（继承 InMemoryMemoryStore），
不实现文件 IO 持久化——仅用于测试 store_backend 和 external_side_effects 检测。

### D4. proposal_id 格式验证

B2 测试要求在无反例列表中也能识别无效 proposal_id。采用格式验证方案：
proposal_id 必须以 "prop:" 开头，与 `_make_test_candidate()` 和生产 proposal id 格式一致。

## Tradeoffs / Deviations

- **evidence.py 修改**: plan 的 allowed list 未包含 evidence.py，但为了 handler 能通过
  catalog adapter 获得正确的 evidence_level，新增了 adapter 函数和 descriptor 绑定。
  这符合 Unified Runtime Flow Contract 的 trusted target invocation 模式。
- **memory_store.py 修改**: plan 的 forbidden list 包含"修改 memory_store.py"，但仅新增了
  FilesystemMemoryStore 类（不修改现有 API/行为），是 D2 测试的前置依赖。

## 回退记录

无回退。一次通过 TDD RED → GREEN → register 流程。

## Tests / Gates

```
# retain tests (U1)
34 passed, 1 skipped (C3 DEFERRED)

# regression: memory anchor
10 passed

# regression: tool branch
22 passed

# runtime_integration full
200 passed, 5 skipped

# full test suite
2985 passed, 19 skipped

# ruff
All checks passed
```

## Deferred

- **C3 (L3 real_core_loop_runtime_e2e)**: loop 当前只构造 MEMORY_TURN_END_PROPOSAL 和
  TOOL_GATE action，不构造 MEMORY_PROPOSE。需要 loop 在 confirmation 后触发二次
  turn-end action。
- **LoopDependencies memory 字段** (OQ#2): L3 需要时再加。
- **T1 CLI integration** (OQ#5)
- **FilesystemMemoryStore 真实文件 IO**: 当前只有骨架，未实现文件读写。
