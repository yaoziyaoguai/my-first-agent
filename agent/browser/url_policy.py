"""018 browser URL/egress admission policy（spec §3.3）。

closed admission：构造注入 resolver，不读 host resolver 配置；只允许 HTTPS +
canonical host + 全部 A/AAAA answer 为 public unicast 地址；site-bound 模式
还要求 canonical origin 属于 exact allowlist。本模块不接触 Playwright/browser，
页面内容（redirect、CSP、ARIA 文本）永远不能扩大这里的判定。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from agent.browser.contracts import BrowserMode
from agent.runtime.contracts import canonical_json_digest

DEFAULT_HTTPS_PORT = 443


class URLPolicyError(Exception):
    """closed admission 拒绝；reason 是 bounded 诊断码，不携带 URL 原文。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AddressResolver(Protocol):
    """url_policy 唯一的 DNS 注入点；production 实现由 composition 提供。"""

    def resolve(self, host: str) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class AdmittedURLV1:
    """admission 通过后的 immutable canonical identity + address-set digest。"""

    canonical_url: str
    canonical_origin: str
    address_digest: str


def _canonical_host(host: str) -> str:
    # trailing dot 是绝对 FQDN 形式，可绕过 allowlist 字符串匹配，直接拒绝。
    if host.endswith("."):
        raise URLPolicyError("non_canonical_host")
    try:
        canonical = host.lower().encode("idna").decode("ascii")
    except UnicodeError as error:
        raise URLPolicyError("non_canonical_host") from error
    if not canonical:
        raise URLPolicyError("non_canonical_host")
    return canonical


def _require_public_address(answer: str) -> None:
    try:
        address = ipaddress.ip_address(answer)
    except ValueError as error:
        raise URLPolicyError("unresolvable_address") from error
    # v4-mapped v6 地址按内嵌 v4 判定，不依赖具体 Python 版本的行为差异。
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not address.is_global
    ):
        raise URLPolicyError("non_public_address")


def canonical_https_origin(value: str) -> str:
    """把 user-owned site policy 收窄到无路径的 canonical HTTPS origin。"""

    if not isinstance(value, str) or not value:
        raise URLPolicyError("non_canonical_origin")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise URLPolicyError("non_canonical_origin")
    host = parts.hostname
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise URLPolicyError("non_canonical_origin")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise URLPolicyError("non_canonical_origin")
    try:
        port = parts.port
    except ValueError as error:
        raise URLPolicyError("non_canonical_origin") from error
    if port is not None:
        raise URLPolicyError("non_canonical_origin")
    canonical = f"https://{_canonical_host(host)}"
    if value != canonical:
        raise URLPolicyError("non_canonical_origin")
    return canonical


def browser_site_policy_digest(allowed_origins: tuple[str, ...]) -> str:
    """site-bound profile 与 session 共同使用的 exact-origin set identity。"""

    if not allowed_origins:
        raise URLPolicyError("empty_site_policy")
    canonical = tuple(canonical_https_origin(item) for item in allowed_origins)
    if len(set(canonical)) != len(canonical):
        raise URLPolicyError("duplicate_site_origin")
    return canonical_json_digest({"allowed_origins": sorted(canonical)})


class BrowserURLPolicy:
    """HTTPS-only public-address admission；SITE_BOUND 另要求 exact origin allowlist。"""

    def __init__(self, *, resolver: AddressResolver) -> None:
        # resolver 只能构造注入：production composition 不存在 permissive 开关。
        if resolver is None:
            raise ValueError("resolver must be injected")
        self._resolver = resolver

    def admit(
        self,
        url: str,
        *,
        mode: BrowserMode,
        allowed_origins: tuple[str, ...] = (),
    ) -> AdmittedURLV1:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise URLPolicyError("scheme_not_https")
        if parts.username is not None or parts.password is not None:
            raise URLPolicyError("userinfo_not_allowed")
        host = parts.hostname
        if not host:
            raise URLPolicyError("host_required")
        if host == "localhost" or host.endswith(".localhost"):
            raise URLPolicyError("localhost_not_allowed")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise URLPolicyError("ip_literal_not_allowed")
        canonical_host = _canonical_host(host)
        try:
            port = parts.port
        except ValueError as error:
            raise URLPolicyError("non_canonical_port") from error
        if port is not None and port != DEFAULT_HTTPS_PORT:
            raise URLPolicyError("non_default_port")
        canonical_origin = f"https://{canonical_host}"
        if (
            mode is BrowserMode.SITE_BOUND_INTERACTIVE
            and canonical_origin not in tuple(allowed_origins)
        ):
            raise URLPolicyError("origin_not_in_allowlist")
        answers = self._resolver.resolve(canonical_host)
        if not answers:
            raise URLPolicyError("no_dns_answer")
        for answer in answers:
            _require_public_address(answer)
        canonical_url = urlunsplit(
            ("https", canonical_host, parts.path or "", parts.query, parts.fragment)
        )
        address_digest = canonical_json_digest(
            {"origin": canonical_origin, "addresses": sorted(set(answers))}
        )
        return AdmittedURLV1(
            canonical_url=canonical_url,
            canonical_origin=canonical_origin,
            address_digest=address_digest,
        )
