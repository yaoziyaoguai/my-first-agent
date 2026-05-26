# TDD: MCP L3 Real Core-Loop Integration

Date: 2026-05-23
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 测试分层

```
L3 (real_core_loop_runtime_e2e) — 本轮目标
  ├── core.chat() → run_main_loop() → route_from_runtime_loop()
  └── 所有三个 stage 必须有 runtime-loop provenance

L2 (harness_runtime_e2e) — 保留为辅助验证
  └── dispatcher.route() 或 hook 级直接调用

L1 (subsystem_integration) — 不在本轮
  └── direct FakeMCPClient.call_tool()
```

## 测试文件

`tests/runtime_integration/test_mcp_l3_real_core_loop.py`

---

## T1: core.chat() 触发 MCP tool-like call 完整管线

**test name**: `test_t1_core_chat_triggers_mcp_tool_full_pipeline_l3`

**purpose**: 证明 MCP tool-like call 能通过 `core.chat()` 真实路径进入 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线，并获得 L3 evidence。

**setup**:
1. 使用 `register_tool()` 直接注册测试 MCP 工具（`confirmation="never"`, `capability="mcp_tool"`），函数闭包包裹 `FakeMCPClient.call_tool()`
2. 构造 `FakeProvider`（不调用真实 LLM API）
3. 构造 `_PipelineSpy` 包裹 dispatcher，捕获所有 route 调用
4. 设置 `HOME` 为隔离路径

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="mcp__demo__hello",
)
```

**expected evidence**:
1. spy 捕获到至少 3 次 `route_from_runtime_loop` 调用（TOOL_GATE, TOOL_INVOKE, TOOL_RESULT）
2. TOOL_GATE result:
   - `status == "success"`
   - `gate_disposition == "allowed"`
   - `evidence_level == "real_core_loop_runtime_e2e"`
   - `dispatcher_origin == "runtime_loop"`
   - `core_entrypoint == "core.chat"`
   - `runtime_hook_name == "loop.turn_end"`
3. TOOL_INVOKE result:
   - `status == "success"`
   - `tool_invoked == True`
   - `tool_output` 包含 FakeMCPClient 返回的 MCP result content
   - `evidence_level == "real_core_loop_runtime_e2e"`
4. TOOL_RESULT result:
   - `status == "success"`
   - `prompt_section` 非空
   - `evidence_level == "real_core_loop_runtime_e2e"`
5. 三个 stage 的顺序严格为 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT

**forbidden behavior**:
- spy 中不得出现 `route` 方法调用（只能是 `route_from_runtime_loop`）
- TOOL_GATE 不能是 confirmation_required 状态
- TOOL_INVOKE 不能在 TOOL_GATE 之前
- 不能读取 .env
- 不能连接真实 MCP server

**pass/fail criteria**:
- PASS: 所有 expected evidence 满足，所有 forbidden behavior 未出现
- FAIL: 任一 expected evidence 不满足，或任一 forbidden behavior 出现

---

## T2: direct MCP adapter call 保持 L1

**test name**: `test_t2_direct_mcp_adapter_call_is_l1`

**purpose**: 验证直接调用 `FakeMCPClient.call_tool()` 不经过 dispatcher 时，只能获得 L1 (subsystem_integration) 或更低 evidence。

**setup**:
1. 构造 `FakeMCPClient` 和 `FakeMCPClient.call_tool()` 调用
2. 不经过 dispatcher、不经过 core.chat()

**action**:
```python
result = client.call_tool(server, "hello", {})
```

**expected evidence**:
1. 返回 `MCPCallResult`，不包含 `evidence_level` 字段（不是 RuntimeActionResult）
2. 没有 dispatcher provenance
3. 没有 runtime-loop provenance

**forbidden behavior**:
- 不得声称 L2 或 L3
- 不得通过任何路径进入 dispatcher

**pass/fail criteria**:
- PASS: 结果是纯 MCPCallResult，无 RuntimeAction evidence
- FAIL: 结果意外获得 dispatcher/runtime-loop provenance

---

## T3: direct dispatcher.route 保持 L2

**test name**: `test_t3_direct_dispatcher_route_mcp_tool_is_l2`

**purpose**: 验证 `dispatcher.route(TOOL_GATE, ...)` 直接调用时只能获得 L2 (harness_runtime_e2e)，不能通过 payload 伪造升级为 L3。

**setup**:
1. 注册测试 MCP 工具（同 T1）
2. 构造 dispatcher（注册 TOOL_GATE + TOOL_INVOKE + TOOL_RESULT handler）

**action**:
```python
# 尝试在 payload 中伪造 core_loop_invoked / core_entrypoint
result = dispatcher.route(RuntimeActionRequest(
    action_type=RuntimeActionType.TOOL_GATE,
    source="test",
    parent_trace_id="",
    payload={
        "tool_name": "mcp__demo__hello",
        "core_loop_invoked": True,       # 伪造
        "core_entrypoint": "core.chat",  # 伪造
        "runtime_hook_name": "loop.turn_end",  # 伪造
    },
))
```

**expected evidence**:
- `evidence_level == "harness_runtime_e2e"`（不是 L3）
- `dispatcher_origin == "direct_dispatcher"`（dispatcher 不从 payload 读取）
- `core_loop_invoked` 不在 evidence 中（或为 False）
- payload 中的伪造字段被忽略

**forbidden behavior**:
- 不得因为 payload 中有 `core_loop_invoked: True` 而升级为 L3
- `dispatcher_origin` 不得变为 `"runtime_loop"`

**pass/fail criteria**:
- PASS: evidence_level 严格为 harness_runtime_e2e，payload 伪造无效
- FAIL: evidence 被 payload 字段污染，或 evidence_level 被错误升级

---

## T4: hook 级 MCP 工具走通完整管线（L3 via hook-level）

**test name**: `test_t4_hook_level_mcp_tool_full_pipeline_l3`

**purpose**: 补充验证：通过 `_try_phase1_turn_end_runtime_action()` 直接调用（模拟 loop turn-end hook），MCP 工具以 `confirmation="never"` 注册时，能走通 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线并获得 L3。

**setup**:
1. 注册测试 MCP 工具（`confirmation="never"`, `capability="mcp_tool"`）
2. 构造 `_PipelineSpy` 包裹 dispatcher
3. 构造 mock state
4. 构造 `LoopDependencies(tool_gate_tool_name="mcp__demo__hello", ...)`

**action**:
```python
_try_phase1_turn_end_runtime_action(
    state=mock_state,
    result_text="test response",
    dispatcher=spy,
    dependencies=deps,
)
```

**expected evidence**:
1. TOOL_GATE: `status="success"`, `gate_disposition="allowed"`, L3 evidence
2. TOOL_INVOKE: `status="success"`, `tool_invoked=True`, L3 evidence
3. TOOL_RESULT: `status="success"`, `prompt_section` 非空, L3 evidence
4. 三个 stage 通过 `route_from_runtime_loop` 调用
5. 严格顺序：GATE → INVOKE → RESULT

**forbidden behavior**:
- TOOL_INVOKE 不被跳过（与现有 E2 test 不同——E2 中 MCP 工具 confirmation="always" 导致 gate 返回 confirmation_required，TOOL_INVOKE 不触发）
- TOOL_GATE 不返回 confirmation_required

**pass/fail criteria**:
- PASS: 完整三阶段管线，全部 L3 evidence
- FAIL: 任一 stage 缺失或 evidence 降级

---

## T5: MCP 工具 confirmation="always" 在 gate 被拦截

**test name**: `test_t5_mcp_tool_confirmation_always_blocked_at_gate`

**purpose**: 验证 MCP 工具以 `confirmation="always"` 注册时，在 hook 级 TOOL_GATE 被正确拦截（confirmation_required），TOOL_INVOKE 不触发。确认为 `confirmation="never"` 的测试配置不改变生产安全策略。

**setup**:
1. 通过 `register_tool()` 直接注册 MCP 工具并设 `confirmation="always"`——与 `register_mcp_tools()` 的 hardcoded `confirmation="always"` 在 gate 行为上等价（SPEC §E.2），避免引入对 `register_mcp_tools()` 内部实现细节的硬依赖
2. 使用 `FakeMCPClient`
3. 构造 `_PipelineSpy` 包裹 dispatcher
4. 构造 `LoopDependencies(tool_gate_tool_name="mcp__demo__hello", ...)`

**action**:
```python
_try_phase1_turn_end_runtime_action(
    state=mock_state,
    result_text="test response",
    dispatcher=spy,
    dependencies=deps,
)
```

**expected evidence**:
1. TOOL_GATE: `status="confirmation_required"`, `gate_disposition="confirmation_required"`, L3 evidence
2. TOOL_INVOKE: **不触发**（gate 不满足 `status="success" and disposition="allowed"`）
3. TOOL_RESULT: **不触发**

**forbidden behavior**:
- TOOL_INVOKE 不得被触发（即使 gate 有 L3 evidence）

**pass/fail criteria**:
- PASS: TOOL_GATE 正确返回 confirmation_required，TOOL_INVOKE/TOOL_RESULT 未触发
- FAIL: TOOL_INVOKE 意外触发，或 TOOL_GATE 未返回 confirmation_required

---

## T6: 不读 .env / 不调用真实 API

**test name**: `test_t6_no_real_api_or_env_access`

**purpose**: 验证 pipeline 执行过程中不读取 .env、不调用真实 LLM API、不连接真实 MCP server。HOME 设为隔离路径。

**setup**:
1. HOME 指向隔离的临时目录（`/private/tmp/my-first-agent-mcp-l3-home`）
2. 注册测试 MCP 工具 + FakeMCPClient + FakeProvider

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="mcp__demo__hello",
)
```

