# SPEC: Tool Gate not_found L3

Date: 2026-05-23
Status: active
Parent: [First Agent Subsystem Integration Roadmap](../../plans/first-agent-subsystem-integration-roadmap.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. Branch Point 判断

Tool gate not_found 是 Tool gate 的第四个 disposition 分支行为（前三为 allowed / confirmation_required / rejected）。

归属：**已有 Tool gate branch point**（`tool_gate.py` handler 已有完整 not_found 逻辑，见第 86-90 行）。这是纯 branch behavior，不新增 capability milestone，不新增 Anchor。

## B. 当前 Behavior Scope

`tool_gate.py:86-90`:
```python
elif entry is None:
    gate_disposition = None
    decision = "not_found"
    risk_level = "unknown"
    rejection_reason = "tool not found in production ToolRegistry"
```

当前行为：
- 工具名不在 `TOOL_REGISTRY` 中 → `gate_disposition = None`，`decision = "not_found"`
- 最终 `status = "rejected"`（因为 gate_disposition 既不是 "allowed" 也不是 "confirmation_required"）
- `loop.py:153` 不会触发 TOOL_INVOKE（status != "success"）
- 已有 L1 和 L2 覆盖（`test_tool_anchor_fake.py` 中的 direct dispatcher 测试），但 L3 未专项验证

## C. 目标

验证 tool gate not_found 通过 `core.chat()` → `_try_phase1_turn_end_runtime_action()` → `route_from_runtime_loop()` 真实路径：

1. TOOL_GATE 返回 `status="rejected"`，`decision="not_found"`，L3 evidence
2. TOOL_INVOKE 不触发
3. TOOL_RESULT 不触发

## D. fake/real 边界

- 使用 `FakeProvider`（不调用真实 LLM API）
- 使用 `_PipelineSpy` 包裹 dispatcher（不改变 dispatcher 行为）
- HOME 指向隔离路径
- 不读取 .env
- 不连接真实 MCP server

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
- 不实现 not_found 后的 recovery 流程
- 不修改 tool_gate.py 的 not_found 逻辑

## G. Open Questions

- 无。这是纯测试补齐，不涉及设计决策。

## H. Review Checklist

- [x] 不需要新增 branch point
- [x] 不需要新增 Anchor
- [x] 不修改 pipeline 代码
- [x] 不涉及真实 API / .env
- [x] scope 收敛到单一 branch behavior
- [x] 可以进入 TDD
