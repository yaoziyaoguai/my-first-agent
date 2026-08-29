"""018 Task 3 Step 3：egress routing 的 Reds（先 Red）。

document/redirect/popup/frame/subresource/WebSocket 每一种 request 事件都经
同一个 current mode/origins guard；被拒事件 guard-attempt+1 而 network-send
保持 0；DNS rebinding（同 origin 地址集漂移）与 mixed answer fail closed；
test-only 注入只经 constructor seam，production 签名无 allow_private/
disable_guard。
"""

import inspect

import pytest

from agent.browser.contracts import BrowserMode
from agent.browser.playwright_adapter import (
    BrowserEgressGuard,
    PlaywrightBrowserEnvironment,
    RequestKind,
)
from agent.browser.url_policy import URLPolicyError
from tests.browser.fakes import FakeResolver, FakeTransport

PUBLIC_HOST = "site.example.test"
PUBLIC_V4 = "93.184.216.34"
ALL_KINDS = (
    RequestKind.DOCUMENT,
    RequestKind.REDIRECT,
    RequestKind.POPUP,
    RequestKind.FRAME,
    RequestKind.SUBRESOURCE,
    RequestKind.WEBSOCKET,
)


def make_guard(mapping=None):
    resolver = FakeResolver(mapping or {PUBLIC_HOST: (PUBLIC_V4,)})
    transport = FakeTransport()
    return (
        BrowserEgressGuard(resolver=resolver, transport=transport),
        resolver,
        transport,
    )


def test_every_request_kind_uses_the_same_guard_admission():
    guard, _resolver, transport = make_guard()
    for kind in ALL_KINDS:
        admitted = guard.admit_request(
            kind,
            f"https://{PUBLIC_HOST}/asset",
            mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
            allowed_origins=(),
        )
        assert admitted.canonical_origin == f"https://{PUBLIC_HOST}"
        # send 只在真实 continuation 时记录。
        guard.record_send(kind, admitted)
        assert guard.attempts_for(kind) == 1
        assert guard.rejections_for(kind) == 0
        assert guard.sends_for(kind) == 1
    assert guard.attempts == 6
    assert guard.sends == 6
    assert len(transport.sends) == 6


def test_rejected_requests_increment_attempts_but_never_send():
    guard, _resolver, transport = make_guard()
    for kind in ALL_KINDS:
        with pytest.raises(URLPolicyError):
            guard.admit_request(
                kind,
                f"http://{PUBLIC_HOST}/plain",
                mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
                allowed_origins=(),
            )
    assert guard.attempts == 6
    assert guard.sends == 0
    assert transport.sends == []
    for kind in ALL_KINDS:
        assert guard.attempts_for(kind) == 1
        assert guard.rejections_for(kind) == 1
        assert guard.sends_for(kind) == 0


def test_mixed_dns_answers_fail_closed_per_event():
    guard, resolver, transport = make_guard({PUBLIC_HOST: (PUBLIC_V4, "10.0.0.5")})
    with pytest.raises(URLPolicyError):
        guard.admit_request(
            RequestKind.SUBRESOURCE,
            f"https://{PUBLIC_HOST}/script.js",
            mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
            allowed_origins=(),
        )
    assert guard.attempts == 1 and guard.sends == 0 and transport.sends == []
    # 地址集恢复 public 后同一 guard 仍可 admit。
    resolver.mapping[PUBLIC_HOST] = (PUBLIC_V4,)
    admitted = guard.admit_request(
        RequestKind.SUBRESOURCE,
        f"https://{PUBLIC_HOST}/script.js",
        mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
        allowed_origins=(),
    )
    guard.record_send(RequestKind.SUBRESOURCE, admitted)
    assert guard.sends == 1


