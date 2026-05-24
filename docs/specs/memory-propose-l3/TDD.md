# TDD: MEMORY_PROPOSE L3 Wiring

Date: 2026-05-24
SPEC: [SPEC.md](./SPEC.md)

## Test Matrix

分层策略：
- L1 (subsystem_integration): 已有 test_memory_retain_branch_behavior.py 覆盖
- L2 (harness_runtime_e2e): 已有 test_memory_retain_branch_behavior.py 覆盖
- L3 (real_core_loop_runtime_e2e): core.chat() → turn-end hook → MEMORY_PROPOSE dispatch

---

## T1: core.chat() dispatches MEMORY_PROPOSE for queued confirmed proposal

- **purpose**: 验证 turn-end hook 检测到 state.task.pending_retain_proposals 非空时，
  构造并 dispatch MEMORY_PROPOSE RuntimeActionRequest
- **setup**: FakeProvider + observer spy on dispatcher
- **action**: 
  1. chat("hello") → 触发 MEMORY_TURN_END_PROPOSAL
  2. 手动 queue confirmed proposal 到 state.task.pending_retain_proposals
  3. chat("confirm") → turn-end hook 应 dispatch MEMORY_PROPOSE
- **expected evidence**:
  - observer 捕获到 action_type="memory.propose" 的 route_from_runtime_loop 调用
  - dispatch result status="success"
  - payload 包含 stored=True, disposition="retain"
- **forbidden**: MEMORY_PROPOSE 未被 dispatch，队列未清空
- **pass/fail**: 所有 assert 通过

## T2: empty queue → no MEMORY_PROPOSE dispatch

- **purpose**: 验证 pending_retain_proposals 为空时不触发 MEMORY_PROPOSE
- **setup**: FakeProvider + observer spy, pending_retain_proposals=[]
- **action**: chat("hello")
- **expected evidence**: observer 未捕获任何 MEMORY_PROPOSE dispatch
- **pass/fail**: 无 MEMORY_PROPOSE event

## T3: no real API or env access

- **purpose**: L3 test 不使用真实 API / secret / env
- **action**: 检查测试中不 import 真实 provider、不读 .env
- **pass/fail**: 所有 import 来自 fake_provider

## T4: pending_retain_proposals cleared after dispatch

- **purpose**: 验证 MEMORY_PROPOSE dispatch 后队列被清空
- **setup**: FakeProvider + queued confirmed proposal
- **action**: chat("hello") → MEMORY_PROPOSE dispatched
- **expected evidence**: state.task.pending_retain_proposals 在 dispatch 后为空
- **pass/fail**: 队列为空
