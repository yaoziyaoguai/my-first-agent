# Tool Pipeline L3 Completion — Implementation Notes

Status: completed
Date: 2026-05-23
SPEC: [SPEC.md](../specs/tool-pipeline-l3-completion/SPEC.md)
TDD: [TDD.md](../specs/tool-pipeline-l3-completion/TDD.md)
Plan: [IMPLEMENTATION_PLAN.md](../specs/tool-pipeline-l3-completion/IMPLEMENTATION_PLAN.md)

## 实现了什么

在 `agent/loop.py` 的 `_try_phase1_turn_end_runtime_action` 中补齐了 Tool lifecycle pipeline 的后两个 stage：

- **TOOL_INVOKE**: TOOL_GATE 返回 `gate_disposition="allowed"` 后，自动构造 TOOL_INVOKE RuntimeActionRequest 并通过 `route_from_runtime_loop` 路由，执行已注册工具函数
- **TOOL_RESULT**: TOOL_INVOKE 完成后，提取 `tool_output` + `execution_status`，构造 TOOL_RESULT RuntimeActionRequest 并通过同一路径路由，格式化工具结果为 prompt section

三个 stage (GATE → INVOKE → RESULT) 均达到 `real_core_loop_runtime_e2e`（L3）evidence level。

## 没做什么

- 未修改 `agent/core.py`、`agent/runtime_integration/` 下任何 handler/dispatcher/evidence 代码
- 未新增 RuntimeActionType
- 未新增 handler、dispatcher、branch point
- 未新增 MCP 专用 pipeline（MCP 工具通过同一管线验证，见 E2 测试）
- 未做 Policy re-eval、Retry/Error Recovery、Multi Tool、UI confirmation
- `test_phase1_real_core_loop.py` 仅做 handler 注册补充（+6 行）——不是测试逻辑变更，是与 production 行为一致的接线修正

## 复用的原 Tool 代码

所有 handler、ToolRegistry、execute_tool、dispatcher、evidence/adapter 全部复用，零修改。

## 关键技术决策

### 1. gate_result 捕获

TOOL_GATE 的 `route()` 调用原本丢弃返回值，改为捕获 `gate_result`，通过 `gate_result.payload["gate_disposition"]` 判断是否为 "allowed"。

### 2. 独立 try/except

四个 stage（MEMORY / TOOL_GATE / TOOL_INVOKE / TOOL_RESULT）各自独立 try/except。TOOL_INVOKE 的 try 嵌套在 `if gate allowed` 内（缩进更深），TOOL_RESULT 的 try 在 TOOL_INVOKE try 外部。

### 3. tool_input 传递

当前实现中 `tool_input` 使用 `{}`（_safe_noop 是 zero-arg tool）。未来带参数工具需要从 TOOL_GATE request 的 tool_args 传递真实参数。

### 4. TOOL_RESULT 仅在 invoke_result 非 None 时构造

如果 TOOL_INVOKE 抛异常导致 invoke_result=None，跳过 TOOL_RESULT。未来可扩展为即使 invoke 失败也构造 RESULT（带 execution_status="error"）。

## Tradeoffs / Deviations

- **Model call 路径 L3 未覆盖**: L3 来自 `_try_phase1_turn_end_runtime_action → route_from_runtime_loop` 的 dispatcher 层 provenance，不是 `core.chat()` 的 model call 路径。完整语义需要 provider + tool_use response chain，已 deferred。
- **test_phase1_real_core_loop.py 需要注册新 handler**: 该测试调用 `core.chat()` 验证真实接线，需要 TOOL_INVOKE + TOOL_RESULT handler 注册，否则这些 stage 会得到 not_supported 状态并降级。

## Tests/Gates

- 新增 `test_tool_pipeline_l3_completion.py`: 17/17 pass
- 回归 `test_tool_branch_confirmation_required.py`: 22/22 pass
- 回归 `test_tool_invoke_branch_behavior.py`: 19/19 pass
- 回归 `test_tool_result_feedback_branch_behavior.py`: 17/17 pass
- 回归 `test_mcp_runtime_integration.py`: 19/19 pass
- 回归 `test_phase1_real_core_loop.py`: 15/15 pass
- Full suite: 3072 passed, 19 skipped, 0 failed
- Ruff: all checks passed

