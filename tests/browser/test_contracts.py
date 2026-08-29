"""018 Task 1 Step 1：browser typed contracts 的 closed 校验（先 Red）。

覆盖计划 Task 1 的合同要求：closed enums、site-bound session spec 校验、
action identity 绑定 observation/target/parameters、executed receipt 的
pre/post identity 与 outcome class 前提，以及 ``BrowserEnvironment`` port
复用 runtime 拥有的 ``KnownNotExecuted``（禁止 browser 包重复定义）。
"""

from dataclasses import replace

import pytest

from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionOutcome,
    BrowserActionReceiptV1,
    BrowserActionV1,
    BrowserCleanupOutcome,
    BrowserCleanupReceiptV1,
    BrowserConsequence,
    BrowserMode,
    BrowserSessionSpecV1,
)
from agent.browser.ports import BrowserEnvironment
from agent.runtime.contracts import KnownNotExecuted


def test_browser_modes_are_closed_enums():
    assert BrowserMode.PUBLIC_READ_EPHEMERAL.value == "public_read_ephemeral"
    assert BrowserMode.SITE_BOUND_INTERACTIVE.value == "site_bound_interactive"
    with pytest.raises(ValueError):
        BrowserMode("personal_chrome")


def test_action_kinds_and_consequences_reject_unknown_strings():
    for kind in (
        "navigate", "back", "reload", "scroll", "click",
        "select", "fill_form", "upload", "download", "close",
    ):
        assert BrowserActionKind(kind).value == kind
    with pytest.raises(ValueError):
        BrowserActionKind("evaluate_js")
    for consequence in ("observe", "disclose", "download", "upload", "commit"):
        assert BrowserConsequence(consequence).value == consequence
    with pytest.raises(ValueError):
        BrowserConsequence("trust_page")


def test_interactive_spec_requires_exact_origin_and_profile_revision():
    with pytest.raises(ValueError):
        BrowserSessionSpecV1.site_bound(
            goal_id="goal-1",
            goal_revision=1,
            profile_ref=None,
            allowed_origins=(),
            action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
        )


def test_interactive_spec_rejects_empty_origin_allowlist():
    with pytest.raises(ValueError):
        BrowserSessionSpecV1.site_bound(
            goal_id="goal-1",
            goal_revision=1,
            profile_ref="profile-ref-1",
            allowed_origins=(),
            action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
        )


def test_public_read_spec_has_no_profile_binding():
    spec = BrowserSessionSpecV1.public_read(goal_id="goal-1", goal_revision=1)
    assert spec.mode is BrowserMode.PUBLIC_READ_EPHEMERAL
    assert spec.profile_ref is None
    assert len(spec.identity_digest) == 64


def test_interactive_spec_binds_goal_profile_and_origins_in_identity():
    spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-ref-1",
        allowed_origins=("https://example.test",),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
    )
    assert spec.mode is BrowserMode.SITE_BOUND_INTERACTIVE
    drifted = replace(spec, goal_revision=2)
    assert drifted.identity_digest != spec.identity_digest


def test_session_spec_positive_limits_reject_bool_and_non_positive():
    with pytest.raises(ValueError):
        BrowserSessionSpecV1.site_bound(
            goal_id="goal-1",
            goal_revision=1,
            profile_ref="profile-ref-1",
            allowed_origins=("https://example.test",),
            action_budget=True,
            profile_revision=1,
            browser_identity_digest="b" * 64,
            expiry_monotonic=10000.0,
        )
    with pytest.raises(ValueError):
        BrowserSessionSpecV1.site_bound(
            goal_id="goal-1",
            goal_revision=1,
            profile_ref="profile-ref-1",
            allowed_origins=("https://example.test",),
            action_budget=0,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
        )


def test_action_identity_binds_observation_target_and_parameters():
    action = BrowserActionV1.click("a" * 64, "page-1", "frame-1", "ref-7")
    assert action.identity_digest != replace(action, target_ref="ref-8").identity_digest


def test_action_identity_binds_navigation_parameters():
    base = BrowserActionV1.navigate(
        "a" * 64, "page-1", "frame-1", "https://example.test/x"
    )
    other = BrowserActionV1.navigate(
        "a" * 64, "page-1", "frame-1", "https://example.test/y"
    )
    assert base.identity_digest != other.identity_digest
    assert base.identity_digest != replace(base, observation_digest="b" * 64).identity_digest


