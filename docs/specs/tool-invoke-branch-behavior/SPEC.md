# SPEC: Tool Invoke Branch Behavior

Date: 2026-05-23
Status: active

## 1. Branch Point 判断

TOOL_INVOKE 归属 Unified Runtime Flow Contract §2 "tool execution / confirmation handling" 既有 branch point。

Tool 生命周期的三个环节都落在同一 branch point 下：

```
tool.gate (pre-execution gating) → tool.invoke (execution) → tool.result (post-execution feedback)
```

- TOOL_GATE: 回答"这个工具能不能用？" → allowed / confirmation_required / blocked / not_found
- TOOL_INVOKE: 回答"执行这个工具，拿到结果" → 调用 tool function，返回 result
- TOOL_RESULT: 回答"把结果格式化后注入模型上下文" → format / truncate / redact / prompt section

**这不是新 Anchor。** 这是已有 Tool 介入点下的 branch behavior。

schema.py 中 TOOL_INVOKE = "tool.invoke" 已定义，evidence.py 中有占位 descriptor（指向 ToolGateHandler），但无真正 handler 实现。

## 2. Behavior Scope

### 2.1 核心行为

ToolInvokeHandler 接收 RuntimeActionRequest，payload 包含：

- `tool_name` (str, required): 要执行的工具名
- `tool_input` (dict, required): 工具参数
- `gate_disposition` (str, optional): 上游 TOOL_GATE 的判断结果，用于 cross-check

Handler 执行流程：

1. **验证 tool_name**: 非空，必填
2. **验证 tool_input**: 必填字段
3. **查找 TOOL_REGISTRY**: 工具必须存在
4. **执行工具函数**: 通过 catalog adapter → `ToolRegistry.execute_tool`
5. **返回 result**: tool_output + execution_status + evidence

### 2.2 Disposition 语义

| disposition | 含义 |
|---|---|
| `invoked` | 工具函数被成功调用 |
| `not_found` | tool_name 不在 TOOL_REGISTRY 中 |
| `failed` | 缺少必填字段或执行异常 |

### 2.3 Evidence 字段

| 字段 | 含义 |
|---|---|
| `tool_invoked` | 工具函数是否被实际调用 |
| `dangerous_tool_function_invoked` | 工具 risk_level == "high" |
| `external_side_effects` | 工具 capability 可能产生外部副作用 |
| `tool_name` | 被调用的工具名 |
| `execution_status` | success / error |
| `no_tool_registry_modification` | handler 不修改 TOOL_REGISTRY |

### 2.4 与 TOOL_GATE 的关系

TOOL_INVOKE 不重复 TOOL_GATE 的检查。gate_disposition 仅作为 informational cross-check 记录在 evidence 中，不作为 invoke 的 blocking 条件。

TOOL_INVOKE 自己验证工具是否存在（因为 TOOL_REGISTRY 是 single source of truth）。

### 2.5 与 TOOL_RESULT 的关系

TOOL_INVOKE 返回的工具输出（tool_output, execution_status）是 TOOL_RESULT handler 的输入。两个 handler 是 pipeline 关系：

```
TOOL_INVOKE → { tool_output, execution_status } → TOOL_RESULT → prompt section
```

## 3. Fake/Real 边界

- Fake 和 real 共享同一个 ToolInvokeHandler
- fake/real 只在 TOOL_REGISTRY 内容上不同（register_tool 注册不同 func）
- handler 不关心工具函数的实现细节
- catalog adapter 调用 `execute_tool()` 而非直接调用 `info["func"](**tool_input)`，保持 registry 作为单一执行入口

## 4. Dogfood/Evidence 边界

- L1 (subsystem_integration): handler 直接实例化调用，无 target_module_proof
- L2 (harness_runtime_e2e): dispatcher.route() with target_module_proof（通过 catalog adapter）
- L3 (real_core_loop_runtime_e2e): deferred，需 loop.py 构造 TOOL_INVOKE action

## 5. 不做什么

- 不重复 TOOL_GATE 的 policy 检查
- 不做 confirmation handling
- 不做 tool result formatting（那是 TOOL_RESULT 的职责）
- 不修改 TOOL_REGISTRY
- 不触发其他 RuntimeAction
- 不调用真实 API / .env / shell / file write / MCP
- 不实现 Retry / Error Recovery
- 不实现 Multi Tool
- 不新增 runtime flow / Anchor / branch point

## 6. Open Questions

无。TOOL_INVOKE 的行为边界已由 TOOL_GATE（上游）和 TOOL_RESULT（下游）清晰界定。

## 7. Review Checklist

- [ ] 归属 "tool execution / confirmation handling" 既有 branch point
- [ ] 不是新 Anchor，不是新 capability milestone
- [ ] 不新增 runtime flow
- [ ] fake/real 共享同一 handler
- [ ] catalog adapter 通过 execute_tool() 执行
- [ ] tool_invoked / dangerous_tool_function_invoked / external_side_effects evidence 正确
- [ ] 与 TOOL_GATE / TOOL_RESULT 边界清晰
- [ ] scope 收敛，不扩大到 Retry/Multi Tool/MCP/Streaming
