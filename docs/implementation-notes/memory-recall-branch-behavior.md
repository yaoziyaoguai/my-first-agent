# Implementation Notes: Memory Recall Branch Behavior

Date: 2026-05-23
Plan: [IMPLEMENTATION_PLAN.md](../specs/memory-recall-branch-behavior/IMPLEMENTATION_PLAN.md)
SPEC: [SPEC.md](../specs/memory-recall-branch-behavior/SPEC.md)
TDD: [TDD.md](../specs/memory-recall-branch-behavior/TDD.md)

## 实现了什么

- **MEMORY_RECALL RuntimeActionType** (`agent/runtime_integration/schema.py`): 新增 `memory.recall` action type，
  与 MEMORY_TURN_END_PROPOSAL 和 MEMORY_PROPOSE 并列
- **MemoryRecallHandler** (`agent/runtime_integration/memory_recall.py`): pre-loop memory recall handler。
  从 store 读取已批准/auto_retained records → 通过 catalog adapter (MemoryRuntime.build_memory_snapshot)
  生成 governed MemorySnapshot → build_memory_section 渲染 prompt section → 返回 disposition + prompt_section。
  纯读取操作，不写 store、不触发 proposal/consolidation/emergence/proactive_reminder。
- **catalog descriptor** (`agent/runtime_integration/evidence.py`): 新增 `_memory_recall_snapshot_adapter`
  和 `memory.recall` descriptor，handler 通过 `context.invoke_registered_target()` 获取
  trusted target_module_proof
- **dispatcher 注册** (`agent/runtime_integration/phase1_hook.py`): `build_phase1_dispatcher()` 中
  注册 `MEMORY_RECALL → MemoryRecallHandler`
- **snapshot generator 加固** (`agent/memory_snapshot_generator.py`):
  - `status_omitted`: 排除 non-persistent records (rejected/session_only)
  - 空 content 防御: 空 content record 不进 snapshot (MemorySnapshotItem 拒绝空 content)
  - `_safety_filter_summary` 包含 status_omitted
- **15 个测试** (Phase A-F): `tests/runtime_integration/test_memory_recall_branch_behavior.py`
  - L1 (subsystem_integration): direct handler
  - L2 (harness_runtime_e2e): dispatcher.route() with target_module_proof

## 没做什么

- core.py integration (dispatcher 在 recall 点之后构建, real_core_loop_runtime_e2e deferred)
- L3 real_core_loop_runtime_e2e 测试
- FilesystemMemoryStore 跨 session recall
- recall budget tuning / performance (1000+ records)
- Background consolidation / emergence detection
- Proactive reminder
- Memory delete/update/review UI
- Vector/RAG/semantic retrieval
- Tool/MCP/Skill/Checkpoint 修改 (beyond necessary dispatcher registration)
- 真实 API / .env / memory episodes 读取

## Plan 未覆盖但执行中做出的决策

### D1. status_omitted 过滤

IMPLEMENTATION_PLAN 预期 `build_memory_snapshot_from_store` 的 filter 规则不修改，
但测试发现 snapshot generator 不过滤 rejected records——这些 records 会泄漏进 prompt。
新增 `status_omitted` 计数器和 `approval_status not in ("approved", "auto_retained")`
过滤，这是 recall 语义的正确实现而非规则变更。

### D2. 空 content 防御

`MemoryRecord` 和 `MemorySnapshotItem` 均拒绝空 content。在 snapshot generator 的
item 构建前新增 `content.strip()` 检查，避免 corrupt record 导致 handler crash。

### D3. 测试 ID 冲突

`derive_memory_record_id(source_summary)` 是确定性的——相同 source_summary 产生相同 ID。
`_make_approved_record` 工厂最初对所有 record 使用 `source_summary="test_factory:auto"`，
导致所有 record ID 相同。修复为 `uuid.uuid4().hex[:12]` 确保唯一性。
