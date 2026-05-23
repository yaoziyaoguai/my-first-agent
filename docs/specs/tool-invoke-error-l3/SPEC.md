# SPEC: Tool Invoke error L3

Date: 2026-05-24
Status: active
Parent: [First Agent Subsystem Integration Roadmap](../../plans/first-agent-subsystem-integration-roadmap.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. Branch Point 判断

Tool invoke error 是 TOOL_INVOKE 的 error-path branch behavior。归属：**已有 TOOL_INVOKE branch point**（`tool_invoke.py:130-132` 已有 execution_status="error" → disposition="invoked" 逻辑）。

这是纯 branch behavior，不新增 capability milestone，不新增 Anchor。

## B. 当前 Behavior Scope

`tool_invoke.py:127-135`:
```python
if not found:
    disposition = "not_found"
    tool_invoked = False
elif execution_status == "error":
    disposition = "invoked"
    tool_invoked = True
else:
    disposition = "invoked"
    tool_invoked = True
```

error 路径：工具在 TOOL_REGISTRY 中找到（found=True），但执行返回 execution_status="error"。此时 disposition="invoked"、tool_invoked=True，但 exec_status 为 error。

L1/L2 有基础覆盖（`test_tool_invoke_branch_behavior.py` 的 happy-path），但 TOOL_INVOKE error 路径的 L3 evidence 未专项验证。

## C. 目标

验证 TOOL_INVOKE error 通过 core.chat() → TOOL_GATE(allowed) → TOOL_INVOKE(error) 真实路径获得 L3 evidence。

## D. Trigger 策略

注册确认级别为 "never" 但执行时抛异常的工具。`loop.py:153` 在 gate_disposition="allowed" 时触发 TOOL_INVOKE。

## E. fake/real 边界

- FakeProvider + _PipelineSpy
- HOME 隔离路径
- 不读 .env / 不调真实 API

## F. 复用关系

| 模块 | 改动 |
|------|------|
| `agent/` | 零改动 |
| `tests/runtime_integration/` 已有文件 | 零改动 |

## G. Review Checklist

- [x] 不需要新增 branch point
- [x] 不需要新增 Anchor
- [x] 不修改 pipeline 代码
- [x] 不涉及真实 API / .env
- [x] 可以进入 TDD
