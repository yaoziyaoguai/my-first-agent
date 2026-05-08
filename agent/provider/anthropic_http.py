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
        if scheme == "auto":
            scheme = "bearer"
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
    ) -> ProviderResponse:
        if tools and not self.config.supports_tools:
            raise ProviderCapabilityError("tools_not_supported")
        body: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system,
            "messages": messages,
        }
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
            raise ProviderAuthError(f"http_status:{response.status_code}", status_code=response.status_code)
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
