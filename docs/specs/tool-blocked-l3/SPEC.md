# SPEC: Tool Gate blocked L3

Date: 2026-05-24
Status: active
Parent: [First Agent Subsystem Integration Roadmap](../../plans/first-agent-subsystem-integration-roadmap.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. Branch Point 判断

Tool gate blocked 是 Tool gate 的第三个 disposition 分支行为（四者为 allowed / confirmation_required / not_found / blocked）。

归属：**已有 Tool gate branch point**（`tool_gate.py` handler 已有完整 blocked/rejected 逻辑）。这是纯 branch behavior，不新增 capability milestone，不新增 Anchor。

## B. 当前 Behavior Scope

`tool_gate.py` 有三个 blocked/rejected 路径：

1. **Shell-like 工具** (`tool_gate.py:81-85`):
```python
if tool_name in _FORBIDDEN_TOOL_NAMES:  # frozenset({"bash", "shell", "run_shell"})
    gate_disposition = "rejected"
    decision = "rejected"
    risk_level = "high"
    rejection_reason = "shell-like tool is out of scope"
```

2. **_ 前缀非 allowlist 工具** (`tool_gate.py:113-114`):
```python
else:  # tool_name.startswith("_") and tool_name NOT in ("_safe_noop", "_confirmable_noop")
    gate_disposition = "rejected"
    decision = "rejected"
    # (rejection_reason 和 risk_level 从 entry 继承)
```

3. **confirmation policy block** (`tool_gate.py:101-104`):
```python
if confirmation == "block":
    gate_disposition = "rejected"
    decision = "rejected"
    rejection_reason = "tool policy blocked request"
```

已有 L1/L2 覆盖（`test_tool_anchor_fake.py::test_shell_like_tool_is_blocked`、`test_other_internal_underscore_tool_is_blocked_unless_allowlisted`；`test_tool_branch_confirmation_required.py::test_blocked_forbidden_tool_name` 等），但 L3 未专项验证。

## C. 目标

验证 tool gate blocked/rejected 通过 `core.chat()` → `_try_phase1_turn_end_runtime_action()` → `route_from_runtime_loop()` 真实路径：

1. TOOL_GATE 返回 `status="rejected"`，`decision="rejected"`，L3 evidence（shell-like 路径）
2. TOOL_GATE 返回 `status="rejected"`，`decision="rejected"`，L3 evidence（_ 前缀路径）
3. TOOL_INVOKE 不触发（gate 返回 rejected）
4. TOOL_RESULT 不触发

## D. fake/real 边界

- 使用 `FakeProvider`（不调用真实 LLM API）
- 使用 `_PipelineSpy` 包裹 dispatcher（不改变 dispatcher 行为）
- HOME 指向隔离路径
- 不读取 .env
- 不连接真实 MCP server
- 不注册任何测试工具到 TOOL_REGISTRY（shell-like 路径）
- 注册 `_blocked_tool` 但不在 allowlist 中（_ 前缀路径，如果 registry 需要）

## E. 复用关系

| 模块 | 改动 |
|------|------|
| `agent/core.py` | 零改动（`tool_gate_tool_name` 参数已存在） |
| `agent/loop.py` | 零改动 |
| `agent/runtime_integration/tool_gate.py` | 零改动 |
| `agent/runtime_integration/dispatcher.py` | 零改动 |
| `agent/runtime_integration/tool_invoke.py` | 零改动 |
| `agent/runtime_integration/tool_result_feedback.py` | 零改动 |

## F. 不做什么

- 不修改 Tool Pipeline 任何模块
- 不新增 RuntimeActionType
- 不新增 Anchor
- 不新增 branch point
- 不新增 runtime flow
- 不测试 confirmation="block" 路径（需要注册工具 + 修改 policy，风险高于价值）
- 不修改 tool_gate.py 的 blocked 逻辑

## G. Open Questions

- T3: confirmation="block" 路径当前不测——需要在 TOOL_REGISTRY 中注册工具并设置 confirmation="block"，涉及 registry 修改。本轮 scope 限定 shell-like + _ prefix 两条纯参数路径。
- _ prefix 路径测试是否需要注册 `_blocked_tool` 到 TOOL_REGISTRY？tool_gate.py 先检查 `_FORBIDDEN_TOOL_NAMES`，再检查 `entry is None`，最后才检查 `_` 前缀。所以 `_blocked_tool` 必须存在于 TOOL_REGISTRY 中（否则先命中 not_found）。但测试不应修改生产 TOOL_REGISTRY——需要确认 test helper 是否有 register_tool 机制。

## H. Review Checklist

- [x] 不需要新增 branch point
- [x] 不需要新增 Anchor
- [x] 不修改 pipeline 代码
- [x] 不涉及真实 API / .env
- [x] scope 收敛到 Tool gate 的 shell-like + _ prefix blocked 两个分支
- [x] 可以进入 TDD
