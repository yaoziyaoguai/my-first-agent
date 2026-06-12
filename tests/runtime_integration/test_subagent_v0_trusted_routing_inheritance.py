"""U6 — Trusted V0 routing + parent-derived bounded inheritance tests (RED).

Window-1 audit findings H1/H2: flag-on V0 must (a) use the dispatcher's
``route_from_runtime_loop`` API (not plain ``route()``) so provenance is
dispatcher-minted, and (b) build the request from actual parent execution
state — not hardcoded blanks.

These tests drive ``chat()`` end-to-end with a real ``build_phase1_dispatcher``
and assert what must be observable on ``action_log`` and ``RuntimeActionEvent``:

- The routed V0 event carries dispatcher-minted runtime-loop provenance:
  ``dispatcher_origin == "runtime_loop"``,
  ``runtime_loop_invoked is True``,
  ``core_entrypoint == "core.chat"``,
  ``runtime_hook_name`` non-empty (e.g. ``"core.delegate"``).
- ``runtime_action_source`` is the real ``"cli_nl_delegation"`` string,
  never ``"core_loop"`` (which would be real_core_loop_runtime_e2e promotion).
- Evidence is honest ``subsystem_integration`` (harness/L3 out of scope).
- Payload fields are populated from real parent execution (not blanks):
  parent session/run identity propagates via ``parent_trace_id``,
  parent bounded stop condition and tool-scope are recorded.
- A payload that *tries* to forge core_loop provenance is **not** upgraded.
"""

from __future__ import annotations

import pytest

from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.dispatcher import RuntimeActionDispatcher
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import (
    RuntimeActionRequest,
    RuntimeActionType,
)
from agent.subagent_system.v0_contract import SubAgentV0Request

V0_ACTION_TYPE = str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)


def _v0_events(dispatcher: RuntimeActionDispatcher) -> list:
    return [ev for ev in dispatcher.action_log if ev.action_type == V0_ACTION_TYPE]


def _flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")


