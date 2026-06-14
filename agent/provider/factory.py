"""Provider factory for AgentLoop."""

from __future__ import annotations

import os

from agent.provider.anthropic_http import AnthropicCompatibleProvider
from agent.provider.anthropic_native import AnthropicNativeProvider
from agent.provider.config import PROVIDER_ENV, AgentProviderConfig, load_agent_provider_config
from agent.provider.openai_http import OpenAICompatibleProvider
from agent.provider.openai_native import OpenAINativeProvider
from agent.provider.protocol import (
    ModelProvider,
    ProviderNotImplementedError,
)


def build_model_provider(config: AgentProviderConfig) -> ModelProvider | None:
    if config.provider_type == "anthropic_native":
        return AnthropicNativeProvider(config=config)
    if config.provider_type == "anthropic_compatible":
        return AnthropicCompatibleProvider(config=config)
    if config.provider_type == "openai_compatible":
        return OpenAICompatibleProvider(config=config)
    if config.provider_type == "openai_native":
        return OpenAINativeProvider(config=config)
    if config.provider_type == "fake":
        from agent.provider.fake_provider import FakeProvider

        return FakeProvider()
    raise ProviderNotImplementedError(
        f"{config.provider_type} provider is registered but not implemented"
    )


def build_model_provider_from_env() -> ModelProvider | None:
    """从环境变量构造 provider；未设置时默认返回 FakeProvider（安全本地路径）。

    中文学习边界——为什么默认必须是 FakeProvider 而不是 None：
    1. 项目默认是 fake/local safe path：用户不需要设置任何环境变量就能运行。
    2. diagnose_provider_config() 已默认 "fake"，provider factory 必须一致。
    3. 返回 None 会导致 call_model() → ProviderNotImplementedError，
       使整个 unified runtime flow 在无 env var 的默认场景下崩溃。
    4. FakeProvider 和 RealProvider 共享同一条 core.chat/loop.py 路径，
       这不是 fake/real 双 runtime。

    Config resolution precedence (v0.12+):
    1. config/config.yaml (推荐入口)
    2. FIRST_AGENT_PROVIDER_PROFILE + provider_profiles.yaml (legacy)
    3. MY_FIRST_AGENT_LLM_PROVIDER + 分散 env vars (legacy)
    4. default fake
    """
    from agent.provider.fake_provider import FakeProvider

    # 1. config/config.yaml (推荐入口)
    from agent.provider.simple_config import load_unified_provider_config

    unified = load_unified_provider_config()
    if unified.source in ("config_local", "config_yaml", "config_yaml_disabled"):
        if unified.config_error:
            # YAML 有错误 → safe fallback fake（不静默，错误会通过 diagnostics 报告）
            return FakeProvider()
        if unified.config.provider_type == "fake":
            return FakeProvider()
        return build_model_provider(unified.config)

    # 2. FIRST_AGENT_PROVIDER_PROFILE (legacy)
    from agent.provider.profiles import (
        load_provider_profiles,
        profile_to_agent_config,
        resolve_active_profile,
    )

    profiles = load_provider_profiles()
    if profiles:
        resolved, method = resolve_active_profile(profiles)

        if resolved is not None and method not in ("legacy", "default_fake"):
            if resolved.provider_type == "fake":
                return FakeProvider()
            config = profile_to_agent_config(resolved)
            return build_model_provider(config)

    # 3. MY_FIRST_AGENT_LLM_PROVIDER (legacy)
    if os.environ.get(PROVIDER_ENV):
        config = load_agent_provider_config()
        return build_model_provider(config)

    # 4. default fake
    return FakeProvider()
