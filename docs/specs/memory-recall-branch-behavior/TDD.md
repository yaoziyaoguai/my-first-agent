# Memory Recall Branch Behavior TDD / Test Plan

Status: draft
Date: 2026-05-23
Parent: docs/specs/memory-recall-branch-behavior/SPEC.md

## Test Strategy

测试分为两层：
- **L1 subsystem_integration**: direct handler 调用，验证 MemoryRecallHandler 正确性
- **L2 harness_runtime_e2e**: dispatcher.route() 调用，验证 catalog + handler + evidence 全链路

L3 real_core_loop_runtime_e2e 本轮 deferred（需 core_entrypoint 接入）。

## Test File

`tests/runtime_integration/test_memory_recall_branch_behavior.py`

## Phase A: Recall Happy Path（store 有已批准 memory）

### A1: recall with approved records injects snapshot into prompt

- **purpose**: 验证 store 中有 approved memory 时，recall handler 能生成 snapshot 并返回 prompt section
- **setup**: InMemoryMemoryStore + 3 条 approved MemoryRecord（不同 scope）
- **action**: dispatch MEMORY_RECALL via dispatcher.route()
- **expected evidence**:
  - action_type = MEMORY_RECALL
  - disposition = "recalled"
  - snapshot_item_count >= 1
  - prompt_section 非空且包含 memory content
  - target_module_proof 存在
- **forbidden**: 不修改 store、不调用外部 API、不读取文件
- **pass/fail**: result.ok is True, snapshot_item_count > 0, "--- Memory ---" in prompt_section

### A2: recall respects snapshot budget (max 5 items)

- **purpose**: 验证 snapshot budget enforcement — 超过 5 条 non-procedural 时截断
- **setup**: InMemoryMemoryStore + 8 条 approved MemoryRecord
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: snapshot_item_count <= 5, omitted_count >= 3
- **pass/fail**: snapshot_item_count <= 5, omitted_count > 0

### A3: recall filters HIGH sensitivity records

- **purpose**: 验证 HIGH/SECRET sensitivity 记录被过滤，不在 prompt 中泄漏
- **setup**: InMemoryMemoryStore + 2 条 approved LOW + 1 条 approved HIGH（sensitive_redacted=True）
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: snapshot_item_count = 2, HIGH 记录不在 prompt_section 中
- **pass/fail**: snapshot_item_count = 2, "[已过滤敏感记忆]" not in prompt_section for LOW records

## Phase B: Empty Store / No Memory

### B1: recall with empty store returns empty snapshot

- **purpose**: 验证 store 为空时 recall 不崩溃，返回空 snapshot placeholder
- **setup**: 空 InMemoryMemoryStore
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: disposition = "no_memory", snapshot_item_count = 0, prompt_section 包含空占位
- **pass/fail**: result.ok is True, "当前未注入长期记忆" in prompt_section

### B2: recall with only rejected/blocked records

- **purpose**: 验证 store 中只有非 approved 记录时，recall 正确返回空
- **setup**: InMemoryMemoryStore + 2 条 rejected MemoryRecord
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: snapshot_item_count = 0
- **pass/fail**: snapshot_item_count = 0

## Phase C: No Side Effects

### C1: recall does not modify store

- **purpose**: 验证 recall 是纯读取操作，不产生 store 写入
- **setup**: InMemoryMemoryStore + 3 条 approved MemoryRecord，记录 pre 状态
- **action**: dispatch MEMORY_RECALL，对比 store 前后状态
- **expected evidence**: store record count / content 不变
- **pass/fail**: pre_record_count == post_record_count, 每条 record 内容一致

### C2: recall does not trigger MEMORY_PROPOSE or MEMORY_TURN_END_PROPOSAL

- **purpose**: 验证 recall handler 不触发其他 memory action
- **setup**: InMemoryMemoryStore + 3 条 approved MemoryRecord，action_log spy
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: action_log 只有 MEMORY_RECALL，无 PROPOSE
- **pass/fail**: only MEMORY_RECALL in action_log action_types

### C3: recall does not trigger consolidation or emergence

- **purpose**: 验证 recall 不触发 background consolidation / emergence pipeline
- **setup**: InMemoryMemoryStore + 3 条 records，spy on consolidation/emergence hooks
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: 无 consolidation/emergence 调用
- **pass/fail**: consolidation hook not called, emergence hook not called

### C4: recall does not read filesystem or call external API

- **purpose**: 验证 recall 是纯内存/内部操作
- **setup**: FilesystemMemoryStore with base_dir，确保目录中无文件
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: external_side_effects = False（如果 FilesystemMemoryStore 标记了 external_side_effects，则此测试需调整）
- **pass/fail**: 无文件读取、无 HTTP 调用

## Phase D: Evidence Classification

### D1: dispatcher.route() produces harness_runtime_e2e evidence

- **purpose**: 验证通过 dispatcher 调用时 evidence 分类正确
- **setup**: InMemoryMemoryStore + 1 条 approved MemoryRecord
- **action**: dispatcher.route(MEMORY_RECALL)
- **expected evidence**:
  - target_module_proof 存在
  - handler_identity = "MemoryRecallHandler"
  - target_module = "MemoryStore" 或 "MemoryRuntime"
- **pass/fail**: evidence.classification_level == "harness_runtime_e2e"

### D2: direct handler call produces subsystem_integration evidence

- **purpose**: 验证 direct handler 调用时 evidence 降级
- **setup**: InMemoryMemoryStore + 1 条 approved MemoryRecord
- **action**: MemoryRecallHandler(store).handle(request, context)
- **expected evidence**: 无 dispatcher_origin, 无 target_module_proof
- **pass/fail**: evidence 分类为 subsystem_integration 或更低

## Phase E: Regression Isolation

### E1: existing MEMORY_PROPOSE tests unaffected

- **purpose**: 验证 recall handler 注册不影响已有 MEMORY_PROPOSE 测试
- **setup**: 运行 test_memory_retain_branch_behavior.py
- **action**: 全量运行
- **expected**: 34 passed, 1 skipped（C3 deferred 不变）
- **pass/fail**: 34 passed

### E2: existing TOOL_GATE tests unaffected

- **purpose**: 验证 recall handler 不影响 tool gate 行为
- **setup**: 运行 tool confirmation 相关测试
- **action**: 全量运行
- **expected**: 全部通过
- **pass/fail**: all pass

## Phase F: Negative Tests

### F1: recall with invalid store reference

- **purpose**: 验证 handler 对无效 store 的防御
- **setup**: store=None
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: disposition = "error" 或 "no_memory"
- **pass/fail**: 不抛异常，graceful degradation

### F2: recall with corrupted record

- **purpose**: 验证 handler 对 corrupt record 的防御（缺失 content 字段等）
- **setup**: InMemoryMemoryStore + 1 条正常 + 1 条异常 record（content=""）
- **action**: dispatch MEMORY_RECALL
- **expected evidence**: 正常 record 仍被注入，异常 record 被过滤
- **pass/fail**: snapshot_item_count >= 1, 无 crash

## Deferred

- L3 `real_core_loop_runtime_e2e`：需 core_entrypoint 接入 dispatcher.route()
- recall with FilesystemMemoryStore persisted records 跨 session 测试
- recall budget tuning（rendered_char_budget = 500 的边界测试）
- recall performance（1000+ records 的 snapshot generation 延迟）
