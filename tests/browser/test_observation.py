"""018 Task 1 Step 5 后半：bounded observation projection 的 Reds（先 Red）。

覆盖 spec §5.1：ARIA projection 的 400 nodes/64 KiB/depth 15 确定性截断、
password/secret/hidden value 永不投影、普通 input 只投影是否为空、不保存
HTML/cookie/header/body/screenshot，以及 session/page/frame/navigation/
browser/profile revision 全部绑定进 observation digest。
"""

from dataclasses import fields

from agent.browser.contracts import BrowserElementRefV1, BrowserObservationV1
from agent.browser.observation import (
    DEFAULT_OBSERVATION_LIMITS,
    ObservationIdentityV1,
    RawAriaNodeV1,
    RawBrowserSnapshotV1,
    project_aria_snapshot,
)


def make_identity(**overrides) -> ObservationIdentityV1:
    payload = {
        "session_ref": "session-1",
        "page_id": "page-1",
        "frame_id": "frame-1",
        "navigation_revision": 3,
        "browser_revision": "b" * 64,
        "profile_revision": None,
        "canonical_url": "https://site.example.test/page",
        "canonical_origin": "https://site.example.test",
        "frame_tree_digest": "f" * 64,
        "observed_at": 1000.0,
    }
    payload.update(overrides)
    return ObservationIdentityV1(**payload)


def node(
    ref: str,
    *,
    role: str = "button",
    name: str = "OK",
    depth: int = 0,
    input_type: str | None = None,
    form_action: str | None = None,
    value: str | None = None,
) -> RawAriaNodeV1:
    return RawAriaNodeV1(
        ref=ref,
        role=role,
        name=name,
        depth=depth,
        input_type=input_type,
        form_action=form_action,
        value=value,
    )


def project(nodes, identity=None):
    return project_aria_snapshot(
        RawBrowserSnapshotV1(nodes=tuple(nodes)),
        identity or make_identity(),
    )


def test_default_limits_are_frozen_at_contract_values():
    assert DEFAULT_OBSERVATION_LIMITS.max_nodes == 400
    assert DEFAULT_OBSERVATION_LIMITS.max_bytes == 64 * 1024
    assert DEFAULT_OBSERVATION_LIMITS.max_depth == 15


def test_projection_binds_identity_fields():
    observation = project([node("e1", role="heading", name="Login")])
    assert isinstance(observation, BrowserObservationV1)
    assert observation.session_ref == "session-1"
    assert observation.page_id == "page-1"
    assert observation.frame_id == "frame-1"
    assert observation.navigation_revision == 3
    assert observation.canonical_origin == "https://site.example.test"
    assert "Login" in observation.aria_projection
    assert len(observation.observation_digest) == 64
    assert observation.truncated is False
    assert observation.node_count == 1


def test_digest_binds_all_revisions_and_page_frame_identity():
    base = project([node("e1")])
    for override in (
        {"navigation_revision": 4},
        {"page_id": "page-2"},
        {"frame_id": "frame-2"},
        {"session_ref": "session-2"},
        {"browser_revision": "c" * 64},
        {"profile_revision": 2},
    ):
        drifted = project([node("e1")], make_identity(**override))
        assert drifted.observation_digest != base.observation_digest, override


def test_node_cap_truncates_deterministically():
    nodes = [node(f"e{i}", role="listitem", name=f"item {i}") for i in range(401)]
    observation = project(nodes)
    assert len(observation.element_refs) == 400
    assert observation.node_count == 400
    assert observation.truncated is True
    assert observation.element_refs[0].ref == "e0"
    assert observation.element_refs[-1].ref == "e399"
    repeat = project(nodes)
    assert repeat.observation_digest == observation.observation_digest


def test_byte_cap_truncates_projection():
    nodes = [node(f"e{i}", role="article", name="x" * 200) for i in range(400)]
    observation = project(nodes)
    assert observation.byte_size <= 64 * 1024
    assert observation.truncated is True


def test_depth_cap_prunes_deep_nodes():
    observation = project(
        [
            node("e1", role="heading", name="Top"),
            node("e2", role="listitem", name="Deep", depth=16),
        ]
    )
    assert [item.ref for item in observation.element_refs] == ["e1"]
    assert observation.truncated is True
    assert "Deep" not in observation.aria_projection


def test_password_values_never_projected():
    observation = project(
        [
            node(
                "pw",
                role="textbox",
                name="Password",
                input_type="password",
                value="hunter2-secret",
            )
        ]
    )
    assert "hunter2-secret" not in observation.aria_projection
    assert not hasattr(observation.element_refs[0], "value")
    # password 不泄漏是否为空。
    assert observation.element_refs[0].value_empty is None


def test_hidden_and_secret_input_values_redacted():
    observation = project(
        [
            node("h", role="textbox", name="csrf", input_type="hidden", value="csrf-token"),
            node("s", role="textbox", name="pin", input_type="secret", value="1234"),
        ]
    )
    assert "csrf-token" not in observation.aria_projection
    assert "1234" not in observation.aria_projection
    assert observation.element_refs[0].value_empty is None
    assert observation.element_refs[1].value_empty is None


def test_plain_input_projects_only_emptiness_and_public_label():
    observation = project(
        [
            node(
                "u",
                role="textbox",
                name="Username",
                input_type="text",
                value="ada@example.test",
                form_action="https://site.example.test/login",
            ),
            node("e", role="textbox", name="Search", input_type="search", value=""),
        ]
    )
    assert "ada@example.test" not in observation.aria_projection
    assert observation.element_refs[0].value_empty is False
    assert observation.element_refs[1].value_empty is True
    assert observation.element_refs[0].form_action == "https://site.example.test/login"


def test_observation_contract_stores_no_raw_page_state():
    # closed 字段集合：HTML、cookie、header、network body、screenshot 无处安放。
    observation_fields = {item.name for item in fields(BrowserObservationV1)}
    assert observation_fields == {
        "session_ref",
        "page_id",
        "frame_id",
        "navigation_revision",
        "browser_revision",
        "profile_revision",
        "canonical_url",
        "canonical_origin",
        "frame_tree_digest",
        "aria_projection",
        "element_refs",
        "node_count",
        "byte_size",
        "truncated",
        "observed_at",
        "observation_digest",
    }
    element_fields = {item.name for item in fields(BrowserElementRefV1)}
    assert element_fields == {
        "ref", "role", "name", "input_type", "form_action", "form_method", "value_empty",
    }


# --------------------------------------------------------------------------- #
# Task 4 类型一致性：observation profile_revision 必须与 durable profile
# revision 同型（positive int | None），拒绝 bool/0/string。
# --------------------------------------------------------------------------- #


def test_profile_revision_must_be_positive_int_or_none():
    import pytest

    with pytest.raises(ValueError):
        make_identity(profile_revision="p" * 64)
    with pytest.raises(ValueError):
        make_identity(profile_revision=True)
    with pytest.raises(ValueError):
        make_identity(profile_revision=0)
    with pytest.raises(ValueError):
        make_identity(profile_revision=-1)
    # None 与 positive int 合法。
    assert make_identity(profile_revision=None).profile_revision is None
    assert make_identity(profile_revision=4).profile_revision == 4
