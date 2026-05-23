# Memory Retain Branch Behavior SPEC

Status: draft
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
Prior Stage: [Tool confirmation_required closeout](../../implementation-notes/tool-branch-confirmation-required-closeout.md)

## 1. Branch Point 判断

**Is this a new capability milestone?** No.

**Is this a branch behavior test under an existing capability?** Yes.

**Is this a harness/subsystem-only validation?** No — `retain` 可通过
`core.chat` → runtime loop → turn-end hook → `MemoryTurnEndProposalHandler`
→ confirmation → `route_from_runtime_loop()` 到达，具备
`real_core_loop_runtime_e2e` 路径。

**Branch point:** `memory.turn_end_proposal`（Contract §2, §3 已定义）。

`memory.turn_end_proposal` 下当前已有的 branch behaviors：

| Behavior | 语义 | 当前覆盖状态 |
|----------|------|-------------|
| `proposed` | 策略判定应保留，生成 pending review proposal | MemoryTurnEndProposalHandler 已返回 |
| `should_not_remember` | 检测到 secret-like 或策略 REJECT | MemoryTurnEndProposalHandler 已返回 |
| `no_action` | 策略判定无需保留 | MemoryTurnEndProposalHandler 已返回 |

本轮新增的 branch behavior：

| Behavior | 语义 | 状态 |
|----------|------|------|
| `retain` | proposal 经确认后写入 memory store | **本 SPEC 目标** |

`retain` 是 `proposed` 的自然下游——`proposed` 产生 pending review proposal，
`retain` 在用户确认后执行实际写入。

**关键判断：** `retain` 是否需要新增 RuntimeActionType？

不需要。`retain` 是 `MEMORY_TURN_END_PROPOSAL` handler 在收到
confirmation 后的第二条执行路径。当前 handler 只在 turn-end evaluation
时被调用并返回 `proposed`；同一 handler 也可以在 confirmation context 下
被再次调用，传入 `confirmation_result=accepted`，执行 store write 并返回
`retain`。

或者：`retain` 可以作为 `MEMORY_PROPOSE`（已定义，无 handler）的
positive disposition——`MEMORY_PROPOSE` handler 接收已确认的 proposal，
写入 store 并返回 `retain`。

具体采用哪种方式在 TDD / Implementation Plan 阶段决策。本 SPEC 只定义
behavior scope 和边界。

## 2. Behavior Scope

### 2.1 retain 语义

`retain` 表示：一个已经过用户确认（inline confirmation 或 T1 pending review
accept）的 memory proposal 被正式写入 memory store。

触发条件：

1. `MemoryTurnEndProposalHandler` 先前已返回 `proposed`（`pending_review=True`）
2. 用户已通过确认机制（inline confirmation 或 T1 CLI）接受该 proposal
3. Runtime action 携带 `confirmation_result="accepted"` 和 `proposal_id`
4. Handler 验证 proposal 存在且未被篡改
5. Handler 调用 `MemoryStore.write()` 写入

或者（如果走 `MEMORY_PROPOSE` 路径）：

1. 调用方构造 `MEMORY_PROPOSE` request，携带完整 `MemoryCandidate`
2. Handler 执行 `MemoryStore.write(candidate)`
3. 返回 `disposition="retain"`，`stored=True`

### 2.2 retain 的 positive path 特征

- `disposition="retain"` — memory 已正式保留
- `stored=True` — 写入 store 成功
- `proposal_id` — 被保留的 proposal ID
- `store_backend` — 使用的 store backend（`in_memory` / `filesystem`）
- `storage_path` — 如果 filesystem，记录路径
- `no_silent_retain=True` — 不变式：始终标记非静默保留
- `external_side_effects=True` — 如果 filesystem store（写入磁盘）

### 2.3 retain 的 negative path

| 场景 | disposition | 说明 |
|------|------------|------|
| proposal_id 不存在 | `rejected` | proposal 未找到或已过期 |
| proposal 已被篡改 | `rejected` | content hash 不匹配 |
| store write 失败 | `failed` | IO 错误或权限问题 |
| confirmation_result=rejected | `not_retained` | 用户明确拒绝 |

### 2.4 不在本 SPEC 范围

- **Memory recall into context** — 从 store 读取 memory 注入模型上下文是
  独立关注点（候选分析中的另一项），不属于 retain behavior
