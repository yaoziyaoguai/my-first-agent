"""只组装 Kernel v1 支持的三个 Provider。"""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.protocol import ModelProvider, ProviderConfigurationError
from agent.runtime.contracts import ModelResponse


def build_model_provider(
    config: AgentProviderConfig,
    *,
    http_client: httpx.Client | None = None,
    scripted_responses: Iterable[ModelResponse | Exception] | None = None,
) -> ModelProvider:
    if config.provider_type == "fake":
        from agent.provider.fake_provider import FakeProvider

        return FakeProvider(scripted_responses=scripted_responses)
    if scripted_responses is not None:
        raise ProviderConfigurationError()
    if config.provider_type == "anthropic_compatible":
        from agent.provider.anthropic_http import AnthropicCompatibleProvider

        return AnthropicCompatibleProvider(config=config, http_client=http_client)
    if config.provider_type == "openai_compatible":
        from agent.provider.openai_http import OpenAICompatibleProvider

        return OpenAICompatibleProvider(config=config, http_client=http_client)
    raise ProviderConfigurationError()


__all__ = ["build_model_provider"]
