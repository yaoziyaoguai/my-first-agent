"""MCP config management service/use-case layer.

Pack 1 deliberately stops at list/inspect/validate/plan preview:
- it reuses Slice 1 parser/path policy/redaction instead of reading real home config;
- it never writes config files, executes server commands, or connects to MCP endpoints;
- CLI adapter should call these use cases instead of embedding business policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from agent.mcp_config import (
    MCPConfigValidationIssue,
    MCPConfigValidationResult,
    MCPServerEntry,
    SecretValueRef,
    load_mcp_config,
)


@dataclass(frozen=True, slots=True)
class MCPServerInspectionResult:
    """inspect 用例结果；server lookup 语义放在 service，不放进 CLI adapter。"""

    validation: MCPConfigValidationResult
    server: MCPServerEntry | None = None
    errors: tuple[MCPConfigValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return self.validation.ok and self.server is not None and not self.errors


@dataclass(frozen=True, slots=True)
class MCPConfigPlanOperation:
    """计划中的单步配置变更。

    Pack 1 的 plan 是 preview-only，所以这里保存的是安全展示值：env secret 会被
    SecretValueRef redaction 处理，args 也只保留 redacted display form。
    """

    action: str
    server_name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, SecretValueRef] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))


@dataclass(frozen=True, slots=True)
class MCPConfigDiff:
    """人类可读 diff preview；表达意图，不代表已写入文件。"""

    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MCPConfigPlan:
    """Plan-first governance 的最小模型；Pack 1 不提供 apply。"""

    operation: MCPConfigPlanOperation
    diff: MCPConfigDiff


@dataclass(frozen=True, slots=True)
class MCPConfigPlanResult:
    """plan-add / plan-remove 的结果容器，避免 CLI 直接拼业务错误。"""

    validation: MCPConfigValidationResult
    plan: MCPConfigPlan | None = None
    errors: tuple[MCPConfigValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return self.validation.ok and self.plan is not None and not self.errors


def list_mcp_config(path: str | Path) -> MCPConfigValidationResult:
    """列出配置前只做 safe path read + validation，不扫描默认 home config。"""

    return load_mcp_config(path)


def validate_mcp_config(path: str | Path) -> MCPConfigValidationResult:
    """validate 是 service 语义，不让 CLI adapter 复制 parser 判断。"""

    return load_mcp_config(path)


def inspect_mcp_server(path: str | Path, name: str) -> MCPServerInspectionResult:
    """查询单个 server；不存在时返回结构化错误而不是让 presenter 猜。"""

    validation = load_mcp_config(path)
    if not validation.ok or validation.config is None:
        return MCPServerInspectionResult(validation=validation)

    server = validation.config.servers_by_name.get(name)
    if server is None:
        return MCPServerInspectionResult(
            validation=validation,
            errors=(_issue("not_found", "MCP server 不存在", server_name=name),),
        )
    return MCPServerInspectionResult(validation=validation, server=server)


def plan_add_mcp_server(
    path: str | Path,
    *,
    name: str,
    command: str,
    args: tuple[str, ...] = (),
    env_specs: tuple[str, ...] = (),
) -> MCPConfigPlanResult:
    """生成 add plan preview，不写 config 文件。

    这里故意只返回计划和 diff：destructive/apply 能力必须后续单独做 --yes、backup、
    safe-path 审核，不能被 Pack 1 顺手绕过。
    """

    validation = load_mcp_config(path)
    if not validation.ok or validation.config is None:
        return MCPConfigPlanResult(validation=validation)
    if name in validation.config.servers_by_name:
        return MCPConfigPlanResult(
            validation=validation,
            errors=(_issue("already_exists", "MCP server 已存在", server_name=name),),
        )

    env, env_errors = _parse_env_specs(env_specs, server_name=name)
    if env_errors:
        return MCPConfigPlanResult(validation=validation, errors=env_errors)

    operation = MCPConfigPlanOperation(
        action="add",
        server_name=name,
        command=command,
        args=tuple(_safe_display_arg(arg) for arg in args),
        env=env,
    )
    return MCPConfigPlanResult(
        validation=validation,
        plan=MCPConfigPlan(
            operation=operation,
            diff=MCPConfigDiff(lines=(_format_add_diff_line(operation),)),
        ),
    )


def plan_remove_mcp_server(path: str | Path, *, name: str) -> MCPConfigPlanResult:
    """生成 remove plan preview；不做 destructive config change。"""

    validation = load_mcp_config(path)
    if not validation.ok or validation.config is None:
        return MCPConfigPlanResult(validation=validation)

    server = validation.config.servers_by_name.get(name)
    if server is None:
        return MCPConfigPlanResult(
            validation=validation,
            errors=(_issue("not_found", "MCP server 不存在", server_name=name),),
        )

    operation = MCPConfigPlanOperation(action="remove", server_name=name)
    return MCPConfigPlanResult(
        validation=validation,
        plan=MCPConfigPlan(
            operation=operation,
            diff=MCPConfigDiff(lines=(f"- {server.name}: command={server.command}",)),
        ),
    )


def _parse_env_specs(
    env_specs: tuple[str, ...],
    *,
    server_name: str,
) -> tuple[Mapping[str, SecretValueRef], tuple[MCPConfigValidationIssue, ...]]:
    env: dict[str, SecretValueRef] = {}
    errors: list[MCPConfigValidationIssue] = []
    for spec in env_specs:
        if "=" not in spec:
            errors.append(
                _issue(
                    "invalid_env_spec",
                    "--env 必须使用 KEY=VALUE 格式",
                    server_name=server_name,
                    field="env",
                )
            )
            continue
        key, value = spec.split("=", 1)
        if not key:
            errors.append(
                _issue(
                    "invalid_env_spec",
                    "--env key 不能为空",
                    server_name=server_name,
                    field="env",
                )
            )
            continue
        env[key] = SecretValueRef.from_env_value(key, value)
    return MappingProxyType(dict(sorted(env.items()))), tuple(errors)


def _safe_display_arg(value: str) -> str:
    return SecretValueRef.from_env_value("arg", value).display_value


def _format_add_diff_line(operation: MCPConfigPlanOperation) -> str:
    args = ", ".join(operation.args)
    env = ", ".join(
        f"{key}={value.display_value}"
        for key, value in sorted(operation.env.items())
    )
    args_part = f" args=[{args}]" if args else ""
    env_part = f" env=[{env}]" if env else ""
    return f"+ {operation.server_name}: command={operation.command}{args_part}{env_part}"


def _issue(
    code: str,
    message: str,
    *,
    server_name: str | None = None,
    field: str | None = None,
) -> MCPConfigValidationIssue:
    return MCPConfigValidationIssue(
        code=code,
        message=message,
        server_name=server_name,
        field=field,
    )
