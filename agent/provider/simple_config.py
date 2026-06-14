"""Unified project config loader (config/config.yaml)。

本模块唯一职责：从 config/config.yaml 读取 provider section，
转换为 AgentProviderConfig，交给 factory/runtime。

配置来源（唯一入口）：
1. config/config.yaml（唯一推荐入口）
2. 文件不存在 → default fake

秘密管理：
- provider.api_key 直接写在 config.yaml 中（个人本地项目）
- config/config.yaml 不可提交 git
- diagnostics 显示 API key: SET (inline, redacted)
- 不打印 key 原文、prefix、suffix
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent.provider.config import SUPPORTED_PROVIDER_TYPES, AgentProviderConfig

# 默认配置文件路径（相对于 project root）
DEFAULT_CONFIG_PATH = "config/config.yaml"

# config source 类型
UnifiedConfigSource = Literal[
    "config_yaml",            # 来自 config/config.yaml 且 enabled=true
    "config_yaml_disabled",   # 来自 config/config.yaml 但 enabled=false
    "default_fake",           # 无任何配置
    "legacy_profile",         # FIRST_AGENT_PROVIDER_PROFILE (deferred)
    "legacy_provider_env",    # MY_FIRST_AGENT_LLM_PROVIDER (deferred)
]


@dataclass(frozen=True)
class UnifiedProviderConfig:
    """从 config/config.yaml 解析出的 provider 配置。"""

    config: AgentProviderConfig
    source: UnifiedConfigSource
    yaml_path: str | None = None
    config_error: str | None = None


def _try_read_yaml(path: Path) -> dict | None:
    """尝试读取 YAML 文件，返回 dict 或 None。"""
    if not path.is_file():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def load_unified_provider_config(
    config_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    project_root: str | Path | None = None,
) -> UnifiedProviderConfig:
    """从 config/config.yaml 读取 provider section。

    返回 UnifiedProviderConfig，包含 AgentProviderConfig + source 信息。

    解析规则：
    1. config/config.yaml 不存在 → default_fake
    2. provider.enabled=false → config_yaml_disabled (fake)
    3. provider.enabled=true → 必须提供 provider.api_key
       - api_key 存在 → config_yaml (real)
       - api_key 缺失 → config_yaml + config_error
    """
    root = Path(project_root) if project_root else Path.cwd()
    config_path = root / DEFAULT_CONFIG_PATH if config_path is None else Path(config_path)
    yaml_path_str = str(config_path.resolve())

    data = _try_read_yaml(config_path)

    # config.yaml 不存在 → default_fake
    if data is None:
        return UnifiedProviderConfig(
            config=_make_fake_config(),
            source="default_fake",
        )

    provider_section = data.get("provider")
    if not isinstance(provider_section, dict):
        return UnifiedProviderConfig(
            config=_make_fake_config(),
            source="default_fake",
        )

    enabled = provider_section.get("enabled", False)
    if not enabled:
        return UnifiedProviderConfig(
            config=_make_fake_config(
                model=str(provider_section.get("model", "fake-llm")),
            ),
            source="config_yaml_disabled",
            yaml_path=yaml_path_str,
        )

    # enabled=true → 从 config.yaml 读取用户字段
    # 用户只需配置 enabled/type/model/base_url/api_key 或 api_key_env
    # request_path 和 auth_scheme 由 provider adapter 内部决定，不在用户配置中暴露
    provider_type = str(provider_section.get("type", "fake")).strip().lower()
    model = str(provider_section.get("model", "fake-llm")).strip()
    base_url = _opt_str(provider_section, "base_url")

    # api_key 支持两种模式：
    # 1. inline api_key（deprecated, 仅本地未提交场景）
    # 2. api_key_env（推荐）—— 从 process env 读取 key
    api_key: str | None = _opt_str(provider_section, "api_key")
    api_key_env: str | None = _opt_str(provider_section, "api_key_env")

    # 校验 provider type
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        return UnifiedProviderConfig(
            config=_make_fake_config(),
            source="config_yaml",
            yaml_path=yaml_path_str,
            config_error=f"不支持的 provider type: {provider_type}",
        )

    # api_key_env 优先：从 process env 读取 key
    if api_key_env and provider_type != "fake":
        if env is None:
            import os
            key_value = os.environ.get(api_key_env)
        else:
            key_value = env.get(api_key_env)
        if not key_value or not key_value.strip():
            return UnifiedProviderConfig(
                config=_make_fake_config(model=model),
                source="config_yaml",
                yaml_path=yaml_path_str,
                config_error=(
                    f"环境变量 {api_key_env} 未设置或为空。"
                    "请在 .env 或 shell 中设置该环境变量，"
                    "或将 config/config.yaml 中的 api_key_env 字段改为正确的变量名"
                ),
            )
        api_key = key_value.strip()

    # enabled=true 但 api_key 缺失（且无 api_key_env）→ 配置错误，不回退 fake
    if provider_type != "fake" and not api_key:
        return UnifiedProviderConfig(
            config=_make_fake_config(model=model),
            source="config_yaml",
            yaml_path=yaml_path_str,
            config_error=(
                "provider.api_key 缺失。请在 config/config.yaml 的 "
                "provider section 中设置 api_key 字段或 api_key_env 字段"
            ),
        )

    if provider_type == "fake":
        return UnifiedProviderConfig(
            config=_make_fake_config(model=model),
            source="config_yaml",
            yaml_path=yaml_path_str,
        )

    # adapter 内部默认值：用户不配置，由 loader 根据 provider type 推导
    if provider_type.startswith("anthropic"):
        request_path = "/v1/messages"
        auth_scheme = "auto"  # adapter 内部解析为 x-api-key
        compatibility_mode = "anthropic_messages"
    elif provider_type.startswith("openai"):
        request_path = "/v1/chat/completions"
        auth_scheme = "bearer"
        compatibility_mode = "openai"
    else:
        request_path = ""
        auth_scheme = "auto"
        compatibility_mode = "fake"

    supports_streaming = provider_type == "anthropic_native"

    config = AgentProviderConfig(
        provider_type=provider_type,
        provider_name="config_yaml",
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        model=model,
        auth_scheme=auth_scheme,
        request_path=request_path,
        compatibility_mode=compatibility_mode,
        supports_tools=provider_type != "fake",
        supports_streaming=supports_streaming,
    )

    return UnifiedProviderConfig(
        config=config,
        source="config_yaml",
        yaml_path=yaml_path_str,
    )


def _opt_str(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return str(value).strip() or None


def _make_fake_config(model: str = "fake-llm") -> AgentProviderConfig:
    """创建默认 fake provider 配置。"""
    return AgentProviderConfig(
        provider_type="fake",
        provider_name="fake",
        api_key=None,
        api_key_env=None,
        base_url=None,
        model=model,
        auth_scheme="auto",
        request_path="",
        supports_tools=False,
        supports_streaming=False,
        compatibility_mode="fake",
    )