**expected evidence**:
- 所有调用完成，无异常
- FakeProvider 被使用（provider_kind 反映 fake provider）
- FakeMCPClient 被使用（不启动真实进程）

**forbidden behavior**:
- 不读 .env 文件
- 不发起网络请求
- 不启动子进程（MCP server）
- 不调用真实 Anthropic API

**pass/fail criteria**:
- PASS: 所有操作在隔离环境中完成，无外部调用
- FAIL: 任何 .env 读取、网络请求、或子进程启动

---

## T7: 已有 Tool Pipeline L3 测试仍通过（回归）

**test name**: (由已有测试覆盖，非新增)

**purpose**: 验证本轮改动不破坏已有 Tool Pipeline L3 测试。`chat()` 新增 `tool_gate_tool_name` 参数为可选参数，默认行为不变。

**setup**:
- 已有测试文件 `tests/runtime_integration/test_tool_pipeline_l3_completion.py`
- 已有测试文件 `tests/runtime_integration/test_mcp_runtime_integration.py`

**action**:
```bash
pytest tests/runtime_integration/test_tool_pipeline_l3_completion.py -q
pytest tests/runtime_integration/test_mcp_runtime_integration.py -q
pytest tests/runtime_integration/ -q
```

**pass/fail criteria**:
- PASS: 所有已有测试通过，0 失败
- FAIL: 任何已有测试失败

