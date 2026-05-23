# Tool Pipeline L3 Completion Implementation Plan

Status: active
Date: 2026-05-23
SPEC: [SPEC.md](SPEC.md)
TDD: [TDD.md](TDD.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## Implementation Units

### U1: Test File (RED first)

**Goal:** 新建 `tests/runtime_integration/test_tool_pipeline_l3_completion.py`，17 个测试覆盖 Phase A-F

**Files:**
- Create: `tests/runtime_integration/test_tool_pipeline_l3_completion.py`

**Patterns to follow:**
- `tests/runtime_integration/test_tool_branch_confirmation_required.py` — B5 的 SpyDispatcher 模式、_try_phase1_turn_end_runtime_action 调用方式
- `tests/runtime_integration/test_tool_invoke_branch_behavior.py` — TOOL_INVOKE handler 直接和 dispatcher 测试模式
- `tests/runtime_integration/test_mcp_runtime_integration.py` — MCP 工具注册 helper

**Execution note:** TDD-first — 先写全部测试，验证 RED（期望 TOOL_INVOKE/TOOL_RESULT 被构造但实际没有）

**Verification:** `pytest tests/runtime_integration/test_tool_pipeline_l3_completion.py -q` — RED（A 组失败，因为 loop.py 尚未修改）

### U2: loop.py Pipeline Completion (GREEN)

**Goal:** 修改 `agent/loop.py` 的 `_try_phase1_turn_end_runtime_action`，在 TOOL_GATE allowed 后构造 TOOL_INVOKE + TOOL_RESULT

**Files:**
- Modify: `agent/loop.py` — `_try_phase1_turn_end_runtime_action` 函数（约 +50 行）

**Approach:**

```
当前结构：
  try: MEMORY action → route()
  try: TOOL_GATE action → route()

目标结构：
  try: MEMORY action → route()
  try: TOOL_GATE action → route() → 捕获 gate_result
  if gate allowed:
    try: TOOL_INVOKE action → route() → 捕获 invoke_result
    if invoke_result:
      try: TOOL_RESULT action → route()
```

**关键设计决策：**

1. **捕获 TOOL_GATE result 以判断 disposition：**
   - `gate_result = route(tool_gate_request)` — 当前丢弃返回值，改为捕获
   - 从 `gate_result.payload.get("gate_disposition")` 判断是否为 "allowed"
   - gate_result 为 None（异常）时跳过后续

2. **TOOL_INVOKE payload 构造：**
   - tool_name: 从 `tool_gate_tool_name` 获取（与 TOOL_GATE 一致）
   - tool_input: 从 TOOL_GATE request 的 tool_args 获取（当前为 {}）
   - source: "core_loop"

3. **TOOL_RESULT payload 构造：**
   - tool_name: 同 TOOL_GATE
   - tool_output: 从 TOOL_INVOKE result 的 payload.tool_output 获取
   - execution_status: 从 TOOL_INVOKE result 的 payload.execution_status 获取

4. **独立 try/except：**
   - 每个 stage 独立 try/except，与 MEMORY / TOOL_GATE 一致
   - TOOL_RESULT 的 try 在 TOOL_INVOKE 的 try 外部——即使 TOOL_INVOKE 抛异常也尝试构造 TOOL_RESULT（报告错误信息）

5. **route_from_runtime_loop：**
   - 三个 stage 使用同一个 `route` callable（已在 TOOL_GATE 中通过 getattr 获取）
   - 保证 dispatcher_origin="runtime_loop" → L3 classification

**Patterns to follow:**
- TOOL_GATE action 构造模式（`_try_phase1_turn_end_runtime_action` 现有代码）
- provider_kind / provider_external_call / external_side_effects 写入 payload 的模式

**Verification:** `pytest tests/runtime_integration/test_tool_pipeline_l3_completion.py -q` — GREEN（17/17）

### U3: Implementation Notes

**Goal:** 记录实现细节、决策、deferred 项

**Files:**
- Create: `docs/implementation-notes/tool-pipeline-l3-completion.md`

**Verification:** 文档完整，覆盖所有 required sections

---

## 允许修改范围

| 文件 | 修改类型 | 最大行数 |
|------|---------|---------|
| `agent/loop.py` | Modify `_try_phase1_turn_end_runtime_action` | ~50 行新增 |
| `tests/runtime_integration/test_tool_pipeline_l3_completion.py` | Create | ~600 行 |
| `docs/implementation-notes/tool-pipeline-l3-completion.md` | Create | ~150 行 |
| `docs/specs/tool-pipeline-l3-completion/SPEC.md` | Created (Phase 1) | — |
| `docs/specs/tool-pipeline-l3-completion/TDD.md` | Created (Phase 2) | — |
| `docs/specs/tool-pipeline-l3-completion/IMPLEMENTATION_PLAN.md` | Created (Phase 3) | — |

## 禁止修改范围

- `agent/core.py` — 不修改
- `agent/runtime_integration/phase1_hook.py` — 不修改（handler 注册不变）
- `agent/runtime_integration/dispatcher.py` — 不修改
- `agent/runtime_integration/tool_gate.py` — 不修改
- `agent/runtime_integration/tool_invoke.py` — 不修改
- `agent/runtime_integration/tool_result_feedback.py` — 不修改
- `agent/runtime_integration/evidence.py` — 不修改
- `agent/runtime_integration/schema.py` — 不修改（不新增 RuntimeActionType）
- `agent/tool_registry.py` — 不修改
- `agent/tools/` — 不修改
- 所有已有测试文件 — 不修改（只新增测试文件）
- `tests/runtime_integration/test_phase1_real_core_loop.py` — 注册 TOOL_INVOKE + TOOL_RESULT handler（+6 行），确保 core.chat() 路径中完整管线可用（approved focused fix: handler 注册不是测试逻辑变更，是与 production 行为一致的接线修正）

---

## Evidence / Classification 边界

### 为什么 TOOL_INVOKE + TOOL_RESULT 能达到 L3

1. 两个 action 在 `_try_phase1_turn_end_runtime_action` 中构造 — 与 TOOL_GATE 同一 hook
2. 通过 `route_from_runtime_loop()` 路由 — dispatcher_origin="runtime_loop"
3. source="core_loop", core_entrypoint="core.chat", runtime_hook_name="loop.turn_end"
4. handler 通过 `context.invoke_registered_target()` 获取 catalog-owned proof
5. `classify_evidence_level()` 检查 dispatcher_origin + runtime_loop_invoked + core_entrypoint + runtime_hook_name → real_core_loop_runtime_e2e

### 为什么不会 overclaim

1. 诚实声明：L3 来自 `_try_phase1_turn_end_runtime_action` → `route_from_runtime_loop`，不是 `core.chat()` 的 model call 路径
2. 与 TOOL_GATE B5 相同路径、相同声明
3. payload 中不伪造 core_loop_invoked — 由 dispatcher 的 route_from_runtime_loop 方法写入 evidence

---

## Fake/Real 边界

- fake provider: LoopDependencies.provider_kind="fake", provider_external_call=False
- real provider: 路径相同，metadata 不同——"real", True
- 同一 `_try_phase1_turn_end_runtime_action` 函数 — 不是 fake/real 双路径
- provider_kind 通过 dependencies 注入，不在 loop.py 中硬编码

---

## Dogfood/Evidence 边界

- 测试调用 `_try_phase1_turn_end_runtime_action`（与生产代码同一函数）→ L3
- 测试直接调用 `dispatcher.route()` → L2（harness_runtime_e2e）
- 测试直接调用 `handler.handle()` → L1（subsystem_integration）
- 不做 dogfood-only path

---

## MCP 影响边界

- 本轮零修改 MCP 代码
- E2 测试验证 MCP 工具通过同一 pipeline
- MCP capability="mcp_tool" 是 TOOL_GATE 元数据维度，不影响 pipeline 结构
- 后续 MCP L3 = 验证 MCP 工具在完整 pipeline 中的行为（pipeline 本身已 L3）

---

## Stop Conditions

| 条件 | 动作 |
|------|------|
| Phase 0 检查失败 | 停止 |
| SPEC review FAIL/BLOCKED/P0/P1 | 停止，Ask User |
| TDD review FAIL/BLOCKED/P0/P1 | 停止，Ask User |
| Plan review FAIL/BLOCKED/P0/P1 | 停止，Ask User |
| Implementation 同一问题修 2 次仍失败 | 停止，Ask User |
| Audit FAIL/BLOCKED/P0/P1 | 停止，Ask User |
| 发现需要改 core.py / 新增 handler / 新增 RuntimeActionType | 停止，回退 SPEC |
| 发现需要改已有测试文件 | 停止，评估 |

---

## Implementation Notes 路径

`docs/implementation-notes/tool-pipeline-l3-completion.md`
