"""Anthropic official SDK provider wrapper.

这是唯一允许 lazy import Anthropic SDK 的 provider boundary 之一。core.py、
Memory、Skill、SubAgent、dogfood runner 只能依赖 ModelProvider / provider
factory；不得在这些层直接构造 Anthropic client。
"""

from __future__ import annotations

from typing import Any

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import normalize_anthropic_response
from agent.provider.protocol import ProviderResponse
from agent.provider.streaming import ProviderStreamEvent


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
        # Provider adapter 内部实现细节：SDK 只在这里 lazy import，避免 import
        # agent/core.py 或测试时把全局架构重新绑回 Anthropic/Python SDK。
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

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        """把 Anthropic SDK stream 事件转换为 provider-neutral events。"""

        sequence = 0
        with self._client_or_create().messages.stream(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "content_block_start":
                    block_type = getattr(event.content_block, "type", None)
                    if block_type == "tool_use":
                        sequence += 1
                        yield ProviderStreamEvent.tool_request(sequence=sequence)
                elif event_type == "content_block_delta":
                    delta_text = getattr(event.delta, "text", None)
                    if delta_text:
                        sequence += 1
                        yield ProviderStreamEvent.delta(
                            sequence=sequence,
                            text_delta=delta_text,
                        )

            final_response = normalize_anthropic_response(
                stream.get_final_message(),
                raw_provider_name=self.provider_type,
            )
            for block in final_response.content:
                text = getattr(block, "text", None)
                if isinstance(text, str) and text:
                    sequence += 1
                    yield ProviderStreamEvent.delta(
                        sequence=sequence,
                        text_delta=text,
                    )
            sequence += 1
            yield ProviderStreamEvent.final(sequence=sequence)
