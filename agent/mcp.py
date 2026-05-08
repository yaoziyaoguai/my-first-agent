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
from typing import Any, Mapping, Sequence

from agent.mcp_models import (
    MCPClient,
    MCPServerConfig,
    MCPToolDescriptor,
    mcp_registry_tool_name,
)
from agent.tool_registry import TOOL_REGISTRY, register_tool


SENSITIVE_CONFIG_NAMES = frozenset({".env", "agent_log.jsonl"})
SENSITIVE_CONFIG_PARTS = frozenset({"sessions", "runs"})


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


def register_mcp_tools(
    servers: Sequence[MCPServerConfig],
    client: MCPClient,
    *,
    server_allowlist: frozenset[str] | None = None,
    dry_run: bool = True,
    _discovery_stats: dict[str, int] | None = None,
) -> tuple[str, ...]:
    """显式把 enabled MCP tools 注册成本地 optional registry tools。

    中文学习边界：
    这是 MCP client 和 tool_registry 的唯一连接点。在注册前必须经过两层
    policy gate —— server 策略评估和 tool 策略评估。只有通过策略检查的
    server + tool 才能进入 TOOL_REGISTRY。

    policy gate 流程（对有 enabled 的 server）：
    1. evaluate_server_policy → blocked？→ audit + skip
    2. client.list_tools → 获取 raw descriptors
    3. evaluate_tool_policy（逐 tool）→ blocked？→ audit + skip
    4. allowed tool：使用 sanitized_description 注册 + audit

    所有 MCP tools 默认 confirmation="always"、risk_level="high"。
    raw descriptor 不进入 model-visible description。

    注意：MCP client 不写 checkpoint、不参与 runtime transition，
    也不绕过 HITL。
    """
    from agent.mcp_policy import evaluate_server_policy, evaluate_tool_policy
    from agent.mcp_audit import (
        emit_mcp_server_blocked,
        emit_mcp_server_discovered,
        emit_mcp_tools_listed,
        emit_mcp_tool_registered,
        emit_mcp_tool_blocked,
    )

    allowlist = server_allowlist or frozenset()
    registered: list[str] = []
    _total_discovered = 0
    _total_blocked = 0

    for server in servers:
        if not server.enabled:
            continue

        # 第一层：server policy gate
        server_result = evaluate_server_policy(
            server,
            server_allowlist=allowlist if allowlist else None,
            dry_run=dry_run,
        )
        if server_result.decision == "blocked":
            emit_mcp_server_blocked(
                server.name,
                reason=server_result.reason,
            )
            continue
        emit_mcp_server_discovered(server.name)

        # 第二层：list_tools → tool policy gate
        descriptors = client.list_tools(server)
        _total_discovered += len(descriptors)
        emit_mcp_tools_listed(server.name, tool_count=len(descriptors))

        for descriptor in descriptors:
            if descriptor.server_name != server.name:
                raise ValueError(
                    f"MCP tool '{descriptor.name}' 属于 server "
                    f"'{descriptor.server_name}'，不能注册到 '{server.name}'"
                )

            tool_result = evaluate_tool_policy(
                server,
                descriptor,
                server_decision=server_result.decision,
            )

            if tool_result.decision == "blocked":
                _total_blocked += 1
                emit_mcp_tool_blocked(
                    server.name,
                    descriptor.name,
                    reason=tool_result.reason,
                )
                continue

            # 通过 policy gate：使用 sanitized description 注册
            registry_name = mcp_registry_tool_name(
                server.name, descriptor.name
            )
            if registry_name in TOOL_REGISTRY:
                raise ValueError(
                    f"MCP tool registry name 已存在: {registry_name}"
                )

            def _call_mcp_tool(
                _server: MCPServerConfig = server,
                _descriptor: MCPToolDescriptor = descriptor,
                **tool_input: Any,
            ) -> str:
                result = client.call_tool(
                    _server, _descriptor.name, tool_input
                )
                return result.to_legacy_tool_result(
                    server_name=_server.name,
                    tool_name=_descriptor.name,
                )

            register_tool(
                name=registry_name,
                description=tool_result.sanitized_description,
                parameters=descriptor.parameters(),
                confirmation="always",
                capability="mcp_tool",
                risk_level=tool_result.assigned_risk,
                output_policy="bounded_text",
            )(_call_mcp_tool)
            registered.append(registry_name)
            emit_mcp_tool_registered(server.name, descriptor.name)

    if _discovery_stats is not None:
        _discovery_stats["discovered"] = _total_discovered
        _discovery_stats["blocked"] = _total_blocked
        _discovery_stats["registered"] = len(registered)
    return tuple(registered)
