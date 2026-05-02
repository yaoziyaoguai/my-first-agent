"""Presenter for MCP config management output.

Presenter 只把 service/parser 已经 redacted 的模型转成人类可读文本；它不读取路径、
不判断 policy、不执行 MCP server，也不把展示逻辑塞回 CLI adapter。
"""

from __future__ import annotations

from agent.mcp_config import (
    MCPConfigValidationIssue,
    MCPConfigValidationResult,
    MCPServerEntry,
    SecretValueRef,
)
from agent.mcp_config_service import (
    MCPConfigApplyResult,
    MCPConfigPlanResult,
    MCPServerInspectionResult,
)


def render_config_list(result: MCPConfigValidationResult) -> str:
    """渲染 list 输出；secret/env 明细不属于 list 摘要。"""

    if not result.ok or result.config is None:
        return render_validation_result(result)

    lines = ["MCP config servers"]
    for server in result.config.servers:
        lines.append(
            f"- {server.name}: enabled={server.enabled} "
            f"transport={server.transport} command={server.command}"
        )
    return "\n".join(lines) + "\n"


def render_server_inspection(result: MCPServerInspectionResult) -> str:
    """渲染 inspect 输出；args/env 只使用安全展示值。"""

    if not result.validation.ok:
        return render_validation_result(result.validation)
    if result.errors:
        return _render_issues("invalid MCP config request", result.errors)
    if result.server is None:
        return _render_issues(
            "invalid MCP config request",
            (
                MCPConfigValidationIssue(
                    code="not_found",
                    message="MCP server 不存在",
                    field="name",
                ),
            ),
        )

    server = result.server
    lines = [
        f"Server: {server.name}",
        f"enabled: {server.enabled}",
        f"transport: {server.transport}",
        f"command: {server.command}",
    ]
    if server.args:
        lines.append(
            "args: "
            + " ".join(
                SecretValueRef.from_env_value("arg", arg).display_value
                for arg in server.args
            )
        )
    if server.env:
        lines.append("env:")
        lines.extend(_format_env_lines(server))
    return "\n".join(lines) + "\n"


def render_validation_result(result: MCPConfigValidationResult) -> str:
    """渲染 validate 结果；错误码/字段可读，但不包含 secret 明文。"""

    if result.ok:
        server_count = len(result.config.servers) if result.config is not None else 0
        return f"valid MCP config: {server_count} server(s)\n"
    return _render_issues("invalid MCP config", result.errors)


def render_plan_result(result: MCPConfigPlanResult) -> str:
    """渲染 plan preview；明确这是计划，不是已 apply 的变更。"""

    if not result.validation.ok:
        return render_validation_result(result.validation)
    if result.errors:
        return _render_issues("invalid MCP config plan", result.errors)
    if result.plan is None:
        return _render_issues(
            "invalid MCP config plan",
            (
                MCPConfigValidationIssue(
                    code="missing_plan",
                    message="未生成 MCP config plan",
                ),
            ),
        )

    operation = result.plan.operation
    lines = [
        f"Plan: {operation.action} {operation.server_name}",
        "Diff preview (no files written):",
        *result.plan.diff.lines,
    ]
    return "\n".join(lines) + "\n"


def render_apply_result(result: MCPConfigApplyResult) -> str:
    """渲染 safe apply evidence；只展示 redacted diff 和 manifest。"""

    if not result.ok:
        return _render_issues("invalid MCP config apply", result.errors)

    manifest = result.manifest
    backup = str(result.backup_path) if result.backup_path is not None else "<none>"
    lines = [
        "MCP config apply completed",
        f"backup: {backup}",
        "Diff evidence:",
        *result.diff.lines,
        "Safety manifest:",
        f"- path_allowed={manifest.path_allowed}",
        f"- explicit_yes={manifest.explicit_yes}",
        f"- plan_present={manifest.plan_present}",
        f"- no_network={manifest.no_network}",
        f"- no_command_execution={manifest.no_command_execution}",
        f"- no_env_expansion={manifest.no_env_expansion}",
        f"- no_real_home_write={manifest.no_real_home_write}",
    ]
    return "\n".join(lines) + "\n"


def render_cli_error(message: str) -> str:
    return f"invalid MCP config command: {message}\n"


def _format_env_lines(server: MCPServerEntry) -> list[str]:
    return [
        f"  {key}={value.display_value}"
        for key, value in sorted(server.env.items())
    ]


def _render_issues(title: str, issues: tuple[MCPConfigValidationIssue, ...]) -> str:
    lines = [title]
    for issue in issues:
        server = f" server={issue.server_name}" if issue.server_name else ""
        field = f" field={issue.field}" if issue.field else ""
        lines.append(f"- {issue.code}{server}{field}: {issue.message}")
    return "\n".join(lines) + "\n"
