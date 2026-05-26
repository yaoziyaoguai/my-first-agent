# Implementation Plan: MCP L3 Real Core-Loop Integration

Date: 2026-05-23
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Parent TDD: [TDD.md](TDD.md)

## 实现单元

### U1: chat() 新增 tool_gate_tool_name 参数（production code）

**文件**: `agent/core.py`

**改动**: `chat()` 函数签名新增可选参数 `tool_gate_tool_name: str | None = None`，透传至 `_run_main_loop()`。

**TDD 顺序**: 先写 T8（向后兼容），确保不传参数时行为不变。

### U2: _run_main_loop() 透传 tool_gate_tool_name（production code）

**文件**: `agent/core.py`

**改动**: `_run_main_loop()` 接收 `tool_gate_tool_name` 参数，传入 `LoopDependencies` 构造。

**TDD 顺序**: 先写 T1（core.chat L3），验证参数正确流入 LoopDependencies。

### U3: 测试文件 — MCP L3 real core-loop 测试

**文件**: `tests/runtime_integration/test_mcp_l3_real_core_loop.py`（新增）

**内容**: T1-T8 全部测试。

**TDD 顺序**: 严格 TDD-first — 每项测试先写、先跑红、再实现。

---

## TDD-First 顺序

```
1. 创建测试文件骨架 + T8 (backward compat) → RED
2. U1: chat() 参数 → GREEN (T8)
3. T1 (core.chat L3) → RED
4. U2: _run_main_loop() 透传 → GREEN (T1)
5. T4 (hook L3, confirmation="never") → 验证已有管线支持
6. T5 (hook, confirmation="always" blocked) → 验证安全策略不变
7. T2 (L1 direct adapter call) → 验证降级规则
8. T3 (L2 payload spoof) → 验证防伪造
9. T6 (no real API) → 验证隔离
10. T7 (regression) → 验证不破坏已有测试
```

---

## 允许修改范围

| 文件 | 改动类型 | 改动内容 |
|------|---------|---------|
| `agent/core.py:300-310` | 修改 | `chat()` 新增 `tool_gate_tool_name` 参数 |
| `agent/core.py:755-790` | 修改 | `_run_main_loop()` 接收并透传 `tool_gate_tool_name` |
| `tests/runtime_integration/test_mcp_l3_real_core_loop.py` | 新增 | T1-T8 全部测试 |
| `docs/implementation-notes/mcp-l3-real-core-loop.md` | 新增 | Implementation notes |

## 禁止修改范围

- `agent/loop.py` — 零改动（已支持 `tool_gate_tool_name` 参数化）
- `agent/runtime_integration/tool_gate.py` — 零改动
- `agent/runtime_integration/tool_invoke.py` — 零改动
- `agent/runtime_integration/tool_result_feedback.py` — 零改动
- `agent/runtime_integration/dispatcher.py` — 零改动
- `agent/runtime_integration/phase1_hook.py` — 零改动
- `agent/runtime_integration/evidence.py` — 零改动
- `agent/mcp.py` — 零改动（测试使用 `register_tool()` 直接注册，不走 `register_mcp_tools()`）
- `agent/mcp_models.py` — 零改动
- `agent/mcp_policy.py` — 零改动
- `agent/tool_registry.py` — 零改动

---

## 如何从 core.chat() 自然触发 MCP tool-like call

```
chat(user_input, tool_gate_tool_name="mcp__demo__hello", ...)
  → _run_main_loop(tool_gate_tool_name="mcp__demo__hello", ...)
    → LoopDependencies(tool_gate_tool_name="mcp__demo__hello", ...)
      → run_main_loop()
        → model call → dispatch → result is not None
          → _try_phase1_turn_end_runtime_action()
            → dependencies.tool_gate_tool_name = "mcp__demo__hello"
            → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
```

`chat()` 的新参数 `tool_gate_tool_name` 是纯透传参数——不参与任何 pipeline 决策，只决定 loop.py 中 TOOL_GATE action 使用哪个 tool_name。

## 如何复用 Tool Pipeline L3

