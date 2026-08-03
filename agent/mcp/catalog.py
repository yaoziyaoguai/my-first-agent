"""显式 MCP catalog 解析与不可变 descriptor 冻结。

startup 只解析 operator 审核过的 JSON catalog，不联网、不 spawn、不 initialize。
catalog 只做本地校验与 identity 冻结；MCP SDK 仅在 invocation（bridge/session）时才需要。
错误信息不携带 credential value 或绝对私有路径。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent.runtime.contracts import (
    ApprovalPolicy,
    JSONValue,
    OutputPolicy,
    SideEffectClass,
    ToolRisk,
)

MCP_PROTOCOL_REVISION = "2025-11-25"
_LOCAL_PREFIX = "mcp__"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REMOTE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_CREDENTIAL_KEY = re.compile(r"(secret|password|token|api[_-]?key|credential|private[_-]?key)")
_CREDENTIAL_VALUE = re.compile(
    r"^(sk-[A-Za-z0-9]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{10,}|-----BEGIN|Bearer\s)"
)


class McpCatalogError(Exception):
    """catalog 解析失败。错误信息不携带 value 或绝对私有路径。"""


@dataclass(frozen=True, slots=True)
class McpLimits:
    max_servers: int = 16
    max_tools_per_server: int = 32
    max_schema_bytes: int = 50_000
    max_schema_depth: int = 12
    max_args: int = 32
    max_env_names: int = 32
    max_executable_bytes: int = 5_000_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_servers", self.max_servers),
            ("max_tools_per_server", self.max_tools_per_server),
            ("max_schema_bytes", self.max_schema_bytes),
            ("max_schema_depth", self.max_schema_depth),
            ("max_args", self.max_args),
            ("max_env_names", self.max_env_names),
            ("max_executable_bytes", self.max_executable_bytes),
        ):
            if value < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class McpToolDescriptor:
    server_id: str
    remote_name: str
    local_name: str
    description: str
    input_schema: Mapping[str, JSONValue]
    output_schema: Mapping[str, JSONValue] | None
    output_limit_chars: int
    descriptor_digest: str

    @property
    def risk(self) -> ToolRisk:
        return ToolRisk.HIGH

    @property
    def side_effect(self) -> SideEffectClass:
        return SideEffectClass.EXTERNAL

    @property
    def approval_policy(self) -> ApprovalPolicy:
        # 所有 v1 MCP tool 统一 HIGH + EXTERNAL + ALWAYS_APPROVAL，
        # remote annotation 不能降低。
        return ApprovalPolicy.ALWAYS

    @property
    def output_policy(self) -> OutputPolicy:
        return OutputPolicy.BOUNDED_TEXT


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    server_id: str
    transport: str
    command: str
    args: tuple[str, ...]
    cwd: str | None
    env_names: tuple[str, ...]
    credential_profile: str | None
    safety_generation: str
    protocol_revision: str
    spawn_identity: SpawnIdentity
    config_digest: str


@dataclass(frozen=True, slots=True)
class SpawnIdentity:
    """approval 前冻结、spawn 前复验的 identity bundle（009 closure gate）。

    - ``executable``：command 的 dev/ino/mode/size/content_digest（startup 已 size-gate）。
    - ``ancestor``：command 父目录的 dev/ino（检测保留 executable inode 但替换目录）。
    - ``cwd``：cwd 目录的 dev/ino，或 None。

    run_stdio_session 在 spawn（与 latch arm）之前重新计算并比较三者；任一不一致即
    NOT_EXECUTED（被篡改的 binary 永不 spawn）。目录类 identity 只比较 dev/ino。
    """

    executable: Mapping[str, JSONValue]
    ancestor: Mapping[str, JSONValue]
    cwd: Mapping[str, JSONValue] | None


def freeze_spawn_identity(command: str, cwd: str | None, limits: McpLimits) -> SpawnIdentity:
    executable = _freeze_executable(command, limits)
    ancestor = _freeze_dir_identity(Path(command).parent, label="ancestor")
    cwd_identity = None
    if cwd is not None:
        if not Path(cwd).is_absolute():
            raise McpCatalogError("cwd must be an absolute path")
        cwd_identity = _freeze_dir_identity(Path(cwd), label="cwd")
    return SpawnIdentity(executable=executable, ancestor=ancestor, cwd=cwd_identity)


def revalidate_spawn_identity(command: str, cwd: str | None, frozen: SpawnIdentity) -> None:
    """spawn 前复验 executable + ancestor + cwd identity；任一不一致 raise McpCatalogError。"""
    current_exe = _stat_executable(command)
    if dict(current_exe) != dict(frozen.executable):
        raise McpCatalogError("spawn identity drifted; rebuild the catalog")
    current_ancestor = _freeze_dir_identity(Path(command).parent, label="ancestor")
    if (current_ancestor["dev"], current_ancestor["ino"]) != (
        frozen.ancestor["dev"],
        frozen.ancestor["ino"],
    ):
        raise McpCatalogError("spawn identity drifted; rebuild the catalog")
    if frozen.cwd is not None:
        if cwd is None:
            raise McpCatalogError("spawn identity drifted; rebuild the catalog")
        current_cwd = _freeze_dir_identity(Path(cwd), label="cwd")
        if (current_cwd["dev"], current_cwd["ino"]) != (
            frozen.cwd["dev"],
            frozen.cwd["ino"],
        ):
            raise McpCatalogError("spawn identity drifted; rebuild the catalog")


@dataclass(frozen=True, slots=True)
class McpCatalog:
    servers: tuple[McpServerConfig, ...]
    tools: tuple[McpToolDescriptor, ...]
    catalog_digest: str


def build_mcp_catalog(
    config: Mapping[str, object], *, limits: McpLimits | None = None
) -> McpCatalog:
    effective_limits = limits or McpLimits()
    _scan_credential_values(config)
    if not isinstance(config, Mapping) or not isinstance(config.get("servers"), list):
        raise McpCatalogError("catalog must be an object with a servers list")
    servers_list = config["servers"]
    if not servers_list:
        raise McpCatalogError("catalog must contain at least one server")
    if len(servers_list) > effective_limits.max_servers:
        raise McpCatalogError("too many servers configured")

    servers: list[McpServerConfig] = []
    tools: list[McpToolDescriptor] = []
    local_names: set[str] = set()
    for raw in servers_list:
        server, server_tools = _build_server(raw, effective_limits)
        if server.server_id in {existing.server_id for existing in servers}:
            raise McpCatalogError("duplicate server id")
        servers.append(server)
        for tool in server_tools:
            if tool.local_name in local_names:
                raise McpCatalogError("duplicate local tool name")
            local_names.add(tool.local_name)
            tools.append(tool)

    catalog_digest = _digest_json(
        {
            "servers": [s.config_digest for s in servers],
            "tools": [t.descriptor_digest for t in tools],
            "protocol_revision": MCP_PROTOCOL_REVISION,
        }
    )
    return McpCatalog(
        servers=tuple(servers),
        tools=tuple(tools),
        catalog_digest=catalog_digest,
    )


def _build_server(
    raw: object, limits: McpLimits
) -> tuple[McpServerConfig, list[McpToolDescriptor]]:
    if not isinstance(raw, Mapping):
        raise McpCatalogError("server entry must be an object")
    server_id = _require_string(raw, "server_id")
    transport = _require_string(raw, "transport")
    if transport != "stdio":
        raise McpCatalogError("only stdio transport is supported")
    safety_generation = _require_string(raw, "safety_generation")
    protocol_revision = _require_string(raw, "protocol_revision")
    if protocol_revision != MCP_PROTOCOL_REVISION:
        raise McpCatalogError("unsupported protocol revision")
    command = _require_string(raw, "command")
    args = _require_string_list(raw.get("args"), "args", limits.max_args)
    cwd = raw.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise McpCatalogError("cwd must be a string")
    env_names = _require_string_list(raw.get("env_names") or [], "env_names", limits.max_env_names)
    for name in env_names:
        if not _ENV_NAME.match(name):
            raise McpCatalogError("invalid environment variable name")
    credential_profile = raw.get("credential_profile")
    if credential_profile is not None and not isinstance(credential_profile, str):
        raise McpCatalogError("credential_profile must be a string label")
    if raw.get("tools") is None or not isinstance(raw["tools"], list):
        raise McpCatalogError("server must declare a tools list")
    if len(raw["tools"]) > limits.max_tools_per_server:
        raise McpCatalogError("too many tools for one server")

    tool_descriptors: list[McpToolDescriptor] = []
    for raw_tool in raw["tools"]:
        tool_descriptors.append(_build_tool(server_id, raw_tool, limits))

    spawn_identity = freeze_spawn_identity(command, cwd, limits)
    config_digest = _digest_json(
        {
            "server_id": server_id,
            "command_identity": dict(spawn_identity.executable),
            "ancestor_identity": dict(spawn_identity.ancestor),
            "cwd_identity": dict(spawn_identity.cwd) if spawn_identity.cwd is not None else None,
            "args": list(args),
            "cwd": cwd,
            "env_names": list(env_names),
            "credential_profile": credential_profile,
            "safety_generation": safety_generation,
            "protocol_revision": protocol_revision,
            "tools": [t.descriptor_digest for t in tool_descriptors],
        }
    )
    server = McpServerConfig(
        server_id=server_id,
        transport=transport,
        command=command,
        args=tuple(args),
        cwd=cwd,
        env_names=tuple(env_names),
        credential_profile=credential_profile,
        safety_generation=safety_generation,
        protocol_revision=protocol_revision,
        spawn_identity=spawn_identity,
        config_digest=config_digest,
    )
    return server, tool_descriptors


def _build_tool(server_id: str, raw_tool: object, limits: McpLimits) -> McpToolDescriptor:
    if not isinstance(raw_tool, Mapping):
        raise McpCatalogError("tool descriptor must be an object")
    remote_name = _require_string(raw_tool, "remote_name")
    if not _REMOTE_NAME.match(remote_name):
        raise McpCatalogError("invalid remote tool name")
    description = _require_string(raw_tool, "description")
    if not 1 <= len(description) <= 1024:
        raise McpCatalogError("tool description length is out of range")
    schema = raw_tool.get("input_schema")
    if not isinstance(schema, dict):
        raise McpCatalogError("input_schema must be an object")
    schema_blob = json.dumps(schema, sort_keys=True, ensure_ascii=False)
    if len(schema_blob.encode("utf-8")) > limits.max_schema_bytes:
        raise McpCatalogError("input schema exceeds the size limit")
    if _json_depth(schema) > limits.max_schema_depth:
        raise McpCatalogError("input schema exceeds the depth limit")
    output_schema = raw_tool.get("output_schema")
    if output_schema is not None and not isinstance(output_schema, dict):
        raise McpCatalogError("output_schema must be an object")
    output_limit = raw_tool.get("output_limit_chars")
    if not isinstance(output_limit, int) or output_limit < 1:
        raise McpCatalogError("output_limit_chars must be a positive integer")

    local_name = f"{_LOCAL_PREFIX}{server_id}__{remote_name}"
    descriptor_digest = _digest_json(
        {
            "server_id": server_id,
            "remote_name": remote_name,
            "local_name": local_name,
            "description": description,
            "input_schema": schema,
            "output_schema": output_schema,
            "output_limit_chars": output_limit,
            "policy": {
                "risk": ToolRisk.HIGH.value,
                "side_effect": SideEffectClass.EXTERNAL.value,
                "approval": ApprovalPolicy.ALWAYS.value,
            },
        }
    )
    return McpToolDescriptor(
        server_id=server_id,
        remote_name=remote_name,
        local_name=local_name,
        description=description,
        input_schema=_freeze_mapping(schema),
        output_schema=_freeze_mapping(output_schema) if output_schema is not None else None,
        output_limit_chars=output_limit,
        descriptor_digest=descriptor_digest,
    )


def _stat_executable(command: str) -> Mapping[str, JSONValue]:
    """计算 executable identity（dev/ino/mode/size/content_digest），不做 size 限制校验。

    startup 与 spawn 复验共用：startup 额外做 size gate，spawn 复验只比较 identity。
    """
    path = Path(command)
    if not path.is_absolute():
        raise McpCatalogError("command must be an absolute executable path")
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError as error:
        raise McpCatalogError("command executable does not exist") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise McpCatalogError("command must be a regular executable, not a symlink")
    with open(path, "rb") as handle:  # noqa: PTH123
        content = handle.read()
    return _freeze_mapping(
        {
            "dev": info.st_dev,
            "ino": info.st_ino,
            "mode": info.st_mode,
            "size": info.st_size,
            "content_digest": hashlib.sha256(content).hexdigest(),
        }
    )


def _freeze_executable(command: str, limits: McpLimits) -> Mapping[str, JSONValue]:
    identity = _stat_executable(command)
    if identity["size"] > limits.max_executable_bytes:
        raise McpCatalogError("command executable exceeds the size limit")
    return identity


def _freeze_dir_identity(path: Path, *, label: str) -> Mapping[str, JSONValue]:
    """目录 identity（dev/ino，no-follow）。错误信息不泄露绝对路径。"""
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError as error:
        raise McpCatalogError(f"{label} directory does not exist") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise McpCatalogError(f"{label} path must be a real directory")
    return _freeze_mapping({"dev": info.st_dev, "ino": info.st_ino})


_LEGIT_CATALOG_KEYS = frozenset(
    {
        "servers",
        "server_id",
        "transport",
        "command",
        "args",
        "cwd",
        "env_names",
        "credential_profile",
        "safety_generation",
        "protocol_revision",
        "tools",
        "remote_name",
        "local_name",
        "description",
        "input_schema",
        "output_schema",
        "output_limit_chars",
        "version",
        "type",
        "properties",
        "required",
        "additionalProperties",
    }
)


def _scan_credential_values(value: object, *, key_hint: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                isinstance(key, str)
                and key not in _LEGIT_CATALOG_KEYS
                and _CREDENTIAL_KEY.search(key.lower())
                and isinstance(item, str | int | float)
                and item not in ("", 0)
            ):
                raise McpCatalogError("catalog must not contain credential-looking values")
            _scan_credential_values(item, key_hint=key if isinstance(key, str) else key_hint)
    elif isinstance(value, list):
        for item in value:
            _scan_credential_values(item, key_hint=key_hint)
    elif isinstance(value, str) and _CREDENTIAL_VALUE.match(value):
        raise McpCatalogError("catalog must not contain credential-looking values")


def _json_depth(value: object) -> int:
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


def _require_string(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise McpCatalogError(f"{key} must be a non-empty string")
    return value


def _require_string_list(value: object, label: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise McpCatalogError(f"{label} must be a bounded list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise McpCatalogError(f"{label} entries must be strings")
        result.append(item)
    return result


def _freeze_mapping(mapping: dict[str, object]) -> Mapping[str, JSONValue]:
    from types import MappingProxyType

    encoded = json.loads(json.dumps(mapping, sort_keys=True))
    return MappingProxyType(encoded)


def _digest_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
