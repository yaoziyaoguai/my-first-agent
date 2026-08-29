"""018 Task 4 Step 1/3：纯 consequence policy 与 exact binding 的 Reds（先 Red）。

closed consequence 矩阵（spec §6）：observed same-origin link/scroll/back/
reload=OBSERVE；fill/select/model-built query=DISCLOSE；download=DOWNLOAD；
upload=UPLOAD；submit/unknown 元素语义=COMMIT；模型 risk=low 无效。模块只
import contracts（纯函数，不触碰 Playwright/Runtime/resolver）。preview 由
typed metadata 构造——value 原文与页面 prose 都不进入。
"""

from dataclasses import replace
from pathlib import Path

import pytest

from agent.browser.action_policy import (
    BrowserActionBindingV1,
    BrowserActionPolicy,
)
from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionV1,
    BrowserConsequence,
)
from agent.browser.observation import (
    ObservationIdentityV1,
    RawAriaNodeV1,
    RawBrowserSnapshotV1,
    project_aria_snapshot,
)

ORIGIN = "https://site.example.test"
OBS_A = "1" * 64
PAGE = "session-0123456789abcdef"
POLICY_SOURCE = Path(BrowserActionPolicy.__module__.replace(".", "/") + ".py")


def make_observation(nodes, *, origin=ORIGIN, profile_revision=None):
    identity = ObservationIdentityV1(
        session_ref=PAGE,
        page_id=PAGE,
        frame_id="main",
        navigation_revision=1,
        browser_revision="a" * 64,
        profile_revision=profile_revision,
        canonical_url=f"{origin}/page",
        canonical_origin=origin,
        frame_tree_digest="f" * 64,
        observed_at=1000.0,
    )
    return project_aria_snapshot(
        RawBrowserSnapshotV1(nodes=tuple(RawAriaNodeV1(**node) for node in nodes)),
        identity,
    )


BASE_NODES = [
    {"ref": "e1", "role": "link", "name": "Docs", "depth": 0},
    {
        "ref": "e2", "role": "textbox", "name": "Search", "depth": 0,
        "input_type": "text",
    },
    {
        "ref": "e3", "role": "button", "name": "Sign in", "depth": 0,
        "form_action": f"{ORIGIN}/login", "input_type": "submit",
    },
]


def test_module_imports_only_contracts():
    source = POLICY_SOURCE.read_text()
    assert "playwright" not in source
    assert "agent.runtime" not in source
    assert "url_policy" not in source
    assert "playwright_adapter" not in source


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        pytest.param(
            BrowserActionV1(
            kind=BrowserActionKind.BACK, observation_digest=OBS_A, page_id=PAGE, frame_id="main"
        ),
            BrowserConsequence.OBSERVE,
            id="back",
        ),
        pytest.param(
            BrowserActionV1(
            kind=BrowserActionKind.RELOAD, observation_digest=OBS_A, page_id=PAGE, frame_id="main"
        ),
            BrowserConsequence.OBSERVE,
            id="reload",
        ),
        pytest.param(
            BrowserActionV1(
            kind=BrowserActionKind.SCROLL, observation_digest=OBS_A, page_id=PAGE, frame_id="main"
        ),
            BrowserConsequence.OBSERVE,
            id="scroll",
        ),
        pytest.param(
            BrowserActionV1(
            kind=BrowserActionKind.CLOSE, observation_digest=OBS_A, page_id=PAGE, frame_id="main"
        ),
            BrowserConsequence.OBSERVE,
            id="close-session",
        ),
        pytest.param(
            BrowserActionV1.navigate(OBS_A, PAGE, "main", f"{ORIGIN}/docs"),
            BrowserConsequence.OBSERVE,
            id="same-origin-link",
        ),
        pytest.param(
            BrowserActionV1.navigate(OBS_A, PAGE, "main", f"{ORIGIN}/search?q=1"),
            BrowserConsequence.DISCLOSE,
            id="model-built-query",
        ),
        pytest.param(
            BrowserActionV1.navigate(OBS_A, PAGE, "main", "https://other.example.test/x"),
            BrowserConsequence.DISCLOSE,
            id="cross-origin",
        ),
        pytest.param(
            BrowserActionV1.click(OBS_A, PAGE, "main", "e1"),
            BrowserConsequence.OBSERVE,
            id="click-observed-link",
        ),
        pytest.param(
            BrowserActionV1.click(OBS_A, PAGE, "main", "e3"),
            BrowserConsequence.COMMIT,
            id="click-submit-button",
        ),
        pytest.param(
            BrowserActionV1(
            kind=BrowserActionKind.SELECT, observation_digest=OBS_A,
            page_id=PAGE, frame_id="main", target_ref="e2",
            params={"value": "option-a"},
        ),
            BrowserConsequence.DISCLOSE,
            id="select",
        ),
        pytest.param(
            BrowserActionV1.fill_form(OBS_A, PAGE, "main", "e2", {"q": "hello"}),
            BrowserConsequence.DISCLOSE,
            id="fill-form",
        ),
        pytest.param(
            BrowserActionV1(
                kind=BrowserActionKind.UPLOAD, observation_digest=OBS_A,
                page_id=PAGE, frame_id="main", target_ref="e2",
            ),
            BrowserConsequence.UPLOAD,
            id="upload",
        ),
        pytest.param(
            BrowserActionV1(
                kind=BrowserActionKind.DOWNLOAD, observation_digest=OBS_A,
                page_id=PAGE, frame_id="main", target_ref="e1",
            ),
            BrowserConsequence.DOWNLOAD,
            id="download",
        ),
    ],
)
def test_closed_consequence_matrix(action, expected):
    observation = make_observation(BASE_NODES)
    binding = BrowserActionPolicy.prepare(observation, action)
    assert isinstance(binding, BrowserActionBindingV1)
    assert binding.consequence is expected


