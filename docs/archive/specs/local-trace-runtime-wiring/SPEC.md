# SPEC: Local Trace Runtime Wiring

Date: 2026-05-24
Status: active
Type: Normal Capability Loop（已有 turn-end hook branch point 上的 branch behavior）

## A. Architecture Decision

### 为什么不需要 Architecture Extension Loop

Local trace 接入是 pure observation infrastructure hardening——在已有 turn-end hook branch point 上增加 trace event emission，不新增 RuntimeActionType、handler、catalog entry 或 branch point。

原因：
- TraceEvent 是事实记录（"工具 X 被调用了，结果是 Y"），不是 runtime 决策
- dispatcher pattern 用于 decision routing（gate/invoke/result/recall）——trace 不需要证据链 provenance，它自己就是证据
- TurnState 已有 `on_trace_event` sink、`trace_run_id`、`trace_id`——基础设施已就位
- `emit_tool_result_trace_event()` 已有投影逻辑——只需从 turn-end hook 调用

### 为什么现有 branch point 能承载

turn-end hook (`_try_phase1_turn_end_runtime_action`) 是统一主流程中所有 turn-end action 的汇聚点。Trace 作为 turn-end 观测 side-effect，自然挂在它上面，与已有 MEMORY / TOOL / CHECKPOINT / CONSOLIDATE / RECALL / SKILL / SUBAGENT dispatch 同级。

## B. Scope

### In scope
- 在 turn-end hook 末尾添加 `_try_trace_event_emission()` 调用
- 发射两种 TraceEvent：`state_transition`（turn-end 标记）和 `tool_call`（工具调用结果）
- 只在 `state.on_trace_event` sink 存在时发射（默认路径零开销）
- L3 测试：core.chat() + FakeProvider + on_trace_event → 验证 TraceEvent 产生

### Out of scope
- 新增 RuntimeActionType / handler / catalog entry
- 修改 TurnState 或 LoopDependencies
- 修改 core.py 或 chat() 签名
- 修改 LocalTraceRecorder 的 temp-only 限制
- model_call / checkpoint / memory_update span 类型
- 写入 JSONL 文件

## C. Design

### 调用链

```
chat(on_trace_event=my_sink)
  → _run_main_loop()
    → run_main_loop()
      → _try_phase1_turn_end_runtime_action(state, result_text, dispatcher, dependencies)
        → _try_trace_event_emission(state, result_text, tool_name, invoke_result)
          → state.on_trace_event(TraceEvent("state_transition", ...))
          → emit_tool_result_trace_event(state, ...)
            → state.on_trace_event(TraceEvent("tool_call", ...))
```

### 发射的 TraceEvent 类型

1. **state_transition**: 每次 turn-end 发射一条
   - span_type="state_transition"
   - name="loop.turn_end"
   - metadata 包含 tool_name 和 result_text_preview（前 200 字符）

2. **tool_call**: TOOL_INVOKE 完成后发射（invoke_result 非 None 时）
   - span_type="tool_call"
   - tool_name=tool_gate_tool_name
   - tool_result="[{execution_status}] {tool_output}"

### Error handling

- sink 不存在 → 直接返回（零开销）
- 任何异常 → 静默吞掉（trace 失败不阻塞 loop）
- run_id/trace_id 缺失 → 吞掉 ValueError

## D. Evidence Plan

| Level | Classification | How verified |
|-------|---------------|-------------|
| L1 (subsystem) | Direct LocalTraceRecorder.record() | 已有 test_observability_local_trace_contract.py |
| L2 (harness) | Direct call to _try_trace_event_emission | T3: 构造 mock state + sink → 验证 events |
| L3 (real_core_loop) | core.chat() → turn-end hook → sink called | T1/T2: chat() + FakeProvider + sink |

## E. Fake/Real Boundary

- 所有测试使用 FakeProvider
- TraceEvent sink 是内存回调，不涉及文件 IO
- 不读取 .env / 真实 sessions / runs / agent_log.jsonl

## F. Stop Conditions

- 需要新增 RuntimeActionType → 停止（超出 scope）
- 需要修改 core.py 签名 → 停止（已有 on_trace_event 参数）
- 需要解除 temp-only 限制 → 停止（deferred）
