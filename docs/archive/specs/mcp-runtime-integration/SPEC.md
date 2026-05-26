# SPEC: MCP Runtime Integration

Date: 2026-05-23
Status: active
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. Branch Point 判断

MCP tool-like execution 接入已有 **"tool execution / confirmation handling"** branch point（Contract §2）。

判断依据：
- 现有 TOOL_GATE handler 已能查询 TOOL_REGISTRY 中任何工具（含 MCP 工具）
- 现有 TOOL_INVOKE handler 已能通过 execute_tool adapter 执行 TOOL_REGISTRY 中任何工具函数（含 MCP 工具）
- 现有 TOOL_RESULT handler 已能格式化任何工具执行结果
- MCP 工具不在 TOOL_REGISTRY 之外——它们通过 register_mcp_tools() 注册，条目结构与本地工具一致
- MCP 工具与本地工具的唯一差异是 capability="mcp_tool" 和 risk_level="high"——这已经是 TOOL_GATE 的已知元数据维度

**不新增 branch point**。MCP tool-like execution 是已有 Tool branch point 下的一个 variant：capability="mcp_tool" 的工具走同一 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT 管线。

**不新增 Anchor**。这不是新 capability milestone，而是已有 Tool 管线的分支行为（behavior variant by capability type）。

**不新增 runtime flow**。编排层只组合已有 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT handler，不引入新的 RuntimeActionType。

**如果现有 Tool 生命周期不能承载 MCP tool-like call，必须停止并 Ask User。** 当前判断：可以承载。MCP 工具已在 TOOL_REGISTRY，所有三个 handler 的 adapter 已支持 TOOL_REGISTRY 查询/执行/格式化。

## B. 复用关系

必须复用（不可重写）：

### MCP subsystem（已有，不变）
| 模块 | 复用方式 |
|------|---------|
| `agent/mcp.py` (register_mcp_tools) | 已在 TOOL_REGISTRY 中注册 MCP 工具——这是管线入口的数据源 |
| `agent/mcp_models.py` (MCPServerConfig, MCPToolDescriptor, MCPClient Protocol) | 数据模型不变 |
| `agent/mcp_policy.py` (evaluate_server_policy, evaluate_tool_policy) | 注册时 policy gate 不变；本轮不改变其调用时机 |
| `agent/mcp_sanitizer.py` | 描述脱敏不变 |
| `agent/mcp_audit.py` | 审计事件发射器不变 |
| `agent/mcp_stdio.py` (StdioMCPClient) | 真实 transport 不变；本轮只用 FakeMCPClient |
| `agent/mcp_bridge.py` (run_mcp_bridge) | bridge 编排不变；本轮不改变其调用者 |
| `agent/mcp_external_readiness.py` | readiness report 不变 |

### Tool lifecycle（已有，不变）
| 模块 | 复用方式 |
|------|---------|
| `agent/runtime_integration/tool_gate.py` (ToolGateHandler) | MCP 工具名称传入，复用 lookup_and_risk_check adapter |
| `agent/runtime_integration/tool_invoke.py` (ToolInvokeHandler) | MCP 工具名称+tool_input 传入，复用 execute_tool adapter |
| `agent/runtime_integration/tool_result_feedback.py` (ToolResultFeedbackHandler) | MCP 执行结果传入，复用 format_tool_result adapter |
| `agent/tool_registry.py` (TOOL_REGISTRY, execute_tool) | 不改变——MCP 工具已在其中 |

### 新增的 thin orchestrator
仅新增一个编排函数/类，负责：
1. 接收 MCP tool-like call（tool_name, tool_input）
2. 组合调用已有 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
3. 返回统一 evidence

不承载 policy、不执行工具函数、不做格式化——所有业务逻辑仍在已有 handler/adapter 中。

## C. 目标路径

```
MCP tool-like call (tool_name="mcp__server__tool", tool_input={...})
  → MCP tool orchestrator (thin composition layer)
    → TOOL_GATE dispatch (ToolGateHandler → lookup_and_risk_check)
    │   └─ gate_disposition: allowed/confirmation_required/blocked/not_found
    → TOOL_INVOKE dispatch (ToolInvokeHandler → execute_tool)
    │   └─ tool_output + execution_status + dangerous/risk/evidence
    → TOOL_RESULT dispatch (ToolResultFeedbackHandler → format_tool_result)
    │   └─ prompt_section + disposition
    → unified evidence return
  → return to caller (test harness or future runtime loop)
```

