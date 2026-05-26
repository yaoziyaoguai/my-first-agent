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

    v0.11+ profile 支持：
    优先检查 FIRST_AGENT_PROVIDER_PROFILE → 从 YAML 加载 profile → 转 AgentProviderConfig。
    其次检查 MY_FIRST_AGENT_LLM_PROVIDER (legacy 兼容)。
    都没有则返回 FakeProvider。
    """
    from agent.provider.profiles import (
        load_provider_profiles,
        profile_to_agent_config,
        resolve_active_profile,
    )

    # 尝试 profile 路径
    profiles = load_provider_profiles()
    if profiles:
        resolved, method = resolve_active_profile(profiles)

        if resolved is not None and method != "legacy":
            # 通过 profile 解析得到 AgentProviderConfig
            if resolved.provider_type == "fake":
                from agent.provider.fake_provider import FakeProvider

                return FakeProvider()
            config = profile_to_agent_config(resolved)
            return build_model_provider(config)

    # legacy 路径：MY_FIRST_AGENT_LLM_PROVIDER 直接设置
    if os.environ.get(PROVIDER_ENV):
        config = load_agent_provider_config()
        return build_model_provider(config)

    # 默认：fake
    from agent.provider.fake_provider import FakeProvider

    return FakeProvider()
