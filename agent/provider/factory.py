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
    if not os.environ.get(PROVIDER_ENV):
        return None
    config = load_agent_provider_config()
    return build_model_provider(config)
