"""MCP CLI Config Management Slice 1：安全配置解析/校验/redaction。

本模块是未来 MCP CLI 的 model/parser/policy foundation，不是 MCP client，也不是
runtime 入口。它只读取调用方显式传入的 safe fixture/tmp path 或 mapping：
- 不扫描 home；
- 不读取 `.env` / agent_log / sessions / runs；
- 不展开 env var；
- 不执行 server command；
- 不连接 MCP server 或网络。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from json import JSONDecodeError
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Any, Mapping


SUPPORTED_TRANSPORTS = frozenset({"stdio", "http", "sse", "streamable_http"})
SENSITIVE_PATH_NAMES = frozenset({".env", "agent_log.jsonl"})
SENSITIVE_PATH_PARTS = frozenset({"sessions", "runs"})
SECRET_NAME_MARKERS = (
    "TOKEN",
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "AUTH",
)
SECRET_VALUE_MARKERS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
)
REDACTED = "<redacted>"


@dataclass(frozen=True, slots=True)
class SecretValueRef:
    """配置值的安全展示视图。

    对 secret-like key/value，本对象故意不保存原始明文，只保存 redacted marker。
    这样即使 dataclass repr、validation result 或未来 presenter 被打印，也不会把
    token/password 值带进日志或测试 snapshot。
    """

    display_value: str
    redacted: bool = False

    @classmethod
    def from_env_value(cls, key: str, value: str) -> "SecretValueRef":
        if _is_secret_like(key, value):
            return cls(display_value=REDACTED, redacted=True)
        return cls(display_value=value, redacted=False)


@dataclass(frozen=True, slots=True)
class MCPConfigSourceInfo:
    """配置来源说明；只记录路径元数据，不读取真实用户目录。"""

    path: Path | None
    source_kind: str
    policy_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MCPServerEntry:
    """单个 MCP server 的配置模型。

    这是 config management 视图，不是可执行 server handle。`command` / `args`
    只是配置文本，Slice 1 不会启动它们。
    """

    name: str
    transport: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, SecretValueRef] = field(default_factory=dict)
    enabled: bool = False
    unknown_fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))
        object.__setattr__(
            self,
            "unknown_fields",
            MappingProxyType(dict(self.unknown_fields)),
        )


@dataclass(frozen=True, slots=True)
class MCPConfig:
    """已解析且无 validation error 的 MCP config。

    `servers_by_name` 方便 Slice 2 list/inspect/validate CLI adapter 查询，但仍然只是
    read-only model，不提供 apply/write/execute 能力。
    """

    servers: tuple[MCPServerEntry, ...]
    source: MCPConfigSourceInfo
    unknown_fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unknown_fields",
            MappingProxyType(dict(self.unknown_fields)),
        )

    @property
    def servers_by_name(self) -> Mapping[str, MCPServerEntry]:
        return MappingProxyType({server.name: server for server in self.servers})


@dataclass(frozen=True, slots=True)
class MCPConfigValidationIssue:
    """结构化 validation issue；message 不包含原始 secret value。"""

    code: str
    message: str
    server_name: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class MCPConfigValidationResult:
    """配置读取/解析/校验结果。

    `config is None` 表示存在 blocking errors。warnings 预留给 Slice 2/3，例如
    disabled server、unknown fields 或未来 deprecated transport。
    """

    ok: bool
    source: MCPConfigSourceInfo
    config: MCPConfig | None = None
    errors: tuple[MCPConfigValidationIssue, ...] = ()
    warnings: tuple[MCPConfigValidationIssue, ...] = ()


class MCPConfigPathPolicy:
    """Slice 1 safe path policy。

    早期只允许 tmp_path / tests fixture 这类可控路径。真实 home MCP config 未来即使
    要支持，也必须单独授权并增加 UX/backup/diff 保护。
    """

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        temp_root: Path | None = None,
    ) -> None:
        self.project_root = (
            project_root
            if project_root is not None
            else Path(__file__).resolve().parents[1]
        )
        self.temp_root = (
            temp_root
            if temp_root is not None
            else Path(tempfile.gettempdir()).resolve()
        )
        self.fixture_root = (self.project_root / "tests" / "fixtures").resolve()

    def validate_read_path(self, path: Path) -> MCPConfigValidationIssue | None:
        """校验读取路径；返回 issue 表示拒绝读取。"""

        raw_path = Path(path)
        if (
            raw_path.name in SENSITIVE_PATH_NAMES
            or SENSITIVE_PATH_PARTS.intersection(raw_path.parts)
        ):
            return _issue(
                "unsafe_path",
                "拒绝读取敏感运行产物或 secret 文件作为 MCP config",
                field="path",
            )

        resolved = raw_path.resolve(strict=False)
        if _is_relative_to(resolved, self.temp_root):
            return None
        if _is_relative_to(resolved, self.fixture_root):
            return None

        return _issue(
            "unsafe_path",
            "Slice 1 只允许 tmp_path 或 tests/fixtures 下的显式 MCP config",
            field="path",
        )


def load_mcp_config(
    path: str | Path,
    *,
    path_policy: MCPConfigPathPolicy | None = None,
) -> MCPConfigValidationResult:
    """从显式 safe path 读取 MCP config。

    这里的 service 只负责 read + parse + validation；它不扫描默认位置、不读取
    home config、不展开 env、不启动 server。unsafe path 会在读取文件前被拒绝。
    """

    config_path = Path(path)
    policy = path_policy or MCPConfigPathPolicy()
    source = MCPConfigSourceInfo(path=config_path, source_kind="explicit_path")
    path_issue = policy.validate_read_path(config_path)
    if path_issue is not None:
        return MCPConfigValidationResult(
            ok=False,
            source=source,
            errors=(path_issue,),
        )

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError:
        return MCPConfigValidationResult(
            ok=False,
            source=source,
            errors=(_issue("read_failed", "无法读取 MCP config 文件", field="path"),),
        )

    try:
        raw_config = json.loads(raw_text)
    except JSONDecodeError:
        return MCPConfigValidationResult(
            ok=False,
            source=source,
            errors=(_issue("invalid_json", "MCP config 不是合法 JSON", field="path"),),
        )

    return parse_mcp_config_mapping(raw_config, source=source)


def parse_mcp_config_mapping(
    config: Any,
    *,
    source: MCPConfigSourceInfo | None = None,
) -> MCPConfigValidationResult:
    """从 mapping 解析/校验 MCP config，不执行任何外部动作。"""

    source_info = source or MCPConfigSourceInfo(path=None, source_kind="mapping")
    if not isinstance(config, Mapping):
        return MCPConfigValidationResult(
            ok=False,
            source=source_info,
            errors=(_issue("invalid_type", "MCP config root 必须是 object"),),
        )

    raw_servers = config.get("mcpServers")
    if raw_servers is None:
        return MCPConfigValidationResult(
            ok=False,
            source=source_info,
            errors=(_issue("missing_required", "缺少 mcpServers", field="mcpServers"),),
        )
    if not isinstance(raw_servers, Mapping):
        return MCPConfigValidationResult(
            ok=False,
            source=source_info,
            errors=(_issue("invalid_type", "mcpServers 必须是 object", field="mcpServers"),),
        )

    servers: list[MCPServerEntry] = []
    errors: list[MCPConfigValidationIssue] = []
    for name, raw_server in raw_servers.items():
        server, server_errors = _parse_server(str(name), raw_server)
        if server is not None:
            servers.append(server)
        errors.extend(server_errors)

    if errors:
        return MCPConfigValidationResult(
            ok=False,
            source=source_info,
            errors=tuple(errors),
        )

    mcp_config = MCPConfig(
        servers=tuple(sorted(servers, key=lambda server: server.name)),
        source=source_info,
        unknown_fields=_unknown_fields(config, known_keys={"mcpServers"}),
    )
    return MCPConfigValidationResult(
        ok=True,
        source=source_info,
        config=mcp_config,
    )


def summarize_mcp_config(config: MCPConfig) -> str:
    """返回 Slice 2 presenter 可复用的安全摘要。

    这个 helper 不是完整 presenter，只是证明 model 层已经能输出 redacted summary，
    不会把 secret 明文交给 CLI adapter。
    """

    lines = [f"MCP servers: {len(config.servers)}"]
    for server in config.servers:
        env_summary = ", ".join(
            f"{key}={value.display_value}"
            for key, value in sorted(server.env.items())
        )
        env_part = f" env=[{env_summary}]" if env_summary else ""
        lines.append(
            f"- {server.name}: transport={server.transport} "
            f"enabled={server.enabled}{env_part}"
        )
    return "\n".join(lines)


def _parse_server(
    name: str,
    raw_server: Any,
) -> tuple[MCPServerEntry | None, tuple[MCPConfigValidationIssue, ...]]:
    errors: list[MCPConfigValidationIssue] = []
    if not isinstance(raw_server, Mapping):
        return None, (
            _issue(
                "invalid_type",
                "MCP server 配置必须是 object",
                server_name=name,
            ),
        )

    command = raw_server.get("command")
    if not isinstance(command, str) or not command.strip():
        errors.append(
            _issue(
                "missing_required",
                "MCP server command 必须是非空字符串",
                server_name=name,
                field="command",
            )
        )

    raw_args = raw_server.get("args", ())
    if not isinstance(raw_args, list | tuple):
        errors.append(
            _issue(
                "invalid_type",
                "MCP server args 必须是 array",
                server_name=name,
                field="args",
            )
        )

    raw_env = raw_server.get("env", {})
    if not isinstance(raw_env, Mapping):
        errors.append(
            _issue(
                "invalid_type",
                "MCP server env 必须是 object",
                server_name=name,
                field="env",
            )
        )

    raw_transport = raw_server.get("transport", "stdio")
    if not isinstance(raw_transport, str) or raw_transport not in SUPPORTED_TRANSPORTS:
        errors.append(
            _issue(
                "invalid_transport",
                "MCP server transport 不受支持",
                server_name=name,
                field="transport",
            )
        )

    if errors:
        return None, tuple(errors)

    env = {
        str(key): SecretValueRef.from_env_value(str(key), str(value))
        for key, value in sorted(raw_env.items())
    }
    server = MCPServerEntry(
        name=name,
        transport=raw_transport,
        command=command,
        args=tuple(str(arg) for arg in raw_args),
        env=env,
        enabled=bool(raw_server.get("enabled", False)),
        unknown_fields=_unknown_fields(
            raw_server,
            known_keys={"transport", "command", "args", "env", "enabled"},
        ),
    )
    return server, ()


def _unknown_fields(config: Mapping[str, Any], *, known_keys: set[str]) -> Mapping[str, Any]:
    return MappingProxyType({
        str(key): _redact_unknown_value(str(key), value)
        for key, value in sorted(config.items(), key=lambda item: str(item[0]))
        if key not in known_keys
    })


def _redact_unknown_value(key: str, value: Any) -> Any:
    if _is_secret_like(key, str(value)):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(child_key): _redact_unknown_value(str(child_key), child_value)
            for child_key, child_value in sorted(
                value.items(),
                key=lambda item: str(item[0]),
            )
        }
    if isinstance(value, list):
        return [_redact_unknown_value(key, item) for item in value]
    return value


def _is_secret_like(key: str, value: str) -> bool:
    normalized_key = key.upper()
    normalized_value = value.lower()
    return any(marker in normalized_key for marker in SECRET_NAME_MARKERS) or any(
        marker in normalized_value for marker in SECRET_VALUE_MARKERS
    )


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


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
