"""OpenAI Chat Completions-compatible 的非流式 Kernel Provider。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import (
    context_to_openai_messages,
    context_tools_to_openai,
    normalize_openai_response,
    trusted_completion_goal_binding,
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
from agent.runtime.contracts import RESERVED_CONTROL_NAME, ContextPack, ModelResponse
from agent.transport_audit import TransportAttemptRecorder

DEFAULT_MAX_RESPONSE_BYTES = 4_000_000


class OpenAICompatibleProvider:
    """每次 ``generate`` 恰好执行一个有限时 HTTP request。"""

    def __init__(
        self,
        *,
        config: AgentProviderConfig,
        http_client: httpx.Client | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        attempt_recorder: TransportAttemptRecorder | None = None,
    ) -> None:
        if config.provider_type != "openai_compatible" or max_response_bytes < 1:
            raise ProviderConfigurationError()
        self._config = config
        self._http_client = http_client
        self._max_response_bytes = max_response_bytes
        self._attempt_recorder = attempt_recorder

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
        if self._config.auth_scheme == "bearer":
            headers["authorization"] = f"Bearer {credential}"
        elif self._config.auth_scheme == "x-api-key":
            headers["x-api-key"] = credential
        else:
            raise ProviderConfigurationError()
        return headers

    def generate(self, context: ContextPack) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "messages": context_to_openai_messages(context),
        }
        if self._config.thinking_mode is not None:
            body["thinking"] = {"type": self._config.thinking_mode}
        tools = context_tools_to_openai(context, strict=self._config.strict_tools)
        if tools:
            body["tools"] = tools
        if self._config.strict_tools:
            # Agent control 优先确定性；strict schema 负责形状，temperature=0。
            # bootstrap 轮精确选择保留 control，防止只读产品工具抢在 Goal 前执行；
            # Goal 建立后仍允许模型在产品工具与 closed control 间选择。
            body["temperature"] = 0
            if context.control_schema is not None:
                body["tool_choice"] = (
                    {
                        "type": "function",
                        "function": {"name": RESERVED_CONTROL_NAME},
                    }
                    if context.goal_bootstrap is not None
                    else "required"
                )

        try:
            if self._attempt_recorder is not None:
                self._attempt_recorder("model", self._config.base_url)
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
        return normalize_openai_response(
            payload,
            trusted_completion_binding=(
                None
                if self._config.strict_tools
                else trusted_completion_goal_binding(context)
            ),
        )


def _raise_for_status(status_code: int) -> None:
    if status_code in {401, 403}:
        raise ProviderAuthError(status_code=status_code)
    if status_code == 429 or status_code >= 500:
        raise ProviderHTTPRetryableError(status_code=status_code)
    if status_code >= 400:
        raise ProviderHTTPError(status_code=status_code)


__all__ = ["OpenAICompatibleProvider"]