- **Memory consolidation** — LLM-based memory consolidation pipeline 已存在，
  不在本轮 runtime action 范围
- **Memory emergence detection** — 已实现，不在本轮范围
- **T1/T2/T3 governance routing** — 路由逻辑已存在，本轮只覆盖 runtime action
  路径下的 retain behavior
- **Inline confirmation UI flow** — 确认交互是独立关注点，本轮只覆盖确认后
  的 retain action

## 3. 当前代码状态

### 3.1 MemoryTurnEndProposalHandler 已实现

`agent/runtime_integration/memory_hook.py` — 已注册到 Phase 1 dispatcher，
返回三种 disposition：`proposed` / `should_not_remember` / `no_action`。

Handler 当前不执行 store write——它是有意的 stateless proposal generator。

### 3.2 MEMORY_PROPOSE 已定义，无 handler

`agent/runtime_integration/schema.py:27` — `MEMORY_PROPOSE = "memory.propose"`
已定义但无注册 handler。这为 retain behavior 提供了一个自然的挂载点。

### 3.3 Memory Store 已实现

- `agent/memory_store.py` — `InMemoryMemoryStore`, `FilesystemMemoryStore`,
  `MemoryStoreProtocol`
- Store write 操作已稳定，有完整的 contract 测试

### 3.4 Memory 确认机制已实现

- `agent/memory_confirmation.py` — confirmation question/option/result
- `agent/memory_review.py` — T1 pending review CLI
- `agent/memory_interaction.py` — inline confirmation flow

### 3.5 Memory 测试已覆盖现有路径

- `tests/runtime_integration/test_memory_anchor_fake.py` — 10+ tests
- `tests/runtime_integration/test_memory_anchor_real.py` — real provider tests
- `tests/runtime_integration/test_runtime_action_handlers.py` — handler tests
- 大量 `tests/test_memory_*.py` — policy, store, emergence, consolidation

## 4. Fake/Real 配置层边界

Unified Runtime Flow Contract §1：fake 和 real 共享同一业务流，仅在配置和
adapter 层不同。

对于 `retain`：

- **handler 逻辑相同** — 同一 handler 处理 fake/real 的 retain
- **store backend 不同** — fake 使用 `InMemoryMemoryStore`，real 使用
  `FilesystemMemoryStore`
- **provider_kind 仅作为 metadata** — 不作为 branch selector
- **不新增 fake-only / real-only retain 路径**

不允许：
- fake 环境跳过 store write（必须写入 InMemoryMemoryStore）
- real 环境自动 approve（必须走同一 confirmation 路径）
- provider_kind 改变 retain 判定逻辑

## 5. Dogfood 边界

### 5.1 允许的做法

```
dogfood script → 构造 confirmed proposal → core.chat 或 dispatcher
  → MemoryRetainHandler.handle() → store.write() → evidence
```

dogfood 脚本：
- 先通过 `MemoryTurnEndProposalHandler` 获取 `proposed` + `proposal_id`
- 模拟用户确认（设置 `confirmation_result="accepted"`）
- 触发 retain action
- 验证 `stored=True`，`disposition="retain"`

### 5.2 禁止的做法

- dogfood 直接调用 `MemoryStore.write()` 跳过 handler
- dogfood 直接调用 `DeterministicMemoryPolicy.decide()` 跳过 dispatcher
- dogfood 自己生成 proof / evidence
- dogfood 声称 `real_core_loop_runtime_e2e` 但走 direct dispatcher

### 5.3 分类预期

| 路径 | 最高分类 | 备注 |
|------|---------|------|
| `core.chat` → turn-end hook → propose → confirm → retain | `real_core_loop_runtime_e2e` | 需完整 loop |
| dogfood `dispatcher.route()` retain action | `harness_runtime_e2e` | 需 target proof 完整 |
| dogfood 直接调用 handler | `subsystem_integration` | — |

## 6. SPEC 不做什么

1. **不新增 Anchor** — `retain` 是 memory branch behavior
2. **不新增 capability milestone** — memory 能力已存在
3. **不新增 RuntimeActionType** — `MEMORY_PROPOSE` 已定义（或复用
   `MEMORY_TURN_END_PROPOSAL`）
