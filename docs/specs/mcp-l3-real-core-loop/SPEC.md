# SPEC: MCP L3 Real Core-Loop Integration

Date: 2026-05-23
Status: active
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
Parent SPEC: [MCP Runtime Integration](../mcp-runtime-integration/SPEC.md)

## A. Branch Point 判断

MCP tool-like execution 复用已有 **"tool execution / confirmation handling"** branch point（Contract §2）。

判断依据：

- MCP 工具已在 TOOL_REGISTRY 中，与本地工具共享同一 `register_tool()` 入口
- `agent/loop.py` 的 `_try_phase1_turn_end_runtime_action()` 已实现 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 完整管线
- `agent/runtime_integration/tool_gate.py` (ToolGateHandler) 已能查询 TOOL_REGISTRY 中任何工具（含 MCP 工具）
- `agent/runtime_integration/tool_invoke.py` (ToolInvokeHandler) 已能通过 `execute_tool` adapter 执行任何已注册工具函数
- `agent/runtime_integration/tool_result_feedback.py` (ToolResultFeedbackHandler) 已能格式化任何工具执行结果
- `agent/runtime_integration/dispatcher.py` 的 `route_from_runtime_loop()` 已提供 L3 所需的 runtime-loop provenance

**不新增 branch point。不新增 Anchor。不新增 runtime flow。不新增 RuntimeActionType。**

MCP tool-like call 通过 `core.chat()` → `run_main_loop()` → `_try_phase1_turn_end_runtime_action()` → `dispatcher.route_from_runtime_loop()` 进入已有 Tool 管线，获得 L3 evidence。MCP 只是 tool 的一个 capability variant（`capability="mcp_tool"`），不是独立的执行路径。

## B. L3 定义

`real_core_loop_runtime_e2e` (L3) 必须满足 Contract §5 的全部条件：

- action 由真实 `core.chat` / `loop.py` / `run_main_loop` 路径自然产生
- `dispatcher_origin == "runtime_loop"`（由 `route_from_runtime_loop()` 写入，不从 payload 读取）
- `runtime_loop_invoked == true`
- `core_entrypoint == "core.chat"`
- `runtime_hook_name == "loop.turn_end"`
- dispatcher route/result provenance 完整
- target handler was invoked（ToolGateHandler / ToolInvokeHandler / ToolResultFeedbackHandler）
- target module proof exists（ToolRegistry / ToolRuntime）
- result returned to parent runtime

以下路径不能声称 L3：

- direct `FakeMCPClient.call_tool()` → L1 (`subsystem_integration`)
- direct `dispatcher.route()` → L2 (`harness_runtime_e2e`)
- direct `dispatcher.route_from_runtime_loop()` without `core.chat()` → L2（缺少 core_entrypoint provenance）
- payload 中伪造 `core_loop_invoked` / `core_entrypoint` → 无效（dispatcher 不从 payload 读取这些字段）

## C. 目标路径

```
core.chat(user_input, provider=FakeProvider(), runtime_action_dispatcher=dispatcher, tool_gate_tool_name="mcp__demo__hello")
  → _run_main_loop()
    → LoopDependencies(tool_gate_tool_name="mcp__demo__hello", ...)
      → run_main_loop()
        → call_model() → dispatch_model_output() → result is not None
          → _try_phase1_turn_end_runtime_action()
            → TOOL_GATE: dispatcher.route_from_runtime_loop(TOOL_GATE, tool_name="mcp__demo__hello")
            │   └─ ToolGateHandler.handle() → gate_disposition="allowed" (confirmation="never")
            │   └─ evidence_level = real_core_loop_runtime_e2e
            → TOOL_INVOKE: dispatcher.route_from_runtime_loop(TOOL_INVOKE, tool_name="mcp__demo__hello")
            │   └─ ToolInvokeHandler.handle() → execute_tool adapter → FakeMCPClient.call_tool()
            │   └─ tool_output + execution_status
            │   └─ evidence_level = real_core_loop_runtime_e2e
            → TOOL_RESULT: dispatcher.route_from_runtime_loop(TOOL_RESULT, ...)
            │   └─ ToolResultFeedbackHandler.handle() → format_tool_result adapter
            │   └─ prompt_section + disposition
            │   └─ evidence_level = real_core_loop_runtime_e2e
            → return to unified runtime flow
```

关键约束：

