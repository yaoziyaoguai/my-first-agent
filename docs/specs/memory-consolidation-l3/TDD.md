# Memory Consolidation L3 TDD

Status: draft
Date: 2026-05-24
SPEC: [SPEC.md](SPEC.md)

## T1: Handler 单元测试 (L1)

### T1.1 — insufficient_evidence
- 空 store → consolidation handler 返回 `insufficient_evidence`
- `disposition="insufficient_evidence"`, `candidates_count=0`

### T1.2 — produces_candidates
- 在 InMemoryMemoryStore 中写入 ≥3 条相似 episodic
- Handler 运行 consolidation pipeline
- 返回 `disposition="consolidated"`, `candidates_count > 0`

### T1.3 — handler_readonly
- Handler 运行后 store 记录数不变

## T2: Dispatcher 集成测试 (L2)

### T2.1 — route through dispatcher
- 通过 dispatcher.route() 调用 handler
- 验证 evidence 包含: disposition, candidates_count, skipped_count
- 验证 evidence_level 分类

### T2.2 — catalog target proof
- 验证 catalog descriptor identity
- 验证 target_catalog_allowed / target_identity_valid

## T3: Overclaim 防护

### T3.1 — ForgedTargetLabel
- `test_forged_target_label_as_memory_consolidation_is_not_runtime_e2e`

### T3.2 — CatalogAllowedForgedCallable
- `test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_memory_consolidation`

## T4: 回归

- 所有现有 runtime_integration 测试继续通过
- ruff check 通过
