"""SubAgent descriptor schema and SUBAGENT.md parser.

Phase 1 只解析和校验 frontmatter，返回不可变 metadata。这里不加载真实
SubAgent body、不调用 provider、不连接 ToolRegistry，也不读取真实用户目录。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from agent.subagent_system.errors import SubAgentLoadError
from agent.subagent_system.execution_mode import EXECUTION_MODE_VALUES, LOCAL_EXECUTION_MODES

SUBAGENT_MD_FILENAME = "SUBAGENT.md"
REDACTED = "<redacted>"

SUBAGENT_STATUSES = frozenset({"active", "deprecated", "disabled"})
RISK_LEVELS = frozenset({"low", "medium", "high"})
SAFE_MODELS = frozenset({"fake", "fixture", "none", "inherit"})
MEMORY_SCOPES = frozenset({"none", "read_context", "propose"})
CONFIRMATION_POLICIES = frozenset({"inherit_tool_policy", "require_parent"})
KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SECRET_KEY_MARKERS = ("secret", "token", "password", "credential", "api_key")
SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)


@dataclass(frozen=True)
class SubAgentDescriptor:
    """Registered SUBAGENT.md metadata projection.

    这是 registry-visible 的 L0 descriptor，不包含 body，也不授予执行能力。
    """

    name: str
    description: str
    role: str
    model: str = "fake"
    status: str = "active"
    risk_level: str = "low"
    allowed_tools: tuple[str, ...] = ()
    allowed_skills: tuple[str, ...] = ()
    memory_scope: str = "none"
    max_iterations_default: int = 1
    confirmation_policy: str = "inherit_tool_policy"
    supported_modes: tuple[str, ...] = ("local_fake",)
    tags: tuple[str, ...] = ()
    version: str = "0.1.0"
    source_dir: Path | None = None
    manifest_path: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_tools", tuple(self.allowed_tools))
        object.__setattr__(self, "allowed_skills", tuple(self.allowed_skills))
        object.__setattr__(self, "supported_modes", tuple(self.supported_modes))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def is_visible(self) -> bool:
        """Only active descriptors are visible for delegation selection."""

        return self.status == "active"


def load_subagent_descriptor(path: str | Path) -> SubAgentDescriptor:
    """Load and validate a `SUBAGENT.md` descriptor."""

    manifest_path = Path(path)
    if manifest_path.is_dir():
        manifest_path = manifest_path / SUBAGENT_MD_FILENAME
    if manifest_path.name != SUBAGENT_MD_FILENAME:
        raise _load_error("INVALID_PATH", "SubAgent manifest must be SUBAGENT.md", path=manifest_path)  # noqa: E501
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _load_error("READ_ERROR", "Unable to read SUBAGENT.md", path=manifest_path) from exc

    frontmatter = _parse_frontmatter(raw_text, manifest_path)
    _validate_frontmatter(frontmatter, manifest_path)

    metadata = frontmatter.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    return SubAgentDescriptor(
        name=str(frontmatter["name"]),
        description=str(frontmatter["description"]),
        role=str(frontmatter["role"]),
        model=str(frontmatter.get("model", "fake")),
        status=str(frontmatter["status"]),
        risk_level=str(frontmatter.get("risk_level", "low")),
        allowed_tools=_as_tuple(frontmatter.get("allowed_tools", ())),
        allowed_skills=_as_tuple(frontmatter.get("allowed_skills", ())),
        memory_scope=str(frontmatter.get("memory_scope", "none")),
        max_iterations_default=int(frontmatter.get("max_iterations_default", 1)),
        confirmation_policy=str(frontmatter.get("confirmation_policy", "inherit_tool_policy")),
        supported_modes=_as_tuple(frontmatter.get("supported_modes", ("local_fake",))),
        tags=_as_tuple(frontmatter.get("tags", ())),
        version=str(frontmatter.get("version", "0.1.0")),
        source_dir=manifest_path.parent,
        manifest_path=manifest_path,
        metadata=_redact_mapping(metadata),
    )


def _parse_frontmatter(raw_text: str, path: Path) -> dict[str, Any]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise _load_error("MISSING_FRONTMATTER", "SUBAGENT.md must start with frontmatter", path=path)  # noqa: E501
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise _load_error("MISSING_FRONTMATTER", "SUBAGENT.md frontmatter is not closed", path=path)
    try:
        data = yaml.safe_load("\n".join(lines[1:end_index])) or {}
    except yaml.YAMLError as exc:
        raise _load_error("PARSE_ERROR", "SUBAGENT.md frontmatter is invalid", path=path) from exc
    if not isinstance(data, dict):
        raise _load_error("PARSE_ERROR", "SUBAGENT.md frontmatter must be a mapping", path=path)
    return data


def _validate_frontmatter(data: dict[str, Any], path: Path) -> None:
    for field_name, code in (
        ("name", "MISSING_NAME"),
        ("description", "MISSING_DESCRIPTION"),
        ("role", "MISSING_ROLE"),
        ("status", "MISSING_STATUS"),
    ):
        if not data.get(field_name):
            raise _load_error(code, f"Missing required field: {field_name}", path=path)

    name = str(data["name"])
    if not KEBAB_CASE_PATTERN.match(name) or name != path.parent.name:
        raise _load_error("INVALID_NAME", "SubAgent name must be kebab-case and match directory", path=path)  # noqa: E501
    if data["status"] not in SUBAGENT_STATUSES:
        raise _load_error("INVALID_STATUS", "Invalid SubAgent status", path=path)
    if data.get("model", "fake") not in SAFE_MODELS:
        raise _load_error(
            "INVALID_MODEL",
            "v1 SubAgent model must be fake/fixture/none/inherit",
            path=path,
        )
    if data.get("risk_level", "low") not in RISK_LEVELS:
        raise _load_error("INVALID_RISK_LEVEL", "Invalid SubAgent risk level", path=path)
    if data.get("memory_scope", "none") not in MEMORY_SCOPES:
        raise _load_error("INVALID_MEMORY_SCOPE", "Invalid SubAgent memory scope", path=path)
    if data.get("confirmation_policy", "inherit_tool_policy") not in CONFIRMATION_POLICIES:
        raise _load_error("INVALID_CONFIRMATION_POLICY", "Invalid confirmation policy", path=path)
    max_iterations = data.get("max_iterations_default", 1)
    if not isinstance(max_iterations, int) or max_iterations < 1 or max_iterations > 10:
        raise _load_error("INVALID_MAX_ITERATIONS", "max_iterations_default must be 1-10", path=path)  # noqa: E501
    supported_modes = _as_tuple(data.get("supported_modes", ("local_fake",)))
    if not supported_modes or not set(supported_modes).issubset(EXECUTION_MODE_VALUES):
        raise _load_error("INVALID_SUPPORTED_MODE", "Unsupported execution mode", path=path)
    if not set(supported_modes).issubset(LOCAL_EXECUTION_MODES):
        raise _load_error(
            "INVALID_SUPPORTED_MODE",
            "Phase 1 descriptors may only enable local execution modes by default",
            path=path,
        )


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _redact_value(str(key), value) for key, value in data.items()}


def _redact_value(key: str, value: object) -> object:
    if any(marker in key.lower() for marker in SECRET_KEY_MARKERS):
        return REDACTED
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            return REDACTED
        return value
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return tuple(_redact_value(key, item) for item in value)
    return value


def _load_error(code: str, message: str, *, path: Path | None = None) -> SubAgentLoadError:
    return SubAgentLoadError(
        code=code,
        message=message,
        path=path,
        recoverable=False,
        safe_preview=message,
    )

