"""018 Task 8：optional browser composition 的 Reds。

base 启动不依赖 Playwright；显式 browser 配置只做 read-only closed
qualification；缺 package/bundled Chromium binary/profile 权限/egress
readiness 各给恰好一条 closed reason + 零 registration；无 Chrome/Safari/
CDP fallback；closeables 真正关闭 composition 拥有的 session/worker；
签名不含 allow_private/disable_guard。
"""

import inspect

import pytest

from agent.composition import (
    BrowserReadiness,
    BrowserResources,
    build_browser_resources,
)


def test_signature_has_no_permissive_knobs():
    parameters = inspect.signature(build_browser_resources).parameters
    assert "allow_private" not in parameters
    assert "disable_guard" not in parameters


def test_disabled_build_yields_zero_registrations_and_not_enabled(tmp_path):
    resources = build_browser_resources(
        tmp_path, tmp_path / "state", enabled=False,
    )
    assert isinstance(resources, BrowserResources)
    assert resources.registrations == ()
    assert resources.readiness is BrowserReadiness.NOT_ENABLED
    assert resources.reason_code is None
    assert resources.closeables == ()


def test_missing_playwright_package_fails_closed_with_one_reason(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def without_playwright(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("injected missing optional package")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_playwright)
    resources = build_browser_resources(
        tmp_path, tmp_path / "state", enabled=True,
    )
    assert resources.registrations == ()
    assert resources.readiness is BrowserReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "browser_package_missing"


def test_public_signature_is_exactly_frozen(monkeypatch):

    signature = inspect.signature(build_browser_resources)
    assert list(signature.parameters) == [
        "workspace",
        "state_root",
        "enabled",
        "resolver",
        "playwright_factory",
    ]
    assert signature.parameters["enabled"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["resolver"].default is None
    assert signature.parameters["playwright_factory"].default is None


def test_missing_bundled_chromium_binary_fails_closed(tmp_path, monkeypatch):
    import agent.composition as composition_module
    from tests.browser.fakes import Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    # factory 注入绕过 package probe；私有 binary seam 注入 False →
    # browser_binary_missing + 零 registration（binary 判据独立生效）。
    monkeypatch.setattr(
        composition_module,
        "_browser_binary_available_for_factory",
        lambda: False,
    )
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state",
        enabled=True,
        playwright_factory=factory,
    )
    assert resources.registrations == ()
    assert resources.readiness is BrowserReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "browser_binary_missing"


def test_default_binary_probe_contains_playwright_driver_lifecycle(
    tmp_path, monkeypatch, capsys
):
    import subprocess

    import agent.composition as composition_module

    executable = tmp_path / "chromium"
    executable.write_bytes(b"binary")
    calls = []

    def isolated_probe(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=str(executable) + "\n",
            stderr="driver lifecycle warning contained in child\n",
        )

    monkeypatch.setattr(subprocess, "run", isolated_probe)

    assert composition_module._default_browser_binary_available() is True
    assert len(calls) == 1
    assert calls[0][1]["capture_output"] is True
    assert calls[0][1]["text"] is True
    assert capsys.readouterr() == ("", "")


def test_egress_not_ready_fails_closed(tmp_path, monkeypatch):
    import agent.composition as composition_module
    from tests.browser.fakes import Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    monkeypatch.setattr(
        composition_module, "_browser_binary_available_for_factory", lambda: True
    )
    monkeypatch.setattr(
        composition_module, "_BROWSER_EGRESS_SEAM", lambda resolver: False
    )
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state",
        enabled=True,
        playwright_factory=factory,
    )
    assert resources.registrations == ()
    assert resources.readiness is BrowserReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "browser_egress_unavailable"


def test_injected_fake_factory_yields_ready_registrations_and_reverse_close(tmp_path, monkeypatch):
    import agent.composition as composition_module
    from tests.browser.fakes import Journal, make_fake_factory

    journal = Journal()
    _handle, factory = make_fake_factory(journal)
    monkeypatch.setattr(
        composition_module, "_browser_binary_available_for_factory", lambda: True
    )
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state",
        enabled=True,
        playwright_factory=factory,
    )
    assert resources.readiness is BrowserReadiness.READY
    assert resources.reason_code is None
    assert [r.spec.name for r in resources.registrations] == [
        "browser_open",
        "browser_observe",
        "browser_act",
        "browser_close",
        "browser_begin_takeover",
    ]
    # closeables 全部可执行；read-only qualification 不启动 worker。
    for closeable in resources.closeables:
        closeable()
    assert resources.registrations != ()


def test_composition_gives_adapter_and_tools_the_same_quarantine(tmp_path, monkeypatch):
    import agent.browser.playwright_adapter as adapter_module
    import agent.composition as composition_module

    captured = {}

    class RecordingEnvironment:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def shutdown(self):
            return None

    monkeypatch.setattr(
        composition_module, "_browser_binary_available_for_factory", lambda: True
    )
    monkeypatch.setattr(adapter_module, "PlaywrightBrowserEnvironment", RecordingEnvironment)
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state-quarantine",
        enabled=True,
        playwright_factory=lambda: None,
    )

    tool_owner = resources.registrations[2].func.__self__
    assert captured["quarantine"] is tool_owner._quarantine


