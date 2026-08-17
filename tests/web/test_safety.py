from __future__ import annotations

import hashlib

import pytest

from agent.web.safety import WebUrlError, admit_public_url, citation_locator


def test_public_url_admission_is_canonical_and_citation_locator_is_queryless() -> None:
    admitted = admit_public_url("https://Example.COM:443/docs/item?q=public%20value")

    assert admitted == "https://example.com/docs/item?q=public%20value"
    assert citation_locator(admitted) == "https://example.com/docs/item"
    assert hashlib.sha256(admitted.encode()).hexdigest()


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/article",
        "https://user@example.com/article",
        "https://example.com:8443/article",
        "https://example.com/article#fragment",
        "https://localhost/article",
        "https://127.0.0.1/article",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/article",
        "https://127.1/article",
        "https://127.0.1/article",
        "https://0177.0.0.1/article",
        "https://0x7f.0x0.0x0.0x1/article",
        "https://0251.0376.0251.0376/latest/meta-data",
        "https://example.com/article?api_key=secret",
        "https://example.com/article?key=secret",
        "https://example.com/article?sessionid=secret",
        "https://example.com/article?api_key[]=secret",
        "https://example.com/article?token[0]=secret",
        "https://example.com/article?foo[access_token]=secret",
        "https://example.com/article?X-Amz-Signature=secret",
        "https://example.com/article?access_token=secret",
        "https://example.com/article?id_token_hint=secret",
        "https://example.com/article?access-token-hint=secret",
        "https://example.com/article?idTokenHint=secret",
        "https://example.com/article?foo[access_token_hint]=secret",
    ),
)
def test_public_url_admission_rejects_unsafe_or_credential_bearing_urls(url: str) -> None:
    with pytest.raises(WebUrlError):
        admit_public_url(url)


@pytest.mark.parametrize(
    "url",
    (
        "https://example.com/article?monkey=public",
        "https://example.com/article?session_number=42",
        "https://example.com/article?sort=recent",
    ),
)
def test_public_url_admission_keeps_clearly_public_query_keys(url: str) -> None:
    assert admit_public_url(url) == url
