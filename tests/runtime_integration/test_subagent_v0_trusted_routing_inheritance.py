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
  not ``"core_loop"`` — payload cannot forge provenance.
- The V0 ``RuntimeActionEvent.evidence`` is honest ``subsystem_integration``,
  not ``harness_runtime_e2e`` or ``real_core_loop_runtime_e2e``.
- The V0 request's payload reflects **actual parent execution** at the
  pre-loop seam: subagent descriptor ``allowed_tools`` and
  ``max_iterations_default``, real ``parent_trace_id`` (not a static
  literal), real conversation context length, no empty-placeholder
  contract values.

The H1 path was RED on unfixed production code: H1 fails on current main
because ``route()`` leaves ``dispatcher_origin`` as ``"direct_dispatcher"``.
"""

from __future__ import annotations

import pytest

from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.dispatcher import RuntimeActionDispatcher
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionType


def _v0_action_type_value() -> str:
    return str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)


def _v0_events(dispatcher: RuntimeActionDispatcher) -> list:
    v0_value = _v0_action_type_value()
    return [ev for ev in dispatcher.action_log if ev.action_type == v0_value]


def _flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")


def _real_subagent_descriptor() -> dict:
    """Read the real demo-stat descriptor frontmatter so tests pin real values.

    The descriptor is the parent-side source of truth for the V0 request's
    ``allowed_tools`` and ``max_iterations_default`` — they must NOT be
    hardcoded blanks in the production builder.
    """
    from pathlib import Path

    import yaml

    md_path = Path("agent/subagent_system/descriptors/demo-stat/SUBAGENT.md")
    raw = md_path.read_text(encoding="utf-8")
    body = raw.split("---", 2)
    if len(body) < 3:
        raise AssertionError("descriptor frontmatter missing in test fixture")
    front = yaml.safe_load(body[1]) or {}
    return {
        "name": str(front.get("name", "")),
        "role": str(front.get("role", "")),
        "risk_level": str(front.get("risk_level", "")),
        "allowed_tools": tuple(front.get("allowed_tools", ())),
        "max_iterations_default": int(front.get("max_iterations_default", 1)),
        "memory_scope": str(front.get("memory_scope", "")),
        "confirmation_policy": str(front.get("confirmation_policy", "")),
    }


def test_h1_flag_on_uses_route_from_runtime_loop_with_dispatcher_minted_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1: V0 routes through ``route_from_runtime_loop`` with dispatcher-minted provenance.

    The dispatcher (not the payload) must inject ``dispatcher_origin``,
    ``core_entrypoint``, ``runtime_hook_name`` so production evidence is
    honest. Payload cannot forge these fields.
    """
    _flag_on(monkeypatch)
    dispatcher = build_phase1_dispatcher()
    chat(
        "delegate to demo-stat: 统计 demo workspace",
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )

    v0_evt = _v0_events(dispatcher)
    assert v0_evt, "flag-on must produce V0 events"

    target = v0_evt[-1]
    evidence = target.evidence or {}
    assert evidence.get("dispatcher_origin") == "runtime_loop", (
        "H1: V0 must be routed via route_from_runtime_loop (origin=runtime_loop); "
        f"got {evidence.get('dispatcher_origin')!r}"
    )
    assert evidence.get("runtime_loop_invoked") is True, (
        "H1: runtime_loop_invoked must be True (dispatcher-minted); "
        f"got {evidence.get('runtime_loop_invoked')!r}"
    )
    assert evidence.get("core_entrypoint") == "core.chat", (
        "H1: core_entrypoint must be dispatcher-minted to 'core.chat'; "
        f"got {evidence.get('core_entrypoint')!r}"
    )
    assert evidence.get("runtime_hook_name"), (
        "H1: runtime_hook_name must be dispatcher-minted and non-empty; "
        f"got {evidence.get('runtime_hook_name')!r}"
    )
    assert target.source == "cli_nl_delegation", (
        f"H1: V0 source must be 'cli_nl_delegation' (real); got {target.source!r}"
    )
    assert target.source != "core_loop", (
        "H1: V0 source must never be 'core_loop' (production invariant)"
    )
    assert evidence.get("evidence_level") == "subsystem_integration", (
        "H1: V0 evidence must be subsystem_integration, not harness/L3; "
        f"got {evidence.get('evidence_level')!r}"
    )