def test_profile_root_bad_permissions_give_single_closed_reason(tmp_path):
    state_root = tmp_path / "state"
    state_root.mkdir()
    profiles = state_root / "browser" / "profiles"
    profiles.mkdir(parents=True)
    profiles.chmod(0o755)  # 过宽：owner-only 合同被破坏
    from tests.browser.fakes import Journal, make_fake_factory

    _handle, factory = make_fake_factory(Journal())
    resources = build_browser_resources(
        tmp_path, state_root, enabled=True, playwright_factory=factory,
    )
    assert resources.registrations == ()
    assert resources.readiness is BrowserReadiness.TEMPORARILY_UNAVAILABLE
    assert resources.reason_code == "browser_profile_permissions"


@pytest.mark.parametrize("dangling", [False, True])
def test_profile_root_symlink_fails_closed(tmp_path, dangling):
    state_root = tmp_path / "state"
    target = tmp_path / "profile-target"
    if not dangling:
        target.mkdir()
    profiles = state_root / "browser" / "profiles"
    profiles.parent.mkdir(parents=True)
    profiles.symlink_to(target, target_is_directory=True)
    from tests.browser.fakes import Journal, make_fake_factory

    _handle, factory = make_fake_factory(Journal())
    resources = build_browser_resources(
        tmp_path, state_root, enabled=True, playwright_factory=factory,
    )

    assert resources.registrations == ()
    assert resources.reason_code == "browser_profile_permissions"


def test_browser_resources_exposes_only_runtime_takeover_completion_port():
    from dataclasses import fields

    assert {item.name for item in fields(BrowserResources)} == {
        "registrations",
        "closeables",
        "readiness",
        "reason_code",
        "complete_takeover",
    }


def test_closeables_close_resource_owned_session_and_worker(tmp_path, monkeypatch):
    # 经 resources.registrations 的 governed browser_open/observe/close 路径
    # （真实 KernelToolRuntime + approval）打开并关闭 composition 拥有的
    # session；closeables 必须关闭 worker（journal 观察 stop 恰一次）。
    import agent.composition as composition_module
    from agent.runtime.contracts import (
        ApprovalGrant,
        ToolCall,
        ToolResult,
    )
    from agent.runtime.tools import KernelToolRuntime
    from tests.browser.fakes import FakeResolver, Journal, make_fake_factory
    from tests.browser.test_tools import _context

    journal = Journal()
    _playwright_handle, factory = make_fake_factory(journal)
    monkeypatch.setattr(
        composition_module, "_browser_binary_available_for_factory", lambda: True
    )
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state-owned",
        enabled=True,
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
    )
    assert resources.readiness is BrowserReadiness.READY
    runtime = KernelToolRuntime(
        resources.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    open_call = ToolCall(
        "open-1", "browser_open", {"mode": "public_read_ephemeral"}
    )
    approval = runtime.prepare(open_call, _context())
    prepared_open = runtime.prepare(
        open_call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    opened = runtime.invoke(prepared_open)
    assert isinstance(opened, ToolResult)
    session_ref = opened.metadata["session_ref"]
    observe_call = ToolCall(
        "observe-1", "browser_observe", {"session_ref": session_ref}
    )
    observed = runtime.invoke(runtime.prepare(observe_call, _context()))
    assert observed.metadata["browser_result_kind"] == "browser_observe"
    # session worker 打开：journal 已记录 launch/factory start。
    assert len(journal.calls("chromium", "launch")) == 1
    for closeable in resources.closeables:
        closeable()
    # closeables 关闭 composition 拥有的 session/worker：Playwright stop 恰一次。
    assert len(journal.calls("playwright", "stop")) == 1


def test_shutdown_fails_closed_when_session_cleanup_unknown(tmp_path, monkeypatch):
    # closeable 路径的真实失败回归：page.close 失败 → cleanup UNKNOWN →
    # shutdown 必须 fail closed（不伪装成功）；session 已 unusable。
    import agent.composition as composition_module
    from agent.browser.playwright_adapter import BrowserCleanupUnknownError
    from agent.runtime.contracts import ApprovalGrant, ToolCall, ToolResult
    from agent.runtime.tools import KernelToolRuntime
    from tests.browser.fakes import FakeResolver, Journal, make_fake_factory
    from tests.browser.test_tools import _context

    journal = Journal()
    playwright_handle, factory = make_fake_factory(journal)
    monkeypatch.setattr(
        composition_module, "_browser_binary_available_for_factory", lambda: True
    )
    resources = build_browser_resources(
        tmp_path,
        tmp_path / "state-fail",
        enabled=True,
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
    )
    runtime = KernelToolRuntime(
        resources.registrations, clock=lambda: "2026-08-28T10:00:00+00:00"
    )
    open_call = ToolCall(
        "open-1", "browser_open", {"mode": "public_read_ephemeral"}
    )
    approval = runtime.prepare(open_call, _context())
    prepared_open = runtime.prepare(
        open_call,
        _context(),
        approval=ApprovalGrant(
            request_id=approval.request.request_id,
            binding_digest=approval.request.binding_digest,
            approval_basis_revision=7,
        ),
    )
    opened = runtime.invoke(prepared_open)
    assert isinstance(opened, ToolResult)
    # 注入 page.close 失败 → 该 session cleanup 必为 UNKNOWN。
    playwright_handle.last_page.fail_on_close = True
    with pytest.raises(BrowserCleanupUnknownError):
        for closeable in resources.closeables:
            closeable()
