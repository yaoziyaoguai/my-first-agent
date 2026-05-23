# Implementation Plan: MCP Runtime Integration

Date: 2026-05-23
SPEC: [SPEC.md](./SPEC.md)
TDD: [TDD.md](./TDD.md)

## 1. Implementation Units

### U1: MCP Tool Orchestrator (`agent/runtime_integration/mcp_tool_orchestrator.py`)

**职责**：thin composition layer，串联已有 TOOL_GATE → TOOL_INVOKE → TOOL_RESULT handler。

**不是** dispatcher-registered handler —— orchestrator 持有 dispatcher 引用，内部调用 `dispatcher.route()`，不是递归 dispatch。

```python
def run_mcp_tool_pipeline(
    dispatcher: RuntimeActionDispatcher,
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    parent_trace_id: str = "trace:mcp-tool-pipeline",
) -> MCPPipelineResult:
```

返回值：
- `gate_result`: TOOL_GATE dispatch 结果
- `invoke_result`: TOOL_INVOKE dispatch 结果（gate blocked 时为 None）
- `result_feedback`: TOOL_RESULT dispatch 结果（invoke 未执行时为 None）
- `action_log_entries`: 本次 pipeline 在 dispatcher.action_log 中的条目数

**stop 条件**：
- TOOL_GATE 返回 `not_found` / `blocked` / `rejected` → 不继续 TOOL_INVOKE / TOOL_RESULT
- TOOL_INVOKE 返回 `not_found` / `error` → 仍进入 TOOL_RESULT（error 也需要格式化）

### U2: Test File (`tests/runtime_integration/test_mcp_runtime_integration.py`)

按 TDD.md Phase A-F 顺序实现 15 个测试，TDD-first。

---

## 2. 修改范围

### 允许修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent/runtime_integration/mcp_tool_orchestrator.py` | **CREATE** | thin orchestrator |
| `tests/runtime_integration/test_mcp_runtime_integration.py` | **CREATE** | 15 个 TDD 测试 |

### 禁止修改

- `agent/mcp.py` — register_mcp_tools / FakeMCPClient 不变
- `agent/mcp_models.py` — 数据模型不变
- `agent/mcp_policy.py` — policy gate 不变
- `agent/mcp_sanitizer.py` — 脱敏不变
- `agent/mcp_audit.py` — 审计不变
- `agent/mcp_stdio.py` — transport 不变
- `agent/mcp_bridge.py` — bridge 不变
- `agent/mcp_config*.py` — config 不变
- `agent/mcp_external_readiness.py` — readiness 不变
- `agent/tool_registry.py` — TOOL_REGISTRY / execute_tool 不变
- `agent/runtime_integration/tool_gate.py` — ToolGateHandler 不变
- `agent/runtime_integration/tool_invoke.py` — ToolInvokeHandler 不变
- `agent/runtime_integration/tool_result_feedback.py` — ToolResultFeedbackHandler 不变
- `agent/runtime_integration/dispatcher.py` — dispatcher 不变
- `agent/runtime_integration/evidence.py` — evidence/target catalog 不变
- `agent/runtime_integration/phase1_hook.py` — build_phase1_dispatcher 不变
- `agent/core.py` — 不在本轮范围
- `agent/loop.py` — 不在本轮范围

---

## 3. TDD-First 顺序

```
U2 Phase A (3 tests) → RED → U1 orchestrator 不需要(用现有 dispatcher)
U2 Phase B (4 tests) → RED → U1 不需要(用现有 dispatcher)
U2 Phase C (2 tests) → RED → U1 不需要(用现有 dispatcher)
U2 Phase D (3 tests) → RED → U1 orchestrator → GREEN
U2 Phase E (4 tests) → RED → 可能需要 minor fix → GREEN
U2 Phase F (2 tests) → 回归验证 → GREEN
```

Phase A-C 测试使用已有 dispatcher + handler 组合，不需要 orchestrator。
Phase D 测试才驱动 orchestrator 的创建。

---

## 4. 复用策略

### MCP adapter/subsystem 复用

测试中通过以下方式复用：

