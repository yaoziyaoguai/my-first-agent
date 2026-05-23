# Implementation Plan: Memory Retain Branch Behavior

Status: draft
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
SPEC: [Memory Retain Branch Behavior SPEC](SPEC.md)
TDD: [TDD / Test Plan](TDD.md)

## 1. Problem Frame

让 `memory.turn_end_proposal` branch point 的下游 execution behavior `retain`
可覆盖：已确认的 memory proposal → `disposition="retain"`, `stored=True`,
写入 MemoryStore。

当前 `MemoryTurnEndProposalHandler` 是 stateless proposal generator，返回
`proposed` / `should_not_remember` / `no_action`，不执行 store write。
`MEMORY_PROPOSE`（`schema.py:27`）已定义但无 handler——这是 retain 的自然挂载点。

## 2. Scope Boundary

### 2.1 In Scope

- 为 `MEMORY_PROPOSE` 注册 `MemoryRetainHandler`
- Handler 接收已确认 proposal（`confirmation_result="accepted"`），写入 store
- 正例：`retain` disposition，`stored=True`
- 负例：`not_retained`（用户拒绝）、`rejected`（proposal 无效）
- TDD L1/L2 全部测试实现（Phase A-F，约 30 tests）
- 更新 `phase1_hook.py` 注册新 handler
- Implementation notes

### 2.2 NOT in Scope

- Memory recall into context
- Background consolidation / emergence detection
- Proactive reminder
- Memory delete/update/review UI
- Vector/RAG/semantic retrieval
- T1/T2/T3 governance routing 变更
- UI confirmation interaction
- Real API / .env / memory episodes
- Tool/MCP/Skill/Checkpoint 修改
- L3 `real_core_loop_runtime_e2e` 测试（DEFERRED——需要 loop 在 confirmation 后
  触发二次 turn-end action）
- `LoopDependencies` 新增 memory 字段（OQ#2——L3 需要时再加）

### 2.3 Deferred to Follow-Up Work

- L3 C3 测试：`route_from_runtime_loop` → `real_core_loop_runtime_e2e`
- `LoopDependencies` memory 字段（OQ#2）
- FilesystemMemoryStore 的 `external_side_effects` 验证（D2 测试已覆盖）
- T1 CLI integration（SPEC §8 OQ#5）

## 3. Key Technical Decisions

### Decision 1: SPEC OQ#1 — 采用方案 B（MEMORY_PROPOSE handler）

**采纳方案 B：为 `MEMORY_PROPOSE` 注册新 handler `MemoryRetainHandler`。**

理由：
- `MEMORY_PROPOSE` 已在 `schema.py:27` 定义，无需新增 RuntimeActionType
- `MemoryTurnEndProposalHandler` 保持 stateless proposal generator（不变）
- 关注点分离：proposal generation（evaluation）vs proposal execution（retain）
- 符合 SPEC §1 的判断——`retain` 是 `proposed` 的自然下游，不是新的 evaluation behavior

为什么不选其他方案：
- 方案 A（扩展 MemoryTurnEndProposalHandler）：同一 handler 承担 evaluation 和
  execution 两种职责，打破单一职责
- 方案 C（新增 MEMORY_RETAIN）：`MEMORY_PROPOSE` 语义已足够，新增 type 冗余

### Decision 2: Handler 与 Store 的交互方式

**Handler 构造 `MemoryOperationIntent` + `MemoryAuditSummary`，调用 `store.apply_operation_intent()`。**

`InMemoryMemoryStore.apply_operation_intent()` 已经处理了去重、验证、状态管理
等逻辑。Handler 作为 candidate dict → structured intent 的适配层，不重复实现
store 逻辑。

Store 不新增 `write()` 方法——不修改 `MemoryStoreProtocol` 或 `InMemoryMemoryStore`
（TDD §4 明确规定）。

Handler 构造 intent 的映射：
- `content_summary` ← `candidate["content"]`
- `source_summary` ← `candidate.get("source", "turn_end_proposal")`
- `scope` ← `MemoryScope(candidate.get("scope", "user"))`
- `sensitivity` → `sensitive_redacted`（仅 HIGH/SECRET 为 True）
- `safety_summary` ← `"无额外安全标记"`（测试 candidate 均为 low sensitivity）

