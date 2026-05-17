"""OpenAI native (official API) provider adapter.

本轮实现 minimal Chat Completions adapter，复用 openai_compatible 的
消息/工具转换和响应归一化。不做 Responses API，不做 streaming。

与 openai_compatible 的区别：
- base_url 默认 https://api.openai.com/v1（无需用户配置）
- 同样使用 OPENAI_API_KEY / OPENAI_MODEL
- 同样使用 bearer auth
"""

from __future__ import annotations

from typing import Any

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.openai_http import (
    convert_messages_to_openai,
    convert_tools_to_openai,
    normalize_openai_response,
)
from agent.provider.streaming import ProviderStreamEvent
from agent.provider.protocol import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderResponse,
    ProviderResponseError,
    ProviderTimeoutError,
)

_DEFAULT_BASE_URL = "https://api.openai.com"


class OpenAINativeProvider:
    """OpenAI 官方 API Chat Completions provider。

    不依赖 openai SDK，直接用 httpx + HTTP，复用 openai_compatible 的
    转换/归一化逻辑。当前仅支持 non-streaming Chat Completions，
    Responses API 明确不在本轮范围内。
    """

    provider_type = "openai_native"
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
        base_url = (self.config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        request_path = (self.config.request_path or "chat/completions").strip()
        if not request_path:
            return base_url
        return f"{base_url}/{request_path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "content-type": "application/json",
            "accept": "application/json",
        }
        if self.config.api_key:
            headers["authorization"] = f"Bearer {self.config.api_key}"
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

        openai_messages = convert_messages_to_openai(system, messages)
        body: dict[str, Any] = {
            "model": model or self.config.model,
            "max_tokens": max_tokens or self.config.max_tokens,
            "messages": openai_messages,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if tools:
            body["tools"] = convert_tools_to_openai(tools)

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
        if not isinstance(payload, dict):
            raise ProviderResponseError("malformed_response")
        return normalize_openai_response(
            payload,
            raw_provider_name=self.provider_type,
        )

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        """兼容 provider streaming contract；native OpenAI 先用 create() 聚合。"""

        response = self.create(system=system, messages=messages, tools=tools)
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
