# Tool Result Feedback Branch Behavior SPEC

Status: draft
Date: 2026-05-23
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## 1. Branch Point 判断

**Is this a new capability milestone?** No.

**Is this a branch behavior test under an existing capability?** Yes.

**Is this a harness/subsystem-only validation?** No — tool result feedback 可通过
`core.chat` → runtime loop → `route_from_runtime_loop()` 到达，
具备 `real_core_loop_runtime_e2e` 路径。

**Branch point:** "tool execution / confirmation handling"（Contract §2 已定义）。

**当前 tool lifecycle 覆盖状态：**

| 阶段 | RuntimeActionType | 语义 | 覆盖状态 |
|------|------------------|------|---------|
| tool request | `tool.request` | 模型请求工具调用 | schema 已定义，无 handler |
| tool gate | `tool.gate` | 工具执行前置 gate | **已实现** |
| tool invoke | `tool.invoke` | 工具实际执行 | schema 已定义，无 handler |
| **tool result feedback** | **本轮目标** | 工具执行结果注入模型上下文 | **未覆盖** |

`tool.result` 是 tool execution 生命周期的最后一个阶段：工具执行完成 →
结果处理 → 注入模型上下文。它是 `tool.gate` 的互补行为——
`tool.gate` 负责 pre-execution，`tool.result` 负责 post-execution。

## 2. Behavior Scope

### 2.1 tool.result 语义

`tool.result` 表示：工具已执行完成，结果需要被处理并注入模型上下文。

核心行为：
1. 接收 tool result（tool_output, tool_name, execution_status）
2. 验证 result 完整性
3. 格式化/处理 result（截断超长输出、标记错误、redact 敏感内容）
4. 生成 prompt section 注入模型上下文
5. 返回 evidence（含 tool_name, result_size, execution_status）

触发点：
- 在 runtime loop 中，tool 执行完成后，result 需要被注入模型上下文之前
- 属于 "runtime loop model call and model output dispatch" 内的 tool 子路径

### 2.2 result disposition

| disposition | 语义 | 触发条件 |
|------------|------|---------|
| `injected` | 结果已注入模型上下文 | tool 执行成功，result 合法 |
| `truncated` | 结果被截断后注入 | result 超过 char budget |
| `error` | 工具执行出错，错误信息注入 | tool 执行返回错误 |
| `redacted` | 敏感内容已移除后注入 | result 含疑似敏感内容 |
| `empty` | 空结果，注入 placeholder | tool 返回空输出 |

### 2.3 不在本 SPEC 范围

- **工具实际执行**：TOOL_INVOKE（tool.invoke）的 handler 实现不属于本轮
- **Tool retry / error recovery**：工具执行失败后的重试逻辑
- **Multi Tool**：多个工具并行调用的结果合并
- **Streaming tool result**：流式工具输出的增量注入
- **Tool Confirmation UI**：已由 tool.gate 覆盖
- **MCP Tool**：外部 MCP server 工具结果

## 3. 当前代码状态

### 3.1 TOOL_INVOKE / TOOL_REQUEST 已定义但无 handler

`schema.py:23-25` 已定义 `TOOL_INVOKE = "tool.invoke"` 和
`TOOL_REQUEST = "tool.request"`，但在 `phase1_hook.py` 中未注册 handler。
这些 schema 定义为 tool result feedback 提供了现成的命名空间。

### 3.2 当前 loop 中的 tool result 流是隐式的

当前 runtime loop 中，tool 执行结果通过 provider 的内部机制直接注入
模型上下文，没有经过 RuntimeActionDispatcher → handler → evidence 管道。
这与 memory recall 之前的情况类似——功能存在但绕过了统一管道。

### 3.3 与 memory recall 的对称性

`memory.recall` 将隐式的 memory→prompt 注入 formalize 为 RuntimeAction。
`tool.result` 将隐式的 tool-execution-result→prompt 注入 formalize 为
RuntimeAction。两者的 formalize 模式一致。

## 4. Fake/Real 配置层边界

Unified Runtime Flow Contract §1 规定：fake 和 real 共享同一业务流，
仅在配置和 adapter 层不同。

对于 `tool.result`：
- `ToolResultFeedbackHandler.handle()` 的 result 处理逻辑对 fake/real 完全相同
- result formatting / truncation / redaction 逻辑相同
- fake 和 real 的区别仅在于：
  - **tool output 来源**：fake 使用 `_safe_noop` / `_confirmable_noop` 的
    固定输出，real 使用实际工具输出
  - **provider_kind**：evidence metadata 区分

不允许：
- fake-only 的 result 处理路径
- real-only 的 result 处理路径
- provider kind 作为 result 处理分支条件

## 5. Dogfood 边界

### 5.1 允许的做法

