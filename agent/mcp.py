"""MCP client architecture seam（不实现真实 transport）。

本模块只定义 First Agent 未来接 MCP server 前的本地边界：server config、
tool descriptor、call result、client protocol、fake client，以及“显式 opt-in 后
注册成本地 registry tool”的适配函数。它不启动 stdio 进程、不连 HTTP/SSE、
不读取 `.env`，也不参与 runtime transition / checkpoint / TUI。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol, Sequence

from agent.tool_registry import TOOL_REGISTRY, register_tool


MCP_TRANSPORTS = frozenset({"stdio", "http", "sse", "streamable_http"})
SENSITIVE_CONFIG_NAMES = frozenset({".env", "agent_log.jsonl"})
SENSITIVE_CONFIG_PARTS = frozenset({"sessions", "runs"})


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


@dataclass(frozen=True)
class MCPCallResult:
    """MCP call 结果的最小本地表示。

    这不是结构化 ToolResult 迁移；第一阶段只把 MCP fake client 的结果压回当前
    legacy string contract，避免 tool_executor 的 prefix classifier 收到 list 后
    半路暴露结构化迁移缺口。
    """

    content: Any = ""
    is_error: bool = False
    error_message: str | None = None

    def to_legacy_tool_result(self, *, server_name: str, tool_name: str) -> str:
        """映射到现有 legacy string ToolResult contract。"""

        if self.is_error:
            if self.error_message is not None:
                detail = self.error_message
            elif isinstance(self.content, list):
                detail = _stringify_mcp_content_blocks(self.content)
            elif self.content is None:
                detail = ""
            else:
                detail = str(self.content)
            return f"错误：MCP 工具 {server_name}/{tool_name} 执行失败：{detail}"
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return _stringify_mcp_content_blocks(self.content)
        return str(self.content)


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
    ) -> MCPCallResult:
        """调用一个 server tool。"""


@dataclass
class FakeMCPClient:
    """测试用 in-memory MCP client，不启动 server、不联网。"""

    tools_by_server: Mapping[str, Sequence[MCPToolDescriptor]] = field(default_factory=dict)
    results_by_call: Mapping[tuple[str, str], MCPCallResult] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def list_tools(self, server: MCPServerConfig) -> Sequence[MCPToolDescriptor]:
        return tuple(self.tools_by_server.get(server.name, ()))

    def call_tool(
        self,
        server: MCPServerConfig,
        tool_name: str,
        tool_input: Mapping[str, Any],
    ) -> MCPCallResult:
        call_input = dict(tool_input)
        self.calls.append((server.name, tool_name, call_input))
        return self.results_by_call.get(
            (server.name, tool_name),
            MCPCallResult(
                is_error=True,
                error_message="fake MCP result not configured",
            ),
        )


def _reject_sensitive_config_path(path: Path) -> None:
    """拒绝把敏感运行产物当作 MCP 配置读取。"""

    if path.name in SENSITIVE_CONFIG_NAMES or SENSITIVE_CONFIG_PARTS.intersection(path.parts):
        raise ValueError(f"拒绝读取敏感 MCP 配置路径: {path}")


def _stringify_mcp_content_blocks(content: Sequence[Any]) -> str:
    """把 MCP content blocks 压回当前 runtime 可分类的字符串。

    MCP 常见返回形态是 `[{"type": "text", "text": "..."}]`；但当前
    ToolResult classifier 仍是 string prefix contract。这里做最小映射，不把
    ToolResult 半路迁移成结构化对象，也不改变 conversation append 语义。
    """

    parts: list[str] = []
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def load_mcp_server_configs(path: str | Path) -> tuple[MCPServerConfig, ...]:
    """从显式 JSON 配置路径读取 MCP server configs。

    该 loader 不扫描 home、不读取 `.env`、不解析 env var；调用方必须传入明确路径。
    测试使用 tmp fixture，真实用户配置位置应在后续 CLI/config-management slice 决定。
    """

    config_path = Path(path)
    _reject_sensitive_config_path(config_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return load_mcp_server_configs_from_mapping(raw)


def load_mcp_server_configs_from_mapping(config: Mapping[str, Any]) -> tuple[MCPServerConfig, ...]:
    """从 mapping 解析 MCP server configs，便于测试和未来 CLI 管理配置。"""

    raw_servers = config.get("mcpServers", {})
    if not isinstance(raw_servers, Mapping):
        raise ValueError("mcpServers 必须是 object")

    servers: list[MCPServerConfig] = []
    for name, raw_server in raw_servers.items():
        if not isinstance(raw_server, Mapping):
            raise ValueError(f"MCP server '{name}' 配置必须是 object")
        raw_args = raw_server.get("args", ())
        raw_env = raw_server.get("env", {})
        if not isinstance(raw_env, Mapping):
            raise ValueError(f"MCP server '{name}' env 必须是 object")
        servers.append(
            MCPServerConfig(
                name=str(name),
                transport=str(raw_server.get("transport", "stdio")),
                command=(
                    str(raw_server["command"])
                    if raw_server.get("command") is not None
                    else None
                ),
                args=tuple(str(arg) for arg in raw_args),
                env={str(key): str(value) for key, value in raw_env.items()},
                enabled=bool(raw_server.get("enabled", False)),
            )
        )
    return tuple(servers)


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


def register_mcp_tools(
    servers: Sequence[MCPServerConfig],
    client: MCPClient,
) -> tuple[str, ...]:
    """显式把 enabled MCP tools 注册成本地 optional registry tools。

    这是 MCP client 和 tool_registry 的唯一连接点：client 负责 list/call，registry
    负责模型可见 schema、allowed tools 和 confirmation policy。MCP client 不写
    checkpoint、不参与 runtime transition，也不绕过 HITL；所有注册的 MCP tools
    默认 `confirmation="always"`。
    """

    registered: list[str] = []
    for server in servers:
        if not server.enabled:
            continue
        for descriptor in client.list_tools(server):
            if descriptor.server_name != server.name:
                raise ValueError(
                    f"MCP tool '{descriptor.name}' 属于 server '{descriptor.server_name}'，"
                    f"不能注册到 '{server.name}'"
                )
            registry_name = mcp_registry_tool_name(server.name, descriptor.name)
            if registry_name in TOOL_REGISTRY:
                raise ValueError(f"MCP tool registry name 已存在: {registry_name}")

            def _call_mcp_tool(
                _server: MCPServerConfig = server,
                _descriptor: MCPToolDescriptor = descriptor,
                **tool_input: Any,
            ) -> str:
                result = client.call_tool(_server, _descriptor.name, tool_input)
                return result.to_legacy_tool_result(
                    server_name=_server.name,
                    tool_name=_descriptor.name,
                )

            register_tool(
                name=registry_name,
                description=f"[MCP:{server.name}] {descriptor.description}",
                parameters=descriptor.parameters(),
                confirmation="always",
                capability="mcp_tool",
                risk_level="high",
                output_policy="bounded_text",
            )(_call_mcp_tool)
            registered.append(registry_name)
    return tuple(registered)