## D. Policy 语义

### 当前状态
- MCP policy gate (evaluate_server_policy + evaluate_tool_policy) 只在 **注册时** 运行
- 注册后 MCP 工具在 TOOL_REGISTRY 中是普通条目

### 本轮处理
- **每次 MCP tool-like call 必须进入 TOOL_GATE** — 这是本轮的核心交付
- TOOL_GATE 的 lookup_and_risk_check adapter 会检查：
  - 工具是否在 TOOL_REGISTRY（not_found）
  - 工具的 confirmation policy（allowed/confirmation_required）
  - risk_level 赋值
- **不重复运行完整 MCP policy (evaluate_server_policy + evaluate_tool_policy)** — 那属于 MCP config/bridge 层，已有注册时检查

### Deferred: 每次执行时重新运行 MCP policy
- 风险：注册后 server 端 descriptor 变更（Rug Pull）不会被 detect
- 后续最小方案：在 TOOL_GATE 的 lookup_and_risk_check adapter 中为 capability="mcp_tool" 的工具增加重新评估逻辑
- 本轮不实现——scope 限定在接入管线，不扩展 MCP policy 语义

## E. Fake/Real 边界

本轮只允许：
- **FakeMCPClient** — 不启动 server、不联网、不用 .env
- fake MCP tool descriptor（测试中构造，不来自真实 server）
- no network, no real MCP server, no real API, no real external process

fake/real 差异仅限于 MCPClient 实例（FakeMCPClient vs StdioMCPClient），不影响 Tool 管线本身的分类。

## F. Dogfood/Evidence 边界

- direct MCP client call（FakeMCPClient.call_tool）→ **subsystem_integration**
- 通过 orchestrator → dispatcher.route(TOOL_GATE/TOOL_INVOKE/TOOL_RESULT) → **harness_runtime_e2e**（有完整 target_module_proof）
- 只有 real core loop (route_from_runtime_loop) → **real_core_loop_runtime_e2e**（本轮 deferred）
- evidence 不得 overclaim full MCP capability——MCP resources/prompts/multi-server/discovery 不在本轮

## G. 不做什么

- MCP resources, MCP prompts
- 真实 MCP server 连接
- production MCP transport (StdioMCPClient 已有但不用)
- auth/secret flow
- multi-server registry / discovery
- capability discovery expansion
- 真实 API / .env / 真实私人资料
- tool args 大扩展
- retry/error recovery
- UI confirmation interaction
- 修改 MCP policy 调用时机（server/tool policy re-eval deferred）
- run_mcp_bridge() 接入 production runtime（deferred）
- 修改 core.py / loop.py（不在本轮范围——orchestrator 是独立的 composition layer）

## H. Open Questions

1. **TOOL_GATE 对 MCP 工具的 allowlist 策略**：当前 ToolGateHandler 有 `_safe_noop` / `_confirmable_noop` 的内部 allowlist。MCP 工具名称是 `mcp__server__tool` 格式——既不是 `_` 前缀，也不是 model-visible 白名单。按照 ToolGateHandler 的逻辑（line 118: `elif tool_name not in visible_names`），MCP 工具如果不在 `get_model_visible_tools()` 中会被 rejected。需要验证 MCP 工具在 get_model_visible_tools() 中的可见性。

2. **orchestrator 是否应作为一个 RuntimeActionType handler 注册**：如果 orchestrator 作为 dispatcher 中的一个 handler 注册，它内部再调用 dispatcher.route() ——这是递归 dispatch 模式，需要验证 dispatcher 本身是否支持。

3. **orchestrator 与 tool_executor 的关系**：本轮不修改 tool_executor。orchestrator 是一个独立入口，MCP 工具走 orchestrator → dispatcher 管线，非 MCP 工具仍走 tool_executor。长期看所有工具应统一到 dispatcher 管线。

## I. Review Checklist

- [ ] branch point 判断正确——不是新 Anchor，不是新 branch point
- [ ] 复用关系清晰——不改已有 MCP subsystem，不改已有 Tool handler
- [ ] 目标路径走 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
- [ ] fake/real 边界清楚——只用 FakeMCPClient
- [ ] evidence 分类正确——不 overclaim
- [ ] 不做什么明确
- [ ] 没有新增 runtime flow
- [ ] 没有引入 fake/real 双路径
- [ ] 没有绕开已有 Tool 生命周期