1. `_try_phase1_turn_end_runtime_action()` 已实现完整管线（loop.py:30-210）——零改动
2. `ToolGateHandler.handle()` 已能查询 TOOL_REGISTRY 中任何工具 ——零改动
3. `ToolInvokeHandler.handle()` 已能通过 `execute_tool` adapter 执行任何工具函数 ——零改动
4. `ToolResultFeedbackHandler.handle()` 已能格式化任何工具结果 ——零改动
5. `dispatcher.route_from_runtime_loop()` 已提供 runtime-loop provenance ——零改动

## 如何调用 fake MCP adapter/client

测试工具注册方式（不使用 `register_mcp_tools()`——后者 hardcodes `confirmation="always"`）：

```python
from agent.mcp import FakeMCPClient, MCPCallResult
from agent.mcp_models import MCPServerConfig, MCPToolDescriptor
from agent.tool_registry import register_tool

server = MCPServerConfig(name="demo", transport="stdio", command="fake-cmd", enabled=True)
descriptor = MCPToolDescriptor(
    server_name="demo", name="hello",
    description="MCP L3 test tool",
    input_schema={"type": "object", "properties": {}},
)
call_result = MCPCallResult(content="mcp l3 result from fake client")
client = FakeMCPClient(
    tools_by_server={"demo": [descriptor]},
    results_by_call={("demo", "hello"): call_result},
)

def _call_mcp_tool(tool_input=None):
    """通过闭包调用 FakeMCPClient——与 register_mcp_tools() 内部模式一致。"""
    result = client.call_tool(server, descriptor.name, tool_input or {})
    return result.to_legacy_tool_result(server_name=server.name, tool_name=descriptor.name)

register_tool(
    name="mcp__demo__hello",
    description=descriptor.description,
    parameters=descriptor.parameters(),
    confirmation="never",       # 测试用：允许通过 gate allowed 判断
    capability="mcp_tool",      # 与生产注册一致
    risk_level="high",          # 与生产注册一致
    output_policy="bounded_text",
)(_call_mcp_tool)
```

## 如何避免 direct MCP adapter call 冒充 L3

- **证据链**: `dispatcher.route_from_runtime_loop()` 由 dispatcher 写入 `dispatcher_origin="runtime_loop"`，不从 payload 读取
- **payload 隔离**: `core_loop_invoked` / `core_entrypoint` / `runtime_hook_name` 由 dispatcher 写入 evidence，不从 request.payload 读取（dispatcher.py:511-516）
- **分类降级**: `classify_evidence_level()` 在缺少 `route_from_runtime_loop` provenance 时自动降级
- **T3 测试**: 显式验证 payload spoofing 不能升级 evidence

## evidence / classification 边界

| 路径 | evidence_level |
|------|---------------|
| `core.chat()` → `route_from_runtime_loop()` → handler | `real_core_loop_runtime_e2e` |
| `dispatcher.route()` → handler | `harness_runtime_e2e` |
| `dispatcher.route_from_runtime_loop()` without `core.chat()` | `harness_runtime_e2e`（缺少 core_entrypoint provenance）|
| `FakeMCPClient.call_tool()` direct | `subsystem_integration` |
| payload spoofing attempt | 降级为实际路径对应级别 |

## fake/real 边界

- FakeMCPClient: 测试用，不启动子进程、不联网
- FakeProvider: 测试用，不调用真实 LLM API
- 注册方式: `register_tool()` with `confirmation="never"`（测试）vs `register_mcp_tools()` with `confirmation="always"`（生产）
- Tool 管线本身: fake/real 共享同一代码路径，仅 adapter 实例不同

## dogfood 边界

- dogfood 脚本可传入自建 `runtime_action_dispatcher`，在 `chat()` 返回后访问 `action_log`
- dogfood 仍通过 `core.chat()` 入口——不构造 RuntimeActionRequest、不直接调 dispatcher.route()
- dogfood 的 `chat()` 调用自动获得 L3 evidence（通过 route_from_runtime_loop）

## stop conditions

以下任一条件触发时停止并 Ask User:
- P0/P1/BLOCKED 发现
- 同一问题在同一阶段修 2 次仍失败
- 需要修改 pipeline 引擎（loop.py, tool_gate.py, tool_invoke.py, tool_result_feedback.py）
- 需要新增 RuntimeActionType
- 需要修改 MCP subsystem
- full pytest 失败且根因不在本轮改动

## implementation notes 路径

`docs/implementation-notes/mcp-l3-real-core-loop.md`
