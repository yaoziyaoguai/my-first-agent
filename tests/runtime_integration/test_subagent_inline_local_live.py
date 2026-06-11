"""Live inline-local fallback characterization test.

WP-E (plan U3): pin the runtime fact that the *live* CLI/NL delegation
path is "L1-attempt → direct inline-local fallback" via
``subagent_inline.execute_subagent_delegation`` (NOT the registered
``SubAgentDelegateL0Handler`` and NOT ``SubAgentV0Handler``).

This test exercises the path end-to-end:

  1. The Phase 1 dispatcher (from ``build_phase1_dispatcher()``) does NOT
     have a registered ``SUBAGENT_DELEGATE_L1`` handler — confirms
     L1-attempt is a no-op route.
  2. A direct call to ``subagent_inline.execute_subagent_delegation`` with
     a known descriptor (``demo-stat``) returns a rendered string and the
     underlying ``SubAgentRequest`` is constructed with
     ``execution_mode="local_fake"`` — confirms the inline-local fallback
     is the actual live path.

This is a characterization test (R5): it pins current runtime behavior
so a future migration to V0 routing is observable as a behavior change,
not silent.
"""

from __future__ import annotations

import pytest

from agent.runtime_decision_frame import (
    build_decision_frame,
)
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionType


def test_phase1_dispatcher_does_not_register_l1_handler() -> None:
    """L1-attempt route is a no-op: no L1 handler is registered in dispatcher.

    R5 / H1 truth: SUBAGENT_DELEGATE_L1 is the action the live CLI/NL
    route asks for, but the dispatcher has no handler for it — so the
    route returns a "no handler" disposition and core.py then falls back
    to ``_execute_subagent_delegation`` (inline-local).
    """
    dispatcher = build_phase1_dispatcher()
    l1 = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L1)
    assert l1 is None, (
        "SUBAGENT_DELEGATE_L1 must NOT have a registered handler — "
        "L1 is frozen, the live route L1-attempt is a no-op that the "
        "caller (core.py) must fall back from."
    )
    # V0 IS registered, but production call site (core.py) does not route
    # to it (V0_WIRING_DECISION deferred to follow-up). This is the
    # half-finished L1/L2→V0 migration state the plan records as
    # deferred architecture debt.
    v0 = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_V0)
    assert v0 is not None, (
        "SUBAGENT_DELEGATE_V0 must be registered (V0 is registered + "
        "contract-verified, but core.py has not been migrated to route "
        "to it — see V0_WIRING_DECISION)."
    )


def test_l1_route_returns_no_handler_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routing a MEMORY/TOOL/SUBAGENT_L1 request returns 'no handler' disposition.

    Pins the second half of the L1-attempt story: the dispatcher.route()
    call does NOT raise; it returns a result whose payload communicates
    the no-handler state. core.py reads ``payload.get("delegate_l1_called")``
    and only proceeds to ``_execute_subagent_delegation`` if it is falsy.
    """
    from agent.runtime_integration.schema import RuntimeActionRequest

    dispatcher = build_phase1_dispatcher()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L1,
        source="subagent-inline-live-characterization",
        parent_trace_id="",
        payload={
            "subagent_name": "demo-stat",
            "delegation_goal": "characterize live L1-attempt path",
            "delegation_reason": "U3 characterization",
        },
    )
    result = dispatcher.route(request)
    # The result must be returned (not raised) and must NOT carry a
    # delegate_l1_called=True payload — the caller then falls back.
    assert result is not None
    payload = dict(result.payload) if result.payload else {}
    assert payload.get("delegate_l1_called") is not True, (
        "L1 route must not report 'called' — there is no L1 handler. "
        "This is the precondition for the inline-local fallback to fire."
    )


def test_inline_local_fallback_executes_and_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct call to execute_subagent_delegation with demo-stat returns a rendered string.

    Pins the second half of the live path: when core.py falls back to
    inline-local, the call produces a non-empty rendered string. The
    SubAgentRequest inside carries ``execution_mode="local_fake"`` —
    the canonical "inline local fallback" marker.
    """
    from agent import subagent_inline
    from agent.subagent_system import delegation as subagent_delegation

    captured: dict = {}

    real_delegate_once = subagent_delegation.delegate_once

    def capture_run(req, registry):
        captured["request"] = req
        return real_delegate_once(req, registry)

    monkeypatch.setattr(subagent_inline, "delegate_once", capture_run)

    rendered = subagent_inline.execute_subagent_delegation(
        "demo-stat",
        "U3 characterization: live inline-local fallback",
        delegation_reason="U3 test",
        on_runtime_event=None,
    )
    assert isinstance(rendered, str) and rendered.strip(), (
        f"inline-local fallback must return a non-empty rendered string; "
        f"got: {rendered!r}"
    )
    # Sanity: the request the inline path built carries the canonical
    # local_fake marker.
    assert captured["request"] is not None, (
        "delegate_once must have been called by the inline fallback"
    )
    assert captured["request"].execution_mode == "local_fake", (
        f"inline-local fallback must use execution_mode='local_fake'; "
        f"got: {captured['request'].execution_mode!r}"
    )


def test_runtime_decision_frame_subagent_level_reflects_live_fact() -> None:
    """The default ``build_decision_frame`` subagent_level reports the live path.

    WP-A / R1 / R2 lockstep: a freshly built decision frame must report
    the live inline-local fallback path, not the unregistered L1 label.
    This test is a runtime witness for the same contract pinned by
    test_runtime_decision_frame.py and test_subagent_l2_contract.py
    (unit-level), but checks the dynamic build path here.
    """
    frame = build_decision_frame("U3 live fact check")
    assert frame is not None
    assert frame.subagent_level == "inline_local_fallback", (
        f"RuntimeDecisionFrame.subagent_level must report the live "
        f"inline-local fallback path; got: {frame.subagent_level!r}"
    )
    # build_decision_frame is a one-shot factory; it does NOT publish
    # globally. The publish step lives in the chat-loop integration
    # (build_decision_frame_for_turn) which is exercised in the unit
    # tests. Here we just pin the factory's default value.
    #
    # Note: in the full suite some earlier test may have populated
    # _last_decision_frame via set_last_decision_frame, so we use
    # monkeypatch to capture before/after and assert the factory
    # itself did NOT publish.
    import agent.runtime_decision_frame as rdf_mod
    snapshot_before = rdf_mod._last_decision_frame
    frame2 = build_decision_frame("test2")
    assert rdf_mod._last_decision_frame is snapshot_before, (
        "build_decision_frame() must NOT mutate the global _last_decision_frame; "
        "the live publish path is owned by the chat-loop integration"
    )
    assert frame2.subagent_level == "inline_local_fallback"
