# TDD: Checkpoint Save/Resume L3

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 测试分层

```
L3 (real_core_loop_runtime_e2e) — 本轮目标
  └── core.chat() → route_from_runtime_loop() → CHECKPOINT_SAFE_SUMMARY

L2 (harness_runtime_e2e) — 保留为对照
  └── dispatcher.route() 直接调用 CHECKPOINT_SAFE_SUMMARY

L1 (subsystem_integration) — 不在本轮
```

## 测试文件

`tests/runtime_integration/test_checkpoint_save_resume_l3.py`

---

## T1: core.chat() turn-end 触发 CHECKPOINT_SAFE_SUMMARY 获得 L3 evidence

**test name**: `test_t1_core_chat_checkpoint_safe_summary_l3`

**purpose**: 证明 core.chat() 完整路径中 turn-end hook 正确 dispatch CHECKPOINT_SAFE_SUMMARY，获得 L3 evidence。

**setup**:
1. 构造 `FakeProvider`（不调用真实 LLM API）
2. 构造 `_PipelineSpy` 包裹 dispatcher（通过 `build_phase1_dispatcher()` 构建，含 CheckpointSafeSummaryHandler）
3. HOME 设为隔离路径

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
)
```

**expected evidence**:
1. spy 捕获到 CHECKPOINT_SAFE_SUMMARY action
2. CHECKPOINT_SAFE_SUMMARY result:
   - `status == "success"`
   - `evidence_level == "real_core_loop_runtime_e2e"`
   - `dispatcher_origin == "runtime_loop"`
   - `core_entrypoint == "core.chat"`
   - `runtime_hook_name == "loop.turn_end"`
   - `runtime_loop_invoked == True`
3. payload 中:
   - `safe_summary` 存在
   - `checkpoint_boundary == "turn_end_before_save_checkpoint"`
   - `secret_content_detected` 为 bool
4. target_module 为 `"CheckpointSafeSummary"`

**forbidden behavior**:
- evidence_level 不能是 `harness_runtime_e2e` 或更低
- dispatcher_origin 不能是 `direct_dispatcher`
- 不能读取 .env
- 不能连接真实 MCP server

**pass/fail criteria**:
- PASS: CHECKPOINT_SAFE_SUMMARY 返回 success + L3 evidence，target_module 正确
- FAIL: CHECKPOINT_SAFE_SUMMARY 未触发或 evidence_level 低于 L3

---

## T2: hook 级 CHECKPOINT_SAFE_SUMMARY 独立 dispatch

**test name**: `test_t2_hook_level_checkpoint_safe_summary_l3`

**purpose**: 补充验证：通过 `_try_phase1_turn_end_runtime_action()` 直接调用，CHECKPOINT_SAFE_SUMMARY 被正确 dispatch。

**setup**:
1. 构造 `_PipelineSpy` 包裹 dispatcher（含 CheckpointSafeSummaryHandler）
2. 构造 mock state
3. 构造 `LoopDependencies`

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
1. CHECKPOINT_SAFE_SUMMARY: `status="success"`, L3 evidence
2. checkpoint_boundary 正确
3. target_module 为 `"CheckpointSafeSummary"`

**forbidden behavior**:
- CHECKPOINT_SAFE_SUMMARY 不能 absent
- evidence_level 不能低于 L3

**pass/fail criteria**:
- PASS: CHECKPOINT_SAFE_SUMMARY 正确返回 success + L3 evidence
- FAIL: CHECKPOINT_SAFE_SUMMARY 未触发或 evidence 级别不足

---

## T3: direct dispatcher.route CHECKPOINT_SAFE_SUMMARY 保持 L2

**test name**: `test_t3_direct_dispatcher_route_checkpoint_safe_summary_is_l2`

**purpose**: 验证直接调用 `dispatcher.route(CHECKPOINT_SAFE_SUMMARY, ...)` 时只能获得 L2 evidence，不能通过 payload 伪造升级为 L3。

**setup**:
1. 构造 dispatcher（注册 CheckpointSafeSummaryHandler）

**action**:
```python
result = dispatcher.route(RuntimeActionRequest(
    action_type=RuntimeActionType.CHECKPOINT_SAFE_SUMMARY,
    source="test",
    parent_trace_id="",
    payload={
        "runtime_state_summary": "test summary",
        "trigger": "turn_end",
        "core_loop_invoked": True,        # 伪造
        "core_entrypoint": "core.chat",    # 伪造
        "runtime_hook_name": "loop.turn_end",  # 伪造
    },
))
```

**expected evidence**:
- `evidence_level == "harness_runtime_e2e"`（不是 L3）
- `dispatcher_origin == "direct_dispatcher"`
- payload 中的伪造字段被忽略（不在 evidence 中出现为 L3 标记）

**forbidden behavior**:
- 不得因为 payload 中有 `core_loop_invoked: True` 而升级为 L3
- `dispatcher_origin` 不得变为 `"runtime_loop"`

**pass/fail criteria**:
- PASS: evidence_level 严格为 harness_runtime_e2e，payload 伪造无效
- FAIL: evidence 被 payload 字段污染，或 evidence_level 被错误升级

---

## T4: 不读 .env / 不调用真实 API

**test name**: `test_t4_no_real_api_or_env_access`

**purpose**: 验证 checkpoint safe summary pipeline 执行过程中不读取 .env、不调用真实 LLM API。

**setup**:
1. HOME 指向隔离的临时目录
2. FakeProvider + _PipelineSpy

**action**:
```python
chat(
    "hello",
    provider=FakeProvider(),
    runtime_action_dispatcher=spy,
)
```

**expected evidence**:
- 所有调用完成，无异常
- FakeProvider 被使用
- CHECKPOINT_SAFE_SUMMARY 返回 success

**forbidden behavior**:
- 不读 .env 文件
- 不发起网络请求
- 不调用真实 Anthropic API

**pass/fail criteria**:
- PASS: 所有操作在隔离环境中完成，无外部调用
- FAIL: 任何 .env 读取、网络请求、或真实 API 调用

---

## T5: 已有 Tool/Memory Pipeline L3 测试仍通过（回归）

**test name**: (由已有测试覆盖，非新增)

**purpose**: 验证本轮改动不破坏已有 Tool Pipeline L3 测试和 Memory Pipeline L3 测试。

**action**:
```bash
pytest tests/runtime_integration/test_tool_pipeline_l3_completion.py -q
pytest tests/runtime_integration/test_mcp_l3_real_core_loop.py -q
pytest tests/runtime_integration/test_memory_retain_branch_behavior.py -q
pytest tests/runtime_integration/test_memory_recall_branch_behavior.py -q
pytest tests/runtime_integration/ -q
```

**pass/fail criteria**:
- PASS: 所有已有测试通过，0 失败
- FAIL: 任何已有测试失败

---

## 测试执行顺序

```
T1 (core.chat L3 checkpoint) → T2 (hook L3 checkpoint) → T3 (L2 payload spoof) → T4 (no real API) → T5 (regression)
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
- 不修改 checkpoint schema
