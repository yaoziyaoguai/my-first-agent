# Memory Recall Branch Behavior — Implementation Plan

Status: draft
Date: 2026-05-23
Parent: docs/specs/memory-recall-branch-behavior/SPEC.md
Tests: docs/specs/memory-recall-branch-behavior/TDD.md

## Problem Frame

当前 `core.py:refresh_runtime_system_prompt()` 直接调用 `_memory_runtime.snapshot_for_prompt()` → `build_system_prompt()` 完成 memory→prompt 注入，绕过了 RuntimeActionDispatcher → handler → evidence 管道。本轮将此行为正式化为 MEMORY_RECALL RuntimeAction，不改功能语义。

## Scope Boundary

**In scope:**
- `RuntimeActionType.MEMORY_RECALL` action type
- `MemoryRecallHandler` — 读 store → 生成 snapshot → 渲染 prompt section
- Catalog descriptor + dispatcher registration
- 测试文件（harness_runtime_e2e 级别）

**Out of scope (deferred):**
- core.py 生产路径改为 dispatcher.route()（需 real_core_loop_runtime_e2e 支持）
- L3 real_core_loop_runtime_e2e 测试
- FilesystemMemoryStore 跨 session recall
- recall budget tuning

## Branch Point Judgment

归属 Contract Section 2 **"pre-loop explicit Memory evaluation"**。不是新 Anchor / runtime flow / branch point。

## Key Decisions

### D1: MEMORY_RECALL action type 命名

`RuntimeActionType.MEMORY_RECALL = "memory.recall"`，与现有 `memory.turn_end_proposal` / `memory.propose` 命名空间一致。

### D2: handler 通过 context.invoke_registered_target() 获取 proof

handler 调用 `context.invoke_registered_target(target_module="MemoryRuntime", operation="build_memory_snapshot", payload={...})` 走 catalog adapter，获取 trusted `target_module_proof`。这是 harness_runtime_e2e 的必要条件。

### D3: catalog adapter 包装 build_memory_snapshot_from_store()

adapter 接收 `{"store": store, "options": options_dict}`，调用 `build_memory_snapshot_from_store(store, MemorySnapshotBuildOptions(**options_dict))`。store 来自 handler 构造参数，options 由 handler 内部构造。

### D4: handler 构造参数与 MemoryRetainHandler 一致

`MemoryRecallHandler(*, store: InMemoryMemoryStore | None = None)`，默认 InMemoryMemoryStore()。

### D5: snapshot options 使用 SPEC 约定的默认值

`selection_reason="Memory Kernel v1 recall"`, `max_items=5`, `rendered_char_budget=500`，与当前 `MemoryRuntime.snapshot_for_prompt()` 默认值一致。

### D6: prompt section 渲染复用 build_memory_section()

handler 拿到 MemorySnapshot 后调用 `build_memory_section(snapshot)` 渲染为 prompt 文本。handler 不自己拼 prompt 字符串。

### D7: core.py 暂不修改

本轮只做 handler + catalog + dispatcher + 测试。core.py 中的 `refresh_runtime_system_prompt()` 保持不变。`real_core_loop_runtime_e2e`（从 runtime loop 触发 dispatcher.route()）deferred。

## Implementation Units

### U1: RuntimeActionType.MEMORY_RECALL → schema.py

**Files:**
- Modify: `agent/runtime_integration/schema.py:32`（在 RuntimeActionType enum 中添加一行）

**Goal:** 在 RuntimeActionType 枚举中新增 `MEMORY_RECALL = "memory.recall"`。

**Patterns to follow:** 与其他 action type 一致的 StrEnum 命名和值格式。

### U2: MemoryRecallHandler → memory_recall.py（新建）

**Files:**
- Create: `agent/runtime_integration/memory_recall.py`

**Goal:** 实现 MemoryRecallHandler，读 store → 生成 snapshot → 渲染 prompt section → 通过 context.invoke_registered_target() 获取 target_module_proof → 返回 evidence。