- 所有三个 stage (TOOL_GATE, TOOL_INVOKE, TOOL_RESULT) 必须通过 `dispatcher.route_from_runtime_loop()` 获得 runtime-loop provenance
- MCP fake adapter/client 只在 TOOL_INVOKE 阶段被调用——不绕过 gate，不跳过 result feedback
- `tool_gate_tool_name` 通过 `chat()` → `LoopDependencies` 显式传入，不依赖默认值

## D. 复用关系

### 必须复用（不可重写）

**Tool Pipeline（已有，零改动）**：

| 模块 | 复用方式 |
|------|---------|
| `agent/loop.py` (`_try_phase1_turn_end_runtime_action`) | 已有 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 管线，零改动 |
| `agent/runtime_integration/tool_gate.py` (ToolGateHandler) | 复用 lookup_and_risk_check adapter，零改动 |
| `agent/runtime_integration/tool_invoke.py` (ToolInvokeHandler) | 复用 execute_tool adapter，零改动 |
| `agent/runtime_integration/tool_result_feedback.py` (ToolResultFeedbackHandler) | 复用 format_tool_result adapter，零改动 |
| `agent/runtime_integration/dispatcher.py` (RuntimeActionDispatcher) | 复用 route_from_runtime_loop()，零改动 |
| `agent/runtime_integration/phase1_hook.py` | 复用 handler 注册，零改动 |
| `agent/runtime_integration/evidence.py` | 复用 classify_evidence_level()，零改动 |

**MCP Subsystem（已有，零改动）**：

| 模块 | 复用方式 |
|------|---------|
| `agent/mcp.py` (FakeMCPClient, register_mcp_tools) | FakeMCPClient 用于测试；register_mcp_tools 不用于本轮测试工具注册（因为 hardcodes confirmation="always"） |
| `agent/mcp_models.py` | 数据模型不变 |
| `agent/tool_registry.py` (TOOL_REGISTRY, register_tool, execute_tool) | 复用 register_tool 注册测试用 MCP 工具 |

### 本轮最小改动

**仅两处 production code 改动**：

1. **`agent/core.py` `chat()` 函数**：新增 `tool_gate_tool_name` 参数，透传至 `_run_main_loop()` → `LoopDependencies`
2. **`agent/core.py` `_run_main_loop()` 函数**：将 `tool_gate_tool_name` 传入 `LoopDependencies` 构造

`LoopDependencies` 已有 `tool_gate_tool_name` 字段（默认 `"_safe_noop"`），`loop.py` 已使用该字段。改动仅限于参数透传——不改变任何 pipeline 逻辑。

**测试中**：使用 `register_tool()` 直接注册 MCP 工具（`confirmation="never"`），而非通过 `register_mcp_tools()`（后者 hardcodes `confirmation="always"`）。

## E. 关键设计决策

### E.1 为什么 MCP 工具必须用 confirmation="never" 注册

`register_mcp_tools()` 在 `agent/mcp.py:273` hardcodes `confirmation="always"`。这导致 TOOL_GATE 返回 `status="confirmation_required"` + `gate_disposition="confirmation_required"`。

`loop.py:153` 的 gate 检查：
```python
if gate_status == "success" and gate_payload.get("gate_disposition") == "allowed":
```

只有 `status="success"` AND `disposition="allowed"` 才进入 TOOL_INVOKE。`confirmation_required` 不满足此条件——TOOL_INVOKE 和 TOOL_RESULT 不会触发。

**这不是 pipeline bug**——confirmation_required 是真实的安全语义。但当前 runtime 尚未实现 confirmation 交互流程（user prompt → confirm → re-invoke），因此 `confirmation="always"` 的工具在当前 runtime loop 中实际被"卡住"在 gate 阶段。

本轮目标是证明 MCP tool-like call 能走通完整管线（GATE → INVOKE → RESULT），而非实现 confirmation 交互。因此测试用 MCP 工具以 `confirmation="never"` 注册——这允许工具通过 gate 的 allowed 判断，进入 TOOL_INVOKE 和 TOOL_RESULT。

**生产 MCP 工具的 confirmation="always" 不变。** 这是测试配置选择，不是改变 MCP 安全策略。

### E.2 为什么测试工具不通过 register_mcp_tools() 注册

`register_mcp_tools()` 的 confirmation 参数是 hardcoded 的——无法从外部覆盖。如果通过 `register_mcp_tools()` 注册，测试工具必然是 `confirmation="always"`，无法走通完整管线。

