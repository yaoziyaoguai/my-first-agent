# Tool Invoke not_found L3 SPEC

Date: 2026-05-24
Status: active
Type: Normal Capability Loop (branch behavior on existing branch point)

## 问题

`ToolInvokeHandler.handle()` 在 `tool_invoke.py:127-128` 已有 `not_found`
disposition——当 `context.invoke_registered_target(ToolRegistry, execute_tool)`
返回 `found=False` 时，handler 返回 `disposition="not_found"`、`tool_invoked=False`。

这是 handler 的防御性代码：即使 TOOL_GATE 返回 "allowed"，TOOL_INVOKE 仍然
二次检查工具是否在 TOOL_REGISTRY 中（防范 gate→invoke 之间的竞态）。

现有 L2 测试 `test_b3_tool_not_found` 通过 `dispatcher.route()` 直接触发此路径。
但 L3（通过 `core.chat()` → `route_from_runtime_loop()` 完整管线）未验证。

## 架构分析

not_found 是已有 TOOL_INVOKE branch point 的 branch behavior，不是新分支点：

- **branch point**: `ToolRegistry` target module，operation `execute_tool`
- **disposition values**: `invoked`（正常）、`not_found`（工具不存在）、`failed`（参数缺失）
- **归属**: Contract Section 2 "tool execution / confirmation handling"

不需要新增 RuntimeActionType、handler、catalog entry。
只需新增专项 L3 测试。

## 测试策略

拦截 gate→invoke 之间的 pipeline：

1. 注册 dummy tool（confirmation="never"）
2. `core.chat()` → TOOL_GATE(allowed)
3. Spy 在 gate 之后、invoke 之前从 TOOL_REGISTRY 移除工具
4. TOOL_INVOKE → not_found
5. 验证 L3 evidence

## Evidence Plan

| 层级 | 覆盖 |
|------|------|
| L1 | handler 单元测试（已有 `test_b3_tool_not_found`） |
| L2 | dispatcher.route() 测试（已有） |
| L3 | core.chat() → route_from_runtime_loop()（本次新增） |

## 约束

- 不新增 Anchor / branch point / RuntimeActionType
- 不新增 handler / catalog entry
- 不读取 .env / 真实 API / 真实 sessions
- FakeProvider + TOOL_REGISTRY 临时移除

## Stop Condition

无需——这是 Normal Capability Loop，SPY 拦截模式已有先例（`_PipelineSpy` in
`test_tool_invoke_error_l3.py`）。
