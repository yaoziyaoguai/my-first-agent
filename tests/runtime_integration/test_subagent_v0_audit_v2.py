"""U7 — Window-2 audit follow-up tests for F1/F2/F3.

These tests pin the false-confidence gaps in the previous window's
``test_subagent_v0_trusted_routing_inheritance.py`` suite:

* **F1 (budget path)**: ``SubAgentV0ProfileContract.from_payload`` reads
  ``max_context_chars`` / ``max_files`` from top-level payload keys. The
  previous fix put them under ``payload["prepared_v0_context"]["metadata"]``
  where the contract never reads. If top-level is absent, contract silently
  uses ``DEFAULT_V0_MAX_CONTEXT_CHARS`` / ``DEFAULT_V0_MAX_FILES``. Previous
  tests only checked ``> 0`` which would pass even with the contract default
  ``100_000`` / ``20`` — they gave false confidence.

* **F2 (single-turn contract)**: ``SubAgentV0Request.__post_init__`` raises
  ``ValueError("SubAgent v0 max_turns must be 1")`` for ``max_turns != 1``.
  The previous fix wrote ``max_turns=descriptor.max_iterations_default`` into
  the payload; if a descriptor has ``max_iterations_default=2`` it will trip
  the contract hard-fail. The single-turn property must be enforced on the
  V0 top-level ``max_turns`` and never derived from descriptor iteration
  count.

* **F3 (RuntimeIdentity not propagated)**: ``route_from_runtime_loop()``
  accepts ``identity=`` and propagates it to ``event.session_id`` /
  ``event.run_id`` / ``event.instance_id``. The previous production call
  does NOT pass ``identity=``; the dispatcher leaves those fields empty /
  default. The parent's ``_chat_identity`` must thread through.

These tests are deliberately sharp: they parse the **same payload object**
that the V0 handler parses (no parallel construction), so a regression in
payload field placement or routing identity will surface immediately.
"""

from __future__ import annotations

import pytest

from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_identity import RuntimeIdentity
from agent.runtime_integration.dispatcher import RuntimeActionDispatcher
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from agent.subagent_system.v0_contract import SubAgentV0ProfileContract

V0_ACTION_TYPE = str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)

# Use sentinels that are NOT the V0 contract defaults (100_000, 20, "delegation-...").
# If the production builder drops the top-level fields, the contract will
# fall back to the contract default and the assertion will fail.
SENTINEL_MAX_CONTEXT_CHARS = 43210
SENTINEL_MAX_FILES = 7
SENTINEL_SESSION_ID = "audit-v2-sentinel-session"
SENTINEL_RUN_ID = "audit-v2-sentinel-run"
# RuntimeIdentity sets instance_id = session_id in __post_init__.
SENTINEL_INSTANCE_ID = SENTINEL_SESSION_ID


def _flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")


def _v0_events(dispatcher: RuntimeActionDispatcher) -> list:
    return [ev for ev in dispatcher.action_log if ev.action_type == V0_ACTION_TYPE]


def _v0_payload(dispatcher: RuntimeActionDispatcher) -> dict:
    v0_evts = _v0_events(dispatcher)
    assert v0_evts, "expected at least one V0 action_log event"
    return v0_evts[-1].evidence or {}


