"""OpenAI-compatible HTTP adapter for AgentLoop.

架构边界
--------
本模块实现 openai_compatible provider：通过 HTTP 调用 OpenAI Chat Completions
兼容端点（DashScope OpenAI-compatible / OpenRouter / vLLM / LM Studio /
Ollama-compatible / 企业代理）。

注意：DeepSeek 当前推荐使用 anthropic_compatible 路径
（agent/provider/anthropic_http.py），而非 openai_compatible。

与 Anthropic adapter 的关系：
- 两者互不依赖，都实现 ModelProvider.create()
- 两者共享 agent/provider/normalize.py 的 ProviderResponse / ToolUseBlock 类型
- openai_native 保持 registered but not implemented，不在此处实现

消息转换
--------
AgentLoop 内部消息格式是 Anthropic-style（build_execution_messages → _project_to_api），
OpenAI Chat Completions 使用不同的消息和工具格式。本模块负责：
1. _convert_messages: Anthropic-style dict → OpenAI-style dict
2. _convert_tools: Anthropic input_schema → OpenAI function.parameters
3. normalize_openai_response: OpenAI response → ProviderResponse

为什么不做 streaming
------------------
本轮 openai_compatible 只实现 non-streaming create()。原因：
- streaming 需要 SSE 解析，引入额外复杂度
- AgentLoop 的 _call_model 已通过 supports_streaming=False 判断走 non-streaming 路径
- 后续可以单独实现 streaming 而不破坏现有路径
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent.provider.config import AgentProviderConfig
from agent.provider.protocol import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderResponse,
    ProviderResponseError,
    ProviderTextBlock,
    ProviderTimeoutError,
    ToolUseBlock,
)

# ============================================================
# OpenAI 消息格式转换：Anthropic-style dict → OpenAI-style dict
# ============================================================
# 这里的转换不是为了"全面模拟 OpenAI SDK"，而是为了让 AgentLoop 的
# Anthropic 格式 internal messages 能无损投影到 OpenAI Chat Completions API。
# 只处理本轮 E2E 中出现的 block type（text / tool_use / tool_result），
# 不处理 thinking / image / file 等高级类型。


def _flatten_content(content: Any) -> str:
    """把 Anthropic 格式的 user/assistant content 压成纯文本。

    Anthropic content 可能是 string 或 list[dict]。
    这里只提取 type="text" 的块，其他类型跳过。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _extract_tool_calls_from_assistant(content: Any) -> list[dict[str, Any]]:
    """从 Anthropic assistant content 中提取 tool_use 块，转为 OpenAI tool_calls。

    OpenAI tool_calls 格式：
    [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}]
    """
    if not isinstance(content, list):
        return []
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_input = block.get("input", {})
            arguments = (
                json.dumps(tool_input, ensure_ascii=False)
                if isinstance(tool_input, dict)
                else "{}"
            )
            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": arguments,
                },
            })
    return tool_calls


def _extract_tool_results_from_user(content: Any) -> list[dict[str, Any]]:
    """从 Anthropic user content 中提取 tool_result 块。

    返回 list of {"tool_call_id": ..., "content": ...} 格式。
    tool_result 的 content 可能是 string，需要压平。
    """
    if not isinstance(content, list):
        return []
    results: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tc = block.get("content", "")
            if isinstance(tc, list):
                tc = _flatten_content(tc)
            results.append({
                "tool_call_id": block.get("tool_use_id", ""),
                "content": str(tc),
            })
    return results


