"""HTTP adapter for Anthropic-compatible endpoints."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import httpx

from agent.evidence_redaction import redact_text
from agent.provider.config import AgentProviderConfig
from agent.provider.normalize import normalize_anthropic_response
from agent.provider.protocol import (
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderResponse,
    ProviderResponseError,
    ProviderTimeoutError,
    ToolUseBlock,
)
from agent.provider.streaming import ProviderStreamEvent

# Provider APIs (Anthropic / OpenAI / DeepSeek) require tool names matching
# ^[a-zA-Z0-9_-]+$. Internal namespaced tools use dots (e.g. demo.write_demo_note);
# sanitize on send, restore on the tool_use response. Found via the R-series
# real-provider trial (DeepSeek /anthropic returned HTTP 400 on dotted tool names).
_PROVIDER_TOOL_NAME_INVALID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_provider_tool_name(name: str) -> str:
    """单个 name 的基础清洗（非法字符 → ``_``）。不处理冲突——由
    ``_provider_tool_name_pairs`` 保证唯一。"""

    return _PROVIDER_TOOL_NAME_INVALID_RE.sub("_", name or "")


def _provider_tool_name_pairs(original_names: list[str]) -> list[tuple[str, str]]:
    """为每个内部 tool name 生成 provider 可见、稳定唯一的 name。

    返回 ``[(original, provider_name), ...]``（保持输入顺序）。``provider_name`` 匹配
    ``^[a-zA-Z0-9_-]+$`` 且在本次调用内唯一：冲突时追加稳定 ``_2``/``_3`` 后缀，故
    ``demo.a_b`` 与 ``demo.a.b`` 不会都塌缩成 ``demo_a_b``（后者变为 ``demo_a_b_2``）。
    顺序稳定 → 同一工具集每次生成相同 provider name（provider 端缓存友好）。
    """

    used: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for original in original_names:
        base = _sanitize_provider_tool_name(original) or "tool"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        pairs.append((original, candidate))
    return pairs


def _provider_error_hint(status_code: int, body_preview: str) -> str:
    """Protocol-generic actionable hint for a provider HTTP error (R-051).

    No vendor/model special-casing — hints are based on HTTP status + body keywords only.
    Helps the operator distinguish protocol/tool-name/model/auth issues without leaking
    secrets (body_preview is already redacted by the caller).
    """

    if status_code in {401, 403}:
        return "auth/key issue — verify api_key is valid for this endpoint and provider_type"
    if status_code == 429:
        return "rate limit — retry after a delay"
    if status_code >= 500:
        return "server error — retry or check endpoint availability"
    lowered = body_preview.lower()
    if "tool" in lowered and ("name" in lowered or "pattern" in lowered):
        return "tool-name/protocol mismatch — tool names must match ^[a-zA-Z0-9_-]+$"
    if "model" in lowered:
        return "model/endpoint mismatch — verify model name is valid for this endpoint"
    return "protocol/request mismatch — check provider_type, request body, model, endpoint"


def validate_provider_tool_names(tools: list[dict[str, Any]]) -> list[str]:
    """Return tool names that contain characters invalid for the provider pattern
    ``^[a-zA-Z0-9_-]+$`` (R-G05).

    These names need the adapter's sanitize+restore mapping at the provider seam. Use this
    in fake/local diagnostics to surface the issue early — FakeProvider never validated
    tool names, which hid the F-01 bug (dotted names → real provider 400).
    """

    return [
        str(tool.get("name", ""))
        for tool in tools
        if _PROVIDER_TOOL_NAME_INVALID_RE.search(str(tool.get("name", "")))
    ]


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
        # Provider 工具名必须匹配 ^[a-zA-Z0-9_-]+$；内部 namespace 用点，需在 provider
        # seam 处清洗（send，冲突安全）并在 tool_use 响应处还原（restore），避免 400。
        restore_map: dict[str, str] = {}
        if tools:
            pairs = _provider_tool_name_pairs([str(t.get("name", "")) for t in tools])
            restore_map = {provider_name: original for original, provider_name in pairs}
            sent_tools = [
                {**tool, "name": provider_name}
                for tool, (_original, provider_name) in zip(tools, pairs, strict=True)
            ]
            body["tools"] = sent_tools
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
            raw_body = response.text[:300] if response.text else ""
            redacted_body = redact_text(raw_body)
            hint = _provider_error_hint(response.status_code, redacted_body)
            raise ProviderAuthError(
                f"http_status:{response.status_code} | {hint} | body: {redacted_body[:200]}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raw_body = response.text[:300] if response.text else ""
            redacted_body = redact_text(raw_body)
            hint = _provider_error_hint(response.status_code, redacted_body)
            raise ProviderResponseError(
                f"http_status:{response.status_code} | {hint} | body: {redacted_body[:200]}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError("malformed_json") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            raise ProviderResponseError("malformed_response")
        normalized = normalize_anthropic_response(
            payload,
            raw_provider_name=self.provider_type,
        )
        if restore_map:
            # 把 provider 回传的 sanitized tool 名还原为内部 dotted 名，使 dispatcher 能命中。
            restored_content = [
                replace(block, name=restore_map[block.name])
                if isinstance(block, ToolUseBlock) and block.name in restore_map
                else block
                for block in normalized.content
            ]
            normalized = replace(normalized, content=restored_content)
        return normalized

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
