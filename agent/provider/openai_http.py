"""OpenAI Chat Completions-compatible Kernel Provider。

通用路径保持单次非流式请求；只有精确受支持的 DeepSeek V4 Flash thinking 组合使用
有界 SSE，并且仍只返回一个完整 ``ModelResponse`` 给 Runtime。
"""

from __future__ import annotations

import codecs
import json
from collections.abc import Iterator
from contextlib import suppress
from typing import Any

import httpx

from agent.provider.config import (
    DEEPSEEK_API_BASE_URLS,
    DEEPSEEK_FLASH_MODEL_IDS,
    AgentProviderConfig,
)
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
    ProviderStreamCancelledError,
    ProviderStreamInterruptedError,
    ProviderTimeoutError,
    ProviderTransportError,
)
from agent.runtime.contracts import RESERVED_CONTROL_NAME, ContextPack, ModelResponse
from agent.transport_audit import TransportAttemptRecorder

DEFAULT_MAX_RESPONSE_BYTES = 4_000_000
_SSE_BYTES_PER_OUTPUT_TOKEN_BOUND = 512


class OpenAICompatibleProvider:
    """每次 ``generate`` 恰好执行一个有限时 HTTP request。"""

    def __init__(
        self,
        *,
        config: AgentProviderConfig,
        http_client: httpx.Client | None = None,
        max_response_bytes: int | None = None,
        attempt_recorder: TransportAttemptRecorder | None = None,
    ) -> None:
        if max_response_bytes is None:
            max_response_bytes = (
                max(
                    DEFAULT_MAX_RESPONSE_BYTES,
                    int(config.max_tokens) * _SSE_BYTES_PER_OUTPUT_TOKEN_BOUND,
                )
                if config.thinking_mode == "enabled"
                else DEFAULT_MAX_RESPONSE_BYTES
            )
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
            "accept": (
                "text/event-stream"
                if self._config.thinking_mode == "enabled"
                else "application/json"
            ),
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

    def generate(
        self, context: ContextPack, *, delta_observer=None  # noqa: ANN001
    ) -> ModelResponse:
        deepseek_thinking = self._config.thinking_mode == "enabled"
        # DeepSeek-flash 官方端点默认即思考模式：即使未显式 --thinking-mode
        # enabled，响应 message 也会携带 reasoning_content。family 识别后按
        # "预期有 reasoning" 处理（请求侧连续性回放 + 响应侧归一化放行），
        # 否则 normalize 以 unsupported_response_block fail closed（2026-10-09
        # 真实 dogfood 实测缺陷）。
        deepseek_family_reasoning = (
            self._config.model.strip() in DEEPSEEK_FLASH_MODEL_IDS
            and str(self._config.base_url).strip().rstrip("/")
            in {u.rstrip("/") for u in DEEPSEEK_API_BASE_URLS}
        )
        # W3（2026-10-12）：family 推断不得覆盖显式 disabled——显式 disabled
        # 会话按合同不发 reasoning（thinking={"type":"disabled"}），若按“预期
        # 有 reasoning”处理，normalize 会以 missing_reasoning_continuity 拒绝
        # 纯文本 JSON 响应。family 推断只在 thinking_mode is None 时生效。
        reasoning_expected = deepseek_thinking or (
            deepseek_family_reasoning and self._config.thinking_mode is None
        )
        provider_identity_digest = self._config.descriptor().identity_digest
        body: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "messages": context_to_openai_messages(
                context,
                provider_identity_digest=(
                    provider_identity_digest if reasoning_expected else None
                ),
                require_reasoning_continuity=reasoning_expected,
            ),
        }
        if self._config.thinking_mode is not None:
            body["thinking"] = {"type": self._config.thinking_mode}
        if deepseek_thinking:
            body.update(
                {
                    "reasoning_effort": self._config.reasoning_effort,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
            )
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
                if deepseek_thinking:
                    payload = _read_deepseek_stream(
                        response,
                        max_response_bytes=self._max_response_bytes,
                        delta_observer=delta_observer,
                    )
                else:
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

        if not deepseek_thinking:
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
            provider_identity_digest=(
                provider_identity_digest if reasoning_expected else None
            ),
        )


def _sse_data_events(
    response: httpx.Response,
    *,
    max_response_bytes: int,
) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    data_lines: list[str] = []
    size = 0
    try:
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_response_bytes:
                raise ProviderStreamInterruptedError()
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.removesuffix("\r")
                if not line:
                    if data_lines:
                        yield "\n".join(data_lines)
                        data_lines.clear()
                    continue
                if line.startswith(":"):
                    continue
                if line == "data":
                    data_lines.append("")
                elif line.startswith("data:"):
                    data_lines.append(line[5:].removeprefix(" "))
        buffer += decoder.decode(b"", final=True)
    except (UnicodeDecodeError, httpx.HTTPError):
        raise ProviderStreamInterruptedError() from None
    if buffer or data_lines:
        raise ProviderStreamInterruptedError()


def _stream_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderStreamInterruptedError()
    return value


