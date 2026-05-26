# Memory Consolidation L3 SPEC

Status: draft
Date: 2026-05-24
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 1. Branch Point 判断

**Is this a new capability milestone?** No — consolidation pipeline (L1/L2) 已存在。

**Is this an Architecture Extension?** Yes — 需要在 turn-end hook 注册新的
RuntimeActionType + handler + catalog entry。

**为什么现有 branch point 不能承载：**

| 现有 branch point | 语义 | 为何不能承载 consolidation |
|---|---|---|
| `memory.turn_end_proposal` | 从当前 turn 内容判定是否提议保留 | consolidation 操作的是**跨 turn 的累积 episodic**，不是当前 turn |
| `memory.propose` | 执行已确认 proposal 的 retain 写入 | consolidation 是读操作（生成 candidates），不写 store |
| `memory.recall` | 从 store 读取并注入 context | consolidation 不注入 context，它产生 consolidation candidates |

Consolidation 的独特语义：**批量分析跨回合的 episodic 记录 → 生成 semantic candidates**。
这不属于 retain/recall/propose 中任何一个。

**新 branch point 挂载位置：**
Turn-end hook (`_try_phase1_turn_end_runtime_action`) 中，在 MEMORY_RECALL 之后
（recall 之后 store 状态最完整，consolidation 读到的 evidence 最全）。

## 2. Architecture Extension 评估

### 2.1 有限稳定
- 新 RuntimeActionType: `MEMORY_CONSOLIDATE = "memory.consolidate"`（仅 1 个）
- 新 handler: `MemoryConsolidateHandler`（仅 1 个 class）
- 新 catalog target: `MemoryConsolidation`（仅 1 个）

### 2.2 可测试
- L1: handler 单元测试，验证 consolidation pipeline 调用和 evidence 结构
- L2: dispatcher route 测试，验证 catalog target proof
- L3: core.chat() 测试，验证 turn-end consolidation 触发和 evidence 分类

### 2.3 可审计
- Handler 只读 store（list_records），不写 store
- 使用 FakeLLMConsolidationContentGenerator（deterministic）
- 所有 evidence 通过 dispatcher → classifier 标准路径

### 2.4 不改变项目方向
- 仍在统一主流程上
- 不新增 Anchor
- 不新增第二条主流程

## 3. Behavior Scope

### 3.1 Consolidation 触发

Turn-end hook 在每次 turn 结束时触发 consolidation。Handler 内部由
consolidation policy/engine 决定是否实际运行 pipeline（例如，只有 episodic
数量 ≥ 3 时才产出 candidates）。

### 3.2 Handler 行为

`MemoryConsolidateHandler.handle(request, context)`:

1. 从 store 读取 episodic records（list_records, scope="episodic"）
2. 转换为 EpisodicEvidence 列表
3. 运行 `run_consolidation_pipeline(store_root, llm_generator=None)`
4. 返回:
   - `disposition="consolidated"` — 产生了 candidates
   - `disposition="no_candidates"` — pipeline 运行但无 candidates
   - `disposition="insufficient_evidence"` — episodic 不足 N≥3，跳过
5. evidence 包含: candidates_count, skipped_count, warnings, operation_types

### 3.3 只读约束

Consolidation handler **不写入** store。它只生成 candidates 作为 evidence。
Candidates 的 adopt 仍需要通过 T1 review（RFC §6.4），不在本 handler 范围内。

### 3.4 Fake provider 支持

使用 `FakeLLMConsolidationContentGenerator` 替代真实 LLM，保证 deterministic
输出。L3 测试不依赖真实 LLM。

## 4. Evidence Plan

### L1 — Handler unit tests
- `test_consolidate_handler_insufficient_evidence` — episodic < 3 条，返回 insufficient_evidence
- `test_consolidate_handler_produces_candidates` — 足够 evidence，返回 consolidated
- `test_consolidate_handler_readonly` — handler 不修改 store

### L2 — Dispatcher integration tests
- `test_consolidate_route_through_dispatcher` — 通过 dispatcher.route() 调用，验证 evidence 结构
- `test_consolidate_catalog_target_proof` — 验证 catalog target identity

### L3 — core.chat() tests
- `test_consolidation_triggers_at_turn_end` — turn-end hook 触发 consolidation
- `test_consolidation_evidence_level` — evidence 达到 harness_runtime_e2e

### Overclaim prevention
- ForgedTargetLabel + CatalogAllowedForgedCallable for `MemoryConsolidation`
- 更新 `_OVERCLAIM_COVERED_TARGETS`

## 5. Stop Conditions

- consolidation runtime trigger 语义不明确 → deferred
- 需要真实 LLM → deferred
- 改变 store 写入行为 → out of scope

## 6. Rollback Plan

如果 consolidation integration 设计有问题:
1. 从 phase1_hook 取消注册
2. 保留 handler 和 tests（L1/L2 仍然有价值）
3. RuntimeActionType 保留在 schema 中（不破坏向后兼容）
