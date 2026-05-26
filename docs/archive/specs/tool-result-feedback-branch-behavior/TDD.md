# TDD / Test Plan: Tool Result Feedback Branch Behavior

Status: draft
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
SPEC: [Tool Result Feedback Branch Behavior SPEC](SPEC.md)

## 1. Branch Point 判断

1. **当前任务属于哪个 unified runtime flow branch point？**
   "tool execution / confirmation handling"（Contract §2 已定义）

2. **branch point 是否已存在？**
   是。`RuntimeActionType.TOOL_GATE`（`schema.py:24`）已注册 handler。
   `RuntimeActionType.TOOL_INVOKE`（`schema.py:25`）和
   `RuntimeActionType.TOOL_REQUEST`（`schema.py:23`）已在 schema 定义，
   尚未注册 handler。

3. **这是 branch behavior test，还是需要新增 branch point？**
   这是 branch behavior test。`tool.result` 是 tool execution /
   confirmation handling 下的 branch behavior——
   与 `tool.gate`（pre-execution）互补，负责 post-execution result feedback。

4. **是否需要新增 RuntimeActionType？**
   是——`TOOL_RESULT = "tool.result"`。与 `tool.gate`、`tool.invoke`、
   `tool.request` 共用 `tool.*` 命名空间。新增 RuntimeActionType 不等于
   新增 branch point；`tool.result` 归属的 branch point 已在 Contract §2 定义。

## 2. 测试分层策略

本轮 TDD 定义两层测试（L3 deferred）：

| 层级 | 路径 | 最高分类 | 需 loop 集成？ | 本 TDD 阶段 |
|------|------|---------|--------------|------------|
| L1: Handler Logic | `ToolResultFeedbackHandler.handle()` 直接调用 | `subsystem_integration` | 否 | 全部实现 |
| L2: Harness Dispatcher | `dispatcher.route()` with target proof | `harness_runtime_e2e` | 否 | 全部实现 |
| L3: Real Core Loop | `dispatcher.route_from_runtime_loop()` | `real_core_loop_runtime_e2e` | **是** | DEFERRED |

L3 deferred 原因：loop.py 当前不构造 TOOL_RESULT action。与 memory recall 的
core.py integration deferred 一致。

## 3. 测试矩阵

### Phase A: Result Injection Happy Path (L1/L2, 4 tests)

#### A1: normal result → injected

- **Purpose:** 正常 tool result 被格式化并注入 prompt section
- **Setup:** ToolResultFeedbackHandler(store=None)；
  构造 RuntimeActionRequest(TOOL_RESULT, payload={
    tool_name="_safe_noop", tool_output="tool executed successfully",
    execution_status="success"
  })
- **Action:** handler.handle(request, context)
- **Expected evidence:**
  - status="success"
  - payload.disposition="injected"
  - payload.tool_name="_safe_noop"
  - payload.prompt_section 包含 "tool executed successfully"
  - payload.prompt_section 以 "--- Tool Result ---" 开头
  - evidence.no_side_effects=True
- **Forbidden:** 不修改 TOOL_REGISTRY，不触发 TOOL_GATE，不调用真实工具

#### A2: empty result → empty

- **Purpose:** 空 tool result 返回 placeholder
- **Setup:** tool_output="", execution_status="success"
- **Action:** handler.handle()
- **Expected evidence:**
  - status="success"
  - payload.disposition="empty"
  - payload.prompt_section 包含占位文本（如 "工具执行完成，无输出"）
- **Forbidden:** 不崩溃，不返回 error status

#### A3: long result → truncated

- **Purpose:** 超长 result 按 char budget 截断
- **Setup:** tool_output="x" * 600（超过 500 char budget），execution_status="success"
- **Action:** handler.handle()
- **Expected evidence:**
  - status="success"
  - payload.disposition="truncated"
  - payload.prompt_section 中 result 长度 ≤ 500
  - payload.result_original_size=600
  - payload.prompt_section 以 "…" 结尾标记截断
- **Forbidden:** result 完整 600 字符未截断地出现在 prompt 中

#### A4: error result → error

- **Purpose:** tool 执行出错时，错误信息被注入
- **Setup:** tool_output="command not found", execution_status="error"
- **Action:** handler.handle()
- **Expected evidence:**
  - status="success"
  - payload.disposition="error"
  - payload.prompt_section 包含错误标记
  - payload.execution_status="error"
- **Forbidden:** disposition 不是 "injected"

### Phase B: Empty / Missing Payload (L1, 3 tests)

#### B1: missing tool_name → failed

- **Purpose:** 缺 tool_name 时返回 failed
- **Setup:** payload 不包含 tool_name 字段
- **Action:** handler.handle()
- **Expected evidence:**
  - status="failed"
  - payload.disposition="failed"
- **Forbidden:** 不崩溃

#### B2: missing tool_output → failed

- **Purpose:** 缺 tool_output 时返回 failed
- **Setup:** payload 不包含 tool_output 字段
- **Action:** handler.handle()
- **Expected evidence:**
  - status="failed"
- **Forbidden:** 不崩溃

#### B3: tool_output=None → empty