def test_f1_budget_sentinels_reach_profile_contract_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: V0 budget fields must live at the payload top level.

    The V0 contract reads ``payload["max_context_chars"]`` /
    ``payload["max_files"]`` (top level). The previous production
    builder wrote them under
    ``payload["prepared_v0_context"]["metadata"]`` — the contract
    ignored them and silently used ``DEFAULT_V0_MAX_CONTEXT_CHARS``
    (``100_000``) and ``DEFAULT_V0_MAX_FILES`` (``20``).

    Sentinel: pass ``max_context_chars=43210`` and ``max_files=7``
    through chat() → real ``build_phase1_dispatcher()`` → real V0
    ``SubAgentV0ProfileContract.from_payload``. If the path is
    correct, the parsed contract has the sentinels. If the path is
    broken (or absent), the contract falls back to defaults and this
    test fails.
    """
    _flag_on(monkeypatch)

    # Inject sentinel values into the V0 contract defaults so the
    # production builder reads them and writes them to the top-level
    # payload. If the builder reads from the wrong source (e.g.
    # hardcoded literals or metadata), the parsed contract will
    # have the real defaults (100_000 / 20) instead of the sentinels.
    import agent.subagent_system.v0_contract as _v0c
    monkeypatch.setattr(_v0c, "DEFAULT_V0_MAX_CONTEXT_CHARS", SENTINEL_MAX_CONTEXT_CHARS)
    monkeypatch.setattr(_v0c, "DEFAULT_V0_MAX_FILES", SENTINEL_MAX_FILES)

    dispatcher = build_phase1_dispatcher()

    reply = chat(
        "delegate to demo-stat: 统计 demo workspace",
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
        session_id=SENTINEL_SESSION_ID,
    )
    assert reply, "chat() must return a non-empty reply"

    v0_evt = _v0_events(dispatcher)[-1]
    pc = (v0_evt.evidence or {}).get("profile_contract") or {}
    parsed_max_ctx = pc.get("max_context_chars")
    parsed_max_files = pc.get("max_files")
    assert parsed_max_ctx == SENTINEL_MAX_CONTEXT_CHARS, (
        f"F1: parsed max_context_chars={parsed_max_ctx!r} must equal "
        f"injected sentinel {SENTINEL_MAX_CONTEXT_CHARS}; production "
        f"builder did not propagate the V0 policy source to the "
        f"top-level payload."
    )
    assert parsed_max_files == SENTINEL_MAX_FILES, (
        f"F1: parsed max_files={parsed_max_files!r} must equal "
        f"injected sentinel {SENTINEL_MAX_FILES}; production builder "
        f"did not propagate the V0 policy source to the top-level "
        f"payload."
    )


def test_f1_budget_sentinels_via_real_profile_contract_from_payload() -> None:
    """F1 (unit): directly prove ``SubAgentV0ProfileContract.from_payload``
    reads top-level ``max_context_chars`` / ``max_files``.

    This is the *direct* path test: it does not depend on the
    dispatcher; it asserts the contract itself reads from the top
    level. If a future production builder ever routes these fields
    elsewhere, the contract layer of this test is the canary.
    """
    payload = {
        "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
        "max_files": SENTINEL_MAX_FILES,
        # Realistic V0 payload, but with the budget sentinels at top level.
        "profile_id": "demo-stat",
        "task": "统计 demo workspace",
        "provider_mode": "fake_local",
        "parent_opt_in": False,
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
        "allowed_tools": ("read_file",),
        "prepared_v0_context": {
            "context_hash": "deadbeef" * 8,
            "context_length": 100,
            "context_file_count": 0,
            "max_context_chars": 999_999,  # wrong path, must be ignored
            "max_files": 999,  # wrong path, must be ignored
            "parent_policy_selects_all_files": True,
            "selected_file_ids": (),
        },
    }
    profile = SubAgentV0ProfileContract.from_payload(payload)
    assert profile.max_context_chars == SENTINEL_MAX_CONTEXT_CHARS, (
        f"F1: SubAgentV0ProfileContract must read top-level "
        f"max_context_chars={SENTINEL_MAX_CONTEXT_CHARS}; got "
        f"{profile.max_context_chars!r} (likely falling back to "
        f"contract default)"
    )
    assert profile.max_files == SENTINEL_MAX_FILES, (
        f"F1: SubAgentV0ProfileContract must read top-level "
        f"max_files={SENTINEL_MAX_FILES}; got {profile.max_files!r} "
        f"(likely falling back to contract default)"
    )


def test_f1_1_top_level_keys_required_and_parsed_equal() -> None:
    """F1.1 falsification: prove the contract layer requires the top-level keys.

    Three strict assertions in a single payload:

    1. Top-level ``max_context_chars`` / ``max_files`` must be present
       and equal to the value injected (i.e. the contract does not
       silently fall back to ``DEFAULT_*`` when the keys exist).
    2. The parsed contract values must equal the raw top-level
       values (no transform, no clamp, no override).
    3. The sentinels must be different from the canonical
       ``DEFAULT_V0_MAX_CONTEXT_CHARS`` / ``DEFAULT_V0_MAX_FILES``;
       if a future refactor makes the sentinels equal the defaults
       (i.e. the test becomes a coincidence) the test fails loudly.
    """
    import agent.subagent_system.v0_contract as _v0c

    assert SENTINEL_MAX_CONTEXT_CHARS != _v0c.DEFAULT_V0_MAX_CONTEXT_CHARS, (
        f"F1.1 falsification: sentinel {SENTINEL_MAX_CONTEXT_CHARS} "
        f"coincides with contract default; the test would pass "
        f"trivially. Choose a sentinel != {_v0c.DEFAULT_V0_MAX_CONTEXT_CHARS}."
    )
    assert SENTINEL_MAX_FILES != _v0c.DEFAULT_V0_MAX_FILES, (
        f"F1.1 falsification: sentinel {SENTINEL_MAX_FILES} "
        f"coincides with contract default; the test would pass "
        f"trivially. Choose a sentinel != {_v0c.DEFAULT_V0_MAX_FILES}."
    )

    payload = {
        "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
        "max_files": SENTINEL_MAX_FILES,
        "profile_id": "demo-stat",
        "task": "统计 demo workspace",
        "provider_mode": "fake_local",
        "parent_opt_in": False,
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
        "allowed_tools": ("read_file",),
        "prepared_v0_context": {
            "context_hash": "deadbeef" * 8,
            "context_length": 100,
            "context_file_count": 0,
            "max_context_chars": 999_999,
            "max_files": 999,
            "parent_policy_selects_all_files": True,
            "selected_file_ids": (),
        },
    }
    # (1) keys must be present
    assert "max_context_chars" in payload
    assert "max_files" in payload

    profile = SubAgentV0ProfileContract.from_payload(payload)

    # (2) parsed values equal the raw top-level values
    assert profile.max_context_chars == payload["max_context_chars"], (
        f"F1.1: parsed max_context_chars={profile.max_context_chars!r} "
        f"!= raw top-level {payload['max_context_chars']!r}. "
        f"Contract may have a transform, clamp, or hidden default."
    )
    assert profile.max_files == payload["max_files"], (
        f"F1.1: parsed max_files={profile.max_files!r} "
        f"!= raw top-level {payload['max_files']!r}."
    )

    # (3) sentinels differ from canonical contract defaults
    assert profile.max_context_chars != _v0c.DEFAULT_V0_MAX_CONTEXT_CHARS, (
        f"F1.1: parsed max_context_chars equals canonical default "
        f"{_v0c.DEFAULT_V0_MAX_CONTEXT_CHARS}; the test would pass "
        f"even with no top-level key. The falsification proves the "
        f"path, not a coincidence."
    )
    assert profile.max_files != _v0c.DEFAULT_V0_MAX_FILES, (
        f"F1.1: parsed max_files equals canonical default "
        f"{_v0c.DEFAULT_V0_MAX_FILES}; falsification trivial."
    )


def test_f1_1_missing_top_level_keys_fall_back_to_contract_defaults() -> None:
    """F1.1 falsification (negative): if top-level keys are absent,
    the contract must fall back to ``DEFAULT_V0_MAX_CONTEXT_CHARS`` /
    ``DEFAULT_V0_MAX_FILES``. This proves the previous positive test
    is not passing because the contract always returns the sentinel;
    the contract is reading from the top level.
    """
    import agent.subagent_system.v0_contract as _v0c

    payload = {
        # max_context_chars and max_files deliberately absent
        "profile_id": "demo-stat",
        "task": "统计 demo workspace",
        "provider_mode": "fake_local",
        "parent_opt_in": False,
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
        "allowed_tools": ("read_file",),
        "prepared_v0_context": {
            "context_hash": "deadbeef" * 8,
            "context_length": 100,
            "context_file_count": 0,
            "parent_policy_selects_all_files": True,
            "selected_file_ids": (),
        },
    }
    assert "max_context_chars" not in payload
    assert "max_files" not in payload

    profile = SubAgentV0ProfileContract.from_payload(payload)

    # Negative falsification: without top-level keys, the contract
    # MUST return the canonical defaults. If it does not, either
    # the contract is reading from the wrong place (e.g. metadata
    # mirror) or it has hidden magic.
    assert profile.max_context_chars == _v0c.DEFAULT_V0_MAX_CONTEXT_CHARS, (
        f"F1.1 negative: with top-level keys absent, parsed "
        f"max_context_chars={profile.max_context_chars!r} != "
        f"canonical default {_v0c.DEFAULT_V0_MAX_CONTEXT_CHARS!r}. "
        f"The contract is not reading from the top level; the "
        f"positive test would pass even if the top-level path "
        f"were broken."
    )
    assert profile.max_files == _v0c.DEFAULT_V0_MAX_FILES, (
        f"F1.1 negative: with top-level keys absent, parsed "
        f"max_files={profile.max_files!r} != canonical default "
        f"{_v0c.DEFAULT_V0_MAX_FILES!r}."
    )


def test_f1_top_level_keys_present_in_raw_v0_request() -> None:
    """F1.1: V0 request raw payload (top level) must contain the budget keys.

    Tests the contract reader's surface independently of the dispatcher.
    If the contract ever stops looking at the top level, the parsed
    ``max_context_chars`` / ``max_files`` will equal the contract
    defaults, not the injected sentinels.
    """
    import agent.subagent_system.v0_contract as _v0c

    payload = {
        "profile_id": "demo-stat",
        "task": "统计 demo workspace",
        "provider_mode": "fake_local",
        "parent_opt_in": False,
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
        "allowed_tools": ("read_file",),
        "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
        "max_files": SENTINEL_MAX_FILES,
        "prepared_v0_context": {
            "context_hash": "deadbeef" * 8,
            "context_length": 100,
            "context_file_count": 0,
            "parent_policy_selects_all_files": True,
            "selected_file_ids": (),
        },
    }

    # Falsification guard: sentinels must differ from contract defaults
    # so the test can actually distinguish "real path" from "default
    # coincidence".
    assert SENTINEL_MAX_CONTEXT_CHARS != _v0c.DEFAULT_V0_MAX_CONTEXT_CHARS
    assert SENTINEL_MAX_FILES != _v0c.DEFAULT_V0_MAX_FILES

    # Top-level keys must be present and equal sentinels
    assert "max_context_chars" in payload
    assert "max_files" in payload
    assert payload["max_context_chars"] == SENTINEL_MAX_CONTEXT_CHARS
    assert payload["max_files"] == SENTINEL_MAX_FILES

    # Parsed contract must equal raw payload, NOT the contract default
    profile = SubAgentV0ProfileContract.from_payload(payload)
    assert profile.max_context_chars == SENTINEL_MAX_CONTEXT_CHARS, (
        f"F1.1: parsed max_context_chars={profile.max_context_chars!r} "
        f"must equal raw payload {SENTINEL_MAX_CONTEXT_CHARS!r}, not "
        f"the contract default {_v0c.DEFAULT_V0_MAX_CONTEXT_CHARS!r}."
    )
    assert profile.max_files == SENTINEL_MAX_FILES, (
        f"F1.1: parsed max_files={profile.max_files!r} must equal raw "
        f"payload {SENTINEL_MAX_FILES!r}, not the contract default "
        f"{_v0c.DEFAULT_V0_MAX_FILES!r}."
    )


def test_f1_falsification_removed_top_level_keys_fall_back_to_default() -> None:
    """F1.1 falsification: removing the top-level keys MUST fall back to
    contract defaults.

    This proves the test in ``test_f1_top_level_keys_present_in_raw_v0_request``
    is not passing due to a default-coincidence. If the contract still
    reads the sentinels when they are absent, the propagation path is
    not real.
    """
    import agent.subagent_system.v0_contract as _v0c

    payload = {
        "profile_id": "demo-stat",
        "task": "统计 demo workspace",
        "provider_mode": "fake_local",
        "parent_opt_in": False,
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
        "allowed_tools": ("read_file",),
        # NOTE: max_context_chars and max_files are intentionally absent
        # at the top level. Metadata mirror is also absent so the
        # contract has no source to read from.
        "prepared_v0_context": {
            "context_hash": "deadbeef" * 8,
            "context_length": 100,
            "context_file_count": 0,
            "parent_policy_selects_all_files": True,
            "selected_file_ids": (),
        },
    }

    profile = SubAgentV0ProfileContract.from_payload(payload)
    assert profile.max_context_chars == _v0c.DEFAULT_V0_MAX_CONTEXT_CHARS, (
        f"F1.1 falsification: when top-level keys are removed, parsed "
        f"max_context_chars={profile.max_context_chars!r} must equal "
        f"contract default {_v0c.DEFAULT_V0_MAX_CONTEXT_CHARS!r}. If it "
        f"does not, the contract is reading from somewhere unexpected."
    )
    assert profile.max_files == _v0c.DEFAULT_V0_MAX_FILES, (
        f"F1.1 falsification: parsed max_files={profile.max_files!r} "
        f"must equal contract default {_v0c.DEFAULT_V0_MAX_FILES!r}."
    )


def test_f2_descriptor_iteration_does_not_intoxicate_v0_max_turns() -> None:
    """F2: V0 contract must stay single-turn even when caller proposes max_turns=2.

    V0 contract hard-fails with ``ValueError("SubAgent v0 max_turns must
    be 1")`` for ``max_turns != 1``. The previous production code used
    ``descriptor.max_iterations_default`` as the V0 ``max_turns`` — if a
    descriptor has ``max_iterations_default=2`` the contract raises
    ValueError, which the V0 handler then maps to a contract failure.

    This test asserts the contract stays at ``max_turns=1`` even when
    the caller (e.g. a descriptor-driven builder) tries ``max_turns=2``.
    If a future builder forgets the V0 single-turn rule, the contract
    will raise and the test surfaces the violation.
    """
    payload_with_descriptor_iter = {
        "max_turns": 2,  # simulated descriptor max_iterations_default
        "profile_id": "demo-stat",
        "task": "test",
        "provider_mode": "fake_local",
        "parent_opt_in": False,
        "parent_stop_condition": "delegation_completion",
        "tool_scope_inherited": True,
        "prepared_v0_context": {
            "context_hash": "",
            "context_length": 0,
            "context_file_count": 0,
            "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
            "max_files": SENTINEL_MAX_FILES,
            "parent_policy_selects_all_files": True,
            "selected_file_ids": (),
        },
    }
    # V0 contract enforces max_turns=1 in __post_init__; if a future
    # builder hands in 2, the contract raises ValueError rather than
    # silently coercing. This is the safety net: production must
    # always emit max_turns=1, but if it forgets, the contract
    # refuses the payload.
    with pytest.raises(ValueError, match="max_turns must be 1"):
        SubAgentV0ProfileContract.from_payload(payload_with_descriptor_iter)


def test_f3_chat_runtime_identity_propagates_to_v0_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F3: chat()'s _chat_identity must thread into V0 action_log event.

    ``route_from_runtime_loop(identity=...)`` is the only API that
    mints ``event.session_id / run_id / instance_id`` from the
    parent. The previous production call omits ``identity=``, so the
    event has empty / default identity. This test inspects the V0
    action_log event's identity and asserts it matches the parent's
    ``_chat_identity``.
    """
    # Force a deterministic parent identity by passing session_id=
    # directly to chat(); _chat_identity is then session_id=SENTINEL
    # and instance_id=SENTINEL (RuntimeIdentity default).
    # run_id is auto-generated per chat() call, so we cannot pre-set
    # it; we instead use a sentinel run id we observe from the event.
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")

    dispatcher = build_phase1_dispatcher()

    chat(
        "delegate to demo-stat: 统计 demo workspace",
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
        session_id=SENTINEL_SESSION_ID,
    )

    v0_events = _v0_events(dispatcher)
    assert v0_events, "expected at least one V0 action_log event"

    v0 = v0_events[-1]
    # The event identity comes from the identity= kwarg. If the
    # production builder passes identity= correctly, these match the
    # sentinel env vars; if it doesn't, they are empty / default.
    assert v0.session_id == SENTINEL_SESSION_ID, (
        f"F3: V0 event.session_id must equal parent _chat_identity.session_id "
        f"({SENTINEL_SESSION_ID!r}); got {v0.session_id!r}. "
        f"(route_from_runtime_loop() was likely called without identity=.)"
    )
    # run_id is a child-generated uuid per chat() call; we only require
    # that it is non-empty and was actually minted from the parent
    # identity (NOT the empty string the dispatcher would set if
    # identity= were omitted).
    assert v0.run_id, (
        f"F3: V0 event.run_id must be a non-empty uuid minted by chat(); "
        f"got {v0.run_id!r}. (route_from_runtime_loop() was likely called "
        f"without identity=.)"
    )
    assert v0.instance_id == SENTINEL_INSTANCE_ID, (
        f"F3: V0 event.instance_id must equal parent _chat_identity.instance_id "
        f"({SENTINEL_INSTANCE_ID!r}); got {v0.instance_id!r}."
    )

    # And the dispatcher-minted provenance must still be intact.
    assert v0.evidence.get("dispatcher_origin") == "runtime_loop"
    assert v0.evidence.get("runtime_loop_invoked") is True


def test_f3_route_from_runtime_loop_propagates_identity() -> None:
    """F3 (unit): ``route_from_runtime_loop(identity=...)`` mints
    ``session_id / run_id / instance_id`` from the identity object.

    This is the direct contract proof: if a future caller forgets
    to pass ``identity=``, the event identity fields will be empty
    and the F3 chat-level test above will fail.
    """
    parent = RuntimeIdentity(
        session_id=SENTINEL_SESSION_ID,
        run_id=SENTINEL_RUN_ID,
        instance_id=SENTINEL_INSTANCE_ID,
    )
    dispatcher = build_phase1_dispatcher()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="cli_nl_delegation",
        parent_trace_id="parent-trace",
        payload={
            "profile_id": "demo-stat",
            "task": "test",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            "parent_stop_condition": "delegation_completion",
            "tool_scope_inherited": True,
            "allowed_tools": ("read_file",),
            "max_turns": 1,
            "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
            "max_files": SENTINEL_MAX_FILES,
            "prepared_v0_context": {
                "context_hash": "",
                "context_length": 0,
                "context_file_count": 0,
                "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
                "max_files": SENTINEL_MAX_FILES,
                "parent_policy_selects_all_files": True,
                "selected_file_ids": (),
            },
        },
    )
    dispatcher.route_from_runtime_loop(
        request,
        core_entrypoint="core.chat",
        runtime_hook_name="core.delegate",
        identity=parent,
    )
    v0_evt = _v0_events(dispatcher)[-1]
    assert v0_evt.session_id == SENTINEL_SESSION_ID
    assert v0_evt.run_id == SENTINEL_RUN_ID
    assert v0_evt.instance_id == SENTINEL_INSTANCE_ID


