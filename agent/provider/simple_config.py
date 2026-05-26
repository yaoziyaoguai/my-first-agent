"""Unified project config loader (config/config.yaml)。

本模块是**配置层**，不是 runtime 层。它唯一的职责是从 config/config.yaml
读取 provider section，转换为 AgentProviderConfig，交给 factory/runtime。

为什么用 config.yaml 而不是 provider profiles：
- 用户只需要一个文件就知道当前模型怎么配
- 不需要记住 profile 名称（如 kimi_anthropic）
- provider section 直接描述 active provider，不需要概念跳转
- 后续 runtime/memory/logging/workspace/tools 都在同一个文件中

config source precedence:
1. config/config.yaml（推荐入口）
2. FIRST_AGENT_PROVIDER_PROFILE legacy fallback（已废弃，仍可用）
3. MY_FIRST_AGENT_LLM_PROVIDER + 分散 env vars（legacy fallback）
4. default fake

秘密管理：
- api_key_env 只存变量名（如 ANTHROPIC_API_KEY）
- 实际 key 从 os.environ 读取
- config/config.yaml 可以安全提交
- .env 不提交
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent.provider.config import SUPPORTED_PROVIDER_TYPES, AgentProviderConfig

# 默认配置文件路径（相对于 project root）
DEFAULT_CONFIG_PATH = "config/config.yaml"

# config source 类型（比 diagnostics 中的 ConfigSourceKind 更细粒度）
UnifiedConfigSource = Literal[
    "config_yaml",            # 来自 config/config.yaml 且 enabled=true
    "config_yaml_disabled",   # 来自 config/config.yaml 但 enabled=false
    "default_fake",           # 无任何配置
    "legacy_profile",         # FIRST_AGENT_PROVIDER_PROFILE
    "legacy_provider_env",    # MY_FIRST_AGENT_LLM_PROVIDER
]


@dataclass(frozen=True)
class UnifiedProviderConfig:
    """从 config/config.yaml 解析出的 provider 配置。

    与 AgentProviderConfig 的区别：
    - 这是一个中间表示，包含 source 信息
    - AgentProviderConfig 是最终 config（不包含 source）
    - 分开是为了让 diagnostics 能区分 config_yaml / legacy / default_fake
    """

    config: AgentProviderConfig
    source: UnifiedConfigSource
    yaml_path: str | None = None
    config_error: str | None = None  # YAML 解析失败等错误信息


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

    Fallback 链:
    1. config/config.yaml 存在 → 读 provider section
    2. 不存 → 返回 default_fake

    即使 config.yaml 存在但 provider.enabled=false，也返回 fake config
    （source=config_yaml_disabled），确保不会静默启用真实 API。
    """
    if env is None:
        env = os.environ

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
        # 文件存在但没有 provider section → default_fake
        return UnifiedProviderConfig(
            config=_make_fake_config(),
            source="default_fake",
        )

    enabled = provider_section.get("enabled", False)
    if not enabled:
        # enabled=false → 显式禁用 real provider
        return UnifiedProviderConfig(
            config=_make_fake_config(
                model=str(provider_section.get("model", "fake-llm")),
            ),
            source="config_yaml_disabled",
            yaml_path=yaml_path_str,
        )

    # enabled=true → 从 YAML 读取 provider 配置
    provider_type = str(provider_section.get("type", "fake")).strip().lower()
    model = str(provider_section.get("model", "fake-llm")).strip()
    base_url = _opt_str(provider_section, "base_url")
    request_path = _opt_str(provider_section, "request_path") or ""
    auth_scheme = _opt_str(provider_section, "auth_scheme") or "auto"
    api_key_env = _opt_str(provider_section, "api_key_env")

    # 读取实际 key（从 env，不从 yaml）
    api_key: str | None = None
    if api_key_env:
        api_key = (env.get(api_key_env) or "").strip() or None

    # 校验
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        return UnifiedProviderConfig(
            config=_make_fake_config(),
            source="config_yaml",
            yaml_path=yaml_path_str,
            config_error=f"不支持的 provider type: {provider_type}",
        )

    if provider_type != "fake" and not api_key:
        return UnifiedProviderConfig(
            config=_make_fake_config(model=model),
            source="config_yaml",
            yaml_path=yaml_path_str,
            config_error=f"API key 未设置：环境变量 {api_key_env} 为空或不存在",
        )

    if provider_type == "fake":
        return UnifiedProviderConfig(
            config=_make_fake_config(model=model),
            source="config_yaml",
            yaml_path=yaml_path_str,
        )

    # 推导默认值
    if not request_path:
        if provider_type.startswith("anthropic"):
            request_path = "/v1/messages"
        elif provider_type.startswith("openai"):
            request_path = "/v1/chat/completions"

    supports_streaming = provider_type == "anthropic_native"
    compatibility_mode = (
        "anthropic_messages" if provider_type.startswith("anthropic") else
        "openai" if provider_type.startswith("openai") else
        "fake"
    )

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