def _read_deepseek_stream(
    response: httpx.Response,
    *,
    max_response_bytes: int,
    delta_observer,
) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    if content_type != "text/event-stream":
        raise ProviderStreamInterruptedError()

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_parts: dict[int, dict[str, str]] = {}
    finish_reason = None
    usage = None
    done = False

    def cancellation_requested() -> bool:
        callback = getattr(delta_observer, "cancellation_requested", None)
        if not callable(callback):
            return False
        with suppress(Exception):
            return bool(callback())
        return False

    try:
        for data in _sse_data_events(
            response,
            max_response_bytes=max_response_bytes,
        ):
            if cancellation_requested():
                raise ProviderStreamCancelledError()
            if done:
                raise ProviderStreamInterruptedError()
            if data == "[DONE]":
                done = True
                continue
            payload = _stream_object(json.loads(data))
            if set(payload).difference(
                {
                    "id",
                    "object",
                    "created",
                    "model",
                    "system_fingerprint",
                    "choices",
                    "usage",
                }
            ):
                raise ProviderStreamInterruptedError()
            if payload.get("model") not in {None, *DEEPSEEK_FLASH_MODEL_IDS}:
                raise ProviderStreamInterruptedError()
            choices = payload.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise ProviderStreamInterruptedError()
            choice = _stream_object(choices[0])
            if set(choice).difference({"index", "delta", "finish_reason", "logprobs"}):
                raise ProviderStreamInterruptedError()
            if choice.get("index") != 0:
                raise ProviderStreamInterruptedError()
            delta = _stream_object(choice.get("delta"))
            if set(delta).difference(
                {"role", "content", "reasoning_content", "tool_calls"}
            ):
                raise ProviderStreamInterruptedError()
            if delta.get("role") not in {None, "assistant"}:
                raise ProviderStreamInterruptedError()
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    raise ProviderStreamInterruptedError()
                text_parts.append(content)
                if content and delta_observer is not None:
                    with suppress(Exception):
                        delta_observer.on_text_delta(content)
            reasoning = delta.get("reasoning_content")
            if reasoning is not None:
                if not isinstance(reasoning, str):
                    raise ProviderStreamInterruptedError()
                reasoning_parts.append(reasoning)
            calls = delta.get("tool_calls", [])
            if not isinstance(calls, list):
                raise ProviderStreamInterruptedError()
            for raw_call in calls:
                call = _stream_object(raw_call)
                if set(call).difference({"index", "id", "type", "function"}):
                    raise ProviderStreamInterruptedError()
                index = call.get("index")
                if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                    raise ProviderStreamInterruptedError()
                current = tool_parts.get(index)
                function = _stream_object(call.get("function"))
                if set(function).difference({"name", "arguments"}):
                    raise ProviderStreamInterruptedError()
                arguments = function.get("arguments", "")
                if not isinstance(arguments, str):
                    raise ProviderStreamInterruptedError()
                if current is None:
                    call_id = call.get("id")
                    name = function.get("name")
                    if (
                        not isinstance(call_id, str)
                        or not call_id
                        or call.get("type") != "function"
                        or not isinstance(name, str)
                        or not name
                    ):
                        raise ProviderStreamInterruptedError()
                    current = {"id": call_id, "name": name, "arguments": ""}
                    tool_parts[index] = current
                elif any(key in call for key in ("id", "type")) or "name" in function:
                    raise ProviderStreamInterruptedError()
                current["arguments"] += arguments

            raw_finish_reason = choice.get("finish_reason")
            if raw_finish_reason is not None:
                if finish_reason is not None or not isinstance(raw_finish_reason, str):
                    raise ProviderStreamInterruptedError()
                finish_reason = raw_finish_reason
            if payload.get("usage") is not None:
                if finish_reason is None:
                    raise ProviderStreamInterruptedError()
                usage = _stream_object(payload["usage"])
            if cancellation_requested():
                raise ProviderStreamCancelledError()
    except ProviderStreamCancelledError:
        raise
    except (ValueError, TypeError):
        raise ProviderStreamInterruptedError() from None

    if (
        not done
        or finish_reason not in {"stop", "tool_calls", "length"}
        or not reasoning_parts
        or usage is None
        or bool(tool_parts) != (finish_reason == "tool_calls")
    ):
        raise ProviderStreamInterruptedError()
    if tool_parts and set(tool_parts) != set(range(len(tool_parts))):
        raise ProviderStreamInterruptedError()
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts),
        "reasoning_content": "".join(reasoning_parts),
    }
    if tool_parts:
        message["tool_calls"] = [
            {
                "id": tool_parts[index]["id"],
                "type": "function",
                "function": {
                    "name": tool_parts[index]["name"],
                    "arguments": tool_parts[index]["arguments"],
                },
            }
            for index in range(len(tool_parts))
        ]
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }


def _raise_for_status(status_code: int) -> None:
    if status_code in {401, 403}:
        raise ProviderAuthError(status_code=status_code)
    if status_code == 429 or status_code >= 500:
        raise ProviderHTTPRetryableError(status_code=status_code)
    if status_code >= 400:
        raise ProviderHTTPError(status_code=status_code)


__all__ = ["OpenAICompatibleProvider"]
