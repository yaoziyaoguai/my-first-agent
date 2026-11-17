"""2026-11-17 审计修复：浏览器准入 DNS rebinding 单次窗口（P3）。

site-bound 的 Chromium 按 session 启动且准入集合恰为 launch 时已知的
exact allowlist（policy 对每类 request 都要求 origin ∈ allowlist）——
launch 边界把每个 allowlist host 钉到本次准入已验证 public 的首选地址
（Chromium --host-resolver-rules MAP host ip），连接层不再二次解析；
Host/SNI/证书校验仍按原域名进行，未 MAP 的 host 照常走 request admission。
public-read 的准入集合由页面内容动态发现，launch 时不可知，不 pin 也不
伪造部分覆盖；解析/判据失败在启动/接管 Chromium 之前 fail closed。
"""

import contextlib
import os

import pytest

from agent.browser.contracts import (
    BrowserMode,
    BrowserSessionSpecV1,
    LoopbackOriginBindingV1,
)
from agent.browser.playwright_adapter import (
    BrowserEgressGuard,
    BrowserUnavailableError,
    PlaywrightBrowserEnvironment,
    RequestKind,
)
from agent.browser.url_policy import URLPolicyError
from tests.browser.fakes import (
    FakeResolver,
    FakeTransport,
    Journal,
    make_fake_factory,
)

HOST_A = "site.example.test"
HOST_B = "other.example.test"
IP_A1 = "93.184.216.34"
IP_A2 = "93.184.216.35"
IP_B1 = "8.8.8.8"


def make_environment(tmp_path, journal, mapping):
    # profile root 由 profile-store owner 预先建立（0700）。
    root = tmp_path / "profiles"
    with contextlib.suppress(FileExistsError):
        os.mkdir(root, 0o700)
    resolver = FakeResolver(mapping)
    _handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=resolver,
        profile_root=root,
    )
    return environment, resolver


def site_bound_spec(origins):
    return BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-0123456789abcdef",
        allowed_origins=tuple(origins),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="a" * 64,
        expiry_monotonic=1e18,
    )


def launch_args_of(call):
    return list(call[2].get("args", ()))


def host_resolver_rule(call):
    matches = [
        arg for arg in launch_args_of(call) if arg.startswith("--host-resolver-rules=")
    ]
    assert len(matches) == 1, "exactly one host-resolver-rules arg per launch"
    return matches[0][len("--host-resolver-rules=") :]


def test_site_bound_open_pins_each_allowlist_host_to_first_verified_address(
    tmp_path,
):
    journal = Journal()
    environment, _resolver = make_environment(
        tmp_path,
        journal,
        {HOST_A: (IP_A1, IP_A2), HOST_B: (IP_B1,)},
    )

    environment.open(site_bound_spec((f"https://{HOST_A}", f"https://{HOST_B}")))

    launches = journal.calls("chromium", "launch_persistent_context")
    assert len(launches) == 1
    rules = host_resolver_rule(launches[0])
    # 覆盖恰为 allowlist host 集：每个 host 恰好一条 MAP，多地址集合只取
    # resolver 顺序首选（其余 answer 永不用于连接）。
    assert rules == f"MAP {HOST_A} {IP_A1}, MAP {HOST_B} {IP_B1}"


def test_site_bound_open_fails_closed_before_launch_when_pin_unverifiable(tmp_path):
    journal = Journal()
    environment, resolver = make_environment(
        tmp_path, journal, {HOST_A: (IP_A1,), HOST_B: (IP_B1,)}
    )

    # 任一 allowlist origin 解析失败 / answer 非 public：启动 Chromium 之前
    # fail closed，零 launch、零 session（与 profile_root_missing 同一
    # worker-open 错误合同：BrowserUnavailableError + closed reason）。
    resolver.mapping[HOST_B] = ("10.0.0.5",)
    with pytest.raises(BrowserUnavailableError) as private_error:
        environment.open(site_bound_spec((f"https://{HOST_A}", f"https://{HOST_B}")))
    assert private_error.value.reason_code == "browser_dns_pin_failed"

    journal2 = Journal()
    environment2, _resolver2 = make_environment(
        tmp_path, journal2, {HOST_A: (IP_A1,), HOST_B: ()}
    )
    with pytest.raises(BrowserUnavailableError) as unresolvable_error:
        environment2.open(site_bound_spec((f"https://{HOST_A}", f"https://{HOST_B}")))
    assert unresolvable_error.value.reason_code == "browser_dns_pin_failed"

    assert journal.calls("chromium", "launch_persistent_context") == []
    assert journal2.calls("chromium", "launch_persistent_context") == []


