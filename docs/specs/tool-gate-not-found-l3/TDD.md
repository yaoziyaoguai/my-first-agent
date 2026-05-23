# TDD: Tool Gate not_found L3

Date: 2026-05-23
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 测试分层

```
L3 (real_core_loop_runtime_e2e) — 本轮目标
  └── core.chat() → route_from_runtime_loop() → TOOL_GATE not_found

L2 (harness_runtime_e2e) — 保留为对照
  └── dispatcher.route() 直接调用不存在的工具名

L1 (subsystem_integration) — 不在本轮
```

## 测试文件

`tests/runtime_integration/test_tool_gate_not_found_l3.py`

---

## T1: core.chat() 触发 not_found 工具获得 L3 evidence

**test name**: `test_t1_core_chat_not_found_tool_l3`

**purpose**: 证明传入不存在的工具名时，TOOL_GATE 通过 core.chat() 真实路径返回 status="rejected" + decision="not_found"，并获得 L3 evidence。

**setup**:
1. 构造 `FakeProvider`（不调用真实 LLM API）
2. 构造 `_PipelineSpy` 包裹 dispatcher，捕获所有 route_from_runtime_loop 调用
3. 设置 `HOME` 为隔离路径
4. **不注册任何测试工具**到 TOOL_REGISTRY（确保工具名不存在）

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="nonexistent__tool__xyz",
)
```

**expected evidence**:
1. spy 捕获到至少 1 次 `route_from_runtime_loop` 调用（TOOL_GATE）
2. TOOL_GATE result:
   - `status == "rejected"`
   - `evidence_level == "real_core_loop_runtime_e2e"`
   - `dispatcher_origin == "runtime_loop"`
   - `core_entrypoint == "core.chat"`
   - `runtime_hook_name == "loop.turn_end"`
   - evidence_extra 中 `decision == "not_found"`
   - payload 中 `gate_disposition` 为 None
   - payload 中 `rejection_reason == "tool not found in production ToolRegistry"`
3. TOOL_INVOKE: **不触发**
4. TOOL_RESULT: **不触发**

**forbidden behavior**:
- TOOL_GATE status 不能是 "success"
- gate_disposition 不能是 "allowed"
- TOOL_INVOKE 不能被触发
- 不能读取 .env
- 不能连接真实 MCP server

**pass/fail criteria**:
- PASS: TOOL_GATE 返回 rejected + not_found + L3 evidence，TOOL_INVOKE/RESULT 不触发
- FAIL: TOOL_GATE 返回 success 或 TOOL_INVOKE 意外触发

---

## T2: hook 级 not_found 工具被正确拒绝（L3 via hook-level）

**test name**: `test_t2_hook_level_not_found_tool_l3`

**purpose**: 补充验证：通过 `_try_phase1_turn_end_runtime_action()` 直接调用，不存在的工具在 TOOL_GATE 被正确拒绝。

**setup**:
1. 构造 `_PipelineSpy` 包裹 dispatcher
2. 构造 mock state
3. 构造 `LoopDependencies(tool_gate_tool_name="nonexistent__tool__xyz", ...)`
4. **不注册任何测试工具**

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
1. TOOL_GATE: `status="rejected"`, `decision="not_found"`, L3 evidence
2. TOOL_INVOKE: 不触发
3. TOOL_RESULT: 不触发

**forbidden behavior**:
- TOOL_GATE 不能返回 success 或 confirmation_required
- TOOL_INVOKE 不能被跳过（应该完全不触发，因为 gate 返回 rejected）

**pass/fail criteria**:
- PASS: TOOL_GATE 正确返回 rejected + not_found，TOOL_INVOKE/RESULT 未触发
- FAIL: TOOL_GATE 返回非 rejected 状态，或 TOOL_INVOKE 意外触发

---

## T3: direct dispatcher.route not_found 保持 L2

**test name**: `test_t3_direct_dispatcher_route_not_found_is_l2`

**purpose**: 验证直接调用 `dispatcher.route(TOOL_GATE, ...)` 时 not_found 只能获得 L2 evidence，不能通过 payload 伪造升级为 L3。

**setup**:
1. 构造 dispatcher（注册 TOOL_GATE handler）
2. **不注册任何测试工具**

**action**:
```python
result = dispatcher.route(RuntimeActionRequest(
    action_type=RuntimeActionType.TOOL_GATE,
    source="test",
    parent_trace_id="",
    payload={
        "tool_name": "nonexistent__tool__xyz",
        "core_loop_invoked": True,       # 伪造
        "core_entrypoint": "core.chat",   # 伪造
        "runtime_hook_name": "loop.turn_end",  # 伪造
    },
))
```

**expected evidence**:
- `evidence_level == "harness_runtime_e2e"`（不是 L3）
- `dispatcher_origin == "direct_dispatcher"`
- evidence_extra 中 `decision == "not_found"`
- payload 中的伪造字段被忽略

**forbidden behavior**:
- 不得因为 payload 中有 `core_loop_invoked: True` 而升级为 L3
- `dispatcher_origin` 不得变为 `"runtime_loop"`

**pass/fail criteria**:
- PASS: evidence_level 严格为 harness_runtime_e2e，payload 伪造无效
- FAIL: evidence 被 payload 字段污染，或 evidence_level 被错误升级

---

## T4: 不读 .env / 不调用真实 API

**test name**: `test_t4_no_real_api_or_env_access`

**purpose**: 验证 not_found pipeline 执行过程中不读取 .env、不调用真实 LLM API。HOME 设为隔离路径。

**setup**:
1. HOME 指向隔离的临时目录
2. FakeProvider + _PipelineSpy

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="nonexistent__tool__xyz",
)
```

**expected evidence**:
- 所有调用完成，无异常
- FakeProvider 被使用
- TOOL_GATE 返回 rejected + not_found

**forbidden behavior**:
- 不读 .env 文件
- 不发起网络请求
- 不启动子进程
- 不调用真实 Anthropic API

**pass/fail criteria**:
- PASS: 所有操作在隔离环境中完成，无外部调用
- FAIL: 任何 .env 读取、网络请求、或子进程启动

---

## T5: 已有 Tool Pipeline L3 测试仍通过（回归）

**test name**: (由已有测试覆盖，非新增)

**purpose**: 验证本轮改动不破坏已有 Tool Pipeline L3 测试。本轮为零代码改动，回归测试应全部通过。

**action**:
```bash
pytest tests/runtime_integration/test_tool_pipeline_l3_completion.py -q
pytest tests/runtime_integration/test_mcp_l3_real_core_loop.py -q
pytest tests/runtime_integration/ -q
```

**pass/fail criteria**:
- PASS: 所有已有测试通过，0 失败
- FAIL: 任何已有测试失败

---

## 测试执行顺序

```
T1 (core.chat L3 not_found) → T2 (hook L3 not_found) → T3 (L2 payload spoof) → T4 (no real API) → T5 (regression)
```

## 禁止模式

- 不新增 Anchor
- 不新增 branch point
- 不新增 runtime flow
- 不新增 fake loop / fake dispatcher / dogfood-only path
- 不让 direct dispatcher.route 冒充 L3
- 不让 payload spoofing 升级 evidence
- 不读 .env
- 不连接真实 MCP server
- 不调用真实 API
- 不修改任何 agent/ 下的生产代码