def test_dns_rebinding_address_drift_fails_closed():
    guard, resolver, _transport = make_guard()
    guard.admit_request(
        RequestKind.DOCUMENT,
        f"https://{PUBLIC_HOST}/",
        mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
        allowed_origins=(),
    )
    # 同 origin 解析到不同（即便都 public）地址集：rebinding fail closed。
    resolver.mapping[PUBLIC_HOST] = ("198.51.100.7",)
    with pytest.raises(URLPolicyError) as exc_info:
        guard.admit_request(
            RequestKind.SUBRESOURCE,
            f"https://{PUBLIC_HOST}/app.js",
            mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
            allowed_origins=(),
        )
    assert exc_info.value.reason
    # 原地址集恢复后仍拒绝漂移窗口内的后续请求？不——恢复原 digest 应放行。
    resolver.mapping[PUBLIC_HOST] = (PUBLIC_V4,)
    guard.admit_request(
        RequestKind.SUBRESOURCE,
        f"https://{PUBLIC_HOST}/app.js",
        mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
        allowed_origins=(),
    )
    # 纯 admission 不再自动计 send。


def test_site_bound_events_use_current_origin_allowlist():
    guard, _resolver, _transport = make_guard(
        {PUBLIC_HOST: (PUBLIC_V4,), "other.example.test": (PUBLIC_V4,)}
    )
    admitted = guard.admit_request(
        RequestKind.POPUP,
        f"https://{PUBLIC_HOST}/win",
        mode=BrowserMode.SITE_BOUND_INTERACTIVE,
        allowed_origins=(f"https://{PUBLIC_HOST}",),
    )
    guard.record_send(RequestKind.POPUP, admitted)
    with pytest.raises(URLPolicyError):
        guard.admit_request(
            RequestKind.REDIRECT,
            "https://other.example.test/",
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            allowed_origins=(f"https://{PUBLIC_HOST}",),
        )
    assert guard.attempts == 2
    assert guard.sends == 1


def test_constructor_seams_expose_no_permissive_flags():
    guard_parameters = inspect.signature(BrowserEgressGuard.__init__).parameters
    assert "allow_private" not in guard_parameters
    assert "disable_guard" not in guard_parameters
    environment_parameters = inspect.signature(
        PlaywrightBrowserEnvironment.__init__
    ).parameters
    assert "allow_private" not in environment_parameters
    assert "disable_guard" not in environment_parameters


# --------------------------------------------------------------------------- #
# 真实 context/page routing 集成：每类事件都必须经过 adapter 安装的
# route/popup handler，reject 时 abort/close 且 send_count=0。
# --------------------------------------------------------------------------- #


def test_every_event_kind_routes_through_installed_guard():
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import FakeFrame, FakeRequest, Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    environment.open(BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1))
    context = _handle.last_context

    events = [
        {"url": f"https://{PUBLIC_HOST}/doc", "kwargs": {"navigation": True}},
        {"url": f"https://{PUBLIC_HOST}/doc2", "kwargs": {
            "navigation": True,
            "redirected_from": FakeRequest(f"https://{PUBLIC_HOST}/doc", navigation=True),
        }},
        {"url": f"https://{PUBLIC_HOST}/frame", "kwargs": {
            "navigation": True, "frame": FakeFrame(),
        }},
        {"url": f"https://{PUBLIC_HOST}/app.js", "kwargs": {"resource_type": "script"}},
    ]
    for event in events:
        context.emit_request(event["url"], **event["kwargs"])
    context.emit_websocket(f"wss://{PUBLIC_HOST}/ws")
    assert len(journal.calls("route", "fetch")) == 3
    assert len(journal.calls("route", "fulfill")) == 3
    assert len(journal.calls("route", "continue")) == 1
    assert len(journal.calls("websocket", "connect")) == 1
    assert len(journal.calls("route", "abort")) == 0


