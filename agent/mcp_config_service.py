"""MCP config management service/use-case layer.

本层承载 config workflow 语义：list/inspect/validate、plan preview，以及
Safe Apply + Governance pack 的受控 apply。
- it reuses Slice 1 parser/path policy/redaction instead of reading real home config;
- apply 只写 safe tmp/fixture path，不写真实 home config；
- it never executes server commands or connects to MCP endpoints;
- CLI adapter should call these use cases instead of embedding business policy.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from agent.mcp_config import (
    MCPConfigPathPolicy,
    MCPConfigValidationIssue,
    MCPConfigValidationResult,
    MCPServerEntry,
    REDACTED,
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

    plan packet 会被 apply 复用，所以 raw_* 只给写入边界使用；常规 repr/presenter
    仍只展示 SecretValueRef redaction 后的安全值。
    """

    action: str
    server_name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, SecretValueRef] = field(default_factory=dict)
    raw_args: tuple[str, ...] = field(default_factory=tuple, repr=False)
    raw_env: Mapping[str, str] = field(default_factory=dict, repr=False)
    transport: str = "stdio"

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))
        object.__setattr__(self, "raw_args", tuple(self.raw_args or self.args))
        object.__setattr__(self, "raw_env", MappingProxyType(dict(self.raw_env)))


@dataclass(frozen=True, slots=True)
class MCPConfigDiff:
    """人类可读 diff preview；表达意图，不代表已写入文件。"""

    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MCPConfigPlan:
    """Plan-first governance 的最小模型；apply 必须从这个模型进入。"""

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


@dataclass(frozen=True, slots=True)
class MCPConfigSafetyManifest:
    """apply governance 的显式证据。

    它记录“做了哪些安全决策”，而不是把 runtime/memory 状态拉进 config workflow。
    """

    path_allowed: bool
    explicit_yes: bool
    plan_present: bool
    backup_path: Path | None = None
    no_network: bool = True
    no_command_execution: bool = True
    no_env_expansion: bool = True
    no_real_home_write: bool = True


@dataclass(frozen=True, slots=True)
class MCPConfigApplyResult:
    """safe apply 结果；repr 不应包含 plan raw secret。"""

    ok: bool
    errors: tuple[MCPConfigValidationIssue, ...] = ()
    diff: MCPConfigDiff = field(default_factory=lambda: MCPConfigDiff(lines=()))
    backup_path: Path | None = None
    manifest: MCPConfigSafetyManifest = field(
        default_factory=lambda: MCPConfigSafetyManifest(
            path_allowed=False,
            explicit_yes=False,
            plan_present=False,
        )
    )


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
        raw_args=args,
        raw_env={key: spec.split("=", 1)[1] for key, spec in _valid_env_specs(env_specs)},
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


def serialize_mcp_config_plan(plan: MCPConfigPlan | None) -> Mapping[str, Any]:
    """把 plan packet 转成可审计 mapping。

    本 pack 只支持 safe tmp/fixture plan packet；如果 packet 携带 env value，也只会在
    safe path 内被 apply 使用，presenter/repr 始终使用 redacted display。
    """

    if plan is None:
        return {}
    operation = plan.operation
    payload: dict[str, Any] = {
        "version": 1,
        "operation": {
            "action": operation.action,
            "server_name": operation.server_name,
        },
    }
    if operation.action == "add":
        payload["operation"].update({
            "command": operation.command,
            "transport": operation.transport,
            "args": list(operation.raw_args),
            "env": dict(operation.raw_env),
        })
    return payload


def parse_mcp_config_plan_mapping(
    packet: Any,
) -> tuple[MCPConfigPlan | None, tuple[MCPConfigValidationIssue, ...]]:
    """解析 plan packet；只构造计划对象，不读取 config、不写文件、不执行命令。"""

    if not isinstance(packet, Mapping):
        return None, (_issue("invalid_plan", "MCP config plan 必须是 object"),)
    operation = packet.get("operation")
    if not isinstance(operation, Mapping):
        return None, (_issue("invalid_plan", "MCP config plan 缺少 operation"),)
    action = operation.get("action")
    server_name = operation.get("server_name")
    if action not in {"add", "remove"} or not isinstance(server_name, str):
        return None, (_issue("invalid_plan", "MCP config plan operation 无效"),)

    if action == "remove":
        plan_operation = MCPConfigPlanOperation(
            action="remove",
            server_name=server_name,
        )
        return MCPConfigPlan(
            operation=plan_operation,
            diff=MCPConfigDiff(lines=(f"- {server_name}",)),
        ), ()

    command = operation.get("command")
    raw_args = operation.get("args", [])
    raw_env = operation.get("env", {})
    transport = operation.get("transport", "stdio")
    if (
        not isinstance(command, str)
        or not isinstance(raw_args, list)
        or not isinstance(raw_env, Mapping)
        or not isinstance(transport, str)
    ):
        return None, (_issue("invalid_plan", "MCP config add plan 字段类型无效"),)

    env = {
        str(key): SecretValueRef.from_env_value(str(key), str(value))
        for key, value in sorted(raw_env.items(), key=lambda item: str(item[0]))
    }
    plan_operation = MCPConfigPlanOperation(
        action="add",
        server_name=server_name,
        command=command,
        args=tuple(_safe_display_arg(str(arg)) for arg in raw_args),
        env=env,
        raw_args=tuple(str(arg) for arg in raw_args),
        raw_env={str(key): str(value) for key, value in raw_env.items()},
        transport=transport,
    )
    return MCPConfigPlan(
        operation=plan_operation,
        diff=MCPConfigDiff(lines=(_format_add_diff_line(plan_operation),)),
    ), ()