直接使用 `register_tool()` 注册测试 MCP 工具（`capability="mcp_tool"`），可以精确控制 confirmation 策略。注册的函数闭包仍包裹 `FakeMCPClient.call_tool()`——MCP adapter 调用路径完全一致。

### E.3 为什么 chat() 需要暴露 tool_gate_tool_name

`_run_main_loop()` 构造 `LoopDependencies` 时不传 `tool_gate_tool_name`——依赖默认值 `"_safe_noop"`。要让 core.chat() 级别的测试能指定 MCP 工具名进入管线，需要：

```
chat() 接收 tool_gate_tool_name
  → _run_main_loop() 接收 tool_gate_tool_name
    → LoopDependencies(tool_gate_tool_name=tool_gate_tool_name, ...)
      → _try_phase1_turn_end_runtime_action() 使用 dependencies.tool_gate_tool_name
```

这是参数透传，不改变任何 pipeline 逻辑。

## F. Fake/Real 边界

- **FakeMCPClient** — 不启动 server、不联网、不读 .env
- **FakeProvider** — 不调用真实 LLM API
- fake MCP tool descriptor（测试中构造）
- 测试注册的 MCP 工具使用 `capability="mcp_tool"`（与生产注册一致）
- fake/real 差异仅限于 adapter 实例（FakeMCPClient vs StdioMCPClient, FakeProvider vs real provider）
- Tool 管线本身不因 fake/real 而产生分支

## G. Dogfood/Evidence 边界

- direct `FakeMCPClient.call_tool()` → L1 (`subsystem_integration`)
- `dispatcher.route(TOOL_GATE/TOOL_INVOKE/TOOL_RESULT)` → L2 (`harness_runtime_e2e`)
- `core.chat()` → `route_from_runtime_loop()` → L3 (`real_core_loop_runtime_e2e`)
- evidence 不得 overclaim——只证明 MCP tool-like call 能走 L3，不声称 MCP resources/prompts/multi-server/auth

## H. 不做什么

- 不新增 Anchor
- 不新增 branch point
- 不新增 runtime flow
- 不新增 RuntimeActionType
- 不修改 ToolGateHandler / ToolInvokeHandler / ToolResultFeedbackHandler
- 不修改 loop.py（已支持 tool_gate_tool_name 参数化）
- 不修改 dispatcher.py
- 不修改 register_mcp_tools() 的 confirmation 策略
- 不实现 MCP resources / prompts
- 不实现 multi-server discovery
- 不实现 auth/secret flow
- 不实现 Policy Re-Eval
- 不实现 D4 mid-pipeline not_found
- 不实现 Retry/Error Recovery
- 不实现 Multi Tool
- 不连接真实 MCP server
- 不调用真实 API
- 不读 .env
- 不让 direct MCP adapter call 冒充 L3
- 不让 direct dispatcher.route 冒充 L3
- 不让 payload spoofing 升级 evidence

## I. Open Questions

1. **生产 MCP 工具的 confirmation="always" 何时能走通完整管线？** — 需要在 runtime loop 中实现 confirmation 交互流程（模型输出 tool_use → user confirm → re-invoke with confirmed tool）。这是 deferred 项，不属于本轮。
2. **工具函数闭包中 FakeMCPClient 的引用方式** — `register_tool()` 注册的函数通过闭包捕获 `client` 和 `server`。测试工具需要在注册时提供 FakeMCPClient 实例——与 `register_mcp_tools()` 内部模式一致。
3. **是否需要新增 RuntimeActionType（如 MCP_TOOL_GATE）？** — 不需要。MCP 是 tool 的 capability variant，不是新的 action 类型。TOOL_GATE / TOOL_INVOKE / TOOL_RESULT 已足够。

## J. Review Checklist

- [ ] branch point 判断正确——复用已有 Tool branch point
- [ ] 不新增 Anchor / branch point / runtime flow
- [ ] 复用关系清晰——Tool Pipeline 和 MCP Subsystem 零改动
- [ ] 目标路径走 core.chat() → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
- [ ] production code 改动仅限于 chat() 参数透传
- [ ] fake/real 边界清楚——FakeMCPClient + FakeProvider
- [ ] evidence 分类正确——L3 需要 route_from_runtime_loop() provenance
- [ ] payload spoofing 不能升级 evidence
- [ ] 不做什么明确——不含 MCP resources/prompts/auth/Policy Re-Eval
- [ ] 测试 MCP 工具 confirmation="never" 不影响生产 MCP 工具 confirmation="always"