### Decision 3: Handler 命名

**`MemoryRetainHandler`** — behavior 名称为 `retain`，TDD 全程使用 "retain handler"。

虽然注册在 `MEMORY_PROPOSE` 下，但 handler 语义是"执行 retain behavior"而非
"propose"。类比：`MemoryTurnEndProposalHandler` 处理 `MEMORY_TURN_END_PROPOSAL`，
但其 behavior 是 `proposed` / `should_not_remember` / `no_action`。

### Decision 4: phase1_hook.py 注册方式

在 `build_phase1_dispatcher()` 中新增一行注册：

```python
registry.register(
    RuntimeActionType.MEMORY_PROPOSE,
    MemoryRetainHandler(),
)
```

与现有 `MEMORY_TURN_END_PROPOSAL` 和 `TOOL_GATE` 注册并列。不修改其他注册逻辑。

## 4. Implementation Units

### U1. Test File — Memory Retain Branch Behavior Tests (L1/L2)

**Goal:** 实现 TDD Phase A-F 全部测试（约 30 tests），先写测试确认 RED。

**Dependencies:** 无（纯测试文件，handler 不存在时测试 FAIL 即为 RED 验证）

**Files:**
- Create: `tests/runtime_integration/test_memory_retain_branch_behavior.py`

**Approach:**
复用 `test_memory_anchor_fake.py` 中的 `_build_phase1_dispatcher()`（已注册
`MemoryTurnEndProposalHandler` + `ToolGateHandler`）和 `_SpyDispatcher` 模式。
本测试文件新增 U1 后，handler 尚未注册 → L1 handler 测试 RED。

实现 TDD §6 的全部测试：

- **Phase A (7 tests):** A1 store write, A2 retrieve from store, A3 metadata
  preservation, A4 no_silent_retain invariant, A5 no recall, A6 no consolidation,
  A7 no implicit generation
- **Phase B (7 tests):** B1 rejected not stored, B2 nonexistent proposal_id,
  B3 tampered content, B4 missing confirmation_result, B5 missing proposal_id,
  B6 store write failure, B7 external_side_effects for InMemory store
- **Phase C (6 tests):** C1 direct handler=subsystem, C2 dispatcher=harness,
  C3 DEFERRED, C4 payload anti-spoofing, C5 direct store.write not E2E,
  C6 direct policy call not E2E
- **Phase D (4 tests):** D1 InMemory same handler, D2 Filesystem
  external_side_effects, D3 no real episodes read, D4 no .env/API needed
- **Phase E (6 tests):** E1-E2 cross-contamination, E3 tool branch regression,
  E4 memory anchor regression, E5-E6 no checkpoint/skill touch
- **Phase F (5 tests):** F1 no recall, F2 no consolidation, F3 no proactive
  reminder, F4 no real PII, F5 no project context

测试辅助工具：
- `_make_test_candidate()` — 构造合法 candidate dict
- `_make_retain_request()` — 构造 MEMORY_PROPOSE RuntimeActionRequest
- `_build_phase1_dispatcher_with_retain_handler()` — 构建含 retain handler 的 dispatcher

**Execution note:** Test-first。先写全部测试 → 确认 L1 handler 测试 RED
（handler 未注册）→ U2/U3 实现后 GREEN。

C3（L3 `real_core_loop_runtime_e2e`）标记 DEFERRED——需要 loop 在 confirmation
后触发二次 turn-end action，当前 loop 不构造 MEMORY_PROPOSE action。

**Patterns to follow:**
- `tests/runtime_integration/test_memory_anchor_fake.py` — 同目录、同模式
- `tests/runtime_integration/test_tool_branch_confirmation_required.py` — branch behavior 测试模式
- TDD §7 中定义的 helper factory

**Test scenarios:** 见 TDD §6.1–6.6（Phase A-F，30 tests）。每个场景已定义 test name、
purpose、setup、action、expected evidence、forbidden behavior。

