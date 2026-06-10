# D-02 — MCP Real External Server Connection Readiness

**创建日期**: 2026-06-02
**状态**: DRAFT
**范围**: MCP bridge real external server connection readiness assessment
**Source**: handoff §8 D-02, §9 Route 3

---

## 1. Current State (What's Done)

| Item | Status | Evidence |
|------|--------|----------|
| MCP bridge lifecycle | CLOSED | MCP_BRIDGE_LIFECYCLE RuntimeActionType + disposable dispatcher (Loop 2.4) |
| Local stdio fixture | CLOSED | `scripts/fixtures/mcp_echo_server.py` — opt-in echo server |
| Bridge registration | CLOSED | REAL-EVIDENCE-005: 12/12 PASS — tools_discovered=2, tools_registered=2, MCP bridge operational with fixture |
| Runtime-mediated invocation | CLOSED | REAL-EVIDENCE-007: 10/10 PASS — core.chat → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → StdioMCPClient.call_tool(subprocess JSON-RPC) → TOOL_RESULT |
| mcp.discover branch point | PARTIAL | code path complete, real server pending |
| mcp.invoke branch point | PARTIAL | MCP tool pipeline complete, real server validation pending |
| Server allowlist | WORKING | rejects non-matching server |
| Destructive tool block | WORKING | blocks known destructive tools |
| Contract tests | 30/30 PASS | bridge module state / dynamic mcp_available / registration / allowlist / invocation |
| confirmation strategy | always (safe default) | production 默认拦截，validation 使用 confirmation='never' override |

## 2. What's Blocked

### 2.1 Real External MCP Server Connection

真实外部 MCP server 连接需要：

1. **外部 MCP server fixture** — 一个真实运行的外部 MCP server 进程（如 filesystem server、GitHub server）
2. **MCP config file** — 含真实 server entry（command/args/env/cwd）
3. **MY_FIRST_AGENT_MCP_ENABLE=1** — opt-in 激活
4. **MY_FIRST_AGENT_MCP_DRY_RUN=0** — 非 dry-run 模式

这些依赖外部服务，不属于代码就绪范围。

### 2.2 Required Validation (Blocked)

```
(1) 搭建真实 MCP server fixture (filesystem/GitHub/memory)
(2) MCP config 文件含真实 server entry
(3) run_mcp_bridge(mode="registration", dry_run=False) → StdioMCPClient 真实连接
(4) list_tools → server allowlist → TOOL_REGISTRY
(5) get_model_visible_tools(max_mcp_tools=5) 含 MCP tools
(6) 模型 tool_use MCP tool (非 FakeProvider deterministic)
(7) TOOL_GATE (含 server_allowlist) → TOOL_INVOKE → StdioMCPClient.call_tool
(8) real server response → TOOL_RESULT → conversation context
(9) confirmation="always" 在 real core loop 中正确拦截
```

## 3. What Can Be Done Now (Without External Server)

以下项可在无外部 server 的情况下完成：

- [x] Bridge lifecycle dispatcher evidence
- [x] Local stdio echo fixture (mcp_echo_server.py)
- [x] Contract tests (30/30)
- [x] Server allowlist / destructive tool block tests
- [x] Branch point status updated to PARTIAL
- [ ] ~~额外 local fixture scenarios~~ (已充分覆盖)

## 4. Next-Step Action

**当前不做**真实外部 MCP server 连接。Blocked by: 需用户提供外部 MCP server fixture/config。

用户就绪后：
1. 在 config/mcp_servers 中添加真实 server entry
2. 设置 `MY_FIRST_AGENT_MCP_ENABLE=1`
3. 设置 `MY_FIRST_AGENT_MCP_DRY_RUN=0`
4. 运行当前 MCP boundary focused tests 验证 bridge connection contract
5. 运行真实 chat loop 验证 MCP tool 在 production confirmation 策略下的行为

## 5. Status

**BLOCKED_BY_EXTERNAL_SERVER** — code path complete, bridge lifecycle evidence dispatched, local fixture validated (12/12 PASS), MCP invocation chain verified (10/10 PASS). Real external MCP server connection requires user-provided server fixture and explicit opt-in config.