## 修改文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `agent/loop.py` | Modify | `_try_phase1_turn_end_runtime_action` 新增 TOOL_INVOKE + TOOL_RESULT 构造（~60 行） |
| `tests/runtime_integration/test_tool_pipeline_l3_completion.py` | Create | 17 测试，~800 行 |
| `tests/runtime_integration/test_phase1_real_core_loop.py` | Modify | `_build_phase1_dispatcher` 注册 TOOL_INVOKE + TOOL_RESULT handler（+6 行） |
| `docs/specs/tool-pipeline-l3-completion/SPEC.md` | Create | 规格说明 |
| `docs/specs/tool-pipeline-l3-completion/TDD.md` | Create | 测试计划 |
| `docs/specs/tool-pipeline-l3-completion/IMPLEMENTATION_PLAN.md` | Create | 实现计划 |

## Deferred 项

- Model call 路径 L3（需要 provider + tool_use response chain）
- MCP resources / prompts / policy re-eval
- Retry / Error Recovery
- Multi Tool
- UI confirmation flow

## MCP 后续影响

MCP 工具通过同一 pipeline 验证（E2 测试：`test_e2_mcp_tool_rides_pipeline_l3`）。MCP L3 自然跟随 Tool pipeline L3，不需要修改 MCP 代码。

## Focused Remediation (2026-05-23)

Independent audit of commit `ab66b9d` found three issues, all remediated:

### P1: Overclaim fix — A4 core.chat() test

**Finding:** 原 17 个测试主要直接调用 `_try_phase1_turn_end_runtime_action()`（hook 级），缺少通过 `core.chat()` 路径的有序管线验证。

**Fix:** 新增 `test_a4_full_core_chat_path_ordered_pipeline_l3`，使用 `core.chat()` + `FakeProvider` + `SpyDispatcher` 验证完整 `core.chat → run_main_loop → hook → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT` 有序序列，全部达到 L3。

**为什么不是 overclaim 了:**
- hook 级测试（A1-A3）证明 dispatcher provenance 完整
- core.chat() 级测试（A4）证明真实 core loop 接线存在
- 两者互补，文档和注释诚实标明各自证明范围

### P2: Safety fix — execution_status 不再无条件默认 "success"

**Finding:** `agent/loop.py` TOOL_RESULT 构造中 `execution_status` 无条件默认为 `"success"`，即使 `invoke_result.status != "success"`。

**Fix:** 检查 `invoke_result.status`：若为 `"success"` 则使用 payload 中的 execution_status，否则强制 `"error"`。

**新增测试:**
- D3: 抛异常工具 → invoke_result.status="failed" → TOOL_RESULT execution_status="error"
- D4: 成功工具 → invoke_result.status="success" → TOOL_RESULT execution_status="success"

### P3: Docs fix — test_phase1 handler registration

**Finding:** IMPLEMENTATION_PLAN.md 声称"所有已有测试文件不修改"，但 `test_phase1_real_core_loop.py` 做了 handler 注册补充。

**Fix:** 更新 IMPLEMENTATION_PLAN.md 和本文件，标注这是 approved focused fix（handler 注册是接线修正，非测试逻辑变更）。

### Remediation 修改文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `agent/loop.py` | Modify | P2: execution_status 逻辑修正（~5 行） |
| `tests/runtime_integration/test_tool_pipeline_l3_completion.py` | Modify | P1: A4 测试（~80 行），P2: D3/D4 测试（~90 行） |
| `docs/specs/tool-pipeline-l3-completion/IMPLEMENTATION_PLAN.md` | Modify | P3: 标注 test_phase1 handler 注册修正 |
| `docs/implementation-notes/tool-pipeline-l3-completion.md` | Modify | 本文件，新增 remediation 记录 |