```
dogfood script → core.chat → runtime loop → route_from_runtime_loop()
  → ToolResultFeedbackHandler.handle() → evidence
```

### 5.2 禁止的做法

- dogfood 调用 `dispatcher.route()` 直接构造 TOOL_RESULT request
- dogfood 调用 `ToolResultFeedbackHandler.handle()` 跳过 dispatcher
- dogfood 自己生成 proof / evidence

### 5.3 分类预期

| 路径 | 最高分类 | 备注 |
|------|---------|------|
| `core.chat` → runtime loop → `route_from_runtime_loop()` | `real_core_loop_runtime_e2e` | 需 loop 集成 |
| dogfood `dispatcher.route()` 直接调用 | `harness_runtime_e2e` | 需 target proof 完整 |
| dogfood 直接调用 handler | `subsystem_integration` | — |

本轮 L1（subsystem_integration）+ L2（harness_runtime_e2e）覆盖。
L3 `real_core_loop_runtime_e2e` deferred——与 memory recall 一致。

## 6. SPEC 不做什么

1. **不新增 Anchor** — `tool.result` 是 "tool execution / confirmation handling"
   branch point 下的 branch behavior
2. **不新增 capability milestone** — tool execution 能力已存在
3. **不新增 branch point** — tool execution / confirmation handling 已在 Contract §2 定义
4. **不实现 TOOL_INVOKE handler** — tool 执行不属于本轮范围
5. **不实现 TOOL_REQUEST handler** — tool 请求解析不属于本轮范围
6. **不修改 ToolGateHandler** — gate 逻辑不变
7. **不引入** Tool retry / Error Recovery / Multi Tool / MCP Tool / Streaming /
   Checkpoint / Skill / SubAgent
8. **不读取 .env / 真实 sessions / 真实 API**
9. **不处理真实私人资料**

## 7. 测试策略概要

以下为 TDD 阶段指导，非本 SPEC 的执行内容。

### 7.1 正例（tool.result happy path）

| 测试 | 条件 | 预期 disposition |
|------|------|-----------------|
| 正常 result 注入 | tool 执行成功，返回文本 | `injected` |
| 空 result | tool 返回空字符串 | `empty` |
| 超长 result 截断 | result 超过 char budget | `truncated` |
| error result | tool 返回错误 | `error` |

### 7.2 负例

| 测试 | 条件 | 预期 |
|------|------|------|
| 无 tool_name | payload 缺 tool_name | `failed` |
| 无 tool_output | payload 缺 tool_output | `failed` |
| 空 content | tool_output 为 None | `empty` |

### 7.3 分类边界测试

| 测试 | 路径 | 预期 evidence_level |
|------|------|-------------------|
| dispatcher.route() with target proof | L2 harness | `harness_runtime_e2e` |
| direct handler call | L1 subsystem | `subsystem_integration` |

### 7.4 无副作用测试

- tool.result 不修改 tool registry
- tool.result 不触发 MEMORY_PROPOSE / TOOL_GATE
- tool.result 是纯读取/格式化操作

## 8. Open Questions

1. **result char budget 默认值**：与 memory recall 的 500 chars 保持一致？
   - 推荐：per-result 500 chars，不设 total budget（tool result 通常只有 1 条）

2. **敏感内容 redact 规则**：是否复用 `agent.runtime_integration.schema._SECRET_PATTERNS`？
   - 推荐：复用现有 secret patterns 做基础 redact，不做 LLM-based 敏感内容检测

3. **loop 中 TOOL_RESULT action 何时触发**：需要在 loop.py 中识别 tool execution
   完成点并构造 TOOL_RESULT action
   - 本轮 deferred（与 memory recall 的 core.py integration deferred 一致）
   - L1/L2 handler 测试不依赖 loop 集成

4. **与 TOOL_INVOKE 的关系**：TOOL_INVOKE 负责执行，TOOL_RESULT 负责结果反馈。
   两阶段是否需要共享 trace/tool_call_id？
   - 推荐：TOOL_RESULT payload 中携带 tool_call_id，但不强制要求 TOOL_INVOKE
     已注册 handler

## 9. Review Checklist

- [ ] branch point 判断正确（"tool execution / confirmation handling"，非新 Anchor）
- [ ] behavior scope 明确（post-execution result → model context）
- [ ] 不包含禁止事项（§6 全部检查）
- [ ] fake/real 边界清晰（共享业务流，仅 tool output 来源不同）
- [ ] dogfood 边界清晰（必须走 `core.chat`，不可 direct dispatch）
- [ ] 与 Unified Runtime Flow Contract 一致
- [ ] 无副作用：no shell / no file write / no external process / no MCP / no real API
- [ ] open questions 未假装已解决
- [ ] 与 memory recall 的 formalize 模式一致
