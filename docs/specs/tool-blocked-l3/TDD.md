# TDD: Tool Gate blocked L3

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 测试分层

```
L3 (real_core_loop_runtime_e2e) — 本轮目标
  └── core.chat() → route_from_runtime_loop() → TOOL_GATE blocked/rejected

L2 (harness_runtime_e2e) — 保留为对照
  └── dispatcher.route() 直接调用被 blocked 的工具名

L1 (subsystem_integration) — 不在本轮
```

## 测试文件

`tests/runtime_integration/test_tool_blocked_l3.py`

---

## T1: core.chat() 触发 shell-like 工具 blocked 获得 L3 evidence

**test name**: `test_t1_core_chat_shell_like_tool_blocked_l3`

**purpose**: 证明传入 shell-like 工具名（bash/shell/run_shell）时，TOOL_GATE 通过 core.chat() 真实路径返回 status="rejected" + decision="rejected"，并获得 L3 evidence。

**setup**:
1. 构造 `FakeProvider`（不调用真实 LLM API）
2. 构造 `_PipelineSpy` 包裹 dispatcher（通过 `build_phase1_dispatcher()` 构建）
3. HOME 设为隔离路径

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="bash",
)
```

**expected evidence**:
1. spy 捕获到 TOOL_GATE action
2. TOOL_GATE result:
   - `status == "rejected"`
   - `evidence_level == "real_core_loop_runtime_e2e"`
   - `dispatcher_origin == "runtime_loop"`
   - `core_entrypoint == "core.chat"`
   - `runtime_hook_name == "loop.turn_end"`
   - evidence_extra 中 `decision == "rejected"`
   - payload 中 `gate_disposition == "rejected"`
   - payload 中 `rejection_reason == "shell-like tool is out of scope"`
   - payload 中 `risk_level == "high"`
3. TOOL_INVOKE: **不触发**
4. TOOL_RESULT: **不触发**

**forbidden behavior**:
- TOOL_GATE status 不能是 "success"
- gate_disposition 不能是 "allowed" 或 "confirmation_required"
- TOOL_INVOKE 不能被触发
- 不能读取 .env

**pass/fail criteria**:
- PASS: TOOL_GATE 返回 rejected + decision="rejected" + shell-like rejection_reason + L3 evidence
- FAIL: TOOL_GATE 返回 success 或 TOOL_INVOKE 意外触发

---

## T2: core.chat() 触发 _ 前缀非 allowlist 工具 blocked 获得 L3 evidence

**test name**: `test_t2_core_chat_underscore_tool_blocked_l3`

**purpose**: 证明传入 `_` 前缀但不在 allowlist（_safe_noop/_confirmable_noop）中的工具名时，TOOL_GATE 返回 rejected + L3 evidence。

**setup**:
1. 使用 `register_tool` 注册 `_blocked_tool` 到 TOOL_REGISTRY（使 entry 不为 None，越过 not_found 路径）
2. `_blocked_tool` 不在 allowlist 中
3. 构造 `FakeProvider` + `_PipelineSpy`
4. HOME 隔离路径

**action**:
```python
@register_tool(
    name="_blocked_tool",
    description="internal test tool for blocked path",
    parameters={},
    confirmation="always",
    capability="local_action",
    risk_level="low",
)
def _blocked_tool_func():
    pass

chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="_blocked_tool",
)
```

**expected evidence**:
1. TOOL_GATE result:
   - `status == "rejected"`
   - `evidence_level == "real_core_loop_runtime_e2e"`
   - `decision == "rejected"`
   - `gate_disposition == "rejected"`
   - `rejection_reason == "internal tool is not in tool gate allowlist"`
2. TOOL_INVOKE: 不触发
3. TOOL_RESULT: 不触发

**forbidden behavior**:
- TOOL_GATE status 不能是 "success"
- gate_disposition 不能是 "allowed"
- TOOL_INVOKE 不触发

**pass/fail criteria**:
- PASS: TOOL_GATE 返回 rejected + L3 evidence，TOOL_INVOKE 不触发
- FAIL: TOOL_GATE 返回 success 或 TOOL_INVOKE 意外触发

---

## T3: direct dispatcher.route blocked 保持 L2

**test name**: `test_t3_direct_dispatcher_route_blocked_is_l2`

**purpose**: 验证直接调用 `dispatcher.route(TOOL_GATE, ...)` 时 blocked 只能获得 L2 evidence，不能通过 payload 伪造升级为 L3。

**setup**:
1. 构造 dispatcher（注册 ToolGateHandler）

**action**:
```python
result = dispatcher.route(RuntimeActionRequest(
    action_type=RuntimeActionType.TOOL_GATE,
    source="test",
    parent_trace_id="",
    payload={
        "tool_name": "bash",
        "core_loop_invoked": True,        # 伪造
        "core_entrypoint": "core.chat",    # 伪造
        "runtime_hook_name": "loop.turn_end",  # 伪造
    },
))
```

**expected evidence**:
- `evidence_level == "harness_runtime_e2e"`（不是 L3）
- `dispatcher_origin == "direct_dispatcher"`
- evidence_extra 中 `decision == "rejected"`
- payload 中的伪造字段被忽略

**forbidden behavior**:
- 不得因 payload 中有 `core_loop_invoked: True` 而升级为 L3
- `dispatcher_origin` 不得变为 `"runtime_loop"`

**pass/fail criteria**:
- PASS: evidence_level 严格为 harness_runtime_e2e，payload 伪造无效
- FAIL: evidence 被 payload 字段污染

---

## T4: 不读 .env / 不调用真实 API

**test name**: `test_t4_no_real_api_or_env_access`

**purpose**: 验证 blocked pipeline 执行过程中不读取 .env、不调用真实 LLM API。

**setup**:
1. HOME 指向隔离的临时目录
2. FakeProvider + _PipelineSpy

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
    tool_gate_tool_name="bash",
)
```

**expected evidence**:
- 所有调用完成，无异常
- FakeProvider 被使用
- TOOL_GATE 返回 rejected + decision="rejected"

**forbidden behavior**:
- 不读 .env 文件
- 不发起网络请求
- 不调用真实 Anthropic API

**pass/fail criteria**:
- PASS: 所有操作在隔离环境中完成，无外部调用
- FAIL: 任何 .env 读取、网络请求、或真实 API 调用

---

## T5: 已有 Tool/Memory/Checkpoint Pipeline L3 测试仍通过（回归）

**test name**: (由已有测试覆盖，非新增)

**purpose**: 验证本轮改动不破坏已有 L3 测试。

**action**:
```bash
pytest tests/runtime_integration/ -q
```

**pass/fail criteria**:
- PASS: 所有已有测试通过，0 新增失败
- FAIL: 任何已有测试失败

---

## 测试执行顺序

```
T1 (core.chat L3 shell-like blocked) → T2 (core.chat L3 _ prefix blocked) → T3 (L2 payload spoof) → T4 (no real API) → T5 (regression)
```

## 禁止模式

- 不新增 Anchor
- 不新增 branch point
- 不新增 runtime flow
- 不新增 RuntimeActionType
- 不新增 handler
- 不让 direct dispatcher.route 冒充 L3
- 不让 payload spoofing 升级 evidence
- 不读 .env
- 不连接真实 MCP server
- 不调用真实 API
- 不修改任何 agent/ 下的生产代码
