"""Anthropic Messages-compatible 的非流式 Kernel Provider。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import (
    context_to_anthropic_messages,
    context_tools_to_anthropic,
    normalize_anthropic_response,
    trusted_completion_goal_binding,
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
from agent.transport_audit import TransportAttemptRecorder

DEFAULT_MAX_RESPONSE_BYTES = 4_000_000


class AnthropicCompatibleProvider:
    """每次 ``generate`` 恰好执行一个有限时 HTTP request。"""

    def __init__(
        self,
        *,
        config: AgentProviderConfig,
        http_client: httpx.Client | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        attempt_recorder: TransportAttemptRecorder | None = None,
    ) -> None:
        if config.provider_type != "anthropic_compatible" or max_response_bytes < 1:
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
        if self._config.auth_scheme == "x-api-key":
            headers["x-api-key"] = credential
            headers["anthropic-version"] = "2023-06-01"
        elif self._config.auth_scheme == "bearer":
            headers["authorization"] = f"Bearer {credential}"
        else:
            raise ProviderConfigurationError()
        return headers

    def generate(
        self,
        context: ContextPack,
        *,
        delta_observer=None,
    ) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            # 已受理回执与 context.system 共用同一 trusted system 投影,
            # 绝不回放进 messages(与 OpenAI 适配器语义对称)。
            "system": trusted_system_projection(context),
            "messages": context_to_anthropic_messages(context),
            # r19 小步 3:请求 SSE 流。增量文本经窄观察合同外发(advisory);
            # 最终响应仍由流结束后的完整重建走唯一 normalize 路径。
            "stream": True,
        }
        tools = context_tools_to_anthropic(context)
        if tools:
            body["tools"] = tools
        if self._config.thinking_mode == "disabled":
            body["thinking"] = {"type": "disabled"}

        # 单次发送,按响应 content-type 分流:SSE 流走事件重建(增量经窄观察
        # 合同实时外发);非 event-stream(部分兼容端点/错误路径回整包 JSON)
        # 走既有整包解析,不发现成事件。
        self._non_sse_body = b""
        sse_events = self._iter_sse_events(body)
        payload = _rebuild_message_payload(sse_events, delta_observer)
        if payload is None:
            try:
                fallback = json.loads(self._non_sse_body)
            except ValueError:
                raise ProviderProtocolError("malformed_response") from None
            if not isinstance(fallback, dict):
                raise ProviderProtocolError("malformed_response")
            payload = fallback
        return normalize_anthropic_response(
            payload,
            trusted_completion_binding=trusted_completion_goal_binding(context),
        )

    def _iter_sse_events(self, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """边读边产出 SSE 事件:增量在到达时即对消费方可见(实时转发的前提)。

        断流/超时按既有 transport 语义失败——已产出的增量保持 advisory,
        不铸造最终响应。非 SSE 响应:读整包存 ``_non_sse_body`` 并结束迭代。
        """
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
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("text/event-stream"):
                    size = 0
                    parts: list[bytes] = []
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise ProviderProtocolError("response_too_large")
                        parts.append(chunk)
                    self._non_sse_body = b"".join(parts)
                    yield {"type": "_fa_non_sse"}
                    return
                buffered = b""
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self._max_response_bytes:
                        raise ProviderProtocolError("response_too_large")
                    buffered += chunk
                    while b"\n" in buffered:
                        raw_line, buffered = buffered.split(b"\n", 1)
                        event = _parse_sse_data_line(raw_line)
                        if event is not None:
                            yield event
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.TransportError:
            raise ProviderTransportError() from None
        except httpx.HTTPError:
            raise ProviderTransportError() from None
        tail = _parse_sse_data_line(buffered)
        if tail is not None:
            yield tail


def _raise_for_status(status_code: int) -> None:
    if status_code in {401, 403}:
        raise ProviderAuthError(status_code=status_code)
    if status_code == 429 or status_code >= 500:
        raise ProviderHTTPRetryableError(status_code=status_code)
    if status_code >= 400:
        raise ProviderHTTPError(status_code=status_code)


def _parse_sse_data_line(raw_line: bytes) -> dict[str, Any] | None:
    """解析一行 SSE `data:` 载荷;非 data 行与 [DONE] 返回 None,坏 JSON fail closed。"""
    line = raw_line.decode("utf-8", errors="strict").strip()
    if not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if not data or data == "[DONE]":
        return None
    try:
        event = json.loads(data)
    except ValueError:
        raise ProviderProtocolError("malformed_response") from None
    if not isinstance(event, dict):
        raise ProviderProtocolError("malformed_response")
    return event


def _rebuild_message_payload(
    events: Iterator[dict[str, Any]],
    delta_observer: Any = None,
) -> dict[str, Any] | None:
    """从 SSE 事件流重建完整 message payload;text 增量在到达时转发 observer。

    权威不变式:重建只产生与端点最终消息等价的 payload,随后走唯一
    normalize 路径;text 增量是 advisory(丢失/重复不改变最终响应);
    不完整 tool_use 的 partial JSON 只在流正常收束后解析,绝不中途执行。
    返回 None 表示响应不是 SSE(内部哨兵事件),由调用方走整包 JSON 路径。
    """
    usage: dict[str, Any] = {}
    stop_reason: str | None = None
    blocks: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    saw_message_stop = False
    for event in events:
        etype = event.get("type")
        if etype == "_fa_non_sse":
            return None
        if etype == "message_start":
            message = event.get("message")
            if isinstance(message, dict) and isinstance(message.get("usage"), dict):
                usage.update(message["usage"])
        elif etype == "content_block_start":
            index = event.get("index")
            block = event.get("content_block")
            if not isinstance(index, int) or not isinstance(block, dict):
                raise ProviderProtocolError("malformed_response")
            blocks[index] = dict(block)
            order.append(index)
        elif etype == "content_block_delta":
            index = event.get("index")
            delta = event.get("delta")
            block = blocks.get(index) if isinstance(index, int) else None
            if block is None or not isinstance(delta, dict):
                raise ProviderProtocolError("malformed_response")
            dtype = delta.get("type")
            if dtype == "text_delta":
                text = delta.get("text")
                if not isinstance(text, str):
                    raise ProviderProtocolError("malformed_response")
                block["text"] = block.get("text", "") + text
                if delta_observer is not None and text:
                    delta_observer.on_text_delta(text)
            elif dtype == "input_json_delta":
                partial = delta.get("partial_json")
                if not isinstance(partial, str):
                    raise ProviderProtocolError("malformed_response")
                block["input_json"] = block.get("input_json", "") + partial
            elif dtype == "thinking_delta":
                thinking = delta.get("thinking")
                if not isinstance(thinking, str):
                    raise ProviderProtocolError("malformed_response")
                block["thinking"] = block.get("thinking", "") + thinking
        elif etype == "message_delta":
            message_delta = event.get("delta")
            if isinstance(message_delta, dict) and isinstance(
                message_delta.get("stop_reason"), str | None
            ):
                stop_reason = message_delta.get("stop_reason")
            if isinstance(event.get("usage"), dict):
                usage.update(event["usage"])
        elif etype == "message_stop":
            saw_message_stop = True
        elif etype == "error":
            raise ProviderProtocolError("malformed_response")
    if not saw_message_stop or not order:
        raise ProviderProtocolError("malformed_response")
    content: list[dict[str, Any]] = []
    for index in order:
        block = blocks[index]
        if block.get("type") == "tool_use":
            raw = block.get("input_json", "")
            try:
                parsed_input = json.loads(raw) if raw.strip() else {}
            except ValueError:
                raise ProviderProtocolError("malformed_tool_call") from None
            rebuilt = {
                "type": "tool_use",
                "id": block.get("id"),
                "name": block.get("name"),
                "input": parsed_input,
            }
            content.append(rebuilt)
        else:
            content.append(block)
    return {"content": content, "stop_reason": stop_reason, "usage": usage}


__all__ = ["AnthropicCompatibleProvider"]
