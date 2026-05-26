# SPEC: MEMORY_PROPOSE L3 Wiring

Date: 2026-05-24
Status: active
Type: Normal Capability Loop（已有 turn-end hook branch point 承载）

## A. Architecture Decision

### 为什么不需要 Architecture Extension Loop

MEMORY_PROPOSE 是 Memory retain pipeline 的执行阶段——turn-end hook 上已有
MEMORY_TURN_END_PROPOSAL（proposal generation）、MEMORY_CONSOLIDATE、
MEMORY_RECALL 等同级 dispatch。MEMORY_PROPOSE handler（MemoryRetainHandler）
已在 phase1_hook 注册。

不新增 RuntimeActionType、handler、catalog entry——只新增 dispatcher 调用。

### 为什么现有 branch point 能承载

`_try_phase1_turn_end_runtime_action` 已有 10 个 action type 的 dispatch 块，
MEMORY_TURN_END_PROPOSAL 是其中之一。MEMORY_PROPOSE 作为 proposal 执行阶段，
自然挂在同一 branch point 上，紧跟 MEMORY_TURN_END_PROPOSAL 之后。

### 跨 turn 协作模式

MEMORY_PROPOSE 的输入（confirmed proposal + confirmation_result）来自用户确认阶段，
不在同一 turn。设计采用 TaskState 队列模式：

```
Turn N:
  turn-end hook → MEMORY_TURN_END_PROPOSAL → proposal (pending_review)
  → Ask User inline confirmation

Turn N+1 (用户确认后):
  confirmation handler → queue confirmed proposal in state.task.pending_retain_proposals
  turn-end hook → MEMORY_PROPOSE for each queued proposal → MemoryRetainHandler → store.write()
```

## B. Scope

### In scope
- 新增 `TaskState.pending_retain_proposals` 字段
- 修改 `handle_inline_confirmation_reply` accept/edit_accept 路径：queue 而非直接写 store
- 在 turn-end hook 新增 MEMORY_PROPOSE dispatch 块
- L3 测试：chat() → turn-end → MEMORY_PROPOSE dispatch → evidence

### Out of scope
- 修改 MemoryTurnEndProposalHandler 或 MemoryRetainHandler
- 修改 confirmation UI/UX
- 新增 RuntimeActionType
- 修改 core.py 或 chat() 签名
- 修改 MemoryPolicy 或 auto-approve 逻辑

## C. Design

### 调用链

```
chat(user_input)
  → confirmation handler: handle_inline_confirmation_reply()
    → state.task.pending_retain_proposals.append(confirmed_candidate)
  → _run_main_loop()
    → run_main_loop()
      → _try_phase1_turn_end_runtime_action()
        → MEMORY_TURN_END_PROPOSAL dispatch
        → MEMORY_PROPOSE dispatch (new)
          → MemoryRetainHandler.handle()
            → context.invoke_registered_target("MemoryStore", "apply_operation_intent")
```

### TaskState.pending_retain_proposals 格式

```python
# 每个 entry 是 JSON-safe dict：
{
    "proposal_id": "prop:abc123",
    "content": "用户偏好简体中文",
    "content_hash": "sha256...",
    "scope": "user",
    "sensitivity": "low",
    "source": "turn_end_proposal",
    "confirmation_result": "accepted",
    "queued_at": "2026-05-24T...",
}
```

### Error handling
- 队列为空 → 跳过 MEMORY_PROPOSE dispatch
- 单个 proposal dispatch 失败 → 静默吞掉，继续下一个
- sink 不存在 → 零开销

## D. Evidence Plan

| Level | Classification | How verified |
|-------|---------------|-------------|
| L1 (subsystem) | Direct MemoryRetainHandler.handle() | 已有 test_memory_retain_branch_behavior.py |
| L2 (harness) | dispatcher.route(MEMORY_PROPOSE) | 已有 test_memory_retain_branch_behavior.py |
| L3 (real_core_loop) | core.chat() → turn-end hook → MEMORY_PROPOSE dispatch | T1: chat() + observer spy |

## E. Fake/Real Boundary
- 所有测试使用 FakeProvider
- MemoryStore 使用 InMemoryMemoryStore
- 不读取 .env / 真实 sessions / runs / episodes

## F. Stop Conditions
- 需要修改 core.py 签名 → 停止（已有 on_trace_event，不需改）
- 需要新增 RuntimeActionType → 停止（复用 MEMORY_PROPOSE）
- 需要真实 API / secret → 停止
