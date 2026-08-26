"""Fixed-destination Tavily Search/Extract HTTP adapter。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping

import httpx

from agent.transport_audit import TransportAttemptRecorder
from agent.web.contracts import WebExtractedPage, WebSearchHit, WebSearchResponse
from agent.web.profile import TAVILY_DESTINATION, WebProfileV1
from agent.web.safety import WebUrlError, admit_public_url, citation_locator

_MAX_RESPONSE_BYTES = 256_000
_MAX_JSON_DEPTH = 8
_MAX_QUERY_CHARS = 1_000
_MAX_TITLE_CHARS = 512
_MAX_SEARCH_CONTENT_CHARS = 4_000
# 给工具的 JSON locator/envelope 保留空间，保证整个 ToolResult 仍落在 50k 上限内。
_MAX_EXTRACT_CONTENT_CHARS = 48_000
_MAX_REQUEST_ID_CHARS = 256
TAVILY_SEARCH_PATH = "/search"
TAVILY_EXTRACT_PATH = "/extract"


class WebClientError(RuntimeError):
    """不包含 response body、API key 或 URL query 的 Web adapter 错误。"""


class WebAuthError(WebClientError):
    pass


class WebRateLimitError(WebClientError):
    pass


class WebProtocolError(WebClientError):
    pass


class WebTimeoutError(WebClientError):
    pass


class WebTransportError(WebClientError):
    pass


class WebServiceError(WebClientError):
    pass


class TavilyClient:
    def __init__(
        self,
        profile: WebProfileV1,
        *,
        api_key: str,
        http_client: httpx.Client | None = None,
        attempt_recorder: TransportAttemptRecorder | None = None,
    ) -> None:
        if (
            not isinstance(api_key, str)
            or not api_key
            or len(api_key) > 1_024
            or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in api_key)
        ):
            raise ValueError("Tavily API key is missing or malformed")
        self.profile = profile
        self._api_key = api_key
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(
            timeout=profile.timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        self._attempt_recorder = attempt_recorder

    @property
    def owns_client(self) -> bool:
        return self._owns_client

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def search(self, query: str, *, max_results: int) -> WebSearchResponse:
        query = _bounded_text(query, "query", _MAX_QUERY_CHARS, allow_empty=False)
        if (
            not isinstance(max_results, int)
            or isinstance(max_results, bool)
            or not 1 <= max_results <= self.profile.max_results
        ):
            raise ValueError("max_results exceeds the configured Web profile")
        document = self._post_json(
            TAVILY_SEARCH_PATH,
            tavily_search_payload(query, max_results=max_results),
        )
        # Tavily 会规范化 response.query（例如重写 site: 语法）。它是远端描述性
        # 回显，不参与权限；request identity 与用户批准仍绑定原始 outgoing query。
        _required_string(document, "query", _MAX_QUERY_CHARS)
        raw_results = document.get("results")
        if not isinstance(raw_results, list) or len(raw_results) > max_results:
            raise WebProtocolError("Tavily search result count is invalid")
        results: list[WebSearchHit] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                raise WebProtocolError("Tavily search result is not an object")
            title = _required_string(raw_result, "title", _MAX_TITLE_CHARS)
            content = _required_string(
                raw_result,
                "content",
                _MAX_SEARCH_CONTENT_CHARS,
                allow_empty=True,
            )
            raw_url = _required_string(raw_result, "url", 3_000)
            try:
                url = admit_public_url(raw_url)
            except WebUrlError as error:
                raise WebProtocolError("Tavily returned a URL outside policy") from error
            score = raw_result.get("score")
            if score is not None:
                if (
                    isinstance(score, bool)
                    or not isinstance(score, int | float)
                    or not math.isfinite(float(score))
                ):
                    raise WebProtocolError("Tavily search score is invalid")
                score = float(score)
            results.append(
                WebSearchHit(
                    title=title,
                    url=url,
                    citation_locator=citation_locator(url),
                    content=content,
                    score=score,
                )
            )
        return WebSearchResponse(
            query=query,
            results=tuple(results),
            request_id=_optional_request_id(document),
        )

    def extract(self, raw_url: str) -> WebExtractedPage:
        try:
            url = admit_public_url(raw_url)
        except WebUrlError as error:
            raise ValueError("extract URL is outside the public Web policy") from error
        document = self._post_json(
            TAVILY_EXTRACT_PATH,
            tavily_extract_payload(url, timeout_seconds=self.profile.timeout_seconds),
        )
        raw_results = document.get("results")
        if not isinstance(raw_results, list) or len(raw_results) > 1:
            raise WebProtocolError("Tavily extract result count is invalid")
        if len(raw_results) != 1 or not isinstance(raw_results[0], dict):
            raise WebProtocolError("Tavily extract returned no matching result")
        raw_result = raw_results[0]
        returned_url = _required_string(raw_result, "url", 3_000)
        try:
            returned_url = admit_public_url(returned_url)
        except WebUrlError as error:
            raise WebProtocolError("Tavily extract returned a URL outside policy") from error
        if returned_url != url:
            raise WebProtocolError("Tavily extract URL did not match the approved URL")
        raw_content = raw_result.get("raw_content")
        if not isinstance(raw_content, str) or not raw_content:
            raise WebProtocolError("Tavily raw_content is malformed")
        truncated = len(raw_content) > _MAX_EXTRACT_CONTENT_CHARS
        content = raw_content[:_MAX_EXTRACT_CONTENT_CHARS]
        return WebExtractedPage(
            url=url,
            citation_locator=citation_locator(url),
            content=content,
            request_id=_optional_request_id(document),
            truncated=truncated,
            original_content_digest=(
                hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
                if truncated
                else None
            ),
        )

    def _post_json(self, path: str, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            if self._attempt_recorder is not None:
                self._attempt_recorder("web", TAVILY_DESTINATION)
            with self._http_client.stream(
                "POST",
                TAVILY_DESTINATION + path,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=self.profile.timeout_seconds,
            ) as response:
                _raise_for_status(response.status_code)
                media_type = response.headers.get("content-type", "").split(";", 1)[
                    0
                ].strip().lower()
                if media_type != "application/json":
                    raise WebProtocolError("Tavily response content type is not JSON")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > _MAX_RESPONSE_BYTES:
                        raise WebProtocolError(
                            "Tavily response exceeded the decompressed byte limit"
                        )
                    chunks.append(chunk)
        except httpx.TimeoutException as error:
            raise WebTimeoutError("Tavily request timed out; outcome is unknown") from error
        except httpx.DecodingError as error:
            raise WebProtocolError("Tavily response encoding is invalid") from error
        except httpx.TransportError as error:
            raise WebTransportError("Tavily transport failed; outcome is unknown") from error
        try:
            document = json.loads(
                b"".join(chunks).decode("utf-8", errors="strict"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
            raise WebProtocolError("Tavily response is not strict JSON") from error
        if not isinstance(document, dict):
            raise WebProtocolError("Tavily response root is not an object")
        if _json_depth(document) > _MAX_JSON_DEPTH:
            raise WebProtocolError("Tavily response JSON exceeds the depth limit")
        return document


def tavily_search_payload(query: str, *, max_results: int) -> dict[str, object]:
    """返回 Search adapter 与审批面共享的 credential-free payload。"""

    return {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "auto_parameters": False,
    }


def tavily_extract_payload(url: str, *, timeout_seconds: float) -> dict[str, object]:
    """返回 Extract adapter 与审批面共享的 credential-free payload。"""

    return {
        "urls": [url],
        "extract_depth": "basic",
        "format": "text",
        "include_images": False,
        "timeout": timeout_seconds,
    }


def _raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status in {401, 403}:
        raise WebAuthError("Tavily authentication was rejected")
    if status in {429, 432, 433}:
        raise WebRateLimitError("Tavily rate or account limit was reached")
    if 400 <= status < 500:
        raise WebProtocolError("Tavily rejected the fixed request")
    if 500 <= status < 600:
        raise WebServiceError("Tavily service failed the request")
    raise WebProtocolError("Tavily returned an unexpected HTTP status")


def _bounded_text(
    value: object,
    field: str,
    max_chars: int,
    *,
    allow_empty: bool,
) -> str:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value.strip())
        or len(value) > max_chars
        or any(ord(ch) < 0x20 and ch not in "\n\r\t" for ch in value)
        or any(0x7F <= ord(ch) <= 0x9F for ch in value)
    ):
        raise WebProtocolError(f"Tavily {field} is malformed or oversized")
    return value


def _required_string(
    document: Mapping[str, object],
    field: str,
    max_chars: int,
    *,
    allow_empty: bool = False,
) -> str:
    return _bounded_text(document.get(field), field, max_chars, allow_empty=allow_empty)


def _optional_request_id(document: Mapping[str, object]) -> str | None:
    value = document.get("request_id")
    if value is None:
        return None
    return _bounded_text(
        value,
        "request_id",
        _MAX_REQUEST_ID_CHARS,
        allow_empty=False,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _json_depth(value: object) -> int:
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


__all__ = [
    "TavilyClient",
    "WebAuthError",
    "WebClientError",
    "WebProtocolError",
    "WebRateLimitError",
    "WebServiceError",
    "WebTimeoutError",
    "WebTransportError",
]
