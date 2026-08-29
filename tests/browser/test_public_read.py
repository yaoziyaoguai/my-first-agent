"""018 Task 3：public-read adapter 的真实-API fake Reds。

base install 无 Playwright 依赖、browser extra 精确 pin、缺包 fail closed；
public-read 只用 headless + fresh non-persistent context（accept_downloads=
False、无 storage-state/extension）、bounded timeouts、route+popup gate 安装、
ARIA refs 经固定 evaluate 脚本、closed action set（fill/upload/download 在
任何 Playwright 调用前拒绝）、navigate 经 guard admit 后才 goto、adapter
不使用任何 fake-only API。
"""

import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionOutcome,
    BrowserActionV1,
    BrowserHandleV1,
    BrowserSessionSpecV1,
)
from agent.browser.playwright_adapter import (
    BrowserActionRefusedError,
    BrowserUnavailableError,
    PlaywrightBrowserEnvironment,
    RequestKind,
    _classify_request,
)
from agent.browser.url_policy import URLPolicyError
from tests.browser.fakes import FakeResolver, Journal, make_fake_factory

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
ADAPTER_SOURCE = Path(
    PlaywrightBrowserEnvironment.__module__.replace(".", "/") + ".py"
)
SPEC = BrowserSessionSpecV1.public_read(goal_id="goal-1", goal_revision=1)


def make_environment(journal: Journal, **kwargs):
    handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        **kwargs,
    )
    return environment, handle


def opened_with_observation(journal: Journal):
    environment, playwright_handle = make_environment(journal)
    handle = environment.open(SPEC)
    page = playwright_handle.last_page
    page.nodes = [
        {"ref": "e1", "role": "heading", "name": "Login", "depth": 0},
        {
            "ref": "e2", "role": "textbox", "name": "Search", "depth": 1,
            "input_type": "search", "value": "",
        },
        {
            "ref": "pw", "role": "textbox", "name": "Password", "depth": 1,
            "input_type": "password", "value": "hunter2-secret",
        },
    ]
    observation = environment.observe(handle)
    return environment, handle, playwright_handle, observation


def test_packaging_keeps_playwright_in_browser_extra_only():
    data = tomllib.loads(PYPROJECT.read_text())
    for dependency in data["project"]["dependencies"]:
        assert "playwright" not in dependency.lower()
    assert data["project"]["optional-dependencies"]["browser"] == ["playwright==1.62.0"]


def test_base_import_does_not_load_playwright():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import agent.browser.playwright_adapter; "
                "raise SystemExit('playwright' in sys.modules)"
            ),
        ],
        check=False,
    )
    assert result.returncode == 0


