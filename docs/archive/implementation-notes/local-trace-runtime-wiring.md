# Implementation Notes: Local Trace Runtime Wiring

Date: 2026-05-24
Capability: local-trace-runtime-wiring
Loop Type: Normal Capability Loop（已有 turn-end hook branch point 承载）

## 架构决策

Trace 是纯观测基础设施，不通过 dispatcher routing。直接在 turn-end hook 末尾构造
TraceEvent 后调用 sink，与已有 MEMORY / TOOL / CHECKPOINT / CONSOLIDATE / RECALL /
SKILL / SUBAGENT dispatch 同级。

## 关键发现：AgentState vs TurnState 分离

`_try_phase1_turn_end_runtime_action` 接收 `dependencies.state`（AgentState），而非
`turn_state`（TurnState）。AgentState 没有 `on_trace_event`、`trace_run_id`、
`trace_id` 字段。

解决方案：将 trace 字段通过 LoopDependencies（frozen dataclass）线程化注入，
复用已有的 `_deps_fields` 模式。从 `_run_main_loop` 中读取 `turn_state.on_trace_event`
等字段，传入 LoopDependencies，再在 `_try_trace_event_emission` 中从 dependencies 读取。

## 实现变更

### agent/loop.py
- `LoopDependencies` 新增 `on_trace_event`、`trace_run_id`、`trace_id` 字段（默认 None）
- 新增 `_try_trace_event_emission()` 函数：发射 state_transition + tool_call TraceEvent
- 在 `_try_phase1_turn_end_runtime_action` 末尾调用 `_try_trace_event_emission`

### agent/core.py
- `_run_main_loop` 中从 `turn_state` 读取 trace 字段注入到 `LoopDependencies`

### 测试
- tests/runtime_integration/test_local_trace_runtime_wiring_l3.py
  - T1: state_transition TraceEvent 发射
  - T2: tool_call TraceEvent 发射
  - T3: 默认路径零开销（不传 on_trace_event）
  - T4: 不读取真实 API / env

## chat() 返回空串说明

`chat()` 返回 `""` 是正常行为。`handle_end_turn_response` 不返回模型正文——
正文已由流式阶段输出到 stdout，返回值只包含控制型 UI 文字。
