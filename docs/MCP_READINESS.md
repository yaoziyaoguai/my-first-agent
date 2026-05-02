# MCP Readiness and Local Stdio Validation

本文件记录 First Agent 当前的 MCP 集成边界。它不是完整 MCP 使用手册，也不声明
已经支持外部 MCP server；当前只完成了最小 client architecture seam 和本地 stdio
fixture 验证。

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

推荐先人工 review 当前本地 stdio validation diff。之后再选择：

1. commit 当前 diff；
2. 做 MCP CLI config management；
3. 做外部/reference MCP server 验证；
4. 做更完整 stdio fake-to-real transition。

任何真实 server、secret、networking、filesystem sandbox 指向都需要单独人工授权。
