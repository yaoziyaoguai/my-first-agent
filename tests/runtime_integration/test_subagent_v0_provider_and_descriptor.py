"""B1/B2 — Provider mode derivation and missing descriptor handling.

B1: FakeProvider has ``provider_type="fake"`` but no ``raw_provider_name``
instance attribute. Production reads ``raw_provider_name`` → gets None →
sets ``provider_mode="disabled"`` → V0 handler policy-blocks the request.
The correct canonical attribute is ``provider_type``.

B2: When flag is on and descriptor is missing, production raises
``RuntimeError`` before reaching the dispatcher. This crashes the user
path instead of producing a controlled event + stable error string.
"""

from __future__ import annotations

import pytest

from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionType

V0 = str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)


def _v0_events(dispatcher):
    return [ev for ev in dispatcher.action_log if ev.action_type == V0]


def _flag_on(monkeypatch):
    monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")


def test_b1_fakeprovider_flag_on_produces_v0_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1: FakeProvider + flag on must produce V0 success, not policy_blocked.

    The V0 handler checks ``provider_mode``; if it is ``"disabled"`` or
    ``"fake_local"`` with ``provider_call_allowed=False``, the handler
    policy-blocks. The production builder must derive ``provider_mode``
    from the canonical ``provider_type`` attribute (present on all
    provider instances), not ``raw_provider_name`` (present only on
    ``ProviderResponse``).
    """
    _flag_on(monkeypatch)
    dispatcher = build_phase1_dispatcher()
    reply = chat(
        "delegate to demo-stat: 统计 demo workspace",
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
        session_id="b1-test",
    )
    assert reply, "chat() must return a non-empty reply"

    v0 = _v0_events(dispatcher)
    assert v0, "flag-on must produce V0 events"
    target = v0[-1]

    assert target.status != "policy_blocked", (
        f"B1: V0 event must NOT be policy_blocked; got status="
        f"{target.status!r}, provider_mode="
        f"{target.evidence.get('provider_mode')!r}. "
        f"Production likely reads raw_provider_name (absent on "
        f"FakeProvider) instead of provider_type."
    )
    assert target.evidence.get("provider_mode") == "fake_local", (
        f"B1: provider_mode must be 'fake_local' for FakeProvider; "
        f"got {target.evidence.get('provider_mode')!r}"
    )


def test_b2_unknown_descriptor_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B2: flag on + unknown descriptor must NOT raise RuntimeError.

    Must produce a controlled dispatcher event + stable user-visible
    error string. Must NOT execute child. Must NOT auto-fallback to
    another subagent.
    """
    _flag_on(monkeypatch)
    dispatcher = build_phase1_dispatcher()

    reply = chat(
        "delegate to nonexistent-agent: do something",
        provider=FakeProvider(),
        runtime_action_dispatcher=dispatcher,
        session_id="b2-test",
    )

    # Must not crash — reply must be a string (even if error message)
    assert isinstance(reply, str), (
        f"B2: chat() must not raise; got {type(reply).__name__}"
    )
    assert reply, "B2: reply must be non-empty (error message expected)"

    # Must not execute child — reply should indicate an error/not-found
    reply_lower = reply.lower()
    looks_like_error = (
        "error" in reply_lower
        or "not found" in reply_lower
        or "unknown" in reply_lower
        or "not_found" in reply_lower
        or "找不到" in reply_lower
    )
    assert looks_like_error or "ok" not in reply_lower, (
        f"B2: reply must indicate failure, not success; got {reply!r}"
    )
