"""Safe provider configuration helpers for the LLM processing MVP.

M4 只解决 provider 配置和 preflight，不把项目扩成完整 provider 平台。这里集中
处理 env 读取和公开输出，是为了让 key/base_url 等配置边界先稳定下来，再进入真实
LLM 调用路径；审计输出只能说明 secret 是否存在，不能输出 secret 值。
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Mapping

from llm.errors import (
    ERROR_MISSING_CONFIG,
    ERROR_UNKNOWN_PROVIDER,
    make_provider_error,
    safe_error_dict,
)


PROVIDER_ENV = "MY_FIRST_AGENT_LLM_PROVIDER"
GENERIC_MODEL_ENV = "MY_FIRST_AGENT_LLM_MODEL"
GENERIC_BASE_URL_ENV = "MY_FIRST_AGENT_LLM_BASE_URL"


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    requires_key: bool
    key_env: str | None
    model_envs: tuple[str, ...]
    base_url_envs: tuple[str, ...]
    default_model: str | None = None
    dependency: str | None = None


PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    "fake": ProviderSpec(
        name="fake",
        requires_key=False,
        key_env=None,
        model_envs=("LLM_FAKE_MODEL", GENERIC_MODEL_ENV),
        base_url_envs=(),
        default_model="fake-llm",
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        requires_key=True,
        key_env="ANTHROPIC_API_KEY",
        model_envs=("ANTHROPIC_MODEL", "MODEL_NAME", GENERIC_MODEL_ENV),
        base_url_envs=("ANTHROPIC_BASE_URL", GENERIC_BASE_URL_ENV),
        dependency="anthropic",
    ),
}


def _env_get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _first_env(env: Mapping[str, str], names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        value = _env_get(env, name)
        if value:
            return value, name
    return None, None


def resolve_provider_name(
    provider_name: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """解析 provider 名称；默认 fake，避免无 key 环境误触真实 provider。"""

    if env is None:
        env = os.environ
    provider = provider_name or _env_get(env, PROVIDER_ENV) or "fake"
    return provider.strip().lower()


def load_provider_config(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProviderConfig:
    """从 env/CLI 读取 provider 配置，只返回运行必需字段。

    key 只留在内存里的 ProviderConfig，调用方不得把它写入 state/runs 或 stdout。
    """

    if env is None:
        env = os.environ
    provider = resolve_provider_name(provider_name, env=env)
    spec = PROVIDER_REGISTRY.get(provider)
    if spec is None:
        raise make_provider_error(
            ERROR_UNKNOWN_PROVIDER,
            "unknown_provider",
            retryable=False,
        )

    model_name = (model.strip() if model else None) or _first_env(env, spec.model_envs)[0]
    if not model_name and spec.default_model:
        model_name = spec.default_model
    if not model_name:
        raise make_provider_error(
            ERROR_MISSING_CONFIG,
            "model_missing",
            retryable=False,
        )

    api_key = _env_get(env, spec.key_env) if spec.key_env else None
    if spec.requires_key and not api_key:
        raise make_provider_error(
            ERROR_MISSING_CONFIG,
            "api_key_missing",
            retryable=False,
        )

    base_url = _first_env(env, spec.base_url_envs)[0]
    return ProviderConfig(
        provider=provider,
        model=model_name,
        api_key=api_key,
        base_url=base_url,
    )


def build_preflight_report(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    live: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """构造不会泄密的 provider preflight 报告。

    报告只展示配置是否存在、依赖是否可用和错误摘要。key/base_url 值、prompt、
    completion、request/response body 都不进入这个 dict。
    """

    if env is None:
        env = os.environ
    errors: list[dict[str, object]] = []
    warnings: list[str] = []
    provider = resolve_provider_name(provider_name, env=env)
    spec = PROVIDER_REGISTRY.get(provider)
    if spec is None:
        return {
            "status": "error",
            "provider": {"name": provider, "configured": False},
            "model": {"configured": False, "name": None, "source": None},
            "base_url": {"configured": False},
            "api_key": {"status": "not_applicable", "env": None},
            "dependency": {"name": None, "available": False},
            "live": {"enabled": live, "status": "skipped"},
            "errors": [
                safe_error_dict(
                    make_provider_error(
                        ERROR_UNKNOWN_PROVIDER,
                        "unknown_provider",
                        retryable=False,
                    )
                )
            ],
            "warnings": warnings,
        }

    model_name = (model.strip() if model else None)
    model_source = "cli" if model_name else None
    if not model_name:
        model_name, model_source = _first_env(env, spec.model_envs)
    if not model_name and spec.default_model:
        model_name = spec.default_model
        model_source = "default"
    if not model_name:
        errors.append(
            safe_error_dict(
                make_provider_error(
                    ERROR_MISSING_CONFIG,
                    "model_missing",
                    retryable=False,
                )
            )
        )

    base_url, _base_url_source = _first_env(env, spec.base_url_envs)
    if spec.base_url_envs and not base_url:
        warnings.append(f"base_url_missing:{provider}")
    api_key = _env_get(env, spec.key_env) if spec.key_env else None
    if not spec.requires_key:
        key_status = "not_required"
    elif api_key:
        key_status = "present"
    else:
        key_status = "missing"
        errors.append(
            safe_error_dict(
                make_provider_error(
                    ERROR_MISSING_CONFIG,
                    "api_key_missing",
                    retryable=False,
                )
            )
        )

    dependency_available = True
    if spec.dependency:
        dependency_available = importlib.util.find_spec(spec.dependency) is not None
        if not dependency_available:
            errors.append(
                safe_error_dict(
                    make_provider_error(
                        ERROR_MISSING_CONFIG,
                        "dependency_missing",
                        retryable=False,
                    )
                )
            )

    if live and errors:
        warnings.append("live_preflight_skipped_config_invalid")

    return {
        "status": "ok" if not errors else "error",
        "provider": {"name": provider, "configured": True},
        "model": {
            "configured": model_name is not None,
            "name": model_name,
            "source": model_source,
        },
        "base_url": {"configured": base_url is not None},
        "api_key": {"status": key_status, "env": spec.key_env},
        "dependency": {"name": spec.dependency, "available": dependency_available},
        "live": {"enabled": live, "status": "not_requested" if not live else "pending"},
        "errors": errors,
        "warnings": warnings,
    }
