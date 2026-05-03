"""MCP external integration dry-run readiness report.

Remaining Roadmap 阶段可以继续推进 fake-first readiness，但不能把 readiness
偷换成真实 MCP client。本模块只复用 safe MCP config parser，生成“未来若授权真实
集成会需要什么”的 dry-run report：不执行 server command、不联网、不读取 secret、
不做 reachability validation，也不接 runtime/checkpoint/tool executor。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from agent.mcp_config import MCPConfigValidationResult, load_mcp_config


@dataclass(frozen=True, slots=True)
class MCPExternalReadinessServer:
    """单个 server 的 dry-run readiness 视图。

    command/args/env 都来自已脱敏的 config model；这里不启动 command，也不 list_tools。
    enabled=True 只表示“未来真实集成会需要 tool discovery 授权”，不是现在注册工具。
    """

    name: str
    transport: str
    command: str
    args: tuple[str, ...] = ()
    env_preview: Mapping[str, str] = field(default_factory=dict)
    enabled: bool = False
    dry_run_status: str = "disabled_not_registered"

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env_preview", MappingProxyType(dict(self.env_preview)))


@dataclass(frozen=True, slots=True)
class MCPExternalReadinessReport:
    """MCP external integration 的 no-op readiness report。

    这些 safety flags 是 evidence 字段，不是 runtime state。报告可被 docs/tests 引用，
    但不能作为“已经连接 server”的证明。
    """

    validation: MCPConfigValidationResult
    servers: tuple[MCPExternalReadinessServer, ...] = ()
    no_network: bool = True
    no_command_execution: bool = True
    no_secret_read: bool = True
    no_reachability_check: bool = True

    @property
    def ok(self) -> bool:
        return self.validation.ok


def build_mcp_external_readiness_report(path: str | Path) -> MCPExternalReadinessReport:
    """为显式 safe MCP config 生成 dry-run readiness report。

    只调用 :func:`load_mcp_config`，因此继承 tmp/fixture path policy 和 secret
    redaction；本函数不会 import 或调用 stdio/http/sse transport，也不会注册工具。
    """

    validation = load_mcp_config(path)
    if not validation.ok or validation.config is None:
        return MCPExternalReadinessReport(validation=validation)

    servers = tuple(
        MCPExternalReadinessServer(
            name=server.name,
            transport=server.transport,
            command=server.command,
            args=server.args,
            env_preview={
                key: value.display_value
                for key, value in sorted(server.env.items(), key=lambda item: item[0])
            },
            enabled=server.enabled,
            dry_run_status=_dry_run_status_for_server(server.enabled, server.transport),
        )
        for server in validation.config.servers
    )
    return MCPExternalReadinessReport(validation=validation, servers=servers)


def _dry_run_status_for_server(enabled: bool, transport: str) -> str:
    if not enabled:
        return "disabled_not_registered"
    if transport == "stdio":
        return "would_require_tool_discovery_authorization"
    return "external_transport_deferred"
