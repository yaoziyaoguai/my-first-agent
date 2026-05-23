# Implementation Notes: MCP L3 Real Core-Loop Integration

Date: 2026-05-23
Status: active
Parent Plan: [IMPLEMENTATION_PLAN.md](../specs/mcp-l3-real-core-loop/IMPLEMENTATION_PLAN.md)

## 实现了什么

- `chat()` 新增 `tool_gate_tool_name: str | None = None` keyword-only 参数
- `_run_main_loop()` 接收并透传 `tool_gate_tool_name` 至 `LoopDependencies`
- `_handle_planning_phase_result()` 透传参数至 `_run_main_loop()`
- 生产 MCP 工具（`confirmation="always"`）安全策略不变
- 7 条新增测试（T1-T8，不含已覆盖的 T7 regression）全部通过

## 没做什么

- 未修改 Tool Pipeline（loop.py / tool_gate.py / tool_invoke.py / tool_result_feedback.py）
- 未修改 dispatcher.py / evidence.py / phase1_hook.py
- 未修改 MCP subsystem（mcp.py / mcp_models.py / mcp_policy.py / tool_registry.py）
- 未新增 Anchor / branch point / runtime flow / RuntimeActionType
- 未实现 confirmation 交互流程（confirmation="always" 工具仍停在 gate）
- 未实现 MCP resources / prompts / auth / Policy Re-Eval / D4

## 复用了哪些代码

| 模块 | 复用方式 |
|------|---------|
| `agent/loop.py` `_try_phase1_turn_end_runtime_action` | 零改动 |
| `agent/loop.py` `LoopDependencies.tool_gate_tool_name` | 零改动（已有默认 `_safe_noop`） |
| `agent/runtime_integration/tool_gate.py` | 零改动 |
| `agent/runtime_integration/tool_invoke.py` | 零改动 |
| `agent/runtime_integration/tool_result_feedback.py` | 零改动 |
| `agent/runtime_integration/dispatcher.py` | 零改动 |
| `agent/runtime_integration/evidence.py` | 零改动 |
| `agent/mcp.py` `FakeMCPClient` | 测试用 |

## 实现中必须做的决策（plan 未覆盖）

1. **`tool_gate_tool_name` 仅在非 None 时传入 `LoopDependencies`**：如果直接传 `tool_gate_tool_name=None`，会覆盖 dataclass 默认值 `"_safe_noop"`，导致 loop.py 中 `getattr` 返回 None。解决方案：用 `dict` 组装参数，条件性添加 `tool_gate_tool_name`。

2. **`prompt_section` 是 payload 字段，不是 evidence 字段**：测试在编写时误将 `result_result.evidence` 当作 `prompt_section` 的来源，实际 `prompt_section` 在 handler 的 `payload` 中。已在发现后修正。

3. **3 条 characterization test 需要更新**：`test_transition_checkpoint_boundaries.py` 中 3 条测试钉死了旧函数签名，新 keyword-only 参数 `tool_gate_tool_name` 需要同步更新断言。

## Tradeoffs / Deviations

- `chat()` 新增参数是纯透传，不参与 pipeline 决策，最小侵入性
- 确认流程中的 `_start_planning_for_handler` → `_handle_planning_phase_result` 路径不走 `tool_gate_tool_name`（使用默认 `_safe_noop`），不改变现有 confirmation 行为
- 未选择将 `tool_gate_tool_name` 放入 `LoopContext`（避免修改 loop_context.py）

## Tests/Gates

| Gate | Result |
|------|--------|
| `test_mcp_l3_real_core_loop.py` (7 tests) | 7 passed |
| `test_mcp_runtime_integration.py` (39 tests) | 39 passed |
| `test_tool_pipeline_l3_completion.py` | passed |
| `test_transition_checkpoint_boundaries.py` (30 tests) | 30 passed |
| Full pytest | 3082 passed, 19 skipped |
| ruff | clean |
| git diff --check | clean |

## 回退记录

- 无回退

## Deferred 项

- 生产 MCP 工具的 `confirmation="always"` 何时能走通完整管线 — 需 runtime loop 中实现 confirmation 交互流程
- `register_mcp_tools()` 的 confirmation 策略参数化