**Verification:**
- `pytest tests/runtime_integration/test_memory_retain_branch_behavior.py -v` — L1 handler tests RED（handler 未注册），L2 dispatcher tests RED
- 所有测试先看 RED 再进入 U2

---

### U2. MemoryRetainHandler

**Goal:** 新增 `agent/runtime_integration/memory_retain.py`，实现 retain handler。

**Dependencies:** U1（测试 RED 确认后实现）

**Files:**
- Create: `agent/runtime_integration/memory_retain.py`

**Approach:**
Handler 接收 `RuntimeActionRequest`（`action_type=MEMORY_PROPOSE`）：
1. 从 payload 提取 `confirmation_result`, `proposal_id`, `candidate`
2. 验证字段存在性和有效性
3. 如果 `confirmation_result="rejected"` → `disposition="not_retained"`
4. 如果 `confirmation_result="accepted"` 且验证通过 → 构造
   `MemoryOperationIntent` + `MemoryAuditSummary` → `store.apply_operation_intent()`
   → `disposition="retain"`, `stored=True`
5. 如果 store apply 返回 SKIPPED/REJECTED → 映射到对应 evidence

Handler 构造函数：
```python
class MemoryRetainHandler:
    def __init__(self, *, store: InMemoryMemoryStore | None = None) -> None:
        self._store = store or InMemoryMemoryStore()
```

使用 `context.success()` / `context.rejected()` / `context.failed()` 构造
RuntimeActionResult，遵循 dispatcher 的 evidence 发行规则。

**关键设计约束：**
- 不读取真实 memory episodes
- 不调用真实 API
- 不作为 MemoryPolicy 的替代（不调用 `policy.decide()`）
- 不自动 approve——必须接收显式 `confirmation_result`
- `no_silent_retain=True` 不变式

**Patterns to follow:**
- `agent/runtime_integration/memory_hook.py` — handler 结构、context 使用模式
- `agent/runtime_integration/tool_gate.py` — handler 注册 + allowlist 模式

**Test scenarios:**
- 同 U1 全部 Phase A/B 测试 — handler 直接调用和 dispatcher 路由均覆盖

**Verification:**
- `pytest tests/runtime_integration/test_memory_retain_branch_behavior.py -v` — Phase A/B 全部 GREEN
- `pytest tests/runtime_integration/test_memory_anchor_fake.py -v` — 全部通过（回归）
- `ruff check agent/runtime_integration/memory_retain.py` — exit code 0

---

### U3. Register MemoryRetainHandler in phase1_hook.py

**Goal:** 在 `build_phase1_dispatcher()` 中注册 `MemoryRetainHandler` → `MEMORY_PROPOSE`。

**Dependencies:** U2

**Files:**
- Modify: `agent/runtime_integration/phase1_hook.py` — import + register（~3 lines）

**Approach:**
1. Import `MemoryRetainHandler` from `agent.runtime_integration.memory_retain`
2. 在 `registry.register(TOOL_GATE, ...)` 之后新增：
   ```python
   registry.register(
       RuntimeActionType.MEMORY_PROPOSE,
       MemoryRetainHandler(),
   )
   ```
3. 更新 docstring 说明新增的 handler

变更量：import 1 行 + register 3 行 + docstring ~2 行 = ~6 lines。

**Patterns to follow:**
- `phase1_hook.py` 中现有的 `registry.register()` 调用模式

**Verification:**
- `pytest tests/runtime_integration/test_memory_retain_branch_behavior.py -v` — 全部 GREEN
- `pytest tests/runtime_integration/test_memory_anchor_fake.py -v` — 全部通过
- `pytest tests/runtime_integration/test_tool_branch_confirmation_required.py -v` — 22/22 pass

---

### U4. Implementation Notes

**Goal:** 编写 implementation notes 记录实际变更和决策。

**Dependencies:** U3

**Files:**
- Create: `docs/implementation-notes/memory-retain-branch-behavior.md`

**Approach:**
记录：实现了什么、没做什么、plan 未覆盖但执行中做出的决策、tradeoffs/deviations、
回退记录、tests/gates 结果、deferred 项。

