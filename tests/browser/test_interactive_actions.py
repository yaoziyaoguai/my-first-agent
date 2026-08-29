"""018 Task 4 Step 2/4：site-bound interactive actions 与 binding revalidation Reds。

site-bound open 只用 owner profile root 的 persistent context + exact origins；
effect 前立即 re-resolve（同一固定 evaluate 脚本）并比对完整 binding——
observation/element/origin/params 任一漂移只返回冻结的
KnownNotExecuted(stale_browser_target|browser_binding_changed) 且零
action/network effect；只用 role/label locator 语义（fill/select_option/
get_by_role().click）。
"""

import pytest

from agent.browser.action_policy import BrowserActionPolicy
from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionV1,
    BrowserSessionSpecV1,
)
from agent.browser.playwright_adapter import (
    BrowserActionRefusedError,
    BrowserUnavailableError,
    PlaywrightBrowserEnvironment,
)
from agent.runtime.contracts import KnownNotExecuted
from tests.browser.fakes import FakeResolver, Journal, make_fake_factory

ORIGIN = "https://site.example.test"
PROFILE_REF = "profile-0123456789abcdef"
SPEC = BrowserSessionSpecV1.site_bound(
    goal_id="goal-1",
    goal_revision=1,
    profile_ref=PROFILE_REF,
    allowed_origins=(ORIGIN,),
    action_budget=8,
        profile_revision=1,
        browser_identity_digest="a" * 64,
        expiry_monotonic=1e18,
)
PUBLIC_SPEC = BrowserSessionSpecV1.public_read(goal_id="goal-2", goal_revision=1)


def make_environment(tmp_path, journal, **kwargs):
    import contextlib
    import os as _os

    # profile root 由 profile-store owner 预先建立（0700）；adapter 只做
    # closed validate + no-follow 校验，不创建 root。
    root = tmp_path / "profiles"
    with contextlib.suppress(FileExistsError):
        _os.mkdir(root, 0o700)
    playwright_handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        profile_root=root,
        **kwargs,
    )
    return environment, playwright_handle


def open_interactive(tmp_path, journal, nodes=None):
    environment, playwright_handle = make_environment(tmp_path, journal)
    handle = environment.open(SPEC)
    playwright_handle.last_page.nodes = nodes or [
        {
            "ref": "e1", "role": "textbox", "name": "Search", "depth": 0,
            "input_type": "text",
        },
        {
            "ref": "e2", "role": "button", "name": "Sign in", "depth": 0,
            "input_type": "submit", "form_action": f"{ORIGIN}/login",
        },
    ]
    observation = environment.observe(handle)
    return environment, handle, playwright_handle, observation


def test_site_bound_open_uses_owner_profile_persistent_context(tmp_path):
    journal = Journal()
    environment, _ = make_environment(tmp_path, journal)
    handle = environment.open(SPEC)
    assert handle.mode.value == "site_bound_interactive"
    persistent = journal.calls("chromium", "launch_persistent_context")
    assert len(persistent) == 1
    user_data_dir = persistent[0][2].get("user_data_dir", "")
    assert user_data_dir.startswith(str(tmp_path / "profiles"))
    assert PROFILE_REF in user_data_dir
    assert persistent[0][2].get("service_workers") == "block"
    # 自动化阶段不可提前显示 headed window；只有 Runtime 已 durable-save
    # takeover pending 后，显式 begin_takeover 才能切换到 headed。
    assert persistent[0][2].get("headless") is True
    assert journal.calls("browser", "new_context") == []


def test_takeover_relaunches_same_profile_headed_only_after_explicit_transition(tmp_path):
    journal = Journal()
    environment, _ = make_environment(tmp_path, journal)
    handle = environment.open(SPEC)
    assert environment.takeover_session_active(handle.session_ref) is False

    environment.begin_takeover(handle)
    assert environment.takeover_session_active(handle.session_ref) is True

    launches = journal.calls("chromium", "launch_persistent_context")
    assert [call[2]["headless"] for call in launches] == [True, False]
    assert environment.persistent_context_launch_modes() == (True, False)
    assert launches[0][2]["user_data_dir"] == launches[1][2]["user_data_dir"]
    assert journal.calls("page", "close")
    assert journal.calls("context", "close")
    assert journal.calls("page", "goto")[-1][2]["url"] == f"{ORIGIN}/page"


