# Implementation Plan: Tool Invoke Branch Behavior

Date: 2026-05-23
SPEC: [SPEC.md](SPEC.md)
TDD: [TDD.md](TDD.md)

## Architecture

TOOL_INVOKE 是 tool.gate → tool.invoke → tool.result 管线的中间环节，负责执行工具函数并返回结果。实现遵循与 ToolResultFeedbackHandler 相同的模式：handler + catalog adapter + dispatcher registration。

## Implementation Units

### U1: `agent/runtime_integration/tool_invoke.py` (CREATE)

ToolInvokeHandler — 接收 tool_name + tool_input，通过 catalog adapter 调用 execute_tool()，返回 tool_output + evidence。

**Files:**
- Create: `agent/runtime_integration/tool_invoke.py`

**Pattern to follow:** `agent/runtime_integration/tool_result_feedback.py` (ToolResultFeedbackHandler)
- handler 结构：`__init__(self, *, store=None)` → `handle(self, request, context)`
- 验证必填字段 → `context.success(..., observed_call=None, ...)`
- 正常路径 → `context.invoke_registered_target(...)` → `context.success(..., observed_call=observed, ...)`

**Execution note:** TDD-first — 先写测试文件，再实现 handler

### U2: `agent/runtime_integration/evidence.py` (MODIFY)

更新 tool.invoke catalog descriptor 和新增 `_tool_invoke_adapter`。

**Files:**
- Modify: `agent/runtime_integration/evidence.py`

**Changes:**
1. 新增 `_tool_invoke_adapter(payload)` — catalog-owned adapter，调用 `execute_tool()`
2. 替换现有 tool.invoke descriptor（当前指向 ToolGateHandler/lookup_and_risk_check）为 ToolInvokeHandler/execute_tool

### U3: `agent/runtime_integration/phase1_hook.py` (MODIFY)

注册 TOOL_INVOKE → ToolInvokeHandler。

**Files:**
- Modify: `agent/runtime_integration/phase1_hook.py`

**Changes:**
1. 新增 import: `from agent.runtime_integration.tool_invoke import ToolInvokeHandler`
2. 新增注册: `registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())`

### U4: `tests/runtime_integration/test_tool_invoke_branch_behavior.py` (CREATE)

测试文件，覆盖 TDD Phase A-F。

**Files:**
- Create: `tests/runtime_integration/test_tool_invoke_branch_behavior.py`

**Pattern to follow:** `tests/runtime_integration/test_tool_result_feedback_branch_behavior.py`

## 允许修改范围

- `agent/runtime_integration/tool_invoke.py` (new)
- `agent/runtime_integration/evidence.py` (修改 descriptor)
- `agent/runtime_integration/phase1_hook.py` (注册 handler)
- `tests/runtime_integration/test_tool_invoke_branch_behavior.py` (new)

## 禁止修改范围

- core.py / loop.py（L3 deferred）
- tool_gate.py / tool_result_feedback.py（已有 handler）
- tool_registry.py（只读使用）
- schema.py（TOOL_INVOKE 已定义）
- dispatcher.py
- 其他已有 handler / test 文件
- .env / 真实 API / sessions / episodes

## 集成点

- `context.invoke_registered_target(target_module="ToolRegistry", operation="execute_tool", ...)` — 通过 catalog adapter 执行工具
- `build_phase1_dispatcher()` — 注册 TOOL_INVOKE handler

## Stop Conditions

- 需要新增 branch point / Anchor / runtime flow → STOP
- 需要调用真实 API / .env / shell / MCP → STOP
- TOOL_REGISTRY 中没有可用的 fake/noop 工具 → STOP
- 已有测试被 TOOL_INVOKE 破坏且无法修复 → STOP

## Implementation Notes

路径: `docs/implementation-notes/tool-invoke-branch-behavior.md`