def test_action_identity_binds_fill_form_field_values():
    base = BrowserActionV1.fill_form(
        "a" * 64, "page-1", "frame-1", "ref-7", {"name": "Ada"}
    )
    changed = BrowserActionV1.fill_form(
        "a" * 64, "page-1", "frame-1", "ref-7", {"name": "Eve"}
    )
    assert base.identity_digest != changed.identity_digest


def test_executed_receipt_requires_pre_post_identity_and_outcome():
    with pytest.raises(ValueError):
        BrowserActionReceiptV1(
            action_digest="c" * 64,
            pre_observation_digest=None,
            post_observation_digest="d" * 64,
            outcome=BrowserActionOutcome.EFFECT_APPLIED,
        )
    with pytest.raises(ValueError):
        BrowserActionReceiptV1(
            action_digest="c" * 64,
            pre_observation_digest="d" * 64,
            post_observation_digest="e" * 64,
            outcome=None,
        )
    ok = BrowserActionReceiptV1(
        action_digest="c" * 64,
        pre_observation_digest="d" * 64,
        post_observation_digest="e" * 64,
        outcome=BrowserActionOutcome.EFFECT_APPLIED,
    )
    assert len(ok.receipt_digest) == 64


def test_cleanup_receipt_records_cleanup_unknown_without_fabricating_success():
    receipt = BrowserCleanupReceiptV1(
        session_ref="session-1",
        outcome=BrowserCleanupOutcome.CLEANUP_UNKNOWN,
    )
    assert len(receipt.receipt_digest) == 64


def test_browser_environment_is_runtime_owned_protocol_reusing_known_not_executed():
    import agent.browser.ports as browser_ports

    for method in ("open", "observe", "execute", "begin_takeover", "close"):
        assert callable(getattr(BrowserEnvironment, method, None))
    # 唯一 KnownNotExecuted 由 agent.runtime.contracts 拥有；browser 只允许 re-export。
    assert browser_ports.KnownNotExecuted is KnownNotExecuted


def test_browser_environment_execute_admits_known_not_executed_return():
    import typing

    return_hint = typing.get_type_hints(BrowserEnvironment.execute)["return"]
    return_args = typing.get_args(return_hint)
    assert BrowserActionReceiptV1 in return_args
    assert KnownNotExecuted in return_args


# --------------------------------------------------------------------------- #
# Task 4 P0-A：site-bound session authority 显式绑定（spec §4.2）
# --------------------------------------------------------------------------- #


def test_site_bound_spec_binds_revision_identity_and_expiry():
    spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-0123456789abcdef",
        allowed_origins=("https://example.test",),
        action_budget=8,
        profile_revision=3,
        browser_identity_digest="b" * 64,
        expiry_monotonic=1000.0,
    )
    assert spec.profile_revision == 3
    assert spec.browser_identity_digest == "b" * 64
    assert spec.expiry_monotonic == 1000.0
    # authority 字段全部纳入 identity digest。
    assert replace(spec, profile_revision=4).identity_digest != spec.identity_digest
    assert (
        replace(spec, browser_identity_digest="c" * 64).identity_digest
        != spec.identity_digest
    )
    assert replace(spec, expiry_monotonic=2000.0).identity_digest != spec.identity_digest


@pytest.mark.parametrize(
    "overrides",
    [
        {"profile_revision": 0},
        {"profile_revision": True},
        {"profile_revision": None},
        {"browser_identity_digest": "Z" * 64},
        {"browser_identity_digest": "b" * 63},
        {"browser_identity_digest": None},
        {"expiry_monotonic": float("inf")},
        {"expiry_monotonic": float("nan")},
        {"expiry_monotonic": None},
    ],
)
def test_site_bound_rejects_vacuous_authority(overrides):
    payload = {
        "goal_id": "goal-1",
        "goal_revision": 1,
        "profile_ref": "profile-0123456789abcdef",
        "allowed_origins": ("https://example.test",),
        "action_budget": 8,
        "profile_revision": 3,
        "browser_identity_digest": "b" * 64,
        "expiry_monotonic": 1000.0,
    }
    payload.update(overrides)
    with pytest.raises(ValueError):
        BrowserSessionSpecV1.site_bound(**payload)


def test_public_read_authority_fields_must_be_null():
    spec = BrowserSessionSpecV1.public_read(goal_id="goal-1", goal_revision=1)
    assert spec.profile_revision is None
    assert spec.browser_identity_digest is None
    assert spec.expiry_monotonic is None