def test_missing_playwright_package_fails_closed_with_reason(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def without_playwright(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("injected missing optional package")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_playwright)
    environment = PlaywrightBrowserEnvironment()
    qualification = environment.qualify()
    assert qualification.ready is False
    assert qualification.reason_code == "browser_package_missing"
    with pytest.raises(BrowserUnavailableError) as exc_info:
        environment.open(SPEC)
    assert exc_info.value.reason_code == "browser_package_missing"


def test_adapter_source_uses_no_fake_only_api():
    source = ADAPTER_SOURCE.read_text()
    for forbidden in (
        "collect_observation_state",
        "resolve_element",
        "click_ref(",
    ):
        assert forbidden not in source, forbidden


def test_redirected_from_is_a_property_not_callable():
    # 官方 API：Request.redirected_from 是 property；adapter 不得按方法调用。
    from tests.browser.fakes import FakeRequest

    assert isinstance(FakeRequest.redirected_from, property)
    assert ".redirected_from()" not in ADAPTER_SOURCE.read_text()


def test_initial_navigation_without_frame_is_only_document_for_exact_goto_url():
    class InitialNavigationRequest:
        url = "https://site.example.test/start"
        resource_type = "document"
        redirected_from = None

        @staticmethod
        def is_navigation_request() -> bool:
            return True

        @property
        def frame(self):
            raise RuntimeError("frame is not created yet")

    request = InitialNavigationRequest()
    assert (
        _classify_request(
            request,
            explicit_navigation_url="https://site.example.test/start",
        )
        is RequestKind.DOCUMENT
    )
    assert (
        _classify_request(
            request,
            explicit_navigation_url="https://site.example.test/other",
        )
        is RequestKind.POPUP
    )


def test_navigation_from_non_primary_page_is_classified_as_popup() -> None:
    primary_page = object()

    class PopupPage:
        @staticmethod
        def opener():
            return None

    class PopupFrame:
        parent_frame = None
        page = PopupPage()

    class PopupRequest:
        url = "https://site.example.test/popup"
        resource_type = "document"
        redirected_from = None
        frame = PopupFrame()

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    assert (
        _classify_request(
            PopupRequest(),
            explicit_navigation_url=None,
            primary_page=primary_page,
        )
        is RequestKind.POPUP
    )


def test_new_context_blocks_service_workers():
    journal = Journal()
    environment, _ = make_environment(journal)
    environment.open(SPEC)
    context_calls = journal.calls("browser", "new_context")
    assert context_calls[0][2].get("service_workers") == "block"


def test_idle_worker_pumps_browser_events_without_observing() -> None:
    journal = Journal()
    environment, _ = make_environment(journal)
    handle = environment.open(SPEC)
    deadline = time.monotonic() + 1
    while not journal.calls("page", "wait_for_timeout") and time.monotonic() < deadline:
        time.sleep(0.01)

    assert journal.calls("page", "wait_for_timeout")
    assert journal.calls("page", "evaluate") == []
    environment.close(handle)


def test_navigate_send_accounted_once_through_route():
    # 唯一记账 seam：实际导航请求由 context.route admit + record_send；
    # execute 的预检是纯查询，不得产生 preflight 双计数。
    journal = Journal()
    environment, handle, _playwright_handle, observation = opened_with_observation(journal)
    action = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "https://site.example.test/docs",
    )
    receipt = environment.execute(handle, action)
    assert receipt.executed is True
    assert len(journal.calls("route", "fetch")) == 1
    assert len(journal.calls("route", "fulfill")) == 1
    assert len(journal.calls("route", "continue")) == 0
    assert environment.egress_attempts() == 1
    assert environment.egress_sends() == 1


def test_disallowed_redirect_settles_as_executed_blocked_outcome() -> None:
    journal = Journal()
    environment, handle, playwright_handle, observation = opened_with_observation(
        journal
    )
    url = "https://site.example.test/redirect"
    playwright_handle.last_page.goto_responses[url] = (
        302,
        {"location": "http://site.example.test/blocked"},
    )
    action = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        url,
    )

    receipt = environment.execute(handle, action)

    assert receipt.executed is True
    assert receipt.outcome is BrowserActionOutcome.EFFECT_BLOCKED
    assert environment.egress_sends() == 1
    assert environment.egress_attempts() == 2


