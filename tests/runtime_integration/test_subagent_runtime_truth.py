"""Runtime-truth alignment for SubAgent dispatcher registration.

After audit 2026-06-11, the real registered product path is V0, with L0
remaining as the inline-fallback probe. L1 is a legacy/frozen handler that
must not be promoted to product. These tests lock that runtime truth into
place so a future refactor cannot accidentally re-promote L1.

These tests are deliberate architecture-contract tests (AST/grep based), not
private-implementation coupling: they assert against the public symbol table
(``RuntimeDispatcher.register_dispatch_route``) and the V4 doc table.

Path states captured here:
  * registered — what ``register_dispatch_route`` actually wires up
  * tested — covered by existing test suite
  * production-called — what ``core.py`` asks the dispatcher to do
  * fallback — explicit fallback when the product path returns no result
  * compatibility — handler exists for back-compat but is not registered
  * frozen — implementation paused; do not promote
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from agent.runtime_integration.dispatcher import (
    RuntimeActionDispatcher,  # noqa: F401  (re-export check)
)
from agent.runtime_integration.schema import RuntimeActionType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _registered_subagent_action_types() -> set[RuntimeActionType]:
    """Build the phase-1 dispatcher and inspect its registry for subagent handlers."""
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    dispatcher = build_phase1_dispatcher()
    return {
        action_type
        for action_type in dispatcher._registry._handlers
        if "subagent" in str(action_type)
    }


def test_v0_is_registered_as_product_path() -> None:
    """V0 must be registered in ``RuntimeDispatcher.__init__``."""
    registered = _registered_subagent_action_types()
    assert RuntimeActionType.SUBAGENT_DELEGATE_V0 in registered, (
        "V0 must be registered as product path. "
        f"Currently registered: {sorted(t.name for t in registered)}"
    )


def test_l0_is_registered_as_probe_path() -> None:
    """L0 (inline-local probe) is registered alongside V0."""
    registered = _registered_subagent_action_types()
    assert RuntimeActionType.SUBAGENT_DELEGATE_L0 in registered, (
        "L0 must remain registered as the inline-fallback probe. "
        f"Currently registered: {sorted(t.name for t in registered)}"
    )


def test_l1_is_not_registered_as_product_path() -> None:
    """L1 must NOT be promoted to product. It is legacy/frozen only."""
    registered = _registered_subagent_action_types()
    assert RuntimeActionType.SUBAGENT_DELEGATE_L1 not in registered, (
        "L1 must not be promoted to product; it stays legacy/frozen. "
        f"Currently registered: {sorted(t.name for t in registered)}"
    )


def test_subagent_v0_handler_is_the_only_active_handler() -> None:
    """SubAgentV0Handler is the active product handler. Do not split it."""
    from agent.runtime_integration import subagent_action

    assert hasattr(subagent_action, "SubAgentV0Handler"), (
        "SubAgentV0Handler must exist as the single active product handler."
    )


def test_v4_capability_table_reflects_v0_as_active_path() -> None:
    """V4 docs must not present L1 as the product path."""
    v4_path = REPO_ROOT / "docs" / "06-audit" / "V4_CAPABILITY_DRIFT_TABLE.md"
    if not v4_path.exists():
        return  # V4 is generated; absence is acceptable.
    text = v4_path.read_text(encoding="utf-8")
    subagent_rows = [
        line
        for line in text.splitlines()
        if "subagent.delegate" in line and "|" in line
    ]
    if not subagent_rows:
        return
    row = subagent_rows[0].lower()
    assert "v0" in row, (
        f"V4 row must mention V0 as the active path; got row={row!r}"
    )
    assert "l1 是生产" not in row and "l1 product" not in row, (
        f"V4 row must not present L1 as product; got row={row!r}"
    )


def test_decision_frame_sot_references_v0_registration() -> None:
    """SoT BranchPointState for subagent.delegate must reference V0 (registered path)."""
    from agent import runtime_decision_frame as rdf

    state = rdf.BRANCH_POINT_REGISTRY["subagent.delegate"]
    blob = (
        state.execution_path
        + " "
        + state.not_ready_behavior
        + " "
        + state.result_feedback_path
    ).lower()
    assert "v0" in blob, (
        f"SoT must reference V0 as active path; blob={blob!r}"
    )


def test_decision_frame_sot_does_not_claim_l1_is_product() -> None:
    """SoT must not claim L1 is the production path."""
    from agent import runtime_decision_frame as rdf

    state = rdf.BRANCH_POINT_REGISTRY["subagent.delegate"]
    blob = (
        state.execution_path
        + " "
        + state.not_ready_behavior
        + " "
        + state.result_feedback_path
    )
    assert "L1 是生产" not in blob and "L1 product" not in blob, (
        f"SoT must not present L1 as product; blob={blob!r}"
    )


def test_phase1_hook_does_not_register_l1_as_product() -> None:
    """phase1_hook.build_phase1_dispatcher must not promote L1 to product."""
    from agent.runtime_integration import phase1_hook

    src = inspect.getsource(phase1_hook.build_phase1_dispatcher)
    matches = re.findall(
        r"registry\.register\(\s*\n?\s*RuntimeActionType\.(\w+)",
        src,
    )
    assert "SUBAGENT_DELEGATE_L1" not in matches, (
        f"phase1_hook must not register L1 as product. Got: {matches}"
    )
    assert "SUBAGENT_DELEGATE_V0" in matches, (
        f"phase1_hook must register V0 as product. Got: {matches}"
    )


def test_production_cli_delegation_routes_v0_when_flag_on() -> None:
    """U3: core.py now wires flag-on V0 production routing.

    Pin the *production-called* dimension: when ``SUBAGENT_V0_ROUTING_ENABLED``
    is set, ``_dispatch_or_fallback_delegation`` dispatches
    ``RuntimeActionType.SUBAGENT_DELEGATE_V0`` with ``source="cli_nl_delegation"``
    before any L1/L0 fallback. The SoT must reflect this routing.
    """
    import inspect

    from agent import core

    src = inspect.getsource(core)
    # U3: V0 production routing exists.
    assert "RuntimeActionType.SUBAGENT_DELEGATE_V0" in src, (
        "U3 must wire V0 routing into _dispatch_or_fallback_delegation; "
        "missing from core.py."
    )
    # source must be the real cli_nl_delegation token.
    assert '"cli_nl_delegation"' in src, (
        "V0 production request source must be 'cli_nl_delegation', never "
        "'core_loop' (no forgery allowed)."
    )
    # Default off + missing/invalid → off handled by helper.
    assert "from agent.subagent_routing_flag import read_v0_routing_enabled" in src, (
        "core.py must consult the env-flag helper for off-by-default routing."
    )


def test_sot_does_not_overclaim_v0_as_live_execution_path() -> None:
    """SoT must qualify V0 as registered/contract-tested, not the live CLI path.

    H1 (2026-06-12 review): the SoT cannot state V0 is the production
    execution_path while core.py routes L1→L0-fallback. The SoT must mark V0
    as registered + contract-verified and describe the live path honestly.
    """
    from agent import runtime_decision_frame as rdf

    state = rdf.BRANCH_POINT_REGISTRY["subagent.delegate"]
    exec_path = state.execution_path

    # The SoT must NOT claim the live CLI delegation routes V0. core.py routes
    # SUBAGENT_DELEGATE_L1 (then falls back to L0 inline); V0 is registered but
    # not production-called. This exact false claim is what H1 flagged.
    assert "CLI/NL delegation → dispatcher.route(SUBAGENT_DELEGATE_V0)" not in exec_path, (
        "SoT must not claim CLI/NL delegation routes V0; core.py routes L1→L0. "
        f"got execution_path={exec_path!r}"
    )

    blob = (exec_path + " " + state.not_ready_behavior).lower()
    # Must acknowledge the live CLI path is L1-attempt → L0-fallback.
    assert "l0" in blob and ("fallback" in blob or "fall back" in blob or "回退" in blob), (
        "SoT must describe the live CLI delegation path as L1→L0-fallback; "
        f"got: {blob!r}"
    )
    # V0 must be qualified as registered + contract-verified, not the live path.
    assert "registered" in blob, (
        "SoT must mark V0 as registered (not the live execution path); "
        f"got: {blob!r}"
    )


def test_subagent_level_is_inline_local_fallback() -> None:
    """RuntimeDecisionFrame.subagent_level must name the current live path.

    H1 (2026-06-12 review, item 3): the field was hard-coded to ``"L1"`` while
    L1 is not registered and the live CLI/NL path is the direct inline-local
    fallback (``subagent_inline.execute_subagent_delegation``,
    ``execution_mode="local_fake"``). The frozen value is
    ``"inline_local_fallback"`` — see plan U1 "Frozen subagent_level target
    value". The registered/requested/fallback distinction is carried by
    ``BranchPointState["subagent.delegate"].execution_path`` (already
    corrected); ``subagent_level`` is a free-form ``str`` naming the path
    that actually executed.
    """
    from agent.runtime_decision_frame import build_decision_frame

    frame = build_decision_frame("test")
    assert frame.subagent_level == "inline_local_fallback", (
        f"subagent_level must name the current live executing path; "
        f"got {frame.subagent_level!r}"
    )
    assert frame.subagent_level != "L1", (
        "subagent_level must NOT be the bare 'L1' string — L1 is not "
        "registered, the live path is the inline-local fallback."
    )


def test_subagent_available_does_not_claim_real_api_capability() -> None:
    """``subagent_available=True`` means "callable", not "real API verified".

    R2 (user refinement #1): the two meanings must be split.
    ``subagent_available`` is True because the inline-local fallback IS
    callable on the live path. The corresponding ``evidence_level`` on the
    BranchPointState for ``subagent.delegate`` must NOT be a real-API level
    (REAL_API_INTERACTIVE / PRODUCTION_PATH) — the live path is
    ``fake/local user path``, executed by the local_fake inline fallback.
    """
    from agent.runtime_decision_frame import (
        EvidenceLevel,
        build_decision_frame,
    )

    frame = build_decision_frame("test")
    assert frame.subagent_available is True, (
        "subagent_available should be True (the inline-local fallback "
        "IS callable on the live path)."
    )

    # Hard-coded REAL_API levels must NOT appear in the runtime-fact SoT.
    real_api_levels = {
        EvidenceLevel.REAL_API_INTERACTIVE,
        EvidenceLevel.PRODUCTION_PATH,
    }
    assert frame.evidence_level not in real_api_levels, (
        f"frame.evidence_level must not overclaim real-API capability; "
        f"got {frame.evidence_level!r}"
    )


def test_subagent_delegate_branch_point_evidence_is_fake_local_user_path() -> None:
    """``BranchPointState["subagent.delegate"].evidence_level`` must be honest.

    The live path is the direct inline-local fallback
    (``execution_mode="local_fake"``). REAL_API_INTERACTIVE was an
    overclaim pinned by the previous body text. The honest value is
    ``FAKE_LOCAL_USER_PATH`` (an existing enum value, no schema change).
    """
    from agent import runtime_decision_frame as rdf

    state = rdf.BRANCH_POINT_REGISTRY["subagent.delegate"]
    assert state.evidence_level == rdf.EvidenceLevel.FAKE_LOCAL_USER_PATH, (
        f"subagent.delegate evidence_level must be FAKE_LOCAL_USER_PATH "
        f"(live path is inline-local local_fake); got {state.evidence_level!r}"
    )
    assert state.evidence_level != rdf.EvidenceLevel.REAL_API_INTERACTIVE, (
        "subagent.delegate evidence_level must NOT be REAL_API_INTERACTIVE; "
        "the live path is the inline-local fallback, not real API."
    )


def test_is_capability_complete_allowed_set_unchanged_by_truth_swap() -> None:
    """Regression: the FAKE_LOCAL_USER_PATH → allowed-set swap must not
    silently change capability-complete semantics.

    H1 boundary: U1 may set evidence_level=FAKE_LOCAL_USER_PATH on
    ``subagent.delegate`` (honest), but MUST NOT modify the allowed set
    inside ``is_capability_complete``. This test pins that boundary by
    asserting the allowed set is byte-for-byte unchanged from the
    pre-U1 value.
    """
    from agent import runtime_decision_frame as rdf

    bp = rdf.BranchPointState(
        branch_id="test.subagent_swap",
        status=rdf.BranchPointStatus.READY,
        evidence_level=rdf.EvidenceLevel.FAKE_LOCAL_USER_PATH,
        trigger_condition="test only",
        not_ready_behavior="no-op",
    )
    # READY + FAKE_LOCAL_USER_PATH must still be considered capability-complete
    # (the value is currently in the allowed set; do NOT remove it in U1).
    assert bp.is_capability_complete() is True, (
        "READY + FAKE_LOCAL_USER_PATH must still be capability-complete "
        "after U1's evidence_level truth swap; is_capability_complete "
        "allowed set must not have been modified."
    )

    # And the four-value allowed set is still exactly the four pre-U1 values.
    # Derive `actual` from the predicate (option B: grid) rather than hand-typed
    # mirror of `expected` so a future mutation of the allowed set is caught.
    allowed: set[rdf.EvidenceLevel] = set()
    for ev in rdf.EvidenceLevel:
        grid_bp = rdf.BranchPointState(
            branch_id="test.subagent_swap_grid",
            status=rdf.BranchPointStatus.READY,
            evidence_level=ev,
            trigger_condition="test only",
            not_ready_behavior="no-op",
        )
        if grid_bp.is_capability_complete():
            allowed.add(ev)
    expected = {
        rdf.EvidenceLevel.PRODUCTION_PATH,
        rdf.EvidenceLevel.REAL_API_INTERACTIVE,
        rdf.EvidenceLevel.REAL_API_SMOKE,
        rdf.EvidenceLevel.FAKE_LOCAL_USER_PATH,
    }
    assert allowed == expected, (
        f"is_capability_complete allowed set must remain exactly {{PRODUCTION_PATH, "
        f"REAL_API_INTERACTIVE, REAL_API_SMOKE, FAKE_LOCAL_USER_PATH}}; "
        f"derived set was {allowed}"
    )


def test_phase1_hook_does_not_claim_v0_is_only_production_path() -> None:
    """``phase1_hook`` must NOT claim V0 is the *sole* / "唯一" production path.

    R3 / H2: the previous comment said ``SUBAGENT_DELEGATE_V0 唯一 product
    Runtime path`` while core.py routes L1 → L0-fallback. The qualified
    claim is "V0 is the only *registered* product handler; live route
    remains L1-attempt → inline-local fallback; V0 wiring pending."
    """
    from agent.runtime_integration import phase1_hook

    src = inspect.getsource(phase1_hook)
    # Single-pass positive-qualifier check: any line containing '唯一' AND
    # ('production' OR '生产' OR 'path' OR 'handler') must also contain a
    # qualifier ('registered' / 'contract-verified' / 'wiring pending') on
    # the same line. This catches both English and Chinese-only phrasings
    # and requires a same-line qualifier (the same form a reflowed claim
    # would have to keep).
    qualifier_markers = ("registered", "contract-verified", "wiring pending")
    for raw_line in src.splitlines():
        stripped = raw_line.strip()
        has_unique = "唯一" in stripped
        has_path_word = any(
            w in stripped.lower()
            for w in ("production", "生产", "path", "handler")
        )
        if has_unique and has_path_word:
            assert any(q in stripped for q in qualifier_markers), (
                f"phase1_hook must not contain unqualified '唯一 ... "
                f"production/path' claim; got line: {stripped!r}"
            )


def test_subagent_action_does_not_claim_v0_is_only_active_production_path() -> None:
    """``subagent_action.py`` must not claim V0 is the only active production
    path in the opposite direction either (it had "V0 current — 唯一活跃
    production path"). The qualified form (registered + contract-verified,
    not production-routed) is acceptable.
    """
    from agent.runtime_integration import subagent_action

    src = inspect.getsource(subagent_action)
    bad_claims = [
        "V0 current — 唯一活跃 production path",
        "唯一活跃 production path",
        "the only production subagent path",
    ]
    for bad in bad_claims:
        assert bad not in src, (
            f"subagent_action.py must not contain the unqualified claim "
            f"{bad!r}; qualify with 'registered + contract-verified, not "
            f"production-routed'."
        )