def test_adapter_uses_browsertype_persistent_api_only():
    # 真实 Playwright：launch_persistent_context 属于 chromium（BrowserType），
    # 不属于 browser 实例——fake 保留 browser 级断言防走错 surface。
    from pathlib import Path

    from agent.browser.playwright_adapter import PlaywrightBrowserEnvironment

    source = Path(
        PlaywrightBrowserEnvironment.__module__.replace(".", "/") + ".py"
    ).read_text()
    assert "browser.launch_persistent_context" not in source
    assert "chromium.launch_persistent_context" in source


def test_site_bound_requires_profile_root(tmp_path):
    journal = Journal()
    _playwright_handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
    )
    with pytest.raises(BrowserUnavailableError) as exc_info:
        environment.open(SPEC)
    assert exc_info.value.reason_code == "browser_profile_root_missing"


def test_site_bound_confines_exact_origins(tmp_path):
    journal = Journal()
    environment, playwright_handle = make_environment(tmp_path, journal)
    environment.open(SPEC)
    context = playwright_handle.last_context
    sends_before = environment.egress_sends()
    context.emit_request(f"{ORIGIN}/doc", navigation=True)
    fetches = journal.calls("route", "fetch")
    assert len(fetches) == 1
    assert fetches[0][2]["max_redirects"] == 0
    assert len(journal.calls("route", "fulfill")) == 1
    assert environment.egress_sends() == sends_before + 1
    context.emit_request("https://other.example.test/x", navigation=True)
    assert len(journal.calls("route", "abort")) == 1


def test_fill_form_executes_with_role_locator_and_receipt(tmp_path):
    journal = Journal()
    environment, handle, _playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    assert binding.consequence.value == "disclose"
    receipt = environment.execute(handle, action, binding=binding)
    assert receipt.executed is True
    fills = journal.calls("page", "fill")
    assert len(fills) == 1
    assert fills[0][2]["role"] == "textbox"
    assert fills[0][2]["name"] == "Search"
    assert fills[0][2]["value"] == "hello"


def test_select_executes_via_role_locator(tmp_path):
    journal = Journal()
    environment, handle, _playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1(
        kind=BrowserActionKind.SELECT,
        observation_digest=observation.observation_digest,
        page_id=observation.page_id,
        frame_id=observation.frame_id,
        target_ref="e1",
        params={"value": "option-a"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    receipt = environment.execute(handle, action, binding=binding)
    assert receipt.executed is True
    selects = journal.calls("page", "select_option")
    assert len(selects) == 1
    assert selects[0][2]["value"] == "option-a"


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda page: page.nodes[0].update(role="combobox"), id="role-drift"),
        pytest.param(lambda page: page.nodes[0].update(name="Query"), id="name-drift"),
        pytest.param(
            lambda page: page.nodes[0].update(form_action="https://evil.example.test/x"),
            id="form-action-drift",
        ),
        pytest.param(
            lambda page: page.goto("https://other.example.test/drifted"),
            id="origin-drift",
        ),
    ],
)
def test_drifted_targets_are_known_not_executed_with_zero_effect(tmp_path, mutation):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    # effect 前页面漂移。
    mutation(playwright_handle.last_page)
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "fill") == []
    assert journal.calls("page", "click") == []


