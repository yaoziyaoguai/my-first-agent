# TDD: Tool Invoke error L3

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](SPEC.md)

## 测试文件

`tests/runtime_integration/test_tool_invoke_error_l3.py`

## T1: core.chat() TOOL_INVOKE error 获得 L3 evidence

**test name**: `test_t1_core_chat_tool_invoke_error_l3`

**purpose**: 注册抛出异常的工具 → core.chat() 触发 TOOL_GATE(allowed) → TOOL_INVOKE(execution_status="error") → L3 evidence。

**setup**:
1. 注册 `error_tool`：confirmation="never"，执行时抛 ValueError
2. FakeProvider + _PipelineSpy
3. HOME 隔离

**action**:
```python
chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy,
     tool_gate_tool_name="error_tool")
```

**expected**:
- TOOL_GATE: status="success", gate_disposition="allowed"
- TOOL_INVOKE: evidence_level=L3, disposition="invoked", tool_invoked=True, execution_status="error"
- TOOL_RESULT: 触发（invoke completed with error）

## T2: direct dispatcher.route TOOL_INVOKE error 保持 L2

**test name**: `test_t2_direct_dispatcher_route_tool_invoke_error_is_l2`

**purpose**: 验证 payload spoofing 无效。

## T3: no real API

**test name**: `test_t3_no_real_api_or_env_access`

## T4: regression

已有测试全部通过。
