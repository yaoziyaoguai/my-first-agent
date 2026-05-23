# Implementation Notes: Tool Result Feedback Branch Behavior

Date: 2026-05-23
Plan: [IMPLEMENTATION_PLAN.md](../specs/tool-result-feedback-branch-behavior/IMPLEMENTATION_PLAN.md)
SPEC: [SPEC.md](../specs/tool-result-feedback-branch-behavior/SPEC.md)
TDD: [TDD.md](../specs/tool-result-feedback-branch-behavior/TDD.md)

## 实现了什么

- **TOOL_RESULT RuntimeActionType** (`agent/runtime_integration/schema.py`): 新增 `tool.result` action type，
  与 TOOL_GATE / TOOL_INVOKE / TOOL_REQUEST 并列
- **ToolResultFeedbackHandler** (`agent/runtime_integration/tool_result_feedback.py`): post-execution tool result
  feedback handler。接收 tool result (tool_name, tool_output, execution_status) →
  通过 catalog adapter (ToolRuntime.format_tool_result) 格式化 result (redact/truncate/error marking) →
  build_tool_result_section 渲染 `--- Tool Result ---` prompt section →
  返回 disposition + prompt_section。纯格式化操作，不修改 TOOL_REGISTRY、不调用真实工具、
  不触发其他 RuntimeAction。
- **catalog descriptor** (`agent/runtime_integration/evidence.py`): 新增 `_tool_result_format_adapter`
  和 `tool.result` descriptor，handler 通过 `context.invoke_registered_target()` 获取
  trusted target_module_proof
- **dispatcher 注册** (`agent/runtime_integration/phase1_hook.py`): `build_phase1_dispatcher()` 中
  注册 `TOOL_RESULT → ToolResultFeedbackHandler`
- **17 个测试** (Phase A-F): `tests/runtime_integration/test_tool_result_feedback_branch_behavior.py`
  - L1 (subsystem_integration): direct handler
  - L2 (harness_runtime_e2e): dispatcher.route() with target_module_proof

## 没做什么

- core.py / loop.py integration (dispatcher 在 tool execution 后构造 TOOL_RESULT action deferred)
- L3 real_core_loop_runtime_e2e 测试
- TOOL_INVOKE / TOOL_REQUEST handler 实现
- Tool retry / error recovery
- Multi Tool / MCP Tool / Streaming tool result
- Real tool execution result processing
- Sensitive content LLM-based detection (只有 regex pattern redact)
- Tool/MCP/Skill/Checkpoint 修改 (beyond necessary dispatcher registration)
- 真实 API / .env / tool episodes 读取

## Plan 未覆盖但执行中做出的决策

### D1. observed_call 必传参数

`context.success()` 的 `observed_call` 参数无默认值。validation failure 路径（B1/B2）
需要传 `observed_call=None`，否则触发 TypeError 被 `_route` 的 except 捕获
转为 `context.failed()`。修复：在 validation 分支中显式传 `observed_call=None`。

### D2. tool_output=None vs missing key 区分

`tool_output` 的 "key 不存在" (None from dict.get()) 和 "值为 None"
(dict 中存在但值为 None) 是不同的语义：
- key 不存在 → "failed" (缺失必填字段)
- 值为 None → "empty" (工具返回了空结果)

修复：用 `"tool_output" not in payload` 区分。

### D3. format_tool_result 拆分

最初计划 handler 直接做格式化，但为了证据分类（L2 harness_runtime_e2e 需要
target_module_proof），将格式化函数拆为独立 `format_tool_result()`，
通过 catalog adapter 调用。与 memory recall 的 `build_memory_snapshot_from_store`
→ `_memory_recall_snapshot_adapter` 模式一致。

## Tradeoffs / Deviations

无架构偏离。实现严格遵循 IMPLEMENTATION_PLAN 的 U1-U4 顺序和 TDD 的 Phase A-F 测试矩阵。

## 回退记录

无回退。一次 TDD cycle 完成（RED: 17 tests written → GREEN: handler + catalog + dispatcher）。
B1/B2/B3 的 `observed_call=None` 修复属于实现层 focused fix，非跨阶段回退。

## Tests / Gates

```
# tool result feedback tests (U4)
17 passed

# regression: memory recall + retain + tool gate
71 passed, 1 skipped (pre-existing)

# runtime_integration full
232 passed, 5 skipped

# full test suite
3017 passed, 19 skipped

# ruff
All checks passed

# git diff --check
clean
```

## Deferred

- **L3 real_core_loop_runtime_e2e**: loop.py 当前不构造 TOOL_RESULT action。
  需要 loop 在 tool execution 完成后构造 TOOL_RESULT action。
- **TOOL_INVOKE / TOOL_REQUEST handler**: schema 已定义但无 handler。
- **工具重试 / 错误恢复**: 工具执行失败后的重试逻辑。
- **Streaming tool result**: 流式输出的增量注入。
