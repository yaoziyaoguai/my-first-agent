"""Minimal stdio MCP transport for local validation.

本模块只实现一个很小的 stdio JSON-RPC transport，用于低风险本地 fixture 验证：
启动显式配置的本地命令、发送一条 JSON-RPC 请求、读取一条 JSON-RPC 响应。它不
使用 shell、不继承真实环境变量、不联网，也不参与 runtime/checkpoint/TUI。
"""

from __future__ import annotations

import json
from json import JSONDecodeError
import subprocess
from typing import Any, Mapping, Sequence

from agent.mcp import MCPCallResult, MCPServerConfig, MCPToolDescriptor


class MCPTransportError(RuntimeError):
    """stdio transport 层错误；由 registry execute_tool 兜底为 legacy failure。"""


class StdioMCPClient:
    """最小 stdio MCP client。

    这是 fake-to-real 的第一步：client 只负责 transport + JSON-RPC shape，不注册工具、
    不做确认、不写 checkpoint。registry opt-in 和 confirmation 仍由 `agent.mcp`
    / `agent.tool_registry` 负责。
    """

    def __init__(self, *, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds

    def initialize(self, server: MCPServerConfig) -> Mapping[str, Any]:
        """发送 initialize 请求，用于端到端验证 server handshake。"""

        return self._send_request(
            server,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "my-first-agent", "version": "mcp-readiness"},
            },
        )

    def list_tools(self, server: MCPServerConfig) -> Sequence[MCPToolDescriptor]:
        result = self._send_request(server, "tools/list", {})
        tools = result.get("tools", ())
        if not isinstance(tools, list):
            raise MCPTransportError("MCP tools/list result.tools 必须是 list")

        descriptors: list[MCPToolDescriptor] = []
        for tool in tools:
            if not isinstance(tool, Mapping):
                raise MCPTransportError("MCP tool descriptor 必须是 object")
            descriptors.append(
                MCPToolDescriptor(
                    server_name=server.name,
                    name=str(tool["name"]),
                    description=str(tool.get("description", "")),
                    input_schema=tool.get("inputSchema", {}),
                )
            )
        return tuple(descriptors)

    def call_tool(
        self,
        server: MCPServerConfig,
        tool_name: str,
        tool_input: Mapping[str, Any],
    ) -> MCPCallResult:
        result = self._send_request(
            server,
            "tools/call",
            {"name": tool_name, "arguments": dict(tool_input)},
        )
        return MCPCallResult(
            content=result.get("content", ""),
            is_error=bool(result.get("isError", False)),
        )

    def _send_request(
        self,
        server: MCPServerConfig,
        method: str,
        params: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """通过 stdio 发送单条 JSON-RPC request 并读取 response。

        安全边界：
        - `shell=False` 且 command/args 来自显式 config；
        - `env` 只使用 config 中的显式 mapping，不继承真实 `.env` / shell 环境；
        - 每次请求启动短生命周期本地进程，避免在本 slice 处理长期 server state。
        """

        if server.transport != "stdio":
            raise MCPTransportError(f"当前只实现 stdio transport: {server.transport}")
        if not server.command:
            raise MCPTransportError("stdio MCP server command 不能为空")

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": dict(params),
        }
        process = subprocess.Popen(
            [server.command, *server.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            env=dict(server.env),
        )
        try:
            stdout, stderr = process.communicate(
                json.dumps(request, ensure_ascii=False) + "\n",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise MCPTransportError(
                f"MCP stdio request timeout: {method}"
            ) from exc

        if process.returncode not in (0, None) and not stdout.strip():
            raise MCPTransportError(
                f"MCP stdio server exited with {process.returncode}: {stderr.strip()}"
            )

        response = _parse_json_response(stdout)
        if "error" in response:
            raise MCPTransportError(f"MCP JSON-RPC error: {response['error']}")
        result = response.get("result", {})
        if not isinstance(result, Mapping):
            raise MCPTransportError("MCP JSON-RPC result 必须是 object")
        return result


def _parse_json_response(stdout: str) -> Mapping[str, Any]:
    """解析 fixture server 的单行 JSON-RPC response。"""

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            response = json.loads(stripped)
        except JSONDecodeError as exc:
            raise MCPTransportError("MCP stdio server 返回了非法 JSON") from exc
        if not isinstance(response, Mapping):
            raise MCPTransportError("MCP JSON-RPC response 必须是 object")
        return response
    raise MCPTransportError("MCP stdio server 未返回 JSON-RPC response")
