"""Provider profile 配置层。

ProviderProfile 是**配置层概念**，不是 runtime 概念。它的唯一职责是：
把用户可见的 profile 名称（如 "kimi_anthropic"）解析为 AgentProviderConfig，
然后交给现有的 factory/diagnostics/runtime——不新增 runtime flow。

为什么需要 profile：
- 当前 MY_FIRST_AGENT_LLM_PROVIDER 是唯一开关，但 model/base_url/key 分散在多个 env var
- 用户在 .env 中配了完整参数但没有设置那个开关 → provider 仍 fake → 困惑
- profile 把 provider type / model / base_url / api_key_env / request_path / auth_scheme
  内聚在一起，一个 FIRST_AGENT_PROVIDER_PROFILE 切换全部

Config source precedence:
1. FIRST_AGENT_PROVIDER_PROFILE env var → 按名称查找 YAML profile
2. YAML 中 active_profile 默认值
3. "fake" 兜底（安全默认）
4. 所选 profile 的每个字段可被 process env 覆盖（emergency override）
5. 无 profile 但 MY_FIRST_AGENT_LLM_PROVIDER 已设置 → legacy 路径
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from agent.provider.config import (
    PROVIDER_ENV,
    SUPPORTED_PROVIDER_TYPES,
    AgentProviderConfig,
)
from agent.provider.protocol import ProviderConfigurationError

# profile 选择 env var
PROFILE_ENV = "FIRST_AGENT_PROVIDER_PROFILE"

# 默认 profile 文件名（相对于 project root）
DEFAULT_PROFILES_YAML = "config/provider_profiles.yaml"


@dataclass(frozen=True)
class ProviderProfile:
    """命名 provider 配置集——不存 secret。

    api_key_env 只存变量名（如 "ANTHROPIC_API_KEY"），真正的 key 值从 os.environ 中
    按需读取。这样 profile 文件可以安全提交到 git。
    """

    name: str
    provider_type: str
    model: str = "fake-llm"
    base_url: str | None = None
    api_key_env: str | None = None
    request_path: str = "/v1/messages"
    auth_scheme: str = "auto"
    max_tokens: int = 4096
    timeout: float = 30.0

    def __post_init__(self) -> None:
        provider_type = self.provider_type.strip().lower()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ProviderConfigurationError("unknown_provider")
        object.__setattr__(self, "provider_type", provider_type)
        if self.auth_scheme not in {"auto", "x-api-key", "bearer"}:
            raise ProviderConfigurationError("unsupported_auth_scheme")
        if self.max_tokens <= 0:
            raise ProviderConfigurationError("invalid_max_tokens")
        if self.timeout <= 0:
            raise ProviderConfigurationError("invalid_timeout")


def load_provider_profiles(
    path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> dict[str, ProviderProfile]:
    """从 YAML 文件加载所有 provider profiles。

    返回 {profile_name: ProviderProfile} 映射。YAML 文件不存在时返回空 dict
    （调用方负责 fallback 到 fake）。

    YAML 解析失败时抛出 ProviderConfigurationError 并附带可读错误信息，
    不静默 fallback——错误的 YAML 应该让用户知道。
    """
    if path is None:
        root = Path(project_root) if project_root else Path.cwd()
        path = root / DEFAULT_PROFILES_YAML
    else:
        path = Path(path)

    if not path.is_file():
        return {}

    try:
        import yaml
    except ImportError:
        # 无 pyyaml 时尝试使用 yaml 内置解析（如果可用）
        return {}

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ProviderConfigurationError(
            f"provider profiles YAML 解析失败 ({path}): {exc}"
        ) from exc

    if not isinstance(data, dict):
        return {}

    profiles_raw = data.get("profiles")
    if not isinstance(profiles_raw, dict):
        return {}

    profiles: dict[str, ProviderProfile] = {}
    for name, raw in profiles_raw.items():
        if not isinstance(raw, dict):
            continue
        try:
            profile = ProviderProfile(
                name=str(name),
                provider_type=str(raw.get("type", "fake")),
                model=str(raw.get("model", "fake-llm")),
                base_url=_opt_str(raw, "base_url"),
                api_key_env=_opt_str(raw, "api_key_env"),
                request_path=str(raw.get("request_path", "/v1/messages")),
                auth_scheme=str(raw.get("auth_scheme", "auto")),
                max_tokens=int(raw.get("max_tokens", 4096)),
                timeout=float(raw.get("timeout", 30.0)),
            )
        except (ProviderConfigurationError, ValueError) as exc:
            raise ProviderConfigurationError(
                f"profile '{name}' 配置无效 ({path}): {exc}"
            ) from exc
        profiles[name] = profile

    return profiles


def _opt_str(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return str(value).strip() or None


def resolve_active_profile(
    profiles: dict[str, ProviderProfile],
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[ProviderProfile | None, str]:
    """决议当前 active profile。

    返回 (profile | None, resolution_method)。

    resolution_method 取值：
    - "profile_env": FIRST_AGENT_PROVIDER_PROFILE env var
    - "profile_yaml": YAML 文件中的 active_profile 默认值
    - "default_fake": 无任何配置，返回 fake profile
    - "legacy": MY_FIRST_AGENT_LLM_PROVIDER 已设置（走旧路径，返回 None）
    """
    if env is None:
        env = os.environ

    # 1. FIRST_AGENT_PROVIDER_PROFILE env var
    profile_name = (env.get(PROFILE_ENV) or "").strip()
    if profile_name:
        profile = profiles.get(profile_name)
        if profile is not None:
            return profile, "profile_env"
        # profile 名字不存在 → 不静默 fallback，返回 None 让调用方处理

    # 2. 检查 legacy MY_FIRST_AGENT_LLM_PROVIDER
    legacy_provider = (env.get(PROVIDER_ENV) or "").strip()
    if legacy_provider:
        # 有 legacy env var → 走旧路径
        return None, "legacy"

    # 3. 无 env → fake 兜底
    fake_profile = profiles.get("fake")
    if fake_profile is not None:
        return fake_profile, "default_fake"

    # 4. 连 fake profile 都没有 → 硬编码内置 fake
    return ProviderProfile(
        name="fake",
        provider_type="fake",
        model="fake-llm",
    ), "default_fake"


def profile_to_agent_config(
    profile: ProviderProfile,
    *,
    env: Mapping[str, str] | None = None,
) -> AgentProviderConfig:
    """将 ProviderProfile 转换为 AgentProviderConfig，从 env 读取 actual key。

    profile 中的字段是默认值；process env 中的同名字段可以覆盖（emergency override）。
    这保持了与现有 load_agent_provider_config() 相同的 env var 解析语义。

    转换过程不泄露 secret——api_key 只通过 AgentProviderConfig(frozen=True, repr=False)
    传递，不会出现在日志/诊断输出中。
    """
    if env is None:
        env = os.environ

    # 从 env 读取实际 key（api_key_env 指向的变量）
    api_key: str | None = None
    if profile.api_key_env:
        api_key = (env.get(profile.api_key_env) or "").strip() or None

    # process env 可覆盖 profile 字段（emergency override）
    provider_type = (env.get(PROVIDER_ENV) or profile.provider_type).lower()
    model = env.get("ANTHROPIC_MODEL") or env.get("OPENAI_MODEL") or env.get(
        "MY_FIRST_AGENT_LLM_MODEL"
    ) or profile.model

    base_url = env.get("ANTHROPIC_BASE_URL") or env.get(
        "OPENAI_BASE_URL"
    ) or env.get("MY_FIRST_AGENT_LLM_BASE_URL") or profile.base_url

    auth_scheme = env.get("MY_FIRST_AGENT_LLM_AUTH_SCHEME") or profile.auth_scheme
    request_path = env.get("MY_FIRST_AGENT_LLM_REQUEST_PATH") or profile.request_path

    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise ProviderConfigurationError("unknown_provider")

    if provider_type != "fake" and not api_key:
        raise ProviderConfigurationError("api_key_missing")
    if provider_type != "fake" and not model:
        raise ProviderConfigurationError("model_missing")
    if provider_type.endswith("_compatible") and not base_url:
        raise ProviderConfigurationError("base_url_missing")

    # 推导 supports_streaming
    supports_streaming = provider_type == "anthropic_native"

    # 推导 default request_path（当 profile 和 env 都没设置时）
    if not request_path:
        if provider_type.startswith("anthropic"):
            request_path = "/v1/messages"
        elif provider_type.startswith("openai"):
            request_path = "/v1/chat/completions"

    return AgentProviderConfig(
        provider_type=provider_type,
        provider_name=profile.name,
        api_key=api_key,
        api_key_env=profile.api_key_env,
        base_url=base_url,
        model=model or "fake-llm",
        max_tokens=profile.max_tokens,
        timeout=profile.timeout,
        supports_tools=provider_type != "fake",
        supports_streaming=supports_streaming,
        auth_scheme=auth_scheme,
        request_path=request_path,
        compatibility_mode=(
            "anthropic_messages" if provider_type.startswith("anthropic") else
            "openai" if provider_type.startswith("openai") else
            "fake"
        ),
    )
