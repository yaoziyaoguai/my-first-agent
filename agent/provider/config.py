"""AgentLoop provider configuration loaded from process environment only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from agent.provider.protocol import ProviderConfigurationError


PROVIDER_ENV = "MY_FIRST_AGENT_LLM_PROVIDER"
PROVIDER_NAME_ENV = "MY_FIRST_AGENT_LLM_PROVIDER_NAME"
GENERIC_MODEL_ENV = "MY_FIRST_AGENT_LLM_MODEL"
GENERIC_BASE_URL_ENV = "MY_FIRST_AGENT_LLM_BASE_URL"
AUTH_SCHEME_ENV = "MY_FIRST_AGENT_LLM_AUTH_SCHEME"
REQUEST_PATH_ENV = "MY_FIRST_AGENT_LLM_REQUEST_PATH"
COMPATIBILITY_MODE_ENV = "MY_FIRST_AGENT_LLM_COMPATIBILITY_MODE"
MAX_TOKENS_ENV = "MY_FIRST_AGENT_LLM_MAX_TOKENS"
TIMEOUT_ENV = "MY_FIRST_AGENT_LLM_TIMEOUT"

SUPPORTED_PROVIDER_TYPES = {
    "anthropic_native",
    "anthropic_compatible",
    "openai_native",
    "openai_compatible",
    "fake",
}


@dataclass(frozen=True)
class AgentProviderConfig:
    provider_type: str
    provider_name: str | None = None
    api_key: str | None = field(default=None, repr=False, compare=False)
    api_key_env: str | None = None
    base_url: str | None = None
    model: str | None = None
    max_tokens: int = 4096
    timeout: float = 30.0
    supports_tools: bool = True
    supports_streaming: bool = False
    auth_scheme: str = "auto"
    request_path: str = "/v1/messages"
    compatibility_mode: str = "anthropic_messages"

    def __post_init__(self) -> None:
        provider_type = self.provider_type.strip().lower()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ProviderConfigurationError("unknown_provider")
        object.__setattr__(self, "provider_type", provider_type)
        provider_name = (self.provider_name or provider_type).strip()
        if not provider_name:
            provider_name = provider_type
        object.__setattr__(self, "provider_name", provider_name)
        if self.auth_scheme not in {"auto", "x-api-key", "bearer"}:
            raise ProviderConfigurationError("unsupported_auth_scheme")
        if self.max_tokens <= 0:
            raise ProviderConfigurationError("invalid_max_tokens")
        if self.timeout <= 0:
            raise ProviderConfigurationError("invalid_timeout")

    def redacted_summary(self) -> dict[str, object]:
        """Return diagnostic config without exposing secret values."""

        return {
            "provider_type": self.provider_type,
            "provider_name": self.provider_name,
            "api_key": "SET" if self.api_key else "empty",
            "api_key_env": self.api_key_env,
            "base_url": "SET" if self.base_url else "empty",
            "model": self.model,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "supports_tools": self.supports_tools,
            "supports_streaming": self.supports_streaming,
            "auth_scheme": self.auth_scheme,
            "request_path": self.request_path,
            "compatibility_mode": self.compatibility_mode,
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


def _int_env(env: Mapping[str, str], name: str, default: int) -> int:
    value = _env_get(env, name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ProviderConfigurationError("invalid_max_tokens") from exc
    return parsed


def _float_env(env: Mapping[str, str], name: str, default: float) -> float:
    value = _env_get(env, name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ProviderConfigurationError("invalid_timeout") from exc
    return parsed


def load_agent_provider_config(
    provider_type: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> AgentProviderConfig:
    """Load provider config from environment without reading .env files."""

    if env is None:
        env = os.environ
    selected = (provider_type or _env_get(env, PROVIDER_ENV) or "anthropic_native").lower()
    if selected not in SUPPORTED_PROVIDER_TYPES:
        raise ProviderConfigurationError("unknown_provider")

    if selected in {"anthropic_native", "anthropic_compatible"}:
        key, key_env = _first_env(env, ("ANTHROPIC_API_KEY",))
        model, _model_env = _first_env(
            env,
            ("ANTHROPIC_MODEL", "MODEL_NAME", GENERIC_MODEL_ENV),
        )
        base_url, _base_url_env = _first_env(
            env,
            ("ANTHROPIC_BASE_URL", GENERIC_BASE_URL_ENV),
        )
        supports_streaming = selected == "anthropic_native"
        auth_scheme = _env_get(env, AUTH_SCHEME_ENV) or "auto"
        request_path = _env_get(env, REQUEST_PATH_ENV) or "/v1/messages"
        compatibility_mode = _env_get(env, COMPATIBILITY_MODE_ENV) or "anthropic_messages"
        requires_base_url = selected == "anthropic_compatible"
    elif selected in {"openai_native", "openai_compatible"}:
        key, key_env = _first_env(env, ("OPENAI_API_KEY",))
        model, _model_env = _first_env(env, ("OPENAI_MODEL", GENERIC_MODEL_ENV))
        base_url, _base_url_env = _first_env(env, ("OPENAI_BASE_URL", GENERIC_BASE_URL_ENV))
        supports_streaming = False
        auth_scheme = _env_get(env, AUTH_SCHEME_ENV) or "bearer"
        request_path = _env_get(env, REQUEST_PATH_ENV) or "/v1/chat/completions"
        compatibility_mode = _env_get(env, COMPATIBILITY_MODE_ENV) or "openai"
        requires_base_url = selected == "openai_compatible"
    else:
        key = None
        key_env = None
        model, _model_env = _first_env(env, ("LLM_FAKE_MODEL", GENERIC_MODEL_ENV))
        base_url = None
        supports_streaming = False
        auth_scheme = "auto"
        request_path = ""
        compatibility_mode = "fake"
        requires_base_url = False

    if selected != "fake" and not key:
        raise ProviderConfigurationError("api_key_missing")
    if selected != "fake" and not model:
        raise ProviderConfigurationError("model_missing")
    if requires_base_url and not base_url:
        raise ProviderConfigurationError("base_url_missing")

    return AgentProviderConfig(
        provider_type=selected,
        provider_name=_env_get(env, PROVIDER_NAME_ENV) or selected,
        api_key=key,
        api_key_env=key_env,
        base_url=base_url,
        model=model or "fake-llm",
        max_tokens=_int_env(env, MAX_TOKENS_ENV, 4096),
        timeout=_float_env(env, TIMEOUT_ENV, 30.0),
        supports_tools=selected != "fake",
        supports_streaming=supports_streaming,
        auth_scheme=auth_scheme,
        request_path=request_path,
        compatibility_mode=compatibility_mode,
    )
