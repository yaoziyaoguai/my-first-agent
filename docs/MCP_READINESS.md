# MCP Readiness and Local Stdio Validation

本文件记录 First Agent 当前的 MCP 集成边界。`v0.7.0` 已 release 并完成
post-release dogfooding closure；这仍不是完整 MCP 使用手册，也不声明已经支持
外部 MCP server。当前完成的是最小 client architecture seam、本地 stdio fixture
验证，以及 release 后 smoke/dogfooding 覆盖。

## 当前已实现

- `agent.mcp.MCPServerConfig`：显式 server config；配置是 source of truth，未来
  CLI 只能管理配置。
- `agent.mcp.MCPToolDescriptor`：外部 MCP tool descriptor，不等于默认 registry tool。
- `agent.mcp.MCPCallResult`：把 MCP call result 映射回当前 legacy string ToolResult
  contract。
- `agent.mcp.MCPClient` / `FakeMCPClient`：用于 architecture seam 测试。
- `agent.mcp.register_mcp_tools()`：显式 opt-in，把 enabled server 的 tools 注册成本地
  `mcp__server__tool`，默认 `confirmation="always"`。
- `agent.mcp_stdio.StdioMCPClient`：最小 stdio JSON-RPC transport，用于本地 fixture
  端到端验证；覆盖 server error、malformed response 和 request timeout 的最小错误边界。

## 当前没有实现

- 没有连接真实外部 MCP server。
- 没有实现 HTTP / SSE / Streamable HTTP transport。
- 没有支持 resources / prompts / sampling / roots。
- 没有读取 `.env`、真实 secret、`agent_log.jsonl`、真实 `sessions/` 或 `runs/`。
- 没有把 MCP tools 放进 base/default registry。
- 没有改变 checkpoint/runtime/TUI/core loop 或 tool_result message 写入语义。

## Release / dogfooding closure status

- `v0.7.0` 已 tag + push，作为 Tooling Foundation / MCP readiness milestone。
- Post-release verification 已确认本地与 remote release 状态一致。
- Self-dogfooding 覆盖了 MCP `list_tools`、`call_tool` success/failure、explicit
  opt-in registry boundary、confirmation policy 和 legacy ToolResult mapping。
- `tests/test_second_round_dogfooding_smoke.py` 固化了 release 后 smoke：MCP local
  fixture 不进 base/default registry，显式 opt-in 后才可执行，且仍需要确认。

## 配置文件与 CLI 的关系

推荐设计是：配置文件是 source of truth，CLI 命令只负责 add/list/remove 这份配置。
当前实现只提供 loader seam，不提供完整 CLI 管理命令。

示例配置形态：

```json
{
  "mcpServers": {
    "demo": {
      "transport": "stdio",
      "command": "/absolute/path/to/server",
      "args": ["--safe-mode"],
      "env": {
        "TOKEN_PLACEHOLDER": "${TOKEN_PLACEHOLDER}"
      },
      "enabled": true
    }
  }
}
```

安全约束：

- 不把真实 token 写进 repo。
- loader 不读取 `.env`，也不解析 env var。
- `enabled=false` 的 server 不会注册任何 tool。

## TUI 与 MCP CLI 的关系

First Agent 已经有 TUI，但 TUI 和 MCP CLI 不在同一层：

- TUI 是用户交互界面，负责输入、显示、确认体验；
- MCP CLI 未来只应是 MCP server config management 的薄入口；
- MCP CLI 不是 runtime 逻辑中心，也不是配置 source of truth；
- 当前 MCP 最小闭环已经通过 config loader / client / local stdio validation / explicit
  registry opt-in / confirmation boundary 建立，因此 MCP CLI 不是本阶段收口 blocker；
- 如果未来 TUI 要管理 MCP server，也应该复用同一个 MCP Config Service / loader，
  而不是把配置读写逻辑写进 TUI 或 runtime core。

## 本地 stdio 验证

测试使用 `tests/fixtures/minimal_mcp_stdio_server.py`。该 fixture：

- 只处理单条 JSON-RPC line；
- 支持 `initialize`、`tools/list`、`tools/call`；
- 覆盖 unknown tool error 到 legacy failure string 的映射；
- 不读取文件；
- 不联网；
- 不访问 secret；
- 不指向真实 home / project root / sessions / runs。

验证命令：

```bash
.venv/bin/python -m pytest tests/test_mcp_stdio_integration.py -q -rx
```

当前验证包含：

- initialize handshake；
- list_tools；
- call_tool success；
- unknown tool / server error；
- malformed JSON response；
- request timeout / process cleanup。

## 架构边界

- MCP client 只负责 config / list_tools / call_tool / transport。
- tool registry 只在显式 opt-in 时接收 MCP tools。
- tool executor 不知道 tool 来自 fake MCP、stdio MCP 还是本地工具。
- confirmation/policy 不被绕过：MCP tools 默认 always confirm。
- MCP result 仍映射到 legacy string ToolResult contract，不做结构化迁移。

## 下一阶段

推荐先人工 review / push 当前 post-release dogfooding closure commit。之后再单独选择：

1. MCP CLI config management：只做 config source-of-truth 的薄管理入口；
2. 外部/reference MCP server 验证：必须先明确 networking、secret、filesystem sandbox
   授权；
3. 更完整 stdio fake-to-real transition；
4. resources / prompts / sampling / roots：后续增强，不属于 v0.7.0 closure。

任何真实 server、secret、networking、filesystem sandbox 指向都需要单独人工授权。
