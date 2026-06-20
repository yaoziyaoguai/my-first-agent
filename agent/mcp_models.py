"""MCP 共享数据模型与命名工具。

中文学习边界：
- 本模块只包含 MCP 相关的纯数据 dataclass、常量和纯函数命名工具，
  不包含任何 transport 逻辑、policy 决策、client 实现或 registry 操作。
- 从 agent/mcp.py 提取出来是为了打破 mcp.py ↔ mcp_policy.py 的循环导入：
  mcp_policy 需要 MCPServerConfig / MCPToolDescriptor / mcp_registry_tool_name，
  但 mcp.py 现在懒导入 mcp_policy。如果这些都在 mcp.py 中就会形成循环。
  把这些纯数据模型和纯函数放在独立模块中，两个模块都可以安全导入。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

MCP_TRANSPORTS = frozenset({"stdio", "http", "sse", "streamable_http"})


@dataclass(frozen=True)
class MCPServerConfig:
    """MCP server 的静态配置模型。

    配置是 source of truth；CLI 未来只能管理这份配置。`enabled=False` 是安全默认：
    写在配置里的 server 也不会自动进入 registry，必须显式启用并调用 opt-in seam。
    本 dataclass 只保存配置，不启动 server、不解析 secret、不读取环境变量。
    """

    name: str
    transport: str = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    enabled: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MCP server name 不能为空")
        if self.transport not in MCP_TRANSPORTS:
            raise ValueError(f"不支持的 MCP transport: {self.transport}")


@dataclass(frozen=True)
class MCPToolDescriptor:
    """MCP server 暴露的 tool 描述。

    descriptor 只描述外部 tool schema；它不是本地 registry entry。只有通过
    `register_mcp_tools()` 显式 opt-in 后，descriptor 才会映射成本地 tool。
    """

    server_name: str
    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    def parameters(self) -> dict[str, Any]:
        """把 MCP object schema 映射到当前 registry 的 properties dict。"""
        if self.input_schema.get("type") != "object":
            return {}
        properties = self.input_schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return {}
        return dict(properties)


class MCPClient(Protocol):
    """MCP client protocol：只定义 list_tools / call_tool seam。

    真实 stdio/HTTP/SSE transport 未来可以实现这个 protocol；当前阶段只用
    FakeMCPClient 做架构测试，避免连接真实 server 或引入依赖。
    """

    def list_tools(self, server: MCPServerConfig) -> Sequence[MCPToolDescriptor]:
        """列出一个 server 暴露的 tools。"""

    def call_tool(
        self,
        server: MCPServerConfig,
        tool_name: str,
        tool_input: Mapping[str, Any],
    ) -> Any:  # 返回 MCPCallResult（在 agent/mcp.py 中定义）
        """调用一个 server tool。"""


def mcp_registry_tool_name(server_name: str, tool_name: str) -> str:
    """生成不会污染 base tool 命名空间的 MCP registry 名。

    `mcp__server__tool` 前缀让模型和审计日志能一眼区分外部能力；MCP tools 仍需
    显式注册，绝不会因为导入 `agent.tools` 进入 base/default registry。
    """
    return f"mcp__{_safe_token(server_name)}__{_safe_token(tool_name)}"


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if not token:
        raise ValueError("MCP registry token 不能为空")
    return token