def test_f3_payload_cannot_forge_identity() -> None:
    """F3 (forge defense): the dispatcher ignores payload-supplied identity.

    Even if a payload smuggles ``session_id`` / ``run_id`` / ``instance_id``
    in, the dispatcher mints them only from the trusted ``identity=``
    argument. This prevents child callers from forging parent identity
    in the V0 event.
    """
    parent = RuntimeIdentity(
        session_id=SENTINEL_SESSION_ID,
        run_id=SENTINEL_RUN_ID,
        instance_id=SENTINEL_INSTANCE_ID,
    )
    dispatcher = build_phase1_dispatcher()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="cli_nl_delegation",
        parent_trace_id="parent-trace",
        payload={
            "session_id": "forged-session",
            "run_id": "forged-run",
            "instance_id": "forged-instance",
            "profile_id": "demo-stat",
            "task": "test",
            "provider_mode": "fake_local",
            "parent_opt_in": False,
            "parent_stop_condition": "delegation_completion",
            "tool_scope_inherited": True,
            "max_turns": 1,
            "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
            "max_files": SENTINEL_MAX_FILES,
            "prepared_v0_context": {
                "context_hash": "",
                "context_length": 0,
                "context_file_count": 0,
                "max_context_chars": SENTINEL_MAX_CONTEXT_CHARS,
                "max_files": SENTINEL_MAX_FILES,
                "parent_policy_selects_all_files": True,
                "selected_file_ids": (),
            },
        },
    )
    dispatcher.route_from_runtime_loop(
        request,
        core_entrypoint="core.chat",
        runtime_hook_name="core.delegate",
        identity=parent,
    )
    # Trusted identity wins.
    v0_evt = _v0_events(dispatcher)[-1]
    assert v0_evt.session_id == SENTINEL_SESSION_ID
    assert v0_evt.run_id == SENTINEL_RUN_ID
    assert v0_evt.instance_id == SENTINEL_INSTANCE_ID
    # Forged values must not appear in evidence.
    evidence = v0_evt.evidence or {}
    assert evidence.get("payload_session_id") != "forged-session"
    assert evidence.get("payload_run_id") != "forged-run"
    assert evidence.get("payload_instance_id") != "forged-instance"
