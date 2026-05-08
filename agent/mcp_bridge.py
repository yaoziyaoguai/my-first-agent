"""MCP bridge / controlled readiness layer。

中文学习边界：
- 本模块是 MCP 从 config → discovery → registration 的 thin adapter。
  它只做编排（orchestration），不承载 policy / sanitizer / audit / transport
  的具体逻辑。所有安全决策仍由 mcp_policy / mcp_sanitizer / mcp_audit 完成。
- bridge 不进入 core loop、不改 checkpoint、不绕过任何现有安全 gate。
- 支持三种 mode：
  - disabled：不做任何 MCP 操作（默认）
  - discovery：只做 tools/list + policy evaluation + audit，不注册工具
  - registration：完整链路（discovery + registration，均经过 policy gate）
- bridge report 包含 server/tool 评估结果、注册状态、审计摘要，
  不包含 raw descriptor / raw args / raw result / secret。

为什么这里是 thin adapter 而不是大 service：
- policy 评估仍在 mcp_policy
- descriptor 清洗仍在 mcp_sanitizer
- 审计事件仍在 mcp_audit
- 工具注册仍在 mcp.py register_mcp_tools
- bridge 只负责：load config → select mode → 调用上述模块 → 返回 report
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal, Mapping

from agent.mcp import (
    FakeMCPClient,
    MCPServerConfig,
    register_mcp_tools,
)
from agent.mcp_models import MCPClient
from agent.mcp_policy import (
    evaluate_server_policy,
    MCPPolicyDecision,
)
from agent.mcp_stdio import StdioMCPClient


MCPBridgeMode = Literal["disabled", "discovery", "registration"]


@dataclass(frozen=True, slots=True)
class MCPBridgeReport:
    """MCP bridge 的只读报告——不含 raw descriptor / raw result / secret。"""

    mode: MCPBridgeMode
    servers_configured: int
    servers_evaluated: int
    servers_blocked: int
    tools_discovered: int
    tools_blocked: int
    tools_registered: int
    overall_decision: MCPPolicyDecision = "blocked"
    errors: tuple[str, ...] = ()


def _load_mcp_config(config_path: str | None = None) -> tuple[MCPServerConfig, ...]:
    """加载 MCP server 配置。

    默认不读取任何路径。调用方必须显式传入 config_path 或设置环境变量。
    """
    import os

    resolved = config_path or os.getenv("MY_FIRST_AGENT_MCP_CONFIG", "")
    if not resolved:
        return ()

    config_file = Path(resolved)
    if not config_file.exists():
        raise FileNotFoundError(f"MCP config 文件不存在: {resolved}")

    return _parse_mcp_config_file(config_file)


def _parse_mcp_config_file(config_file: Path) -> tuple[MCPServerConfig, ...]:
    """从 JSON 文件解析 MCP server configs。"""
    raw = json.loads(config_file.read_text(encoding="utf-8"))
    servers_raw = raw.get("mcpServers", {})
    if not isinstance(servers_raw, Mapping):
        raise ValueError("mcpServers 必须是 object")

    servers: list[MCPServerConfig] = []
    for name, cfg in servers_raw.items():
        if not isinstance(cfg, Mapping):
            raise ValueError(f"server '{name}' 配置必须是 object")
        servers.append(
            MCPServerConfig(
                name=str(name),
                transport=str(cfg.get("transport", "stdio")),
                command=str(cfg["command"]) if cfg.get("command") else None,
                args=tuple(
                    str(a) for a in cfg.get("args", ())
                ),
                enabled=bool(cfg.get("enabled", False)),
            )
        )
    return tuple(servers)


def _create_mcp_client(dry_run: bool = True) -> MCPClient:
    """根据模式选择 MCP client。

    dry_run=True → FakeMCPClient（不连接真实 server）
    dry_run=False → StdioMCPClient（连接真实 stdio server）
    """
    if dry_run:
        return FakeMCPClient({})
    return StdioMCPClient(timeout_seconds=10)


def run_mcp_bridge(
    *,
    mode: MCPBridgeMode = "disabled",
    config_path: str | None = None,
    server_allowlist: frozenset[str] | None = None,
    dry_run: bool = True,
) -> MCPBridgeReport:
    """运行 MCP bridge 并返回 readiness report。

    这是 MCP 从 config → discovery → registration 的唯一受控入口。
    所有模式下的 audit 事件都由 register_mcp_tools 内部发射。

    mode="disabled":
        不做任何 MCP 操作，直接返回空报告（全 0）。这是默认行为。
    mode="discovery":
        只做 server policy readiness 评估，不连接真实 server、不 list_tools、
        不注册工具。tools_discovered / tools_blocked 标记为 -1
        （not_attempted），表示 discovery 模式未实际探测。
    mode="registration":
        完整链路：config load → server policy → client.list_tools → tool policy
        → registration + audit。统计来自 register_mcp_tools 的真实执行过程。
    """
    if mode == "disabled":
        return MCPBridgeReport(
            mode="disabled",
            servers_configured=0,
            servers_evaluated=0,
            servers_blocked=0,
            tools_discovered=0,
            tools_blocked=0,
            tools_registered=0,
            overall_decision="blocked",
        )

    errors: list[str] = []
    try:
        servers = _load_mcp_config(config_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        return MCPBridgeReport(
            mode=mode,
            servers_configured=0,
            servers_evaluated=0,
            servers_blocked=0,
            tools_discovered=0,
            tools_blocked=0,
            tools_registered=0,
            overall_decision="blocked",
            errors=(f"config load error: {e}",),
        )

    if not servers:
        return MCPBridgeReport(
            mode=mode,
            servers_configured=0,
            servers_evaluated=0,
            servers_blocked=0,
            tools_discovered=-1 if mode == "discovery" else 0,
            tools_blocked=-1 if mode == "discovery" else 0,
            tools_registered=0,
            overall_decision="blocked",
        )

    enabled_servers = [s for s in servers if s.enabled]
    allowlist = server_allowlist or frozenset()

    # server-level policy 评估
    servers_evaluated = 0
    servers_blocked = 0
    for server in enabled_servers:
        result = evaluate_server_policy(
            server,
            server_allowlist=allowlist if allowlist else None,
            dry_run=dry_run,
        )
        servers_evaluated += 1
        if result.decision == "blocked":
            servers_blocked += 1

    if mode == "discovery":
        # discovery-only 模式：只做 config + server policy readiness，
        # 不连接真实 server、不 list_tools、不注册。
        # 使用 -1 作为 sentinel 值表示 "未实际探测"。
        return MCPBridgeReport(
            mode="discovery",
            servers_configured=len(servers),
            servers_evaluated=servers_evaluated,
            servers_blocked=servers_blocked,
            tools_discovered=-1,
            tools_blocked=-1,
            tools_registered=0,
            overall_decision="dry_run_only" if servers_evaluated > servers_blocked else "blocked",
            errors=tuple(errors),
        )

    if mode == "registration":
        client = _create_mcp_client(dry_run=dry_run)
        stats: dict[str, int] = {}
        register_mcp_tools(
            enabled_servers,
            client,
            server_allowlist=allowlist if allowlist else None,
            dry_run=dry_run,
            _discovery_stats=stats,
        )
        tools_discovered = stats.get("discovered", 0)
        tools_blocked = stats.get("blocked", 0)
        tools_registered = stats.get("registered", 0)

        overall: MCPPolicyDecision = "allowed" if tools_registered > 0 else "blocked"
        return MCPBridgeReport(
            mode="registration",
            servers_configured=len(servers),
            servers_evaluated=servers_evaluated,
            servers_blocked=servers_blocked,
            tools_discovered=tools_discovered,
            tools_blocked=tools_blocked,
            tools_registered=tools_registered,
            overall_decision=overall,
            errors=tuple(errors),
        )

    # fallback（不应到达）
    return MCPBridgeReport(
        mode=mode,
        servers_configured=len(servers),
        servers_evaluated=0,
        servers_blocked=0,
        tools_discovered=0,
        tools_blocked=0,
        tools_registered=0,
        overall_decision="blocked",
    )