def test_disallowed_events_abort_with_zero_sends():
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import FakeFrame, FakeRequest, Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    session = environment.open(
        BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1)
    )
    context = _handle.last_context
    bad_events = [
        {"url": f"http://{PUBLIC_HOST}/doc", "kwargs": {"navigation": True}},
        {"url": f"http://{PUBLIC_HOST}/r", "kwargs": {
            "navigation": True,
            "redirected_from": FakeRequest(f"https://{PUBLIC_HOST}/start", navigation=True),
        }},
        {"url": f"http://{PUBLIC_HOST}/f", "kwargs": {
            "navigation": True, "frame": FakeFrame(),
        }},
        {"url": f"http://{PUBLIC_HOST}/x.js", "kwargs": {"resource_type": "script"}},
    ]
    for event in bad_events:
        context.emit_request(event["url"], **event["kwargs"])
    context.emit_websocket(f"ws://{PUBLIC_HOST}/ws")
    environment.observe(session)
    assert len(journal.calls("route", "abort")) == 4
    assert len(journal.calls("websocket", "close")) == 1
    assert len(journal.calls("route", "continue")) == 0
    # guard.send == continue 数：abort 的请求没有 network send。
    assert environment.egress_sends() == 0


def test_document_redirect_target_is_checked_before_target_send() -> None:
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import Journal, make_fake_factory

    journal = Journal()
    handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    environment.open(BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1))
    handle.last_context.emit_request(
        f"https://{PUBLIC_HOST}/start",
        navigation=True,
        response_status=302,
        response_headers={"location": f"http://{PUBLIC_HOST}/blocked"},
    )

    assert len(journal.calls("route", "fetch")) == 1
    assert len(journal.calls("route", "abort")) == 1
    assert len(journal.calls("route", "continue")) == 0
    assert environment.egress_sends() == 1  # 只发送已批准的首跳。
    assert environment.egress_attempts() == 2  # 首跳 + 被拒 redirect target。


def test_websocket_uses_dedicated_preconnect_guard() -> None:
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import Journal, make_fake_factory

    journal = Journal()
    handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    session = environment.open(
        BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1)
    )
    context = handle.last_context
    context.emit_websocket(f"ws://{PUBLIC_HOST}/blocked")
    context.emit_websocket(f"wss://{PUBLIC_HOST}/allowed")
    environment.observe(session)

    assert len(journal.calls("websocket", "close")) == 1
    assert len(journal.calls("websocket", "connect")) == 1
    assert environment.egress_attempts() == 2
    assert environment.egress_sends() == 1


def test_popup_gate_admits_or_closes_popup_pages():
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import FakePage, Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    environment.open(BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1))
    context = _handle.last_context
    allowed_popup = FakePage(None, journal, url=f"https://{PUBLIC_HOST}/popup")
    context.emit_popup(allowed_popup)
    assert allowed_popup.closed is False
    disallowed_popup = FakePage(None, journal, url="http://evil.example.test/")
    context.emit_popup(disallowed_popup)
    assert disallowed_popup.closed is True
    assert journal.calls("page", "close"), "disallowed popup must be closed"


def test_primary_page_event_is_containment_only():
    # context.new_page() 也会触发 on("page")：主 page 不得被 close，
    # containment 不得计入 network send。
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import Journal, make_fake_factory

    journal = Journal()
    handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    environment.open(BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1))
    primary = handle.last_page
    assert primary.closed is False
    assert journal.calls("page", "close") == []
    assert environment.egress_sends() == 0


def test_popup_first_request_gated_by_route_and_containment_no_double_send():
    from agent.browser.contracts import BrowserSessionSpecV1
    from tests.browser.fakes import FakePage, Journal, make_fake_factory

    journal = Journal()
    handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({PUBLIC_HOST: (PUBLIC_V4,)}),
    )
    environment.open(BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1))
    context = handle.last_context
    # popup 的初始请求是 first-request gate：route abort、send=0。
    context.emit_request("http://evil.example.test/popup", navigation=True)
    assert len(journal.calls("route", "abort")) == 1
    assert environment.egress_sends() == 0
    # popup containment 只做清理：close 非 allowlist popup，不重复计 send。
    disallowed_popup = FakePage(None, journal, url="http://evil.example.test/popup")
    context.emit_popup(disallowed_popup)
    assert disallowed_popup.closed is True
    assert environment.egress_sends() == 0
    # about:blank 的 popup 尚未导航，containment 不 close（route 才是 gate）。
    blank_popup = FakePage(None, journal, url="about:blank")
    context.emit_popup(blank_popup)
    assert blank_popup.closed is False
    assert environment.egress_sends() == 0
