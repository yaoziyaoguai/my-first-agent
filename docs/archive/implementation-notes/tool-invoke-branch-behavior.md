# Implementation Notes: Tool Invoke Branch Behavior

Date: 2026-05-23
Plan: [IMPLEMENTATION_PLAN.md](../specs/tool-invoke-branch-behavior/IMPLEMENTATION_PLAN.md)
SPEC: [SPEC.md](../specs/tool-invoke-branch-behavior/SPEC.md)
TDD: [TDD.md](../specs/tool-invoke-branch-behavior/TDD.md)

## 实现了什么

- **ToolInvokeHandler** (`agent/runtime_integration/tool_invoke.py`): 工具执行 handler。
  接收 tool_name + tool_input → 查找 TOOL_REGISTRY → 通过 catalog adapter
  (ToolRegistry.execute_tool) 执行工具函数 → 返回 tool_output + execution_status + evidence。
  与 ToolGateHandler (pre-execution gating) 和 ToolResultFeedbackHandler (post-execution
  feedback) 并列，完成 tool.gate → tool.invoke → tool.result 工具生命周期管线。
- **_tool_invoke_adapter** (`agent/runtime_integration/evidence.py`): catalog-owned
  adapter。调用 execute_tool() 执行工具函数，返回结构化数据（found, tool_output,
  execution_status, risk_level, capability）。
- **catalog descriptor** (`agent/runtime_integration/evidence.py`): 替换原有 tool.invoke
  占位 descriptor（指向 ToolGateHandler/lookup_and_risk_check）为
  ToolInvokeHandler/execute_tool。移除 DogfoodFakeToolOverlay 的 tool.invoke descriptor
  （TOOL_INVOKE 不需要 dogfood overlay block——那是 TOOL_GATE 的职责）。
- **dispatcher 注册** (`agent/runtime_integration/phase1_hook.py`): build_phase1_dispatcher()
  中注册 TOOL_INVOKE → ToolInvokeHandler。
- **19 个测试** (Phase A-F): `tests/runtime_integration/test_tool_invoke_branch_behavior.py`
  - L1 (subsystem_integration): direct handler
  - L2 (harness_runtime_e2e): dispatcher.route() with target_module_proof

## 没做什么

- core.py / loop.py integration (dispatcher 在 tool execution 时构造 TOOL_INVOKE action deferred)
- L3 real_core_loop_runtime_e2e 测试
- TOOL_GATE 的 policy 检查在 TOOL_INVOKE 中重复（那属于 gate 的职责）
- Tool result formatting（那是 TOOL_RESULT 的职责）
- Tool retry / error recovery
- Multi Tool / MCP Tool / Streaming tool invoke
- Real tool execution（只通过 fake/_safe_noop 测试）
- 真实 API / .env / tool episodes 读取

## Plan 未覆盖但执行中做出的决策

### D1. dangerous_tool_function_invoked 基于 risk_level

高风险工具（risk_level="high"）标记 dangerous_tool_function_invoked=True，
中/低风险工具为 False。与 ToolGateHandler 中的 risk_check 逻辑保持一致。

### D2. external_side_effects 基于 capability

external_side_effects 基于 capability 判断：file_write, command_execution,
network_fetch 标记为有外部副作用。local_action 等不会产生外部副作用。
与 ToolGateHandler 的 evidence_extra 标注保持一致的词表定义。

### D3. tool.invoke catalog descriptor 清理

原有证据中 tool.invoke 有两个占位 descriptor（ToolRegistry/lookup_and_risk_check
和 DogfoodFakeToolOverlay/block），都指向 ToolGateHandler。这些是 schema.py 中
TOOL_INVOKE 定义时的占位——因为当时没有 ToolInvokeHandler。现在替换为正确的
ToolInvokeHandler → ToolRegistry.execute_tool descriptor。DogfoodFakeToolOverlay
的 tool.invoke descriptor 被移除——TOOL_INVOKE 不需要 dogfood overlay（那是
TOOL_GATE 的职责）。

### D4. tool_input 必填但不验证内容

handler 验证 tool_input 字段是否存在（B2: missing field check），但不验证
tool_input 的内容是否与目标工具的参数 schema 匹配。参数验证属于 tool_registry
执行层（execute_tool → _dispatch_tool_function → func(**tool_input)）。

## Tradeoffs / Deviations

无架构偏离。实现严格遵循 IMPLEMENTATION_PLAN 的 U1-U4 顺序和 TDD 的 Phase A-F 测试矩阵。

## 回退记录

无回退。一次 TDD cycle 完成（RED: 1 error → GREEN: 19/19 passed，含 1 次 test fix）。

## Tests / Gates

```
# tool invoke tests (U4)
19 passed

# regression: tool confirmation + tool result + tool invoke
58 passed

# runtime_integration full
251 passed, 5 skipped

# full test suite
3036 passed, 19 skipped

# ruff
All checks passed

# git diff --check
clean
```

## Deferred

- **L3 real_core_loop_runtime_e2e**: loop.py 当前不构造 TOOL_INVOKE action。
  需要 loop 在 tool execution 环节构造 TOOL_INVOKE action。
- **参数 schema 验证**: handler 当前不验证 tool_input 与工具参数 schema 的匹配。
- **工具重试 / 错误恢复**: 工具执行失败后的重试逻辑。
- **Streaming tool invoke**: 流式输出的增量执行。
