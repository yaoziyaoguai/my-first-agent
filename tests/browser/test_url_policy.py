"""018 Task 1 Step 4：URL policy 的 SSRF/closed-admission Reds（先 Red）。

resolver 必须构造注入 deterministic fake；测试不得触发 host resolver。
覆盖 spec §3.3：HTTPS-only、无 userinfo、canonical host/port、拒绝 IP literal/
localhost/loopback/private/link-local/multicast/unspecified/reserved/cloud
metadata、全部 A/AAAA answer 必须 public、site-bound exact origin allowlist。
"""

import pytest

from agent.browser.contracts import BrowserMode
from agent.browser.url_policy import (
    AdmittedURLV1,
    BrowserURLPolicy,
    URLPolicyError,
)

PUBLIC_HOST = "site.example.test"
PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


class FakeResolver:
    """deterministic 注入 resolver；命中即证明未读取 host resolver。"""

    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        self.mapping = {host: tuple(addrs) for host, addrs in mapping.items()}
        self.calls: list[str] = []

    def resolve(self, host: str) -> tuple[str, ...]:
        self.calls.append(host)
        return self.mapping.get(host, ())


def make_policy(
    mapping: dict[str, tuple[str, ...]] | None = None,
) -> tuple[BrowserURLPolicy, FakeResolver]:
    resolver = FakeResolver(mapping or {PUBLIC_HOST: (PUBLIC_V4,)})
    return BrowserURLPolicy(resolver=resolver), resolver


def admit_public(policy: BrowserURLPolicy, url: str) -> AdmittedURLV1:
    return policy.admit(
        url, mode=BrowserMode.PUBLIC_READ_EPHEMERAL, allowed_origins=(),
    )


def test_https_public_url_is_admitted_with_canonical_identity():
    policy, resolver = make_policy()
    admitted = admit_public(policy, f"https://{PUBLIC_HOST}/docs?q=1")
    assert isinstance(admitted, AdmittedURLV1)
    assert admitted.canonical_origin == f"https://{PUBLIC_HOST}"
    assert admitted.canonical_url == f"https://{PUBLIC_HOST}/docs?q=1"
    assert len(admitted.address_digest) == 64
    assert resolver.calls == [PUBLIC_HOST]


def test_default_port_and_host_case_canonicalize_to_same_origin():
    policy, _ = make_policy()
    with_port = admit_public(policy, "https://SITE.Example.TEST:443/x")
    plain = admit_public(policy, f"https://{PUBLIC_HOST}/x")
    assert with_port.canonical_origin == plain.canonical_origin
    assert with_port.canonical_origin == f"https://{PUBLIC_HOST}"


@pytest.mark.parametrize(
    "url",
    [
        "http://site.example.test/",
        "https://user:secret@site.example.test/",
        "https://user@site.example.test/",
        "https://93.184.216.34/",
        "https://[2606:2800:220:1:248:1893:25c8:1946]/",
        "https://localhost/",
        "https://site.example.test./",
        "https://site.example.test:8443/",
    ],
)
def test_non_canonical_or_non_public_url_shapes_are_rejected(url):
    policy, _ = make_policy()
    with pytest.raises(URLPolicyError) as exc_info:
        admit_public(policy, url)
    assert exc_info.value.reason


@pytest.mark.parametrize(
    ("label", "addresses"),
    [
        ("loopback v4", ("127.0.0.1",)),
        ("loopback v6", ("::1",)),
        ("rfc1918 10/8", ("10.0.0.5",)),
        ("rfc1918 172.16/12", ("172.16.1.1",)),
        ("rfc1918 192.168/16", ("192.168.1.1",)),
        ("unique local v6", ("fd00::1",)),
        ("link-local v4", ("169.254.1.1",)),
        ("link-local v6", ("fe80::1",)),
        ("multicast v4", ("224.0.0.1",)),
        ("multicast v6", ("ff02::1",)),
        ("unspecified v4", ("0.0.0.0",)),
        ("unspecified v6", ("::",)),
        ("reserved documentation v4", ("192.0.2.1",)),
        ("reserved documentation v6", ("2001:db8::1",)),
        ("reserved future v4", ("240.0.0.1",)),
        ("cloud metadata", ("169.254.169.254",)),
        ("v4-mapped private v6", ("::ffff:10.0.0.1",)),
        ("mixed public-private answers", (PUBLIC_V4, "10.0.0.5")),
        ("all private multi-answer", ("10.0.0.5", "192.168.1.1")),
    ],
)
def test_non_public_dns_answers_are_rejected(label, addresses):
    policy, _ = make_policy({PUBLIC_HOST: addresses})
    with pytest.raises(URLPolicyError) as exc_info:
        admit_public(policy, f"https://{PUBLIC_HOST}/")
    assert exc_info.value.reason


def test_public_v6_answer_is_admitted():
    policy, _ = make_policy({PUBLIC_HOST: (PUBLIC_V6,)})
    admitted = admit_public(policy, f"https://{PUBLIC_HOST}/")
    assert admitted.canonical_origin == f"https://{PUBLIC_HOST}"
    assert len(admitted.address_digest) == 64


def test_empty_dns_answer_fails_closed():
    policy, _ = make_policy({PUBLIC_HOST: ()})
    with pytest.raises(URLPolicyError) as exc_info:
        admit_public(policy, f"https://{PUBLIC_HOST}/")
    assert exc_info.value.reason


def test_site_bound_admits_only_exact_canonical_origin():
    policy, _ = make_policy(
        {
            PUBLIC_HOST: (PUBLIC_V4,),
            "other.example.test": (PUBLIC_V4,),
        }
    )
    admitted = policy.admit(
        f"https://{PUBLIC_HOST}/page",
        mode=BrowserMode.SITE_BOUND_INTERACTIVE,
        allowed_origins=(f"https://{PUBLIC_HOST}",),
    )
    assert admitted.canonical_origin == f"https://{PUBLIC_HOST}"


def test_site_bound_redirect_to_drifted_origin_is_rejected():
    # redirect/popup 到 allowlist 外的 canonical origin 必须重新 admit 且失败。
    policy, _ = make_policy(
        {
            PUBLIC_HOST: (PUBLIC_V4,),
            "other.example.test": (PUBLIC_V4,),
        }
    )
    with pytest.raises(URLPolicyError) as exc_info:
        policy.admit(
            "https://other.example.test/",
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            allowed_origins=(f"https://{PUBLIC_HOST}",),
        )
    assert exc_info.value.reason


def test_site_bound_subdomain_of_allowed_origin_is_rejected():
    policy, _ = make_policy({"evil.example.test": (PUBLIC_V4,)})
    with pytest.raises(URLPolicyError) as exc_info:
        policy.admit(
            "https://evil.example.test/",
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            allowed_origins=(f"https://{PUBLIC_HOST}",),
        )
    assert exc_info.value.reason
