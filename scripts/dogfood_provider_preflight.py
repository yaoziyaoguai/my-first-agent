"""Provider preflight helper for gated dogfood runs.

本模块集中处理 real-api dogfood 的 provider 配置审查。它只返回脱敏 preflight
packet；真正的 API key 仅进入 AgentProviderConfig 并交给 provider factory，
不会被打印、写报告或序列化。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import config as _config
from agent.provider.config import (
    PROVIDER_ENV,
    PROVIDER_NAME_ENV,
    AgentProviderConfig,
    load_agent_provider_config,
)
from agent.provider.protocol import ProviderConfigurationError

DOGFOOD_RELEVANT_KEYS = (
    PROVIDER_ENV,
    PROVIDER_NAME_ENV,
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_BASE_URL",
    "OPENAI_BASE_URL",
    "MY_FIRST_AGENT_LLM_BASE_URL",
    "MODEL_NAME",
    "ANTHROPIC_MODEL",
    "OPENAI_MODEL",
    "MY_FIRST_AGENT_LLM_MODEL",
    "MY_FIRST_AGENT_LLM_AUTH_SCHEME",
    "MY_FIRST_AGENT_LLM_REQUEST_PATH",
    "MY_FIRST_AGENT_LLM_COMPATIBILITY_MODE",
    "MY_FIRST_AGENT_LLM_MAX_TOKENS",
    "MY_FIRST_AGENT_LLM_TIMEOUT",
)

KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
MODEL_NAMES = ("MODEL_NAME", "ANTHROPIC_MODEL", "OPENAI_MODEL")


def _first_project_value(project_values: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = project_values.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _has_shell_value(env: Mapping[str, str], names: tuple[str, ...]) -> bool:
    return any(bool(env.get(name, "").strip()) for name in names)


def _provider_public_base_url(config: AgentProviderConfig | None) -> str:
    if config is None:
        return "unknown"
    return config.base_url or "native_default"


def _provider_public_model(
    config: AgentProviderConfig | None,
    project_values: Mapping[str, str],
) -> str:
    if config is not None and config.model:
        return config.model
    return _first_project_value(project_values, MODEL_NAMES) or "unknown"


def _provider_public_name(
    config: AgentProviderConfig | None,
    project_values: Mapping[str, str],
) -> str:
    if config is not None:
        return config.provider_name or config.provider_type
    return project_values.get(PROVIDER_NAME_ENV) or project_values.get(PROVIDER_ENV) or "unknown"


def _provider_public_type(
    config: AgentProviderConfig | None,
    project_values: Mapping[str, str],
) -> str:
    if config is not None:
        return config.provider_type
    return project_values.get(PROVIDER_ENV) or "unknown"


def load_dogfood_provider_config_private(
    project_root: Path,
    *,
    dotenv_loader: Any | None = None,
    shell_env: Mapping[str, str] | None = None,
) -> tuple[AgentProviderConfig | None, dict[str, Any]]:
    """返回 provider config 与脱敏 preflight，不返回、不打印 API key。

    ``dotenv_loader`` 和 ``shell_env`` 仅用于测试注入：runner 默认仍使用项目
    scoped dotenv loader 和当前进程 env 做 fallback 检测，但 shell env 永远不能
    成为 real-api key 来源。
    """

    if dotenv_loader is None:
        dotenv_loader = _config._load_project_dotenv_values
    if shell_env is None:
        shell_env = os.environ

    project_values = dotenv_loader(project_root)
    shell_env_conflict_detected = False
    for key in DOGFOOD_RELEVANT_KEYS:
        project_value = project_values.get(key, "")
        shell_value = shell_env.get(key, "")
        if project_value and shell_value and project_value.strip() != shell_value.strip():
            shell_env_conflict_detected = True
            break

    api_key_present = _first_project_value(project_values, KEY_NAMES) is not None
    shell_env_fallback_used = not api_key_present and _has_shell_value(shell_env, KEY_NAMES)

    config: AgentProviderConfig | None = None
    config_error: str | None = None
    if not shell_env_fallback_used and project_values:
        try:
            # dogfood 的真实 provider 配置只从 project dotenv 映射进入正式
            # AgentProviderConfig；这样四种 API style 都走 provider 层统一校验。
            config = load_agent_provider_config(env=project_values)
        except ProviderConfigurationError as exc:
            config_error = str(exc)

    if shell_env_fallback_used:
        preflight_status = "BLOCKED: shell_env_fallback_disallowed"
        auth_status = "blocked_shell_env_fallback"
    elif config_error == "api_key_missing" or not api_key_present:
        preflight_status = "blocked_missing_project_dotenv_key"
        auth_status = "missing_project_dotenv_key"
    elif config_error == "model_missing":
        preflight_status = "blocked_missing_model"
        auth_status = "missing_model"
    elif config_error:
        preflight_status = f"blocked_provider_config:{config_error}"
        auth_status = "provider_config_error"
    else:
        preflight_status = "ready"
        auth_status = "configured"

    preflight = {
        "key_source_kind": "project_dotenv" if api_key_present else "missing",
        "provider_name": _provider_public_name(config, project_values),
        "provider_type": _provider_public_type(config, project_values),
        "model": _provider_public_model(config, project_values),
        "base_url": _provider_public_base_url(config),
        "project_dotenv_loaded": bool(project_values),
        "shell_env_conflict_detected": shell_env_conflict_detected,
        "shell_env_fallback_used": shell_env_fallback_used,
        "auth_status": auth_status,
        "preflight_status": preflight_status,
    }
    return config, preflight


def load_dogfood_provider_preflight(project_root: Path) -> dict[str, Any]:
    """返回脱敏 real-api preflight，不暴露 provider secret。"""

    _config_obj, preflight = load_dogfood_provider_config_private(project_root)
    return preflight