def test_model_risk_low_is_ignored():
    observation = make_observation(BASE_NODES)
    risky = BrowserActionV1.fill_form(OBS_A, PAGE, "main", "e2", {"q": "hello"})
    safe_claim = BrowserActionV1(
        kind=BrowserActionKind.FILL_FORM, observation_digest=OBS_A,
        page_id=PAGE, frame_id="main", target_ref="e2",
        params={"fields": {"q": "hello"}, "risk": "low"},
    )
    assert (
        BrowserActionPolicy.prepare(observation, risky).consequence
        is BrowserActionPolicy.prepare(observation, safe_claim).consequence
        is BrowserConsequence.DISCLOSE
    )


def test_public_read_plain_initial_navigation_is_observe_but_query_is_disclose():
    observation = make_observation(BASE_NODES, origin="about://")
    plain = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "https://public.example.test/docs",
    )
    query = BrowserActionV1.navigate(
        observation.observation_digest,
        observation.page_id,
        observation.frame_id,
        "https://public.example.test/search?q=user-data",
    )

    assert (
        BrowserActionPolicy.prepare(
            observation,
            plain,
            allow_public_navigation=True,
        ).consequence
        is BrowserConsequence.OBSERVE
    )
    assert (
        BrowserActionPolicy.prepare(
            observation,
            query,
            allow_public_navigation=True,
        ).consequence
        is BrowserConsequence.DISCLOSE
    )
    assert (
        BrowserActionPolicy.prepare(observation, plain).consequence
        is BrowserConsequence.DISCLOSE
    )