4. **不修改 MemoryTurnEndProposalHandler 的 proposal 逻辑** — proposal
   和 retain 是不同关注点
5. **不修改 DeterministicMemoryPolicy** — policy 判定逻辑不变
6. **不修改 T1/T2/T3 governance routing** — 路由已存在
7. **不实现 Memory recall into context** — 独立关注点
8. **不实现 UI confirmation interaction** — 确认交互是独立关注点
9. **不引入** Tool Args / Tool Result / Retry / Error Recovery / Multi Tool /
   MCP Tool / Skill / Checkpoint / Streaming / SubAgent

## 7. 与 tool.gate 模式的对照

`tool.gate` 阶段建立了 branch behavior 的实现模式。`memory retain` 沿用同一模式：

| 维度 | tool.gate | memory retain |
|------|-----------|---------------|
| Branch point | `TOOL_GATE` | `MEMORY_TURN_END_PROPOSAL` 或 `MEMORY_PROPOSE` |
| Handler | `ToolGateHandler` | 现有 `MemoryTurnEndProposalHandler` 扩展或新 handler |
| Positive behavior | `allowed`, `confirmation_required` | `retain` |
| Negative behavior | `blocked`, `not_found` | `rejected`, `not_retained` |
| Neutral behavior | — | `proposed`, `should_not_remember`, `no_action`（已存在） |
| Configuration | `LoopDependencies.tool_gate_tool_name` | `LoopDependencies.memory_proposal_id` 或类似字段 |
| Test layers | L1 handler, L2 dispatcher, L3 loop | 同三层 |
| Internal tool | `_safe_noop` / `_confirmable_noop` | 使用测试 proposal + InMemoryMemoryStore |
| Fake/real | 同一 gate 逻辑 | 同一 retain 逻辑，store backend 不同 |

## 8. Open Questions

1. **retain 走哪个 RuntimeActionType？**
   - 方案 A：扩展 `MemoryTurnEndProposalHandler`，在 confirmation context 下
     执行 retain（同一 handler，不同调用 context）
   - 方案 B：为 `MEMORY_PROPOSE` 注册新 handler，专门处理 retain
   - 方案 C：新增 `MEMORY_RETAIN` RuntimeActionType 和对应 handler
   - 推荐在 TDD/Implementation Plan 阶段决策

2. **LoopDependencies 是否需要新增 memory 相关字段？**
   - 如果 retain 通过 turn-end hook 触发：可能需要 `LoopDependencies` 新增字段
     （如 `memory_proposal_id`, `memory_confirmation_result`）
   - 如果 retain 作为独立 action 通过 dispatcher 直接 route：不需要

3. **retain 的 evidence_level 如何达到 real_core_loop_runtime_e2e？**
   - 如果 retain 嵌在 turn-end hook 中：`route_from_runtime_loop()` →
     `real_core_loop_runtime_e2e`
   - 如果 retain 是独立 action：可能需要 loop 在 confirmation 后触发二次
     turn-end action

4. **InMemoryMemoryStore 的 write 算不算 external_side_effects？**
   - 不算。in-memory write 无持久化副作用。
   - FilesystemMemoryStore write 算（写入磁盘）。

5. **retain 是否需要与现有的 T1 pending review CLI 集成？**
   - 不需要在 SPEC 阶段决策。retain 的 runtime action 路径可以与 CLI 路径
     共存——CLI accept 后触发 retain action，inline confirmation accept 后
     也触发同一 retain action。

## 9. Review Checklist

- [ ] branch point 判断正确（memory.turn_end_proposal，非新 Anchor）
- [ ] behavior scope 明确（retain = 确认后写入 store）
- [ ] 不包含禁止事项（§6 全部检查）
- [ ] fake/real 边界清晰（共享业务流，store backend 不同）
- [ ] dogfood 边界清晰（必须走 dispatcher，不可 direct store.write）
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 与 tool.gate 模式一致（同一三层测试 + fake/real 共享模式）
- [ ] 无真实 API 依赖
- [ ] 无 .env 依赖（InMemoryMemoryStore 不需要 secrets）
- [ ] open questions 未假装已解决
- [ ] 不修改现有 MemoryTurnEndProposalHandler proposal 逻辑
- [ ] 不修改 DeterministicMemoryPolicy