---

## T8: chat() 不传 tool_gate_tool_name 时行为不变（向后兼容）

**test name**: `test_t8_chat_without_tool_gate_tool_name_uses_default`

**purpose**: 验证 `chat()` 不传 `tool_gate_tool_name` 参数时，使用默认值 `"_safe_noop"`，与现有行为完全一致。

**setup**:
1. 同 T1，但不传 `tool_gate_tool_name`

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    # 不传 tool_gate_tool_name
)
```

**expected evidence**:
- TOOL_GATE payload 中 `tool_name == "_safe_noop"`
- pipeline 行为与现有 A4 test 一致

**pass/fail criteria**:
- PASS: tool_name 为默认值 "_safe_noop"
- FAIL: tool_name 为其他值或 pipeline 行为改变

---

## 测试执行顺序

```
T1 (core.chat L3) → T4 (hook L3) → T5 (confirmation_required) → T2 (L1) → T3 (L2 payload spoof) → T6 (no real API) → T8 (backward compat) → T7 (regression)
```

## 禁止模式

- 不新增 Anchor
- 不新增 branch point
- 不新增 runtime flow
- 不新增 fake loop / fake dispatcher / dogfood-only path
- 不让 direct MCP adapter call 冒充 L3
- 不让 direct dispatcher.route 冒充 L3
- 不让 payload spoofing 升级 evidence
- 不读 .env
- 不连接真实 MCP server
- 不调用真实 API