```python
from agent.mcp import FakeMCPClient, register_mcp_tools
from agent.mcp_models import MCPServerConfig, MCPToolDescriptor, mcp_registry_tool_name

# 构造 fake server + fake tool
server = MCPServerConfig(name="demo", transport="stdio", enabled=True)
descriptor = MCPToolDescriptor(
    name="hello", server_name="demo",
    description="Say hello", parameters_schema={},
)
client = FakeMCPClient(
    tools_by_server={"demo": [descriptor]},
    results_by_call={("demo", "hello"): MCPCallResult(content="hello from MCP")},
)
register_mcp_tools([server], client, dry_run=False)
```

### Tool lifecycle 复用

- TOOL_GATE → 已有 ToolGateHandler（MCP tools 在 TOOL_REGISTRY 中，走 `visible_names` 路径）
- TOOL_INVOKE → 已有 ToolInvokeHandler（`_tool_invoke_adapter` 调用 `execute_tool()`）
- TOOL_RESULT → 已有 ToolResultFeedbackHandler（`format_tool_result` 通用）

MCP 工具名格式 `mcp__server__tool` 在 ToolGateHandler 中的路径：
1. 不是 `_` 前缀 → 不进入 allowlist 路径
2. 在 `get_model_visible_tools()` 中（capability="mcp_tool" 通过 filter，受 max_mcp 限制）
3. `needs_tool_confirmation("mcp__demo__hello")` → confirmation="always" → True → gate_disposition="confirmation_required"

### 旧 direct executor path 处理

**本轮不修改** `tool_executor`。MCP 工具在 TOOL_REGISTRY 中仍可通过 `execute_tool("mcp__demo__hello", {})` 直接调用——这是向后兼容行为，不是本轮要消除的。

本轮交付的是**新路径**：orchestrator → dispatcher → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT。这个路径提供 governance layer (gate/invoke/result)，但不删除旧路径。

---

## 5. Policy Gate 处理

### 本轮

- MCP 工具每次通过 orchestrator 调用时进入 TOOL_GATE
- TOOL_GATE 的 `lookup_and_risk_check` adapter 检查 TOOL_REGISTRY + confirmation policy
- `confirmation="always"` → gate_disposition="confirmation_required"

### Deferred

- 不重新运行完整 MCP policy（evaluate_server_policy + evaluate_tool_policy）
- 风险：注册后 server 端 descriptor 变更不会被 detect
- 后续方案：TOOL_GATE 的 adapter 中为 capability="mcp_tool" 增加 re-eval

---

## 6. Evidence / Classification 边界

| 调用路径 | 分类 |
|---------|------|
| `FakeMCPClient.call_tool()` 直接调用 | `subsystem_integration` |
| `dispatcher.route(TOOL_GATE)` 直接调用 | `harness_runtime_e2e` (target_module_proof 完整) |
| `run_mcp_tool_pipeline(dispatcher, ...)` | `harness_runtime_e2e`（orchestrator 内部走 dispatcher） |
| `dispatcher.route_from_runtime_loop(...)` | `real_core_loop_runtime_e2e` — DEFERRED |

orchestrator 只组合已有 handler，不自产 evidence。evidence 来自 dispatcher context，classifier 正确判定为 harness_runtime_e2e。

---

## 7. Fake/Real 边界

- 测试只用 FakeMCPClient
- fake MCPToolDescriptor（测试中构造，不来自真实 server）
- no network, no .env, no real MCP server, no real API

---

## 8. Dogfood 边界

- orchestrator 不写 checkpoint，不推进 runtime state
- 不进入 core.py / loop.py
- 不构造 RuntimeActionRequest 绕过 dispatcher

---

## 9. Stop Conditions

| 条件 | 动作 |
|------|------|
| 现有 Tool 生命周期不能承载 MCP tool-like call | 停止并 Ask User |
| 需要新增 branch point / Anchor / runtime flow | 停止并 Ask User |
| 需要修改已有 MCP subsystem | 停止并 Ask User |
| TDD test 无法通过已有 handler | 检查 SPEC 判断是否正确，回退到 SPEC |
| Phase F 回归失败 | 回退到 Implementation 修正 |
| 同一问题在同一阶段修 2 次仍失败 | 停止并升级 |

---

## 10. Implementation Notes 路径

`docs/implementation-notes/mcp-runtime-integration.md`
