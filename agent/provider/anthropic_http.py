"""HTTP adapter for Anthropic-compatible endpoints."""

from __future__ import annotations

from typing import Any

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import normalize_anthropic_response
from agent.provider.protocol import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderResponse,
    ProviderResponseError,
    ProviderTimeoutError,
)
from agent.provider.streaming import ProviderStreamEvent


class AnthropicCompatibleProvider:
    provider_type = "anthropic_compatible"
    supports_tools = True
    supports_streaming = False

    def __init__(
        self,
        *,
        config: AgentProviderConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._http_client = http_client

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self.config.timeout)
        return self._http_client

    def _url(self) -> str:
        base_url = (self.config.base_url or "").rstrip("/")
        request_path = (self.config.request_path or "").strip()
        if not base_url:
            raise ProviderResponseError("base_url_missing")
        if not request_path:
            return base_url
        return f"{base_url}/{request_path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise ProviderAuthError("api_key_missing")
        scheme = self.config.auth_scheme
        # 对于 Anthropic-compatible，auto 默认为 x-api-key（Anthropic 官方 API 标准）。
        # bearer 是 OpenAI 惯例，不是 Anthropic 惯例。
        if scheme == "auto":
            scheme = "x-api-key"
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
        }
        if scheme == "bearer":
            headers["authorization"] = f"Bearer {self.config.api_key}"
        elif scheme == "x-api-key":
            headers["x-api-key"] = self.config.api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            raise ProviderAuthError("unsupported_auth_scheme")
        return headers

    def create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ProviderResponse:
        if tools and not self.config.supports_tools:
            raise ProviderCapabilityError("tools_not_supported")
        body: dict[str, Any] = {
            "model": model or self.config.model,
            "max_tokens": max_tokens or self.config.max_tokens,
            "system": system,
            "messages": messages,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = tools
        try:
            response = self._client().post(
                self._url(),
                headers=self._headers(),
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError("http_error") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthError(
                f"http_status:{response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"http_status:{response.status_code}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError("malformed_json") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            raise ProviderResponseError("malformed_response")
        return normalize_anthropic_response(
            payload,
            raw_provider_name=self.provider_type,
        )

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        """兼容 provider streaming contract；HTTP adapter 先用 create() 聚合。"""

        response = self.create(
            system=system,
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        sequence = 0
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                sequence += 1
                yield ProviderStreamEvent.delta(sequence=sequence, text_delta=text)
            if getattr(block, "type", None) == "tool_use":
                sequence += 1
                yield ProviderStreamEvent.tool_request(sequence=sequence)
        sequence += 1
        yield ProviderStreamEvent.final(sequence=sequence)