def test_public_read_and_task_loopback_launches_pin_nothing(tmp_path):
    journal = Journal()
    environment, _resolver = make_environment(
        tmp_path, journal, {HOST_A: (IP_A1,)}
    )
    environment.open(BrowserSessionSpecV1.public_read(goal_id="g", goal_revision=1))
    launches = journal.calls("chromium", "launch")
    assert len(launches) == 1
    # 动态准入集合 launch 时不可知：不得伪造部分 MAP 覆盖。
    assert launch_args_of(launches[0]) == []

    loopback_journal = Journal()
    binding = LoopbackOriginBindingV1(
        resource_ref="managed-web-1",
        origin="http://127.0.0.1:43123",
        goal_id="goal-1",
        goal_revision=1,
        process_group_id=4321,
        command_fingerprint="c" * 64,
        issued_monotonic=100.0,
        expires_monotonic=1e18,
    )
    loopback_environment = PlaywrightBrowserEnvironment(
        playwright_factory=make_fake_factory(loopback_journal)[1],
        resolver=FakeResolver({}),
        loopback_verifier=lambda candidate: candidate == binding,
    )
    loopback_environment.open(
        BrowserSessionSpecV1.task_loopback(
            goal_id="goal-1", goal_revision=1, binding=binding
        )
    )
    # task-loopback 是 127.0.0.1 IP literal，没有 DNS 解析层，无 pin 需求。
    assert launch_args_of(journal.calls("chromium", "launch")[0]) == []
    assert launch_args_of(
        loopback_journal.calls("chromium", "launch")[0]
    ) == []


def test_takeover_relaunch_pins_the_same_allowlist_hosts(tmp_path):
    journal = Journal()
    environment, _resolver = make_environment(
        tmp_path, journal, {HOST_A: (IP_A1,)}
    )
    handle = environment.open(site_bound_spec((f"https://{HOST_A}",)))

    environment.begin_takeover(handle)

    launches = journal.calls("chromium", "launch_persistent_context")
    assert [call[2]["headless"] for call in launches] == [True, False]
    assert host_resolver_rule(launches[0]) == f"MAP {HOST_A} {IP_A1}"
    assert host_resolver_rule(launches[1]) == f"MAP {HOST_A} {IP_A1}"


def test_takeover_pin_failure_blocks_before_destroying_headless_context(tmp_path):
    journal = Journal()
    environment, resolver = make_environment(tmp_path, journal, {HOST_A: (IP_A1,)})
    handle = environment.open(site_bound_spec((f"https://{HOST_A}",)))

    # 接管前 DNS 漂移到内网：fresh 重新解析必须 fail closed，且失败发生在
    # 关闭旧 headless context 之前。
    resolver.mapping[HOST_A] = ("10.0.0.9",)
    with pytest.raises(BrowserUnavailableError) as error:
        environment.begin_takeover(handle)
    assert error.value.reason_code == "browser_dns_pin_failed"
    assert journal.calls("context", "close") == []
    assert len(journal.calls("chromium", "launch_persistent_context")) == 1
    # session 已 fail closed（poison），不得继续 observe。
    with pytest.raises(BrowserUnavailableError, match="browser_session_unusable"):
        environment.observe(handle)


def test_guard_launch_pins_are_not_request_events():
    guard = BrowserEgressGuard(
        resolver=FakeResolver({HOST_A: (IP_A1, IP_A2)}), transport=FakeTransport()
    )

    pins = guard.launch_dns_pins(
        mode=BrowserMode.SITE_BOUND_INTERACTIVE,
        allowed_origins=(f"https://{HOST_A}",),
    )
    assert pins == ((HOST_A, IP_A1),)
    # 非 site-bound 的动态准入流不 pin。
    assert (
        guard.launch_dns_pins(
            mode=BrowserMode.PUBLIC_READ_EPHEMERAL, allowed_origins=(f"https://{HOST_A}",)
        )
        == ()
    )
    assert (
        guard.launch_dns_pins(
            mode=BrowserMode.TASK_LOOPBACK_EPHEMERAL, allowed_origins=()
        )
        == ()
    )
    # launch pin 不是 request 事件：不计数、不播种 rebinding 漂移记录。
    assert guard.attempts == 0 and guard.sends == 0
    guard.admit_request(
        RequestKind.SUBRESOURCE,
        f"https://{HOST_A}/app.js",
        mode=BrowserMode.SITE_BOUND_INTERACTIVE,
        allowed_origins=(f"https://{HOST_A}",),
    )
    assert guard.attempts == 1


def test_guard_launch_pin_rejects_non_public_or_empty_answers():
    guard = BrowserEgressGuard(
        resolver=FakeResolver({HOST_A: (IP_A1, "10.0.0.5")}), transport=FakeTransport()
    )
    with pytest.raises(URLPolicyError, match="non_public_address"):
        guard.launch_dns_pins(
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            allowed_origins=(f"https://{HOST_A}",),
        )
    guard = BrowserEgressGuard(
        resolver=FakeResolver({}), transport=FakeTransport()
    )
    with pytest.raises(URLPolicyError, match="no_dns_answer"):
        guard.launch_dns_pins(
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            allowed_origins=(f"https://{HOST_A}",),
        )
