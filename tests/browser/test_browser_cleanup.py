"""018 Task 3 Step 4：adapter-owned worker 生命周期 Reds。

close 顺序 page→context→browser→Playwright 并确认 worker exit（join 失败 →
CLEANUP_UNKNOWN）；worker 异常不再杀线程——caller 收到 error 且 handle 被
poison；roundtrip 超时 poison handle；启动失败 fail closed 无 fallback、
无第二次 launch。
"""

import threading

import pytest

from agent.browser.contracts import (
    BrowserActionV1,
    BrowserCleanupOutcome,
    BrowserSessionSpecV1,
)
from agent.browser.playwright_adapter import (
    BrowserCleanupUnknownError,
    BrowserUnavailableError,
    PlaywrightBrowserEnvironment,
)
from tests.browser.fakes import FakeResolver, Journal, make_fake_factory

SPEC = BrowserSessionSpecV1.public_read(goal_id="goal-1", goal_revision=1)


def make_environment(journal: Journal, **kwargs):
    handle, factory = make_fake_factory(journal)
    resolver = FakeResolver({"site.example.test": ("93.184.216.34",)})
    return (
        PlaywrightBrowserEnvironment(
            playwright_factory=factory, resolver=resolver, **kwargs
        ),
        handle,
    )


def navigate_action(observation):
    return BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "https://site.example.test/next",
    )


def test_close_shuts_down_in_order_and_confirms_worker_exit():
    journal = Journal()
    environment, _ = make_environment(journal)
    handle = environment.open(SPEC)
    receipt = environment.close(handle)
    assert receipt.outcome is BrowserCleanupOutcome.CLEANED
    shutdown_order = [
        (target, method)
        for target, method, _kwargs in journal.events
        if (target, method)
        in {
            ("page", "close"),
            ("context", "close"),
            ("browser", "close"),
            ("playwright", "stop"),
        }
    ]
    assert shutdown_order == [
        ("page", "close"),
        ("context", "close"),
        ("browser", "close"),
        ("playwright", "stop"),
    ]
    # close 返回即确认 worker 已退出，且没有 double-close/double-stop。
    assert environment.worker_alive() is False
    assert len(journal.calls("browser", "close")) == 1
    assert len(journal.calls("playwright", "stop")) == 1
    assert len(journal.calls("page", "close")) == 1
    assert len(journal.calls("context", "close")) == 1


def test_clean_close_allows_a_fresh_session_worker() -> None:
    journal = Journal()
    environment, _ = make_environment(journal)
    first = environment.open(SPEC)
    assert environment.close(first).outcome is BrowserCleanupOutcome.CLEANED

    second = environment.open(SPEC)
    assert second.session_ref != first.session_ref
    assert len(journal.calls("factory", "start")) == 2
    assert environment.close(second).outcome is BrowserCleanupOutcome.CLEANED


def test_shutdown_does_not_reclose_an_already_cleaned_session() -> None:
    journal = Journal()
    environment, _ = make_environment(journal)
    handle = environment.open(SPEC)
    assert environment.close(handle).outcome is BrowserCleanupOutcome.CLEANED

    environment.shutdown()

    assert len(journal.calls("page", "close")) == 1
    assert len(journal.calls("playwright", "stop")) == 1


def test_uncertain_cleanup_reports_unknown_and_marks_handle_unusable():
    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    handle = environment.open(SPEC)
    playwright_handle.last_page.fail_on_close = True
    receipt = environment.close(handle)
    assert receipt.outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN
    with pytest.raises(BrowserUnavailableError):
        environment.observe(handle)
    with pytest.raises(BrowserUnavailableError):
        environment.execute(handle, None)


def test_worker_exception_returns_error_and_poisons_handle():
    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    handle = environment.open(SPEC)
    playwright_handle.last_page.nodes = [
        {"ref": "e1", "role": "heading", "name": "Login", "depth": 0},
    ]
    observation = environment.observe(handle)
    playwright_handle.last_page.raise_on_goto = RuntimeError("navigation crashed")
    with pytest.raises(RuntimeError, match="navigation crashed"):
        environment.execute(handle, navigate_action(observation))
    # worker 仍存活；该 handle 被 poison。
    assert environment.worker_alive() is True
    with pytest.raises(BrowserUnavailableError):
        environment.observe(handle)
    with pytest.raises(BrowserUnavailableError):
        environment.execute(handle, None)