**Verification:**
- 文档内容与 git diff 一致
- deferred 项明确标注

## 5. Implementation Sequencing

```
U1 (tests, RED)
  → U2 (MemoryRetainHandler, GREEN)
    → U3 (phase1_hook.py register)
      → U4 (implementation notes)
```

每步必须：
- 先跑现有测试确认树健康
- 完成后跑全量 runtime_integration 测试
- 不可跳过 U1——TDD-first，先 RED 再 GREEN

## 6. Stop Conditions

- 如果需要新增 branch point → **STOP**，回到 Contract/SDD
- 如果需要修改 Unified Runtime Flow Contract → **STOP**，回到 Contract
- 如果需要真实 API / `.env` → **STOP**，升级 Ask User
- 如果测试设计与 SPEC 冲突 → **STOP**，回 TDD
- 如果发现 SPEC 对 branch point 判断错误 → **STOP**，回 SPEC
- 如果需要修改 `MemoryTurnEndProposalHandler` proposal 逻辑 → **STOP**，回 SPEC
- 如果需要修改 `DeterministicMemoryPolicy` → **STOP**，回 SPEC
- 同一问题在同一阶段最多 2 次修复尝试 → 第 3 次前 **Ask User**

## 7. Allowed vs Forbidden Modifications

**Allowed:**
- `agent/runtime_integration/memory_retain.py` (new)
- `agent/runtime_integration/phase1_hook.py` (import + register, ~6 lines)
- `tests/runtime_integration/test_memory_retain_branch_behavior.py` (new)
- `docs/implementation-notes/memory-retain-branch-behavior.md` (new)

**Forbidden:**
- Memory recall into context
- Background consolidation / emergence detection
- Proactive reminder
- Memory delete/update/review UI
- Vector/RAG/semantic retrieval
- Tool/MCP/Skill/Checkpoint 修改
- 修改 `agent/memory_store.py` / `MemoryStoreProtocol`
- 修改 `agent/memory_hook.py` / `MemoryTurnEndProposalHandler`
- 修改 `agent/memory_policy.py` / `DeterministicMemoryPolicy`
- 修改 `agent/memory_operations.py` / `agent/memory_contracts.py`
- 修改 `agent/loop.py` / `LoopDependencies`
- 读取 `.env` / 真实 API / 真实 memory episodes
- 新增 RuntimeActionType / Anchor / capability milestone

## 8. Regression Risk

| Risk | Mitigation |
|------|-----------|
| MEMORY_TURN_END_PROPOSAL 行为被破坏 | 不修改 `memory_hook.py`；`test_memory_anchor_fake.py` 回归测试 |
| TOOL_GATE 行为被破坏 | `phase1_hook.py` 只新增 register 调用；`test_tool_branch_confirmation_required.py` 回归测试 |
| Store 行为变更 | 不修改 `memory_store.py`；handler 只消费 store 公开 API |
| phase1_hook 循环 import | `memory_retain.py` 不 import phase1_hook；import 方向与 `memory_hook.py` 一致 |

## 9. Review Checklist

- [ ] branch point 判断正确（`memory.turn_end_proposal` 下游，非新 Anchor）
- [ ] SPEC OQ#1 已解决（方案 B：MEMORY_PROPOSE handler）
- [ ] 不修改 `MemoryTurnEndProposalHandler` proposal 逻辑
- [ ] 不修改 `DeterministicMemoryPolicy`
- [ ] 不修改 `MemoryStoreProtocol` / `InMemoryMemoryStore`
- [ ] 不新增 RuntimeActionType（复用 `MEMORY_PROPOSE`）
- [ ] fake/real 共享同一 handler 逻辑（store backend 不同）
- [ ] dogfood 只能通过 dispatcher.route() 进入
- [ ] TDD-first 执行顺序（U1 RED → U2 GREEN → U3 register）
- [ ] Stop conditions 明确
- [ ] Allowed/forbidden 边界清晰
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 与 ENGINEERING_WORKFLOW.md 一致
- [ ] 与 SPEC 一致
- [ ] 与 TDD 一致
