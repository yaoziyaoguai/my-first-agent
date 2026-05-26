# TDD: Streaming L3 Wiring

Date: 2026-05-24
SPEC: [SPEC.md](./SPEC.md)

## Test Matrix

分层策略：
- L1/L2: 已有 test_runtime_action_handlers.py / test_runtime_action_contract.py 覆盖
- L3 (real_core_loop_runtime_e2e): core.chat() → turn-end hook → STREAMING_PROVIDER_CALL dispatch

---

## T1: core.chat() dispatches STREAMING_PROVIDER_CALL at turn-end

- **purpose**: 验证 turn-end hook dispatch STREAMING_PROVIDER_CALL
- **setup**: FakeProvider + spy on dispatcher
- **action**: chat("hello") → turn-end hook dispatch
- **expected evidence**:
  - observer 捕获到 action_type="streaming.provider_call" 的 route_from_runtime_loop 调用
  - evidence_level == real_core_loop_runtime_e2e
  - dispatcher_origin == "runtime_loop"
  - core_entrypoint == "core.chat"
- **pass/fail**: dispatch 发生且 evidence chain 完整

## T2: provider_supports_streaming in payload

- **purpose**: 验证 payload 正确传递 provider streaming capability
- **setup**: FakeProvider (supports_streaming=True)
- **action**: chat("hello")
- **expected evidence**: payload.provider_supports_streaming == True
- **pass/fail**: capability 正确传递

## T3: empty queue after dispatch

- **purpose**: 验证 dispatch 后状态清理（如适用）
- **action**: 确认 dispatch 不泄露状态
- **pass/fail**: 无副作用

## T4: no real API or env access

- **purpose**: L3 test 不使用真实 API / secret / env
- **action**: 检查测试中不 import 真实 provider、不读 .env
- **pass/fail**: 所有 import 来自 fake_provider