def test_preview_uses_typed_metadata_never_values_or_prose():
    observation = make_observation(BASE_NODES)
    action = BrowserActionV1.fill_form(
        OBS_A, PAGE, "main", "e2", {"q": "hunter2-secret-value"}
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    assert ORIGIN in binding.preview
    assert "q" in binding.preview
    assert "hunter2-secret-value" not in binding.preview
    assert len(binding.preview) <= 512


def test_binding_digest_binds_target_params_and_observation():
    observation = make_observation(BASE_NODES)
    action = BrowserActionV1.click(
        observation.observation_digest, observation.page_id, observation.frame_id, "e1"
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    drifted_target = BrowserActionPolicy.prepare(
        observation, replace(action, target_ref="e2")
    )
    drifted_params = BrowserActionPolicy.prepare(
        observation,
        BrowserActionV1.navigate(
            observation.observation_digest,
            observation.page_id,
            observation.frame_id,
            f"{ORIGIN}/a",
        ),
    )
    other_observation = BrowserActionPolicy.prepare(
        make_observation(BASE_NODES, origin="https://other.example.test"),
        BrowserActionV1.navigate(
            observation.observation_digest,
            observation.page_id,
            observation.frame_id,
            "https://other.example.test/a",
        ),
    )
    base = binding.binding_digest
    assert drifted_target.binding_digest != base
    assert drifted_params.binding_digest != base
    assert other_observation.binding_digest != base
    assert binding.action_digest == action.identity_digest
    assert binding.observation_digest == observation.observation_digest


def test_unknown_element_semantics_is_commit():
    nodes = [
        {"ref": "x1", "role": "button", "name": "Mystery", "depth": 0},
        {"ref": "x2", "role": None, "name": None, "depth": 0},
    ]
    observation = make_observation(nodes)
    for ref in ("x1", "x2"):
        binding = BrowserActionPolicy.prepare(
            observation, BrowserActionV1.click(OBS_A, PAGE, "main", ref)
        )
        assert binding.consequence is BrowserConsequence.COMMIT, ref


# --------------------------------------------------------------------------- #
# Task 4 P0-E：binding digest closed invariant（唯一 validate seam）
# --------------------------------------------------------------------------- #


def test_binding_digest_is_closed_immutable_invariant():
    observation = make_observation(BASE_NODES)
    action = BrowserActionV1.click(
        observation.observation_digest, observation.page_id, observation.frame_id, "e1"
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    # replace 改字段 + 旧 digest：构造层即拒（digest 必须与字段一致）。
    with pytest.raises(ValueError):
        replace(binding, target_role="evil")
    with pytest.raises(ValueError):
        replace(binding, preview="forged preview")
    # 直接构造带伪造 digest 也拒。
    with pytest.raises(ValueError):
        BrowserActionBindingV1(
            action_digest=binding.action_digest,
            observation_digest=binding.observation_digest,
            page_id=binding.page_id,
            frame_id=binding.frame_id,
            canonical_origin=binding.canonical_origin,
            consequence=binding.consequence,
            target_ref=binding.target_ref,
            target_role="evil",
            target_name=binding.target_name,
            target_input_type=binding.target_input_type,
            target_form_action=binding.target_form_action,
            target_form_method=binding.target_form_method,
            preview=binding.preview,
            binding_digest="f" * 64,
        )


def test_binding_digest_covers_preview_and_form_method():
    observation = make_observation(BASE_NODES)
    first = BrowserActionPolicy.prepare(
        observation,
        BrowserActionV1.fill_form(
            observation.observation_digest, observation.page_id, observation.frame_id,
            "e2", {"q": "a"},
        ),
    )
    second = BrowserActionPolicy.prepare(
        observation,
        BrowserActionV1.fill_form(
            observation.observation_digest, observation.page_id, observation.frame_id,
            "e2", {"q": "b"},
        ),
    )
    # preview 含 value digest → params 变化应改变 preview 及 binding digest。
    assert first.preview != second.preview
    assert first.binding_digest != second.binding_digest
    nodes_with_method = [
        {"ref": "e1", "role": "link", "name": "Docs", "depth": 0,
         "form_action": f"{ORIGIN}/x", "form_method": "POST"},
    ]
    other = BrowserActionPolicy.prepare(
        make_observation(nodes_with_method),
        BrowserActionV1.click(
            make_observation(nodes_with_method).observation_digest,
            PAGE, "main", "e1",
        ),
    )
    assert other.target_form_method == "POST"


def test_validate_binding_is_the_single_recompute_seam():
    observation = make_observation(BASE_NODES)
    action = BrowserActionV1.click(
        observation.observation_digest, observation.page_id, observation.frame_id, "e1"
    )
    binding = BrowserActionPolicy.prepare(observation, action)
    BrowserActionPolicy.validate_binding(binding)  # 合法 binding 通过。
    forged = object.__new__(BrowserActionBindingV1)
    for field in (
        "action_digest", "observation_digest", "page_id", "frame_id",
        "canonical_origin", "consequence", "target_ref", "target_role",
        "target_name", "target_input_type", "target_form_action",
        "target_form_method", "preview", "binding_digest",
    ):
        object.__setattr__(forged, field, getattr(binding, field))
    object.__setattr__(forged, "target_role", "evil")
    with pytest.raises(ValueError):
        BrowserActionPolicy.validate_binding(forged)