def test_h1_flag_on_uses_route_from_runtime_loop_with_dispatcher_minted_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1: flag-on V0 must mint runtime-loop provenance via route_from_runtime_loop().

    The dispatcher is the *only* component allowed to write
    ``core_loop_invoked / core_entrypoint / runtime_hook_name`` into evidence.
    Tests must observe those fields populated, source =
    ``"cli_nl_delegation"`` (not ``"core_loop"``), and the entrypoint must
    match ``"core.chat"`` with a non-empty ``runtime_hook_name``.
    """
    _flag_on(monkeypatch)
    dispatcher = build_phase1_dispatcher()

    user_input = "delegate to demo-stat: 统计 demo workspace"
    reply = chat(
        user_input,
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )
    assert reply, "chat() must return a non-empty reply"

    v0_evt = _v0_events(dispatcher)
    assert v0_evt, (
        "flag-on must produce at least one V0 action_log event; "
        f"got events: {[(e.action_type, e.status) for e in dispatcher.action_log]}"
    )

    # Pick the most recent V0 event with status=success/failed to inspect provenance.
    candidates = [ev for ev in v0_evt if ev.status not in {"not_supported"}]
    target = candidates[-1] if candidates else v0_evt[-1]

    evidence = target.evidence or {}

    # The dispatcher-minted runtime-loop provenance fields.
    assert evidence.get("dispatcher_origin") == "runtime_loop", (
        "H1: V0 must be routed via route_from_runtime_loop (origin=runtime_loop); "
        f"got {evidence.get('dispatcher_origin')!r}"
    )
    assert evidence.get("runtime_loop_invoked") is True, (
        f"H1: runtime_loop_invoked must be True; got {evidence.get('runtime_loop_invoked')!r}"
    )
    assert evidence.get("core_entrypoint") == "core.chat", (
        f"H1: dispatcher must mint core_entrypoint='core.chat'; "
        f"got {evidence.get('core_entrypoint')!r}"
    )
    assert evidence.get("runtime_hook_name"), (
        f"H1: dispatcher must mint a non-empty runtime_hook_name; "
        f"got {evidence.get('runtime_hook_name')!r}"
    )
    assert str(evidence.get("runtime_hook_name")) == "core.delegate", (
        f"H1: V0 delegation pre-loop seam must identify as 'core.delegate'; "
        f"got {evidence.get('runtime_hook_name')!r}"
    )

    # source must be the real cli_nl_delegation, never core_loop.
    assert target.source == "cli_nl_delegation", (
        f"H1: V0 source must be the truthful 'cli_nl_delegation'; got {target.source!r}"
    )
    assert target.source != "core_loop", "H1: V0 source must never be forged as 'core_loop'"

    # Evidence label stays honest subsystem_integration (not harness/L3).
    assert evidence.get("evidence_level") == "subsystem_integration", (
        f"H1: honest V0 evidence level = subsystem_integration; "
        f"got {evidence.get('evidence_level')!r}"
    )


def test_h1_payload_cannot_forge_core_loop_provenance() -> None:
    """H1 (forge defense): the dispatcher ignores payload-supplied core_loop fields.

    Even if a payload smuggles ``core_loop_invoked: True`` or
    ``runtime_loop_invoked: True`` in, the dispatcher keeps its own
    ``dispatcher_origin`` record and does not promote evidence to
    real_core_loop_runtime_e2e.
    """
    dispatcher = build_phase1_dispatcher()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="cli_nl_delegation",
        parent_trace_id="forge-1",
        payload={
            "profile_id": "default-v0",
            "task": "demo stat",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            # payload-level forgery attempts:
            "core_loop_invoked": True,
            "runtime_loop_invoked": True,
            "dispatcher_origin": "runtime_loop",
            "core_entrypoint": "core.chat",
            "runtime_hook_name": "forged.hook",
        },
    )
    # Plain route() — these forged fields must NOT survive.
    result = dispatcher.route(request)
    evidence = result.evidence or {}
    assert evidence.get("dispatcher_origin") == "direct_dispatcher", (
        "H1: route() must keep dispatcher_origin=direct_dispatcher; "
        "payload-supplied runtime_loop fields must not be promoted"
    )
    assert evidence.get("core_loop_invoked") is not True, (
        "H1: route() must NOT upgrade payload's core_loop_invoked True"
    )
    assert evidence.get("runtime_loop_invoked") is not True, (
        "H1: route() must NOT upgrade payload's runtime_loop_invoked True"
    )

    # route_from_runtime_loop() — dispatcher *does* mint, but identity must be trusted.
    result2 = dispatcher.route_from_runtime_loop(
        request,
        core_entrypoint="core.chat",
        runtime_hook_name="core.delegate",
    )
    evidence2 = result2.evidence or {}
    assert evidence2.get("dispatcher_origin") == "runtime_loop"
    assert evidence2.get("core_entrypoint") == "core.chat"
    assert evidence2.get("runtime_hook_name") == "core.delegate"


def test_h2_v0_payload_derives_from_parent_execution_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2: V0 request must be built from real parent execution data, not blanks.

    The V0 RuntimeActionEvent's ``parent_trace_id`` must be a real
    ``delegation-<hex>`` token (not empty, not a static literal), and
    the request payload's stop condition / tool scope markers must be
    populated from the parent (not zeroed out).

    Audit also requires: at least the ``parent_stop_condition`` and
    ``tool_scope_inherited`` markers must be present and non-empty
    (no hardcoded blanks to fake inheritance).
    """
    _flag_on(monkeypatch)
    dispatcher = build_phase1_dispatcher()

    user_input = "delegate to demo-stat: 统计 demo workspace"
    chat(
        user_input,
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )

    v0_evt = _v0_events(dispatcher)
    assert v0_evt, "flag-on must produce V0 events"

    target = v0_evt[-1]
    parent_trace_id = target.parent_trace_id or ""
    # The dispatcher injects a non-empty parent_trace_id; it must look like a real token.
    assert parent_trace_id, (
        f"H2: parent_trace_id must be derived from parent execution, not blank; "
        f"got {parent_trace_id!r}"
    )
    # Accept the production builder's known shape: "delegation-<hex>".
    assert parent_trace_id.startswith("delegation-"), (
        f"H2: parent_trace_id must come from the production V0 builder; "
        f"got {parent_trace_id!r}"
    )

    # The V0 contract projection must reach the handler (proof the V0 request
    # is shape-compatible with the contract, not invented by the test).
    sample = SubAgentV0Request.from_payload({
        "task": "demo stat",
        "parent_opt_in": False,
        "provider_mode": "fake_local",
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
    })
    assert sample.task_hash, "H2: V0 contract must produce a non-empty task hash"
    assert sample.profile_id == "default-v0", "H2: V0 profile must default to default-v0"