def test_changed_action_params_return_binding_changed(tmp_path):
    from dataclasses import replace

    journal = Journal()
    environment, handle, _playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    tampered = replace(action, params={"fields": {"Search": "evil"}})
    result = environment.execute(handle, tampered, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "browser_binding_changed"
    assert journal.calls("page", "fill") == []


def test_navigation_receipt_waits_out_one_destroyed_execution_context(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(
        tmp_path, journal
    )
    page = playwright_handle.last_page
    page.fail_on_nth_evaluate = page._evaluate_calls + 2
    page.evaluate_error = RuntimeError(
        "Execution context was destroyed, most likely because of a navigation"
    )
    action = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        f"{ORIGIN}/next",
    )
    binding = BrowserActionPolicy.prepare(observation, action)

    receipt = environment.execute(handle, action, binding=binding)

    assert receipt.executed is True
    assert len(journal.calls("page", "wait_for_timeout")) == 1


def test_double_use_binding_returns_binding_changed(tmp_path):
    journal = Journal()
    environment, handle, _playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    first = environment.execute(handle, action, binding=binding)
    assert first.executed is True
    second = environment.execute(handle, action, binding=binding)
    assert isinstance(second, KnownNotExecuted)
    assert second.code == "browser_binding_changed"
    # fill 只发生一次。
    assert len(journal.calls("page", "fill")) == 1


def test_public_read_refuses_interactive_actions(tmp_path):
    journal = Journal()
    environment, playwright_handle = make_environment(tmp_path, journal)
    handle = environment.open(PUBLIC_SPEC)
    playwright_handle.last_page.nodes = [
        {"ref": "e1", "role": "textbox", "name": "Search", "depth": 0},
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    with pytest.raises(BrowserActionRefusedError):
        environment.execute(handle, action, binding=binding)
    assert journal.calls("page", "fill") == []


# --------------------------------------------------------------------------- #
# Task 4 P0 审计：profile path escape、open 失败泄漏、完整 re-observe、
# consume 时机、partial fill、site-bound binding 必需
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "profile_ref",
    [
        "../../escape",
        "/tmp/evil",
        "not-canonical",
        "profile-ZZZZZZZZZZZZZZZZ",
    ],
)
def test_profile_ref_must_be_canonical_opaque_id(tmp_path, profile_ref):
    journal = Journal()
    environment, _ = make_environment(tmp_path, journal)
    bad_spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref=profile_ref,
        allowed_origins=(ORIGIN,),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="a" * 64,
        expiry_monotonic=1e18,
    )
    with pytest.raises(BrowserUnavailableError):
        environment.open(bad_spec)
    assert journal.calls("chromium", "launch_persistent_context") == []


def test_profile_root_symlink_rejected(tmp_path):
    journal = Journal()
    outside = tmp_path / "outside-profiles"
    outside.mkdir()
    (tmp_path / "profiles").symlink_to(outside)
    _playwright_handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        profile_root=tmp_path / "profiles",
    )
    with pytest.raises(BrowserUnavailableError):
        environment.open(SPEC)
    assert journal.calls("chromium", "launch_persistent_context") == []


def test_profile_dir_symlink_rejected(tmp_path):
    journal = Journal()
    root = tmp_path / "profiles"
    root.mkdir()
    escaped = tmp_path / "escaped-profile"
    escaped.mkdir()
    (root / PROFILE_REF).symlink_to(escaped)
    _playwright_handle, factory = make_fake_factory(journal)
    environment = PlaywrightBrowserEnvironment(
        playwright_factory=factory,
        resolver=FakeResolver({"site.example.test": ("93.184.216.34",)}),
        profile_root=root,
    )
    with pytest.raises(BrowserUnavailableError):
        environment.open(SPEC)
    assert journal.calls("chromium", "launch_persistent_context") == []


def test_second_open_fails_closed_single_session(tmp_path):
    journal = Journal()
    environment, _ = make_environment(tmp_path, journal)
    environment.open(SPEC)
    with pytest.raises(BrowserUnavailableError) as exc_info:
        environment.open(SPEC)
    assert exc_info.value.reason_code == "browser_session_active"


