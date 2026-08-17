from __future__ import annotations

import gzip
import json

import httpx
import pytest

from agent.web.client import (
    TavilyClient,
    WebAuthError,
    WebProtocolError,
    WebRateLimitError,
    WebTimeoutError,
)
from agent.web.profile import WebProfileV1


def _profile(**overrides) -> WebProfileV1:
    values = {
        "credential_env": "FIRST_AGENT_WEB_API_KEY",
        "timeout_seconds": 10.0,
        "max_results": 3,
    }
    values.update(overrides)
    return WebProfileV1(**values)


def _json_response(payload, *, status: int = 200, headers=None) -> httpx.Response:  # noqa: ANN001
    return httpx.Response(
        status,
        headers={"content-type": "application/json", **(headers or {})},
        content=json.dumps(payload).encode(),
    )


def test_tavily_search_uses_fixed_minimal_shape_and_parses_bounded_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_response(
            {
                "query": "local first agents",
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com/article?view=public",
                        "content": "A public snippet.",
                        "score": 0.9,
                    }
                ],
                "response_time": "0.1",
                "request_id": "request-1",
            }
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        result = TavilyClient(
            _profile(), api_key="secret-value", http_client=http_client
        ).search("local first agents", max_results=2)

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["authorization"] == "Bearer secret-value"
    body = json.loads(request.content)
    assert body == {
        "auto_parameters": False,
        "include_answer": False,
        "include_images": False,
        "include_raw_content": False,
        "max_results": 2,
        "query": "local first agents",
        "search_depth": "basic",
    }
    assert result.query == "local first agents"
    assert result.results[0].url == "https://example.com/article?view=public"
    assert result.results[0].citation_locator == "https://example.com/article"


def test_tavily_search_keeps_the_approved_query_when_service_normalizes_its_echo() -> None:
    requested_query = "Python 3.13 release site:python.org"

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["query"] == requested_query
        return _json_response(
            {
                "query": "Python 3.13 release site python org",
                "results": [
                    {
                        "title": "Python 3.13.0",
                        "url": "https://www.python.org/downloads/release/python-3130/",
                        "content": "Public release page.",
                    }
                ],
            }
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        result = TavilyClient(
            _profile(), api_key="secret-value", http_client=http_client
        ).search(requested_query, max_results=1)

    # Approval/request identity binds the exact outgoing query. The service echo is
    # untrusted descriptive metadata and may be normalized without changing authority.
    assert result.query == requested_query
    assert len(result.results) == 1


def test_tavily_extract_only_calls_fixed_extract_destination_and_matches_url() -> None:
    requests: list[httpx.Request] = []
    url = "https://example.com/article?view=public"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_response(
            {
                "results": [{"url": url, "raw_content": "Extracted public text."}],
                "failed_results": [],
                "response_time": 0.2,
                "request_id": "request-2",
            }
        )

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        result = TavilyClient(
            _profile(), api_key="secret-value", http_client=http_client
        ).extract(url)

    assert str(requests[0].url) == "https://api.tavily.com/extract"
    assert json.loads(requests[0].content) == {
        "extract_depth": "basic",
        "format": "text",
        "include_images": False,
        "timeout": 10.0,
        "urls": [url],
    }
    assert result.url == url
    assert result.content == "Extracted public text."


@pytest.mark.parametrize(
    ("status", "error_type"),
    ((401, WebAuthError), (403, WebAuthError), (429, WebRateLimitError), (432, WebRateLimitError)),
)
def test_tavily_client_classifies_known_http_failures(status, error_type) -> None:  # noqa: ANN001
    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response({"detail": {"error": "do not echo me"}}, status=status)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        client = TavilyClient(_profile(), api_key="secret-value", http_client=http_client)
        with pytest.raises(error_type) as raised:
            client.search("bounded public query", max_results=1)
    assert "secret-value" not in str(raised.value)
    assert "do not echo me" not in str(raised.value)


def test_tavily_client_rejects_content_type_depth_and_decompressed_size() -> None:
    payloads = iter(
        (
            httpx.Response(200, headers={"content-type": "text/html"}, content=b"{}"),
            _json_response({"results": [[[[[[[[[[[]]]]]]]]]]]}),
            httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                },
                content=gzip.compress(b"{" + b" " * 300_000 + b"}"),
            ),
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(payloads)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        client = TavilyClient(_profile(), api_key="secret-value", http_client=http_client)
        for _ in range(3):
            with pytest.raises(WebProtocolError):
                client.search("bounded public query", max_results=1)


def test_tavily_timeout_is_typed_without_retry() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        client = TavilyClient(_profile(), api_key="secret-value", http_client=http_client)
        with pytest.raises(WebTimeoutError):
            client.search("bounded public query", max_results=1)

    assert count == 1


def test_tavily_extract_rejects_mismatched_url_and_oversized_fields() -> None:
    responses = iter(
        (
            _json_response(
                {
                    "results": [
                        {
                            "url": "https://other.example/article",
                            "raw_content": "content",
                        }
                    ],
                    "failed_results": [],
                }
            ),
            _json_response(
                {
                    "query": "bounded public query",
                    "results": [
                        {
                            "title": "x" * 513,
                            "url": "https://example.com/article",
                            "content": "snippet",
                        }
                    ],
                }
            ),
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    ) as http_client:
        client = TavilyClient(_profile(), api_key="secret-value", http_client=http_client)
        with pytest.raises(WebProtocolError, match="did not match"):
            client.extract("https://example.com/article")
        with pytest.raises(WebProtocolError, match="oversized"):
            client.search("bounded public query", max_results=1)