def convert_messages_to_openai(
    system_text: str,
    anthropic_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 Anthropic-format messages 转为 OpenAI Chat Completions 格式。

    转换规则：
    - system 单独参数 → 第一条 "system" 角色消息
    - user + string content → 保留
    - user + list[text block] → 压成 string
    - user + list[混合 tool_result] → tool_result 拆成独立 "tool" 消息
    - assistant + list[text] → 压成 string
    - assistant + list[含 tool_use] → content=text, tool_calls=[...]
    """
    openai_messages: list[dict[str, Any]] = []

    if system_text and system_text.strip():
        openai_messages.append({"role": "system", "content": system_text})

    for msg in anthropic_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            tool_results = _extract_tool_results_from_user(content)
            if tool_results:
                # 有 tool_result：每条 tool_result 转为独立 "tool" 消息
                for tr in tool_results:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_call_id"],
                        "content": tr["content"],
                    })
                # 如果同一条 user 消息里还有非 tool_result 内容，
                # 附加为 user 文本消息
                text_part = _flatten_content(content)
                if text_part.strip():
                    openai_messages.append({"role": "user", "content": text_part})
            else:
                text_part = _flatten_content(content)
                if text_part.strip():
                    openai_messages.append({"role": "user", "content": text_part})

        elif role == "assistant":
            tool_calls = _extract_tool_calls_from_assistant(content)
            text_part = _flatten_content(content)
            if tool_calls:
                openai_msg: dict[str, Any] = {"role": "assistant", "content": text_part or None}
                openai_msg["tool_calls"] = tool_calls
                openai_messages.append(openai_msg)
            elif text_part.strip():
                openai_messages.append({"role": "assistant", "content": text_part})

        # 其他 role（如 system 已在顶层处理过了）跳过

    return openai_messages


# ============================================================
# 工具 schema 转换：Anthropic input_schema → OpenAI function.parameters
# ============================================================


def convert_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把内部 tool definition 从 Anthropic 格式转为 OpenAI function 格式。

    内部格式（来自 get_model_visible_tools）：
    {"name": "...", "description": "...", "input_schema": {...}}

    OpenAI 格式：
    {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    openai_tools: list[dict[str, Any]] = []
    for tool in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        })
    return openai_tools


# ============================================================
# OpenAI response normalization
# ============================================================


def normalize_openai_response(
    raw_response: dict[str, Any],
    *,
    raw_provider_name: str | None = None,
) -> ProviderResponse:
    """OpenAI Chat Completions response → ProviderResponse。

    处理：
    - choices[0].message.content → ProviderTextBlock
    - choices[0].message.tool_calls[] → ToolUseBlock
    - choices[0].finish_reason → stop_reason (映射)
    - usage → 标准化 dict
    """
    choices: list[dict[str, Any]] = raw_response.get("choices", [])
    if not choices:
        raise ProviderResponseError("no_choices")

    first_choice = choices[0]
    message: dict[str, Any] = first_choice.get("message", {})
    content: list[ProviderTextBlock | ToolUseBlock] = []

    # 文本内容
    text = message.get("content")
    if isinstance(text, str) and text.strip():
        content.append(ProviderTextBlock(text=text))

    # 工具调用
    tool_calls_raw: list[dict[str, Any]] = message.get("tool_calls") or []
    for tc in tool_calls_raw:
        func: dict[str, Any] = tc.get("function", {})
        name = func.get("name", "")
        if not name:
            raise ProviderResponseError("tool_call_missing_name")

        # OpenAI 的 function.arguments 是 JSON 字符串，需要解析
        args_str = func.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except (json.JSONDecodeError, TypeError):
            # 安全处理：malformed arguments 不给空 dict 导致静默吞错，
            # 但也不把原始字符串写进异常
            args = {}

        if not isinstance(args, dict):
            args = {}

        content.append(ToolUseBlock(
            id=str(tc.get("id", "")),
            name=name,
            input=args,
        ))

    # finish_reason → stop_reason 映射
    finish_reason = first_choice.get("finish_reason")
    stop_reason: str | None = None
    if finish_reason == "stop":
        stop_reason = "end_turn"
    elif finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    elif isinstance(finish_reason, str):
        stop_reason = finish_reason

    # usage
    usage_raw = raw_response.get("usage", {})
    usage: dict[str, Any] = {}
    if isinstance(usage_raw, dict):
        for src_key, dst_key in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            if src_key in usage_raw:
                usage[dst_key] = usage_raw[src_key]

    return ProviderResponse(
        content=content,
        stop_reason=stop_reason,
        usage=usage,
        raw_provider_name=raw_provider_name,
    )


# ============================================================
# OpenAICompatibleProvider
# ============================================================


class OpenAICompatibleProvider:
    """OpenAI-compatible HTTP adapter。

    通过 HTTP POST 调用 OpenAI Chat Completions API。
    不依赖 openai SDK，只用 httpx + 手动构造请求体。
    """

    provider_type = "openai_compatible"
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
        """构造 endpoint URL，安全拼接 base_url + request_path。"""
        base_url = (self.config.base_url or "").rstrip("/")
        request_path = (self.config.request_path or "").strip()
        if not base_url:
            raise ProviderResponseError("base_url_missing")
        if not request_path:
            return base_url
        return f"{base_url}/{request_path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        """构造 HTTP headers，key 只出现在 Authorization header。"""
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
        """调用 OpenAI-compatible endpoint，返回归一化 ProviderResponse。"""
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
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        """openai_compatible streaming 尚未实现，必须 fail closed。

        不能把 stream 悄悄降级成 non-streaming create()：SubAgent L1 之后的
        调用方可能依赖逐步反馈语义，静默 fallback 会把 capability 边界变成假象。
        """

        _ = (system, messages, tools, model, max_tokens, temperature)
        raise ProviderCapabilityError("streaming_not_supported")
