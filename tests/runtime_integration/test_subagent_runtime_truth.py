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


def test_production_cli_delegation_routes_l1_then_falls_back() -> None:
    """The live CLI delegation path in core.py routes L1, then falls back to L0.

    This pins the *production-called* dimension that distinguishes registered
    (V0/L0 in phase1_hook) from production-called (L1-attempt → L0-fallback in
    core.py). V0 is registered + contract-tested but is NOT the path core.py
    actually drives today, so the SoT must not claim V0 is the live execution
    path without qualification.
    """
    import inspect

    from agent import core

    src = inspect.getsource(core)
    # The CLI delegation helper routes SUBAGENT_DELEGATE_L1.
    assert "RuntimeActionType.SUBAGENT_DELEGATE_L1" in src, (
        "core.py CLI delegation must still route L1 (then fall back)."
    )
    # No production routing of V0 exists yet.
    assert "RuntimeActionType.SUBAGENT_DELEGATE_V0" not in src, (
        "If core.py begins routing V0, update the SoT execution_path and this "
        "test together; today V0 is registered-only, not production-called."
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
