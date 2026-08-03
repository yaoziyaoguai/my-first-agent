"""Anthropic Messages-compatible 的非流式 Kernel Provider。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import (
    context_to_anthropic_messages,
    context_tools_to_anthropic,
    normalize_anthropic_response,
    trusted_system_projection,
)
from agent.provider.protocol import (
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderHTTPError,
    ProviderHTTPRetryableError,
    ProviderProtocolError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from agent.runtime.contracts import ContextPack, ModelResponse

DEFAULT_MAX_RESPONSE_BYTES = 4_000_000


class AnthropicCompatibleProvider:
    """每次 ``generate`` 恰好执行一个有限时 HTTP request。"""

    def __init__(
        self,
        *,
        config: AgentProviderConfig,
        http_client: httpx.Client | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if config.provider_type != "anthropic_compatible" or max_response_bytes < 1:
            raise ProviderConfigurationError()
        self._config = config
        self._http_client = http_client
        self._max_response_bytes = max_response_bytes

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=self._config.timeout,
                follow_redirects=False,
                trust_env=False,
            )
        return self._http_client

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        credential = self._config.credential
        if credential is None:
            return headers
        if self._config.auth_scheme == "x-api-key":
            headers["x-api-key"] = credential
            headers["anthropic-version"] = "2023-06-01"
        elif self._config.auth_scheme == "bearer":
            headers["authorization"] = f"Bearer {credential}"
        else:
            raise ProviderConfigurationError()
        return headers

    def generate(self, context: ContextPack) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            # 已受理回执与 context.system 共用同一 trusted system 投影,
            # 绝不回放进 messages(与 OpenAI 适配器语义对称)。
            "system": trusted_system_projection(context),
            "messages": context_to_anthropic_messages(context),
        }
        tools = context_tools_to_anthropic(context)
        if tools:
            body["tools"] = tools

        try:
            with self._client().stream(
                "POST",
                self._config.endpoint,
                headers=self._headers(),
                json=body,
                timeout=self._config.timeout,
            ) as response:
                _raise_for_status(response.status_code)
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self._max_response_bytes:
                        raise ProviderProtocolError("response_too_large")
                    chunks.append(chunk)
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.TransportError:
            raise ProviderTransportError() from None
        except httpx.HTTPError:
            raise ProviderTransportError() from None

        try:
            payload = json.loads(b"".join(chunks))
        except ValueError:
            raise ProviderProtocolError("malformed_response") from None
        return normalize_anthropic_response(payload)


def _raise_for_status(status_code: int) -> None:
    if status_code in {401, 403}:
        raise ProviderAuthError(status_code=status_code)
    if status_code == 429 or status_code >= 500:
        raise ProviderHTTPRetryableError(status_code=status_code)
    if status_code >= 400:
        raise ProviderHTTPError(status_code=status_code)


__all__ = ["AnthropicCompatibleProvider"]