**Approach:**
1. 构造函数接收 `store` 参数（默认 InMemoryMemoryStore）
2. `handle(request, context)`:
   a. 从 self._store.list_records() 获取 records
   b. 构造 MemorySnapshotBuildOptions
   c. 调用 `context.invoke_registered_target(target_module="MemoryRuntime", operation="build_memory_snapshot", payload={"store": self._store, "options": {...}})` 获取 ObservedModuleCall
   d. 从 observed_call.value 获取 MemorySnapshot
   e. 调用 `build_memory_section(snapshot)` 渲染 prompt section
   f. 返回 `context.success(handler_name=..., target_module="MemoryRuntime", payload={...}, observed_call=observed_call, evidence_extra={...})`

**Patterns to follow:** `agent/runtime_integration/memory_retain.py:MemoryRetainHandler`

### U3: Catalog descriptor + dispatcher registration → evidence.py + phase1_hook.py

**Files:**
- Modify: `agent/runtime_integration/evidence.py`（新增 catalog descriptor + adapter）
- Modify: `agent/runtime_integration/phase1_hook.py`（注册 MEMORY_RECALL handler）

**Goal:**
- 编写 `_memory_recall_snapshot_adapter` 函数
- 在 `RuntimeActionTargetCatalog._bindings` 中新增 descriptor
- 在 `build_phase1_dispatcher()` 中注册 MEMORY_RECALL → MemoryRecallHandler

**Patterns to follow:**
- adapter: `_memory_store_apply_intent_adapter` 模式（payload 校验 + 调用）
- descriptor: `_descriptor("memory.recall", ...)` 模式
- registration: 与 MEMORY_PROPOSE / MEMORY_TURN_END_PROPOSAL 注册并列

### U4: 测试文件 → test_memory_recall_branch_behavior.py（新建）

**Files:**
- Create: `tests/runtime_integration/test_memory_recall_branch_behavior.py`

**Goal:** 按 TDD.md 实现 Phase A-F 测试。

**Test phases:**
- Phase A: Recall Happy Path (A1-A3)
- Phase B: Empty Store / No Memory (B1-B2)
- Phase C: No Side Effects (C1-C4)
- Phase D: Evidence Classification (D1-D2)
- Phase E: Regression Isolation (E1-E2)
- Phase F: Negative Tests (F1-F2)

**Patterns to follow:** `tests/runtime_integration/test_memory_retain_branch_behavior.py`

## Sequencing

U1 → U2 → U3 → U4（严格顺序，每步依赖前一步）

U1-U3 实现 handler 基础设施，U4 写测试并验证。

## Stop Conditions

- 需要新增 branch point → 停止
- 需要真实 API / .env → 停止
- 需要真实 memory episodes → 停止
- 发现 SPEC 错 → 回 SPEC
- 发现 TDD 错 → 回 TDD
- 同一问题最多 2 次 focused fix；第 2 次仍失败 → 停止

## Allowed Modifications

- `agent/runtime_integration/schema.py` — 新增 MEMORY_RECALL
- `agent/runtime_integration/memory_recall.py` — 新建 handler
- `agent/runtime_integration/evidence.py` — 新增 adapter + descriptor
- `agent/runtime_integration/phase1_hook.py` — 注册 handler
- `tests/runtime_integration/test_memory_recall_branch_behavior.py` — 新建测试

## Forbidden Modifications

- Tool/MCP/Skill/Checkpoint
- memory store 写入语义
- snapshot budget/filter 规则
- loop.py run_main_loop 核心 orchestration
- core.py 生产路径（本轮 deferred）

## Regression Risk

- 在 phase1_hook.py 中新增 handler 注册不影响已有 MEMORY_PROPOSE / MEMORY_TURN_END_PROPOSAL / TOOL_GATE
- 新增 schema 枚举值不改变已有 action type 行为
- 新增 catalog descriptor 不改变已有 descriptor 解析

## Review Checklist

- [ ] MEMORY_RECALL 归属 pre-loop explicit Memory evaluation
- [ ] 不新增 branch point / Anchor / runtime flow
- [ ] handler 通过 context.invoke_registered_target() 获取 proof
- [ ] catalog descriptor 正确绑定 action_type + handler + target_module + adapter
- [ ] fake/real 只有 store adapter 差异
- [ ] 测试覆盖 happy path / empty store / no side effects / evidence classification / negative tests
- [ ] 不修改 Tool/MCP/Skill/Checkpoint
- [ ] 不读取真实数据 / .env / API
