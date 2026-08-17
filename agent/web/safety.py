"""Tavily 可接收的公开 URL admission；本机永不直连 source host。"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_MAX_URL_CHARS = 3_000
_MAX_HOST_CHARS = 253
_MAX_PATH_CHARS = 2_000
_MAX_QUERY_CHARS = 1_000
_CREDENTIAL_KEY_PARTS = tuple(
    tuple(value.split("_"))
    for value in (
        "key",
        "api_key",
        "apikey",
        "access_token",
        "accesstoken",
        "auth",
        "authorization",
        "credential",
        "password",
        "secret",
        "session",
        "session_id",
        "sessionid",
        "signature",
        "sig",
        "token",
        "x_amz_signature",
    )
)
_LEGACY_IPV4_LABEL = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)", re.IGNORECASE)
_PRIVATE_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


class WebUrlError(ValueError):
    """URL 不是 bounded public HTTPS locator。"""


def _has_control_or_space(value: str) -> bool:
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in value) or any(
        ch.isspace() for ch in value
    )


def admit_public_url(raw_url: str) -> str:
    if (
        not isinstance(raw_url, str)
        or not raw_url
        or len(raw_url) > _MAX_URL_CHARS
        or _has_control_or_space(raw_url)
    ):
        raise WebUrlError("URL is empty, oversized, or contains unsafe characters")
    try:
        parts = urlsplit(raw_url)
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise WebUrlError("URL is malformed") from error
    if parts.scheme.lower() != "https" or not host:
        raise WebUrlError("URL must use public HTTPS")
    if parts.username is not None or parts.password is not None:
        raise WebUrlError("URL must not contain userinfo")
    if parts.fragment:
        raise WebUrlError("URL must not contain a fragment")
    if port not in (None, 443):
        raise WebUrlError("URL port is not admitted")
    host = host.rstrip(".").lower()
    if not host or len(host) > _MAX_HOST_CHARS:
        raise WebUrlError("URL host is outside its bound")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise WebUrlError("URL host is malformed") from error
    if ascii_host == "localhost" or ascii_host.endswith(_PRIVATE_HOST_SUFFIXES):
        raise WebUrlError("URL host is not public")
    try:
        address = ipaddress.ip_address(ascii_host)
    except ValueError:
        if _looks_like_legacy_ipv4(ascii_host):
            raise WebUrlError("URL host uses a non-canonical numeric address") from None
        if "." not in ascii_host or any(not label for label in ascii_host.split(".")):
            raise WebUrlError("URL host is not a public DNS name") from None
    else:
        if not address.is_global:
            raise WebUrlError("URL address is not globally routable")
        ascii_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    if len(parts.path) > _MAX_PATH_CHARS or len(parts.query) > _MAX_QUERY_CHARS:
        raise WebUrlError("URL path or query exceeds its bound")
    try:
        query_pairs = parse_qsl(
            parts.query,
            keep_blank_values=True,
            strict_parsing=False,
            max_num_fields=50,
        )
    except ValueError as error:
        raise WebUrlError("URL query is malformed or oversized") from error
    if any(_query_key_is_credential(key) for key, _value in query_pairs):
        raise WebUrlError("URL query appears to carry credentials")
    netloc = ascii_host
    path = parts.path or "/"
    return urlunsplit(("https", netloc, path, parts.query, ""))


def _looks_like_legacy_ipv4(host: str) -> bool:
    labels = host.split(".")
    return 1 <= len(labels) <= 4 and all(
        _LEGACY_IPV4_LABEL.fullmatch(label) for label in labels
    )


def _query_key_is_credential(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
    compact = normalized.replace("_", "")
    if compact.endswith(("idtokenhint", "accesstokenhint")):
        return True
    parts = tuple(part for part in normalized.split("_") if part)
    for credential in _CREDENTIAL_KEY_PARTS:
        width = len(credential)
        for index in range(len(parts) - width + 1):
            if parts[index : index + width] != credential:
                continue
            suffix = parts[index + width :]
            if not suffix or all(part.isdecimal() for part in suffix):
                return True
    return False


def citation_locator(admitted_url: str) -> str:
    canonical = admit_public_url(admitted_url)
    parts = urlsplit(canonical)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


__all__ = ["WebUrlError", "admit_public_url", "citation_locator"]
