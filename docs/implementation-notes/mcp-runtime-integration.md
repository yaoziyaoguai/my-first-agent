# Implementation Notes: MCP Runtime Integration

Date: 2026-05-23
SPEC: [../specs/mcp-runtime-integration/SPEC.md](../specs/mcp-runtime-integration/SPEC.md)
TDD: [../specs/mcp-runtime-integration/TDD.md](../specs/mcp-runtime-integration/TDD.md)
Plan: [../specs/mcp-runtime-integration/IMPLEMENTATION_PLAN.md](../specs/mcp-runtime-integration/IMPLEMENTATION_PLAN.md)

## 实现了什么

### U1: MCP Tool Orchestrator

`agent/runtime_integration/mcp_tool_orchestrator.py` — thin composition layer，串联已有 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT handler。

- `run_mcp_tool_pipeline(dispatcher, tool_name, tool_input)` — 编排三个已有 handler 的调用
- `MCPPipelineResult` — 不可变 dataclass，包含 gate_result / invoke_result / result_feedback / action_log_entries / stopped_early / stop_reason
- 编排逻辑：TOOL_GATE → gate blocked/not_found 则提前终止 → TOOL_INVOKE → TOOL_RESULT
- orchestrator 不是 dispatcher handler、不注册新的 RuntimeActionType、不新增 Anchor/branch point/runtime flow

### U2: Test File

`tests/runtime_integration/test_mcp_runtime_integration.py` — 18 个测试，6 个 Phase (A-F)。

- Phase A (3 tests): MCP 工具通过 TOOL_GATE 被 lookup 和 gating
- Phase B (4 tests): MCP 工具通过 TOOL_INVOKE handler 被实际执行
- Phase C (2 tests): MCP 工具执行结果通过 TOOL_RESULT handler 格式化
- Phase D (3 tests): orchestrator 串联完整管线
- Phase E (4 tests): 负例和边界测试
- Phase F (2 tests): 回归隔离

## 没做什么

- 不修改任何已有 MCP subsystem 文件（mcp.py, mcp_models.py, mcp_policy.py 等）
- 不修改 Tool lifecycle handler（tool_gate.py, tool_invoke.py, tool_result_feedback.py）
- 不修改 dispatcher.py / evidence.py / phase1_hook.py
- 不修改 core.py / loop.py
- 不新增 RuntimeActionType / Anchor / branch point / runtime flow
- 不接入 production runtime loop（L3 DEFERRED）
- 不重新评估完整 MCP policy（DEFERRED）
- 不连接真实 MCP server / 不读 .env / 不用真实 API
- 不实现 MCP resources / prompts

## 复用了哪些已有代码

- **MCP adapter**: FakeMCPClient, register_mcp_tools, MCPServerConfig, MCPToolDescriptor, mcp_registry_tool_name — 全部复用，零修改
- **Tool lifecycle handler**: ToolGateHandler, ToolInvokeHandler, ToolResultFeedbackHandler — 复用，零修改
- **Dispatcher**: RuntimeActionDispatcher, ActionHandlerRegistry — 复用，零修改
- **Tool registry**: TOOL_REGISTRY, execute_tool, get_model_visible_tools, needs_tool_confirmation — 复用，零修改

## 实现中遇到的问题和决策

### 1. conftest.py reset_model_visible_tool_limits 覆盖模块级设置

`tests/conftest.py` 的 `reset_global_runtime_configs` autouse fixture 在每个 test 前运行 `reset_model_visible_tool_limits()`，将 `_max_mcp_tools` 恢复为 5。模块级 `set_model_visible_tool_limits(max_mcp=50, max_total=200)` 在 import 时执行一次，随后被 fixture 覆盖。

**修复**: 在 `_register_fake_mcp_tool` helper 中每次注册前调用 `set_model_visible_tool_limits`。

### 2. TOOL_REGISTRY 跨 test module 泄漏

本模块注册的 MCP 工具（如 `mcp__demo_a1__hello`）会持久存在于全局 `agent.tool_registry.TOOL_REGISTRY` 中，影响后续 test module。`test_mcp_client_architecture.py::test_mcp_tools_do_not_enter_base_registry_until_explicitly_registered` 断言 TOOL_REGISTRY 中没有任何 `mcp__` 前缀工具，因此会被污染。

**修复**: 添加 `_cleanup_mcp_tools` autouse fixture，yield 后从 TOOL_REGISTRY 中移除本模块注册的工具名。

### 3. MCPToolDescriptor 字段名

IMPLEMENTATION_PLAN.md 中使用了 `parameters_schema`，但实际 `MCPToolDescriptor` 的字段是 `input_schema`。已在测试代码中使用正确的字段名。

## Tradeoffs

- **L3 (real_core_loop_runtime_e2e) DEFERRED**: 本轮不接入 production runtime loop。orchestrator 通过 `dispatcher.route()` 直接调用，evidence 分类为 `harness_runtime_e2e`。`real_core_loop_runtime_e2e` 需要修改 core.py/loop.py，超出本轮范围。
- **Policy re-eval DEFERRED**: 注册后 server 端 descriptor 变更不会被 detect。后续 TOOL_GATE adapter 中为 `capability="mcp_tool"` 增加 re-eval。
- **max_mcp/max_total 限制**: 测试需要调高限制以注册多个 MCP 工具。production 默认 max_mcp=5 保持不变。

## Deferred

- MCP resources / prompts
- Real MCP server / production MCP transport
- Auth / secret flow
- Multi-server registry / capability discovery expansion
- Full MCP policy re-eval on each execution
- Real provider E2E (L3)
- UI confirmation for MCP tools

## Tests/Gates

- 新测试文件: 18/18 passed
- MCP 相关测试: 142/142 passed (5 skipped, all opt-in real e2e)
- Tool pipeline 回归: 76/76 passed (含 tool_gate, tool_invoke, tool_result)
- 完整 test suite: 3054/3054 passed (19 skipped)
- ruff: All checks passed