def test_duplicate_role_name_click_is_known_not_executed():
    from agent.runtime.contracts import KnownNotExecuted

    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    handle = environment.open(SPEC)
    playwright_handle.last_page.nodes = [
        {"ref": "e1", "role": "link", "name": "Open", "depth": 0},
        {"ref": "e2", "role": "link", "name": "Open", "depth": 0},
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1.click(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "e1",
    )
    result = environment.execute(handle, action)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "browser_target_ambiguous"
    assert journal.calls("page", "click") == []


def test_public_read_uses_headless_fresh_non_persistent_context():
    journal = Journal()
    environment, _ = make_environment(journal)
    handle = environment.open(SPEC)
    assert isinstance(handle, BrowserHandleV1)
    launch_calls = journal.calls("chromium", "launch")
    assert len(launch_calls) == 1
    assert launch_calls[0][2].get("headless") is True
    context_calls = journal.calls("browser", "new_context")
    assert len(context_calls) == 1
    kwargs = context_calls[0][2]
    assert kwargs.get("accept_downloads") is False
    assert "storage_state" not in kwargs
    assert not any("extension" in key for key in kwargs)
    assert journal.calls("browser", "launch_persistent_context") == []


def test_context_installs_routing_and_popup_gate():
    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    environment.open(SPEC)
    route_calls = journal.calls("context", "route")
    assert len(route_calls) == 1
    assert route_calls[0][2].get("pattern") == "**/*"
    on_calls = journal.calls("context", "on")
    assert on_calls and all(call[2].get("event") == "page" for call in on_calls)


def test_timeouts_are_bounded_nonzero_and_capped():
    journal = Journal()
    environment, _ = make_environment(journal)
    environment.open(SPEC)
    timeout_events = journal.method_called("set_default_timeout") + journal.method_called(
        "set_default_navigation_timeout"
    )
    assert timeout_events, "adapter 必须显式设置 timeouts"
    for _target, _method, kwargs in timeout_events:
        milliseconds = kwargs["milliseconds"]
        assert 0 < milliseconds <= 30_000


def test_observe_collects_refs_via_fixed_evaluate_script():
    journal = Journal()
    environment, handle, playwright_handle, observation = opened_with_observation(journal)
    assert "Login" in observation.aria_projection
    assert observation.canonical_origin == "https://site.example.test"
    assert observation.element_refs[0].ref == "e1"
    assert observation.element_refs[1].value_empty is True
    # password 的 value 与 value_empty 都不投影。
    assert observation.element_refs[2].value_empty is None
    assert "hunter2-secret" not in observation.aria_projection
    assert len(observation.observation_digest) == 64
    evaluate_calls = journal.calls("page", "evaluate")
    assert evaluate_calls and all(call[2].get("marker") for call in evaluate_calls)


def test_public_read_rejects_write_actions_before_any_playwright_call():
    journal = Journal()
    environment, handle, _playwright_handle, observation = opened_with_observation(journal)
    refused = [
        BrowserActionV1.fill_form(
            observation.observation_digest, observation.page_id, observation.frame_id,
            "e1", {"q": "hello"},
        ),
        BrowserActionV1(
            kind=BrowserActionKind.UPLOAD,
            observation_digest=observation.observation_digest,
            page_id=observation.page_id,
            frame_id=observation.frame_id,
            target_ref="e1",
        ),
        BrowserActionV1(
            kind=BrowserActionKind.DOWNLOAD,
            observation_digest=observation.observation_digest,
            page_id=observation.page_id,
            frame_id=observation.frame_id,
            target_ref="e1",
        ),
    ]
    page_events_before = len(
        [event for event in journal.events if event[0] in {"page", "mouse"}]
    )
    for action in refused:
        with pytest.raises(BrowserActionRefusedError):
            environment.execute(handle, action)
    page_events_after = len(
        [event for event in journal.events if event[0] in {"page", "mouse"}]
    )
    assert page_events_after == page_events_before


def test_navigate_admits_url_then_gotos_canonical():
    journal = Journal()
    environment, handle, _playwright_handle, observation = opened_with_observation(journal)
    action = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "https://site.example.test/docs",
    )
    receipt = environment.execute(handle, action)
    assert receipt.executed is True
    assert receipt.pre_observation_digest == observation.observation_digest
    assert receipt.post_observation_digest
    goto_calls = journal.calls("page", "goto")
    assert len(goto_calls) == 1
    assert goto_calls[0][2]["url"] == "https://site.example.test/docs"


def test_navigate_rejects_disallowed_url_before_playwright():
    journal = Journal()
    environment, handle, _playwright_handle, observation = opened_with_observation(journal)
    action = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "http://site.example.test/plain",
    )
    with pytest.raises(URLPolicyError):
        environment.execute(handle, action)
    assert journal.calls("page", "goto") == []


def test_click_uses_role_locator_after_re_resolve():
    journal = Journal()
    environment, handle, _playwright_handle, observation = opened_with_observation(journal)
    action = BrowserActionV1.click(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "e1",
    )
    receipt = environment.execute(handle, action)
    assert receipt.executed is True
    click_calls = journal.calls("page", "click")
    assert len(click_calls) == 1
    assert click_calls[0][2] == {"role": "heading", "name": "Login"}


def test_click_with_drifted_element_is_known_not_executed():
    from agent.runtime.contracts import KnownNotExecuted

    journal = Journal()
    environment, handle, playwright_handle, observation = opened_with_observation(journal)
    # observe 之后 fixture 改了元素 role：re-resolve 发现漂移。
    playwright_handle.last_page.nodes[0]["role"] = "button"
    action = BrowserActionV1.click(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "e1",
    )
    result = environment.execute(handle, action)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "click") == []


def test_scroll_uses_mouse_wheel():
    journal = Journal()
    environment, handle, _playwright_handle, observation = opened_with_observation(journal)
    action = BrowserActionV1(
        kind=BrowserActionKind.SCROLL,
        observation_digest=observation.observation_digest,
        page_id=observation.page_id,
        frame_id=observation.frame_id,
    )
    receipt = environment.execute(handle, action)
    assert receipt.executed is True
    wheel_calls = journal.calls("mouse", "wheel")
    assert len(wheel_calls) == 1
