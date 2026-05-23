# Tool Pipeline L3 Completion TDD

Status: active
Date: 2026-05-23
SPEC: [SPEC.md](SPEC.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## Test File

`tests/runtime_integration/test_tool_pipeline_l3_completion.py`

## 测试分层

| 层级 | 分类 | 说明 |
|------|------|------|
| L1 | `subsystem_integration` | direct handler call |
| L2 | `harness_runtime_e2e` | dispatcher.route() |
| L3 | `real_core_loop_runtime_e2e` | _try_phase1_turn_end_runtime_action → route_from_runtime_loop |

---

## Phase A: Full Pipeline L3 Happy Path (3 tests)

### A1: gate allowed → TOOL_INVOKE 被构造

- **test name:** `test_a1_gate_allowed_constructs_tool_invoke`
- **purpose:** 验证 TOOL_GATE 返回 allowed 后，_try_phase1_turn_end_runtime_action 自动构造 TOOL_INVOKE action 并通过 route_from_runtime_loop 路由
- **setup:**
  - 构建 SpyDispatcher（包装真实 build_phase1_dispatcher）
  - 构造 LoopDependencies（tool_gate_tool_name="_safe_noop", provider_kind="fake"）
  - 构造 state（conversation.messages 包含 user message）
- **action:** 调用 `_try_phase1_turn_end_runtime_action(state, "test result", spy, dependencies)`
- **expected evidence:**
  - spy 捕获的 actions 中包含 TOOL_INVOKE
  - TOOL_INVOKE action 通过 route_from_runtime_loop 路由（非 route）
  - TOOL_INVOKE evidence.dispatcher_origin == "runtime_loop"
- **forbidden behavior:**
  - TOOL_INVOKE 不通过 direct dispatcher.route() 路由
  - TOOL_INVOKE 不由测试手工构造 RuntimeActionRequest
- **pass/fail criteria:** spy 捕获到 TOOL_INVOKE action 且 dispatcher_origin="runtime_loop"

### A2: TOOL_INVOKE 完成后构造 TOOL_RESULT

- **test name:** `test_a2_tool_invoke_feeds_tool_result`
- **purpose:** 验证 TOOL_INVOKE 执行完成后，_try_phase1_turn_end_runtime_action 自动构造 TOOL_RESULT action，将 invoke 结果传给 result handler
- **setup:** 同 A1
- **action:** 同 A1
- **expected evidence:**
  - spy 捕获的 actions 中包含 TOOL_RESULT
  - TOOL_RESULT payload.tool_name == "_safe_noop"
  - TOOL_RESULT payload.tool_output 非空（来自 _safe_noop 返回值）
  - TOOL_RESULT payload.execution_status == "success"
- **forbidden behavior:** TOOL_RESULT 不由测试手工构造
- **pass/fail criteria:** spy 捕获到 TOOL_RESULT 且 payload 包含正确的 tool_name + tool_output

### A3: 完整管线三阶段均达到 L3

- **test name:** `test_a3_full_pipeline_all_stages_real_core_loop_e2e`
- **purpose:** 验证 gate → invoke → result 三个 stage 的 evidence_level 均为 real_core_loop_runtime_e2e
- **setup:** 同 A1
- **action:** 同 A1
- **expected evidence:**
  - TOOL_GATE evidence_level == "real_core_loop_runtime_e2e"
  - TOOL_INVOKE evidence_level == "real_core_loop_runtime_e2e"
  - TOOL_RESULT evidence_level == "real_core_loop_runtime_e2e"
  - 所有 action 的 dispatcher_origin == "runtime_loop"
  - 所有 action 的 runtime_loop_invoked == True
  - 所有 action 的 core_entrypoint == "core.chat"
- **forbidden behavior:** 任何 stage 的 evidence_level 不能是 harness_runtime_e2e 或 subsystem_integration
- **pass/fail criteria:** 三个 stage 全部 real_core_loop_runtime_e2e

---

## Phase B: Classification Boundaries (4 tests)

### B1: direct handler call → L1

- **test name:** `test_b1_direct_handler_call_is_subsystem_integration`
- **purpose:** 验证直接调用 ToolInvokeHandler.handle() 不经过 dispatcher，分类为 subsystem_integration
- **setup:** 构造 ToolInvokeHandler + RuntimeActionContext（无 dispatcher route provenance）
- **action:** `handler.handle(request, context)`
- **expected evidence:** evidence_level 不包含 "runtime_e2e"（dispatcher_routed=False 或 target_module_proof 缺失）
- **forbidden behavior:** evidence_level 不能是 real_core_loop_runtime_e2e 或 harness_runtime_e2e
- **pass/fail criteria:** evidence_level 为 subsystem_integration 或更低

### B2: direct dispatcher.route → L2

- **test name:** `test_b2_direct_dispatcher_route_is_harness_runtime_e2e`
- **purpose:** 验证直接调用 dispatcher.route()（非 route_from_runtime_loop），即使有完整 target_module_proof，分类仍为 harness_runtime_e2e
- **setup:** 构造 RuntimeActionRequest(TOOL_INVOKE) → dispatcher.route()
- **action:** `dispatcher.route(request)`
- **expected evidence:** evidence_level == "harness_runtime_e2e"
- **forbidden behavior:** evidence_level 不能是 real_core_loop_runtime_e2e
- **pass/fail criteria:** evidence_level == harness_runtime_e2e

### B3: payload spoofing 不能升级分类

- **test name:** `test_b3_payload_spoofing_cannot_upgrade_to_l3`
- **purpose:** 验证在 payload 中写入 core_loop_invoked=True / core_entrypoint="core.chat" 不能将 direct dispatcher.route() 的分类升级为 L3
- **setup:** 构造 RuntimeActionRequest(TOOL_INVOKE) 并在 payload 中伪造 core_loop_invoked=True
- **action:** `dispatcher.route(request)`（非 route_from_runtime_loop）
- **expected evidence:** evidence_level 仍为 harness_runtime_e2e（非 real_core_loop_runtime_e2e）
- **forbidden behavior:** payload 字段不能升级 evidence_level
- **pass/fail criteria:** evidence_level != real_core_loop_runtime_e2e

### B4: route_from_runtime_loop → L3 确认

- **test name:** `test_b4_route_from_runtime_loop_is_real_core_loop_e2e`
- **purpose:** 验证通过 dispatcher.route_from_runtime_loop() 路由的 TOOL_INVOKE / TOOL_RESULT 可以达到 real_core_loop_runtime_e2e（dispatcher 层 confirmation）
- **setup:** 构造 RuntimeActionRequest → spy.route_from_runtime_loop()
- **action:** `spy.route_from_runtime_loop(request)`
- **expected evidence:** evidence_level == "real_core_loop_runtime_e2e"
- **forbidden behavior:** 无
- **pass/fail criteria:** evidence_level == real_core_loop_runtime_e2e

---

## Phase C: Gate Disposition Controls Pipeline (3 tests)

### C1: confirmation_required → 不构造 TOOL_INVOKE

- **test name:** `test_c1_confirmation_required_does_not_invoke`
- **purpose:** 验证 TOOL_GATE 返回 confirmation_required 时，不构造 TOOL_INVOKE
- **setup:** LoopDependencies(tool_gate_tool_name="_confirmable_noop") → gate 返回 confirmation_required
- **action:** `_try_phase1_turn_end_runtime_action(state, "test", spy, dependencies)`
- **expected evidence:**
  - TOOL_GATE 存在，gate_disposition="confirmation_required"
  - TOOL_INVOKE 不存在
  - TOOL_RESULT 不存在
- **forbidden behavior:** 不因 confirmation_required 而调用工具
- **pass/fail criteria:** 无 TOOL_INVOKE action 产生

### C2: blocked → 不构造 TOOL_INVOKE

- **test name:** `test_c2_blocked_does_not_invoke`
- **purpose:** 验证 TOOL_GATE 返回 blocked 时，不构造 TOOL_INVOKE
- **setup:** 注册一个 confirmation="block" 的工具，LoopDependencies 指向它
- **action:** `_try_phase1_turn_end_runtime_action(state, "test", spy, dependencies)`
- **expected evidence:** TOOL_GATE 存在（rejected），TOOL_INVOKE 不存在
- **forbidden behavior:** blocked 工具不被调用
- **pass/fail criteria:** 无 TOOL_INVOKE action

### C3: not_found → 不构造 TOOL_INVOKE

- **test name:** `test_c3_not_found_does_not_invoke`
- **purpose:** 验证 tool_name 不在 TOOL_REGISTRY 中时，TOOL_GATE 返回 not_found，不构造 TOOL_INVOKE
- **setup:** LoopDependencies(tool_gate_tool_name="nonexistent_tool")
- **action:** `_try_phase1_turn_end_runtime_action(state, "test", spy, dependencies)`
- **expected evidence:** TOOL_GATE 存在（not_found），TOOL_INVOKE 不存在
- **forbidden behavior:** 不存在的工具不被调用
- **pass/fail criteria:** 无 TOOL_INVOKE action

---

## Phase D: Pipeline Error Isolation (2 tests)

### D1: TOOL_INVOKE 失败不阻断 TOOL_RESULT

- **test name:** `test_d1_tool_invoke_failure_does_not_block_tool_result`
- **purpose:** 验证 TOOL_INVOKE handler 抛异常时，异常被捕获，不阻断 TOOL_RESULT 构造
- **setup:** 构造场景使 TOOL_INVOKE 可能失败（例如 tool_name 缺失）——但当前 gate allowed 后 tool 一定存在
- **action:** 验证各个 stage 独立 try/except
- **expected evidence:** TOOL_INVOKE 失败时有 error 记录，pipeline 继续
- **forbidden behavior:** TOOL_INVOKE 异常不向外传播
- **pass/fail criteria:** 异常被隔离

### D2: 各 stage 独立 try/except

- **test name:** `test_d2_each_stage_independent_try_except`
- **purpose:** 验证三个 stage（GATE/INVOKE/RESULT）各自独立 try/except，一个失败不阻断其他
- **setup:** 同 A1
- **action:** 验证代码结构中每个 stage 有独立异常处理
- **expected evidence:** 结构保证（非行为测试——验证 loop.py 中每个 action 构造在独立 try 块中）
- **forbidden behavior:** 不允许一个大 try/except 包住所有 stage
- **pass/fail criteria:** 代码结构满足独立隔离

---

## Phase E: Regression (3 tests)

### E1: 已有 Tool Gate L3 仍正常工作

- **test name:** `test_e1_existing_tool_gate_l3_still_works`
- **purpose:** 验证本轮改动不破坏已有 TOOL_GATE B5 L3 行为
- **setup:** 与 test_tool_branch_confirmation_required.py B5 相同
- **action:** 同 B5
- **expected evidence:** TOOL_GATE evidence_level 仍为 real_core_loop_runtime_e2e
- **forbidden behavior:** TOOL_GATE L3 退化
- **pass/fail criteria:** TOOL_GATE 达到 L3

### E2: MCP 工具通过同一 pipeline 获得 L3

- **test name:** `test_e2_mcp_tool_rides_pipeline_l3`
- **purpose:** 验证 MCP 工具（capability="mcp_tool"）通过同一 pipeline 验证——TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
- **setup:**
  - 注册 FakeMCPClient 工具（复用 test_mcp_runtime_integration.py helper）
  - LoopDependencies(tool_gate_tool_name="mcp__demo_a1__hello")
- **action:** `_try_phase1_turn_end_runtime_action(state, "test", spy, dependencies)`
- **expected evidence:**
  - TOOL_GATE 识别 capability="mcp_tool"（元数据维度）
  - TOOL_INVOKE 执行 MCP 工具（通过 FakeMCPClient）
  - TOOL_RESULT 格式化 MCP 结果
  - 三个 stage 均达到 L3
- **forbidden behavior:**
  - 不新增 MCP 专用 branch point
  - 不新增 MCP 专用 handler
  - MCP 工具不走出与本地工具不同的 pipeline
- **pass/fail criteria:** MCP 工具通过同一 pipeline 达到 L3

### E3: 不读 .env / 不调用真实 API

- **test name:** `test_e3_no_real_api_or_env_access`
- **purpose:** 验证 pipeline 执行过程中不访问 .env、不调用真实 API
- **setup:** 同 A1
- **action:** pipeline 执行
- **expected evidence:** 所有调用均通过 fake provider / fake store / internal tool
- **forbidden behavior:** 任何 .env 读取、真实 HTTP 调用
- **pass/fail criteria:** 无异常（如果误读了 .env 会因 HOME 隔离而失败）

---

## Phase F: Pipeline 结构约束 (2 tests)

### F1: lifecycle stages 不被称为子系统

- **test name:** `test_f1_stages_are_not_subsystems`
- **purpose:** 文档/注释约束验证——代码和注释中不将 ToolGate/Invoke/Result 称为三个独立子系统
- **setup:** grep 关键代码和注释
- **action:** 检查新代码中的术语
- **expected evidence:** 使用 "lifecycle stage" / "pipeline phase" / "runtime action handler"
- **forbidden behavior:** "三个子系统" / "three subsystems" / "Tool Invoke 子系统"
- **pass/fail criteria:** 术语一致

### F2: pipeline 不引入第二套主流程

- **test name:** `test_f2_no_second_tool_pipeline`
- **purpose:** 验证没有新增 dispatcher / handler 注册路径 / tool execution entry point
- **setup:** 检查 phase1_hook.py / dispatcher.py 未变
- **action:** git diff 验证只改了 loop.py + 测试文件 + docs
- **expected evidence:** 无新增 handler 注册、无新增 dispatcher、无新增 RuntimeActionType
- **forbidden behavior:** 任何第二套 tool pipeline
- **pass/fail criteria:** 修改范围限定

---

## 禁止行为总表

| 禁止行为 | 验证测试 |
|---------|---------|
| direct handler call 冒充 L3 | B1 |
| direct dispatcher.route 冒充 L3 | B2 |
| payload spoofing 升级分类 | B3 |
| confirmation_required 时 invoke | C1 |
| blocked 时 invoke | C2 |
| not_found 时 invoke | C3 |
| 一个大 try/except 包所有 stage | D2 |
| 新增 branch point / Anchor | F2 |
| MCP 专用 pipeline | E2 |
| .env / 真实 API | E3 |

---

## 测试数量

| Phase | 测试数 | 说明 |
|-------|:------:|------|
| A — Happy Path | 3 | 完整管线 L3 |
| B — Classification | 4 | L1/L2/L3 边界 |
| C — Gate Disposition | 3 | 非 allowed 不 invoke |
| D — Error Isolation | 2 | 独立 try/except |
| E — Regression | 3 | 已有行为 + MCP + 安全 |
| F — 结构约束 | 2 | 术语 + 单一路径 |
| **Total** | **17** | |
