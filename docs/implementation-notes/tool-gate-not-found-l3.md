# Implementation Notes: Tool Gate not_found L3

Date: 2026-05-23
Status: active
Parent SPEC: [SPEC.md](../specs/tool-gate-not-found-l3/SPEC.md)

## 实现了什么

- 4 条新增测试覆盖 Tool gate not_found 分支行为的 L3 evidence
- T1: core.chat() 路径中 not_found 工具返回 rejected + L3 evidence
- T2: hook 级 not_found 工具被正确拒绝
- T3: direct dispatcher.route 保持 L2（payload 伪造无效）
- T4: 隔离环境安全验证

## 没做什么

- 未修改任何 `agent/` 下的生产代码（零生产代码改动）
- 未修改 Tool Pipeline（loop.py / tool_gate.py / tool_invoke.py / tool_result_feedback.py）
- 未修改 dispatcher.py / evidence.py
- 未新增 Anchor / branch point / runtime flow / RuntimeActionType

## 复用了哪些代码

| 模块 | 复用方式 |
|------|---------|
| `agent/core.py` `chat(tool_gate_tool_name=...)` | 已有参数，直接使用 |
| `agent/loop.py` `_try_phase1_turn_end_runtime_action` | 已有函数，零改动 |
| `agent/runtime_integration/tool_gate.py` | not_found 逻辑（第86-90行）已存在 |
| `agent/provider/fake_provider.py` | FakeProvider 支撑 L3 测试 |
| `tests/runtime_integration/test_mcp_l3_real_core_loop.py` | `_PipelineSpy`、`_build_pipeline_dispatcher()`、`_make_mock_state()` 模式复用 |

## Tradeoffs / Deviations

- 无。纯测试补齐，零 tradeoff。

## Tests/Gates

| Gate | Result |
|------|--------|
| `test_tool_gate_not_found_l3.py` (4 tests) | 4 passed |
| `tests/runtime_integration/` (full) | 301 passed, 5 skipped |
| ruff | clean |