def load_mcp_config_plan(
    path: str | Path,
) -> tuple[MCPConfigPlan | None, tuple[MCPConfigValidationIssue, ...]]:
    """从显式 safe plan path 读取 plan packet；不读默认 home、不展开 env。"""

    plan_path = Path(path)
    path_issue = MCPConfigPathPolicy().validate_read_path(plan_path)
    if path_issue is not None:
        return None, (path_issue,)
    try:
        packet = json.loads(plan_path.read_text(encoding="utf-8"))
    except OSError:
        return None, (_issue("read_failed", "无法读取 MCP config plan", field="plan"),)
    except json.JSONDecodeError:
        return None, (_issue("invalid_json", "MCP config plan 不是合法 JSON", field="plan"),)
    return parse_mcp_config_plan_mapping(packet)


def apply_mcp_config_plan(
    path: str | Path,
    *,
    plan: MCPConfigPlan | None,
    yes: bool,
) -> MCPConfigApplyResult:
    """执行 safe apply。

    这是 config workflow 的写入边界：必须有 plan、必须显式 `--yes`、必须通过
    safe path policy。它只改 JSON config 文本，不执行 server command、不联网、
    不展开 env，也不碰 runtime/checkpoint/memory。
    """

    target_path = Path(path)
    base_manifest = MCPConfigSafetyManifest(
        path_allowed=False,
        explicit_yes=yes,
        plan_present=plan is not None,
    )
    if plan is None:
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("missing_plan", "apply 需要 MCP config plan"),),
            manifest=base_manifest,
        )
    if not yes:
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("confirmation_required", "apply 需要显式 --yes"),),
            manifest=base_manifest,
        )

    validation = load_mcp_config(target_path)
    if not validation.ok:
        return MCPConfigApplyResult(
            ok=False,
            errors=validation.errors,
            manifest=base_manifest,
        )

    try:
        old_text = target_path.read_text(encoding="utf-8")
        raw_config = json.loads(old_text)
    except OSError:
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("read_failed", "无法读取 MCP config 文件", field="path"),),
            manifest=base_manifest,
        )
    except json.JSONDecodeError:
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("invalid_json", "MCP config 不是合法 JSON", field="path"),),
            manifest=base_manifest,
        )
    if not isinstance(raw_config, Mapping):
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("invalid_type", "MCP config root 必须是 object"),),
            manifest=base_manifest,
        )

    new_config = dict(raw_config)
    raw_servers = new_config.get("mcpServers")
    if not isinstance(raw_servers, Mapping):
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("invalid_type", "mcpServers 必须是 object", field="mcpServers"),),
            manifest=base_manifest,
        )
    servers = dict(raw_servers)
    plan_error = _apply_operation_to_servers(servers, plan.operation)
    if plan_error is not None:
        return MCPConfigApplyResult(
            ok=False,
            errors=(plan_error,),
            manifest=base_manifest,
        )
    new_config["mcpServers"] = servers
    new_text = _serialize_config(new_config)
    redacted_diff = _build_redacted_diff(old_text, new_text, target_path.name)
    backup_path = target_path.with_suffix(target_path.suffix + ".bak")
    manifest = MCPConfigSafetyManifest(
        path_allowed=True,
        explicit_yes=True,
        plan_present=True,
        backup_path=backup_path,
    )

    try:
        backup_path.write_text(old_text, encoding="utf-8")
        target_path.write_text(new_text, encoding="utf-8")
    except OSError:
        return MCPConfigApplyResult(
            ok=False,
            errors=(_issue("write_failed", "无法写入 MCP config 或 backup", field="path"),),
            diff=MCPConfigDiff(lines=redacted_diff),
            backup_path=backup_path,
            manifest=manifest,
        )

    return MCPConfigApplyResult(
        ok=True,
        diff=MCPConfigDiff(lines=redacted_diff),
        backup_path=backup_path,
        manifest=manifest,
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


def _valid_env_specs(env_specs: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (spec.split("=", 1)[0], spec)
        for spec in env_specs
        if "=" in spec and spec.split("=", 1)[0]
    )


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


def _apply_operation_to_servers(
    servers: dict[str, Any],
    operation: MCPConfigPlanOperation,
) -> MCPConfigValidationIssue | None:
    if operation.action == "add":
        if operation.server_name in servers:
            return _issue(
                "already_exists",
                "MCP server 已存在",
                server_name=operation.server_name,
            )
        server_config: dict[str, Any] = {
            "command": operation.command,
            "transport": operation.transport,
        }
        if operation.raw_args:
            server_config["args"] = list(operation.raw_args)
        if operation.raw_env:
            server_config["env"] = dict(sorted(operation.raw_env.items()))
        servers[operation.server_name] = server_config
        return None
    if operation.action == "remove":
        if operation.server_name not in servers:
            return _issue(
                "not_found",
                "MCP server 不存在",
                server_name=operation.server_name,
            )
        del servers[operation.server_name]
        return None
    return _issue("invalid_plan", "MCP config plan action 无效")


def _serialize_config(config: Mapping[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _build_redacted_diff(old_text: str, new_text: str, name: str) -> tuple[str, ...]:
    return tuple(
        _redact_diff_line(line)
        for line in difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"{name}:before",
            tofile=f"{name}:after",
            lineterm="",
        )
    )


def _redact_diff_line(line: str) -> str:
    normalized = line.lower()
    if any(marker in normalized for marker in ("token", "secret", "password", "api_key", "apikey")):
        if ":" in line:
            prefix = line.split(":", 1)[0]
            return f"{prefix}: \"{REDACTED}\""
        if "=" in line:
            prefix = line.split("=", 1)[0]
            return f"{prefix}={REDACTED}"
        return REDACTED
    return line


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
