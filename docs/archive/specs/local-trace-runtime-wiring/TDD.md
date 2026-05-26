# TDD: Local Trace Runtime Wiring

Date: 2026-05-24
SPEC: [SPEC.md](./SPEC.md)

## Test Matrix

分层策略：
- L1 (subsystem_integration): 已有 test_observability_local_trace_contract.py 覆盖
- L3 (real_core_loop_runtime_e2e): core.chat() → on_trace_event sink 被调用

---

## T1: core.chat() emits state_transition trace event

- **purpose**: 验证 core.chat() 通过 turn-end hook 发射 state_transition TraceEvent
- **setup**: FakeProvider + on_trace_event sink (list collector)
- **action**: chat("hello", provider=FakeProvider(), on_trace_event=capture.append)
- **expected evidence**:
  - len(captured) >= 1
  - 至少一条 span_type="state_transition", name="loop.turn_end"
  - captured event 的 run_id / trace_id 非空
- **forbidden**: captured 为空，event 缺少 run_id/trace_id
- **pass/fail**: 所有 assert 通过

## T2: core.chat() emits tool_call trace event for invoked tool

- **purpose**: 验证 TOOL_INVOKE 后发射 tool_call TraceEvent
- **setup**: FakeProvider + on_trace_event sink
- **action**: chat("hello", provider=FakeProvider(), on_trace_event=capture.append)
- **expected evidence**:
  - 至少一条 span_type="tool_call"
  - tool_call event 的 name 包含 "_safe_noop"（默认 tool_gate_tool_name）
- **pass/fail**: tool_call event 存在且 name 正确

## T3: no on_trace_event → no trace events (zero-overhead default)

- **purpose**: 验证默认路径（不传 on_trace_event）不产生任何 trace event
- **setup**: FakeProvider，不传 on_trace_event
- **action**: chat("hello", provider=FakeProvider())
- **expected evidence**: chat() 成功返回，不抛异常
- **forbidden**: 崩溃、异常
- **pass/fail**: chat() 正常返回

## T4: no real API or env access

- **purpose**: L3 test 不使用真实 API / secret / env
- **action**: 检查测试中不 import 真实 provider、不读 .env
- **pass/fail**: 所有 import 来自 fake_provider