def test_poisoned_handle_can_still_be_closed_explicitly():
    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    handle = environment.open(SPEC)
    observation = environment.observe(handle)
    playwright_handle.last_page.raise_on_goto = RuntimeError("navigation crashed")

    with pytest.raises(RuntimeError, match="navigation crashed"):
        environment.execute(handle, navigate_action(observation))

    receipt = environment.close(handle)
    assert receipt.outcome is BrowserCleanupOutcome.CLEANED
    assert environment.worker_alive() is False
    assert len(journal.calls("page", "close")) == 1
    assert len(journal.calls("context", "close")) == 1


def test_shutdown_closes_poisoned_session_instead_of_skipping_cleanup():
    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    handle = environment.open(SPEC)
    observation = environment.observe(handle)
    playwright_handle.last_page.raise_on_goto = RuntimeError("navigation crashed")
    with pytest.raises(RuntimeError, match="navigation crashed"):
        environment.execute(handle, navigate_action(observation))

    environment.shutdown()

    assert environment.worker_alive() is False
    assert len(journal.calls("page", "close")) == 1
    assert len(journal.calls("context", "close")) == 1
    assert len(journal.calls("playwright", "stop")) == 1


def test_roundtrip_timeout_poisons_handle():
    journal = Journal()
    environment, playwright_handle = make_environment(journal, response_timeout=0.5)
    handle = environment.open(SPEC)
    playwright_handle.last_page.nodes = [
        {"ref": "e1", "role": "heading", "name": "Login", "depth": 0},
    ]
    observation = environment.observe(handle)
    release = threading.Event()
    playwright_handle.last_page.hang_on_goto = release
    try:
        with pytest.raises(BrowserUnavailableError) as exc_info:
            environment.execute(handle, navigate_action(observation))
        assert exc_info.value.reason_code == "browser_worker_timeout"
        with pytest.raises(BrowserUnavailableError):
            environment.observe(handle)
    finally:
        release.set()


def test_close_join_failure_returns_cleanup_unknown():
    journal = Journal()
    environment, playwright_handle = make_environment(
        journal, response_timeout=0.5, join_timeout=0.5
    )
    handle = environment.open(SPEC)
    playwright_handle.last_page.hang_on_close = True
    receipt = environment.close(handle)
    assert receipt.outcome is BrowserCleanupOutcome.CLEANUP_UNKNOWN
    # join 失败：worker 仍挂着，receipt 如实 UNKNOWN。
    assert environment.worker_alive() is True


def test_launch_failure_fails_closed_without_fallback():
    journal = Journal()
    _handle, factory = make_fake_factory(journal, launch_error=RuntimeError("no binary"))
    environment = PlaywrightBrowserEnvironment(playwright_factory=factory)
    with pytest.raises(BrowserUnavailableError):
        environment.open(SPEC)
    # 恰好一次 launch 尝试：无重试、无其他浏览器引擎 fallback。
    assert len(journal.calls("chromium", "launch")) == 1
    # 首次 open 失败且无 session：worker fail closed 退出，Playwright scope
    # 恰好 stop 一次——无线程/scope 泄漏。
    assert environment.worker_alive() is False
    assert len(journal.calls("playwright", "stop")) == 1
    with pytest.raises(BrowserCleanupUnknownError, match="open-outcome-unknown"):
        environment.shutdown()


def test_execute_uses_session_mode_and_origins_from_spec():
    # handle 保存 spec 的 mode/allowed_origins；guard 用 session 绑定值而非
    # execute 时硬编码（public-read origins 恒空）。
    journal = Journal()
    environment, playwright_handle = make_environment(journal)
    environment.open(SPEC)
    context = playwright_handle.last_context
    # 直接向 route handler 发事件：必须按 session 的 PUBLIC_READ mode 判定。
    context.emit_request("https://site.example.test/asset.js", resource_type="script")
    continues = journal.calls("route", "continue")
    assert len(continues) == 1
    context.emit_request("http://site.example.test/plain", navigation=True)
    aborts = journal.calls("route", "abort")
    assert len(aborts) == 1