- **Purpose:** tool_output 为 None 时视为空结果
- **Setup:** tool_output=None（非省略字段，值为 None）
- **Action:** handler.handle()
- **Expected evidence:**
  - payload.disposition="empty"
- **Forbidden:** 不崩溃

### Phase C: No Side Effects (L1/L2, 4 tests)

#### C1: does not modify TOOL_REGISTRY

- **Purpose:** handler 不修改工具注册表
- **Setup:** 记录 TOOL_REGISTRY 快照前后
- **Action:** handler.handle()
- **Expected evidence:** TOOL_REGISTRY 前后一致
- **Forbidden:** TOOL_REGISTRY keys 或值发生变化

#### C2: does not trigger other tool actions

- **Purpose:** TOOL_RESULT 不触发 TOOL_GATE / TOOL_INVOKE
- **Setup:** dispatcher.route(TOOL_RESULT)
- **Action:** 检查 dispatcher.action_log
- **Expected evidence:** action_log 中只有 "tool.result"
- **Forbidden:** "tool.gate"、"tool.invoke"、"tool.request" 不在 action_log 中

#### C3: does not trigger memory actions

- **Purpose:** TOOL_RESULT 不触发任何 memory action
- **Setup:** dispatcher.route(TOOL_RESULT)
- **Action:** 检查 dispatcher.action_log
- **Expected evidence:** action_log 中没有 "memory.*" action
- **Forbidden:** "memory.propose"、"memory.turn_end_proposal"、"memory.recall" 不在 action_log 中

#### C4: is pure format operation

- **Purpose:** handler 是纯格式化操作，无外部副作用
- **Setup:** handler.handle()
- **Action:** 检查 evidence
- **Expected evidence:**
  - evidence.external_side_effects=False
  - evidence.read_only_operation=True
- **Forbidden:** evidence 中无 shell/file/network/MCP 标记

### Phase D: Evidence Classification (L2, 2 tests)

#### D1: dispatcher.route() → harness_runtime_e2e

- **Purpose:** 通过 dispatcher + catalog adapter 达到 L2 分类
- **Setup:** 构建注册了 TOOL_RESULT handler 的 dispatcher；
  dispatcher.route(RuntimeActionRequest(TOOL_RESULT, ...))
- **Action:** 检查 result.evidence
- **Expected evidence:**
  - evidence.target_module_proof 不为 None
  - evidence.target_catalog_allowed=True
  - evidence.evidence_level=HARNESS_RUNTIME_E2E
- **Forbidden:** evidence_level 不是 harness_runtime_e2e

#### D2: direct handler call → subsystem_integration

- **Purpose:** direct handler 调用降级为 subsystem_integration
- **Setup:** 直接构造 handler 和 context（不通过 dispatcher）
- **Action:** handler.handle(request, context)
- **Expected evidence:**
  - evidence_level ≤ harness_runtime_e2e（无 target proof）
- **Forbidden:** 不崩溃

### Phase E: Regression Isolation (L2, 2 tests)

#### E1: TOOL_GATE still registered

- **Purpose:** tool.result 不影响已有 tool.gate handler
- **Setup:** build_phase1_dispatcher()（验证完整 registry）
- **Action:** 检查 dispatcher._registry.snapshot()
- **Expected evidence:**
  - "tool.gate" 在 snapshot 中
  - "tool.result" 在 snapshot 中
  - "memory.recall" 在 snapshot 中
  - "memory.propose" 在 snapshot 中
- **Forbidden:** 已有 handler 被替换

#### E2: existing tool gate tests still pass

- **Purpose:** 已有 tool gate 测试不受影响
- **Setup:** 不修改 ToolGateHandler、phase1_hook
- **Action:** 运行 tool gate 相关测试
- **Expected evidence:** 全部通过
- **Forbidden:** tool gate 测试退化

### Phase F: Negative / Edge Cases (L1, 2 tests)

#### F1: handler with None store graceful

- **Purpose:** store=None 时 handler 不崩溃
- **Setup:** ToolResultFeedbackHandler(store=None)
- **Action:** handler.handle(request, context)
- **Expected evidence:** status="success"，不崩溃
- **Forbidden:** 不因 store 为 None 而崩溃

#### F2: very long tool_name

- **Purpose:** 异常长的 tool_name 不导致格式化崩溃
- **Setup:** tool_name="a" * 500
- **Action:** handler.handle()
- **Expected evidence:** status="success"
- **Forbidden:** 不崩溃，tool_name 完整出现在 payload 中

## 4. 实现顺序

```
U1: TOOL_RESULT RuntimeActionType → schema.py
U2: ToolResultFeedbackHandler → tool_result_feedback.py（新建）
U3: Catalog descriptor + dispatcher registration → evidence.py + phase1_hook.py
U4: 测试文件 → test_tool_result_feedback_branch_behavior.py（新建）
```

Phase A-F 共 17 个测试。

## 5. Pass/Fail Criteria

- [ ] 全部 17 个测试通过
- [ ] ruff check 通过
- [ ] 已有 tool gate tests 不退化（Phase E2）
- [ ] 已有 memory recall/retain tests 不退化
- [ ] 无 TOOL_GATE / MEMORY_PROPOSE / MEMORY_RECALL handler 逻辑被修改
- [ ] runtime_integration 全量测试通过
