"""Anthropic official SDK provider wrapper.

本轮默认 AgentLoop 仍保留 core.py 的 legacy streaming path；这个 wrapper 只为
provider-neutral contract 和后续迁移提供 non-streaming create() 边界。
"""

from __future__ import annotations

from typing import Any

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import normalize_anthropic_response
from agent.provider.protocol import ProviderResponse


class AnthropicNativeProvider:
    provider_type = "anthropic_native"
    supports_tools = True
    supports_streaming = True

    def __init__(self, *, config: AgentProviderConfig, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        from anthropic import Anthropic

        kwargs: dict[str, Any] = {"api_key": self.config.api_key}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        self._client = Anthropic(**kwargs)
        return self._client

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ProviderResponse:
        response = self._client_or_create().messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        return normalize_anthropic_response(
            response,
            raw_provider_name=self.provider_type,
        )