def test_same_origin_navigation_revision_drift_is_stale(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.click(
        observation.observation_digest, observation.page_id, observation.frame_id, "e1",
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    # 同 origin 内部导航：origin 不变但 navigation revision 漂移。
    playwright_handle.last_page.goto(f"{ORIGIN}/other")
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "fill") == []
    assert journal.calls("page", "click") == []


def test_form_method_drift_is_stale(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    playwright_handle.last_page.nodes = [
        {
            "ref": "e2", "role": "button", "name": "Sign in", "depth": 0,
            "input_type": "submit", "form_action": f"{ORIGIN}/login",
            "form_method": "POST",
        },
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1.click(
        observation.observation_digest, observation.page_id, observation.frame_id, "e2",
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    playwright_handle.last_page.nodes[0]["form_method"] = "GET"
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "click") == []


def test_partial_fill_is_all_or_nothing(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello", "Missing": "value"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    # 零 partial effect：一个字段都没有 fill。
    assert journal.calls("page", "fill") == []


def test_missing_target_click_is_known_not_executed(tmp_path):
    journal = Journal()
    environment, handle, _playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.click(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "ref-not-in-observation",
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "click") == []


def test_effect_then_post_observe_failure_consumes_binding(tmp_path):
    # B（本轮审计改写）：effect 已发生 + receipt 失败 = unknown——session
    # 必须 fail closed；fill 恰好一次，任何 replay 都不可用。
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    playwright_handle.last_page.fail_on_nth_evaluate = 3
    from agent.browser.playwright_adapter import BrowserEffectReceiptError

    with pytest.raises(BrowserEffectReceiptError):
        environment.execute(handle, action, binding=binding)
    assert len(journal.calls("page", "fill")) == 1
    with pytest.raises(BrowserUnavailableError):
        environment.execute(handle, action, binding=binding)
    with pytest.raises(BrowserUnavailableError):
        environment.observe(handle)
    assert len(journal.calls("page", "fill")) == 1


def test_site_bound_execute_requires_binding(tmp_path):
    journal = Journal()
    environment, handle, _playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    with pytest.raises(BrowserActionRefusedError):
        environment.execute(handle, action)
    assert journal.calls("page", "fill") == []


# --------------------------------------------------------------------------- #
# Task 4 P0 第二轮：authority 绑定（A）、receipt 失败 poison（B）、
# canonical 确认时机（C）、url/frame-tree preflight（D）、forged digest（E）
# --------------------------------------------------------------------------- #


def make_clock(now: float):
    return lambda: now


def bounded_spec(**overrides):
    payload = {
        "goal_id": "goal-1",
        "goal_revision": 1,
        "profile_ref": PROFILE_REF,
        "allowed_origins": (ORIGIN,),
        "action_budget": 8,
        "profile_revision": 7,
        "browser_identity_digest": "a" * 64,
        "expiry_monotonic": 1e18,
    }
    payload.update(overrides)
    return BrowserSessionSpecV1.site_bound(**payload)


def test_observation_binds_real_profile_revision_and_identity(tmp_path):
    journal = Journal()
    environment, _ = make_environment(tmp_path, journal, browser_identity_digest="a" * 64)
    handle = environment.open(bounded_spec())
    observation = environment.observe(handle)
    assert observation.profile_revision == 7
    assert observation.browser_revision == "a" * 64


def test_environment_identity_mismatch_fails_closed(tmp_path):
    journal = Journal()
    environment, _ = make_environment(
        tmp_path, journal, browser_identity_digest="c" * 64
    )
    with pytest.raises(BrowserUnavailableError) as exc_info:
        environment.open(bounded_spec())
    assert exc_info.value.reason_code == "browser_identity_mismatch"


def test_action_budget_decrements_and_exhausts_zero_effect(tmp_path):
    journal = Journal()
    environment, playwright_handle = make_environment(
        tmp_path, journal, browser_identity_digest="a" * 64
    )
    handle = environment.open(bounded_spec(action_budget=1))
    playwright_handle.last_page.nodes = [
        {"ref": "e1", "role": "textbox", "name": "Search", "depth": 0},
    ]
    observation = environment.observe(handle)
    first = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "one"},
    )
    binding = BrowserActionPolicy.prepare(observation, first)
    receipt = environment.execute(handle, first, binding=binding)
    assert receipt.executed is True
    second_observation = environment.observe(handle)
    second = BrowserActionV1.fill_form(
        second_observation.observation_digest,
        second_observation.page_id,
        second_observation.frame_id,
        "e1", {"Search": "two"},
    )
    second_binding = BrowserActionPolicy.prepare(second_observation, second)
    fills_before = len(journal.calls("page", "fill"))
    result = environment.execute(handle, second, binding=second_binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "browser_budget_exhausted"
    assert len(journal.calls("page", "fill")) == fills_before


def test_expired_session_rejects_actions_zero_effect(tmp_path):
    journal = Journal()
    environment, playwright_handle = make_environment(
        tmp_path, journal, browser_identity_digest="a" * 64, clock=make_clock(20000.0)
    )
    handle = environment.open(bounded_spec(expiry_monotonic=10000.0))
    playwright_handle.last_page.nodes = [
        {"ref": "e1", "role": "textbox", "name": "Search", "depth": 0},
    ]
    observation = environment.observe(handle)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "browser_session_expired"
    assert journal.calls("page", "fill") == []


def test_receipt_error_poisons_session_completely(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    playwright_handle.last_page.fail_on_nth_evaluate = 3
    from agent.browser.playwright_adapter import BrowserEffectReceiptError

    with pytest.raises(BrowserEffectReceiptError):
        environment.execute(handle, action, binding=binding)
    assert len(journal.calls("page", "fill")) == 1
    # effect 已发生 = unknown：session 必须 fail closed——同 binding、
    # 不同 binding、甚至 observe 都不可用，禁止任何 replay。
    with pytest.raises(BrowserUnavailableError):
        environment.execute(handle, action, binding=binding)
    fresh_observation = "1" * 64
    different = BrowserActionV1.click(
        fresh_observation, observation.page_id, observation.frame_id, "e2",
    )
    with pytest.raises(BrowserUnavailableError):
        environment.execute(handle, different)
    with pytest.raises(BrowserUnavailableError):
        environment.observe(handle)


def test_navigate_canonical_confirmed_from_real_page(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    playwright_handle.last_page.redirect_after_goto = f"{ORIGIN}/redirected"
    action = BrowserActionV1.navigate(
        observation.observation_digest, observation.page_id, observation.frame_id,
        f"{ORIGIN}/docs",
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    receipt = environment.execute(handle, action, binding=binding)
    assert receipt.executed is True
    after = environment.observe(handle)
    # canonical 只在 goto 成功后从真实 page URL 确认，而不是预写 admitted。
    assert after.canonical_url == f"{ORIGIN}/redirected"


def test_same_origin_url_drift_is_stale(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    # 同 origin 不同 path：origin/revision 不变但 canonical URL 漂移。
    playwright_handle.last_page.goto(f"{ORIGIN}/moved")
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "fill") == []


def test_frame_tree_drift_is_stale(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    from tests.browser.fakes import FakeFrame

    playwright_handle.last_page.frames.append(
        FakeFrame(
            parent=playwright_handle.last_page.main_frame,
            url=f"{ORIGIN}/embedded",
            name="embedded",
        )
    )
    result = environment.execute(handle, action, binding=binding)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "stale_browser_target"
    assert journal.calls("page", "fill") == []


def test_forged_binding_digest_fails_closed_before_effect(tmp_path):
    journal = Journal()
    environment, handle, playwright_handle, observation = open_interactive(tmp_path, journal)
    action = BrowserActionV1.fill_form(
        observation.observation_digest, observation.page_id, observation.frame_id,
        "e1", {"Search": "hello"},
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    forged = object.__new__(type(binding))
    for field in (
        "action_digest", "observation_digest", "page_id", "frame_id",
        "canonical_origin", "consequence", "target_ref", "target_role",
        "target_name", "target_input_type", "target_form_action",
        "target_form_method", "preview", "binding_digest",
    ):
        object.__setattr__(forged, field, getattr(binding, field))
    object.__setattr__(forged, "target_role", "evil")
    result = environment.execute(handle, action, binding=forged)
    assert isinstance(result, KnownNotExecuted)
    assert result.code == "browser_binding_changed"
    assert journal.calls("page", "fill") == []