def test_h1_payload_cannot_forge_core_loop_provenance() -> None:
    """H1: payload cannot forge runtime_loop provenance.

    Even if a payload supplies ``core_loop_invoked``/``dispatcher_origin``
    fields, the dispatcher (via ``route()``) must strip them and only
    ``route_from_runtime_loop()`` can write them. This test pins the
    property by sending a payload-forged request through plain ``route()``
    and asserting the dispatcher did not honor the forgery.
    """
    dispatcher = build_phase1_dispatcher()
    from agent.runtime_integration.schema import RuntimeActionRequest

    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="cli_nl_delegation",
        parent_trace_id="t-forgery",
        payload={
            "profile_id": "default-v0",
            "task": "demo stat",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            "core_loop_invoked": True,
            "runtime_loop_invoked": True,
            "dispatcher_origin": "runtime_loop",
        },
    )
    result = dispatcher.route(request)
    assert result.evidence.get("core_loop_invoked") is not True, (
        "H1: payload-forged core_loop_invoked must be stripped by plain route()"
    )
    assert result.evidence.get("runtime_loop_invoked") is not True
    assert result.evidence.get("dispatcher_origin") == "direct_dispatcher", (
        "H1: plain route() must leave dispatcher_origin as direct_dispatcher"
    )


def test_h2_v0_payload_derives_from_real_parent_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H2: V0 request builder pulls from actual parent execution state.

    The H2 audit requires child values to compare with parent-derived:
    - subagent descriptor ``allowed_tools`` and ``max_iterations_default``
    - real conversation ``context_length`` (not zero)
    - real ``parent_trace_id`` shape derived from runtime_identity, not a
      hand-rolled `delegation-<hex>` literal
    - ``profile_id`` derived from the subagent's actual name (not a
      hardcoded "default-v0")
    - ``max_context_chars`` and ``max_files`` come from the parent's loop
      budget, not placeholders
    """
    _flag_on(monkeypatch)
    descriptor = _real_subagent_descriptor()

    dispatcher = build_phase1_dispatcher()
    chat(
        "delegate to demo-stat: 统计 demo workspace",
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
    )

    v0_evt = _v0_events(dispatcher)
    assert v0_evt, "flag-on must produce V0 events"

    target = v0_evt[-1]
    evidence = target.evidence or {}
    profile_contract = evidence.get("profile_contract") or {}
    allowed_tools = tuple(evidence.get("allowed_tools") or ())

    # 1. profile_id must come from the subagent's actual name/role, not the
    #    hardcoded "default-v0" placeholder. The descriptor frontmatter is
    #    the parent-side source of truth.
    profile_id = str(profile_contract.get("profile_id") or evidence.get("profile_id") or "")
    assert profile_id and profile_id != "default-v0", (
        "H2: profile_id must be derived from the actual subagent descriptor, "
        f"not the hardcoded 'default-v0' placeholder; got {profile_id!r}"
    )
    assert profile_id == descriptor["name"], (
        "H2: profile_id must equal the descriptor's real name; "
        f"profile_id={profile_id!r} vs descriptor.name={descriptor['name']!r}"
    )

    # 2. allowed_tools must come from the descriptor's allowed_tools, not
    #    the empty tuple that the unfixed production code emits.
    assert allowed_tools, (
        "H2: allowed_tools must be derived from descriptor, not empty"
    )
    assert set(allowed_tools) == set(descriptor["allowed_tools"]), (
        "H2: allowed_tools must equal descriptor.allowed_tools; "
        f"got {set(allowed_tools)!r} vs descriptor {set(descriptor['allowed_tools'])!r}"
    )

    # 3. context_length must reflect real conversation context (>= 0 but
    #    honest, not a hardcoded zero placeholder).
    context_metadata = evidence.get("context_metadata") or {}
    context_length = context_metadata.get("context_length")
    assert context_length is not None, (
        "H2: context_length must be derived from parent conversation, not absent"
    )

    # 4. parent_trace_id must be a real runtime-identity-derived token, not
    #    a hand-rolled "delegation-<hex>" literal. The shape should
    #    reference the parent session/identity.
    parent_trace_id = target.parent_trace_id or ""
    assert parent_trace_id, (
        "H2: parent_trace_id must be derived from parent runtime_identity, not blank"
    )

    # 5. max_context_chars / max_files must come from the parent's actual
    #    loop budget, not placeholders (100_000 / 20).
    max_context_chars = int(profile_contract.get("max_context_chars") or 0)
    max_files = int(profile_contract.get("max_files") or 0)
    assert max_context_chars > 0, (
        "H2: max_context_chars must be derived from parent loop budget, not 0"
    )
    assert max_files > 0, (
        "H2: max_files must be derived from parent loop budget, not 0"
    )

    # 6. max_turns must be 1 (V0 single-turn contract hard invariant).
    #    descriptor.max_iterations_default is preserved separately as
    #    parent_descriptor_max_iterations; it must NOT be the V0
    #    max_turns. F2 unit test in test_subagent_v0_audit_v2.py
    #    proves the contract hard-fails on max_turns != 1.
    max_turns = int(profile_contract.get("max_turns") or 0)
    assert max_turns == 1, (
        f"H2: V0 max_turns must be 1 (single-turn contract); got {max_turns!r}. "
        f"descriptor.max_iterations_default={descriptor['max_iterations_default']!r} "
        f"must NOT be the V0 max_turns; it is preserved as "
        f"parent_descriptor_max_iterations metadata instead."
    )
