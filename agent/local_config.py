"""Stage 8 local customization config foundation.

本模块只解析显式 safe path 的 fake/local 配置文件，帮助后续本地产品化拥有清晰
数据模型。它不读取真实 home config、不读取 `.env`、不展开环境变量、不连接
provider/MCP/network，也不修改 `config.py` 或 runtime core。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from typing import Any

from agent.display_events import mask_user_visible_secrets


_RUNTIME_ARTIFACT_PARTS = {"sessions", "runs"}
_RESERVED_CONFIG_NAMES = {".env", "agent_log.jsonl"}
_KNOWN_TOP_LEVEL_FIELDS = {
    "project_profile",
    "safety_policy",
    "module_toggles",
    "model_provider",
}


class LocalConfigPathPolicyError(ValueError):
    """local config loader 拒绝真实用户路径或 runtime artifact 路径。"""


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    """项目级 profile：只描述本地项目身份，不承载 private data。"""

    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """Stage 8 fail-closed 安全开关。"""

    allow_network: bool = False
    allow_real_mcp: bool = False
    allow_real_home_writes: bool = False


@dataclass(frozen=True, slots=True)
class ModuleToggles:
    """各 roadmap 能力的本地开关；缺省全部关闭。"""

    memory: bool = False
    skills: bool = False
    subagents: bool = False
    observability: bool = False


@dataclass(frozen=True, slots=True)
class ModelProviderConfig:
    """provider metadata，不读取也不展开真实 secret。"""

    name: str = ""
    model: str = ""
    api_key_env: str = ""
    base_url: str = ""
    api_key: str = ""

    def to_redacted_dict(self) -> dict[str, Any]:
        """输出给 CLI/docs/trace 的脱敏 provider 配置。"""

        data = {
            "name": self.name,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
        }
        if self.api_key:
            data["api_key"] = "[REDACTED]"
        return data


@dataclass(frozen=True, slots=True)
class LocalAgentConfig:
    """显式 safe path 加载出的 local customization config。"""

    source_path: Path
    project_profile: ProjectProfile
    safety_policy: SafetyPolicy = field(default_factory=SafetyPolicy)
    module_toggles: ModuleToggles = field(default_factory=ModuleToggles)
    model_provider: ModelProviderConfig = field(default_factory=ModelProviderConfig)
    unknown_fields: dict[str, Any] = field(default_factory=dict)

    def to_redacted_dict(self) -> dict[str, Any]:
        """生成可展示/可写 trace 的脱敏 dict，不泄漏 provider secret。"""

        return {
            "source_path": str(self.source_path),
            "project_profile": {
                "name": self.project_profile.name,
                "description": self.project_profile.description,
            },
            "safety_policy": {
                "allow_network": self.safety_policy.allow_network,
                "allow_real_mcp": self.safety_policy.allow_real_mcp,
                "allow_real_home_writes": self.safety_policy.allow_real_home_writes,
            },
            "module_toggles": {
                "memory": self.module_toggles.memory,
                "skills": self.module_toggles.skills,
                "subagents": self.module_toggles.subagents,
                "observability": self.module_toggles.observability,
            },
            "model_provider": self.model_provider.to_redacted_dict(),
            "unknown_fields": _redact_unknown_fields(self.unknown_fields),
        }


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_local_config_path(path: str | Path) -> Path:
    raw = Path(path)
    raw_text = str(path)
    if raw_text.startswith("~"):
        raise LocalConfigPathPolicyError("real home config is not allowed in this stage")
    if raw.name in _RESERVED_CONFIG_NAMES:
        raise LocalConfigPathPolicyError(f"reserved config/runtime path: {raw}")
    if set(raw.parts) & _RUNTIME_ARTIFACT_PARTS:
        raise LocalConfigPathPolicyError(f"runtime artifact path is not allowed: {raw}")

    resolved = raw.expanduser().resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not _is_within(tmp_root, resolved):
        raise LocalConfigPathPolicyError(
            "local config foundation only reads explicit temporary fixture paths"
        )
    return resolved


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _bool(section: dict[str, Any], key: str) -> bool:
    value = section.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _str(section: dict[str, Any], key: str, default: str = "") -> str:
    value = section.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _redact_unknown_fields(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in ("secret", "token", "key")):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_unknown_fields(item)
        return redacted
    if isinstance(value, list):
        return [_redact_unknown_fields(item) for item in value]
    if isinstance(value, str):
        return mask_user_visible_secrets(value)
    return value


def load_local_agent_config(path: str | Path) -> LocalAgentConfig:
    """从显式 safe path 加载本地配置。

    这里是 parser/model 层：只读 JSON 文件并校验形状，不把结果写入 runtime state，
    不读取 env value，不默认扫描当前项目或用户目录。
    """

    source_path = _validate_local_config_path(path)
    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("local config root must be an object")

    profile = _section(raw, "project_profile")
    name = _str(profile, "name")
    if not name:
        raise ValueError("project_profile.name is required")

    safety = _section(raw, "safety_policy")
    toggles = _section(raw, "module_toggles")
    provider = _section(raw, "model_provider")
    unknown_fields = {
        key: value
        for key, value in raw.items()
        if key not in _KNOWN_TOP_LEVEL_FIELDS
    }

    return LocalAgentConfig(
        source_path=source_path,
        project_profile=ProjectProfile(
            name=name,
            description=_str(profile, "description"),
        ),
        safety_policy=SafetyPolicy(
            allow_network=_bool(safety, "allow_network"),
            allow_real_mcp=_bool(safety, "allow_real_mcp"),
            allow_real_home_writes=_bool(safety, "allow_real_home_writes"),
        ),
        module_toggles=ModuleToggles(
            memory=_bool(toggles, "memory"),
            skills=_bool(toggles, "skills"),
            subagents=_bool(toggles, "subagents"),
            observability=_bool(toggles, "observability"),
        ),
        model_provider=ModelProviderConfig(
            name=_str(provider, "name"),
            model=_str(provider, "model"),
            api_key_env=_str(provider, "api_key_env"),
            base_url=_str(provider, "base_url"),
            api_key=_str(provider, "api_key"),
        ),
        unknown_fields=unknown_fields,
    )
