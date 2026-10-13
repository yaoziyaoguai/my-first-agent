"""F3a-D06：owned_resources_closed 只认 exact start/stop/open/action/close + 资源门槛。"""

from __future__ import annotations

import json
from dataclasses import replace

from agent.runtime.contracts import ConversationFact, ConversationState, FactKind
from scripts.run_real_coding_scenario import (
    _browser_executed_facts,
    _managed_web_receipts,
    _resource_closure,
)


def _managed_fact(label: str, tool_name: str, payload: dict) -> ConversationFact:
    return ConversationFact(
        fact_id=f"fact:managed:{label}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": label,
            "text": json.dumps(payload),
            "is_error": False,
            "executed": True,
            "metadata": {"tool_name": tool_name},
        },
    )


def _assert_unclosed(facts) -> None:
    state = replace(ConversationState.new("c"), facts=facts)
    assert _resource_closure(state) is False


def _browser_fact(label: str, metadata: dict) -> ConversationFact:
    return ConversationFact(
        fact_id=f"fact:browser:{label}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": label,
            "text": "browser",
            "is_error": False,
            "executed": True,
            "metadata": metadata,
        },
    )


OPEN_META = {
    "browser_result_kind": "browser_open",
    "session_ref": "session-0123456789abcdef",
}
ACTION_META = {
    "browser_receipt_kind": "browser_action_v1",
    "outcome": "effect_applied",
    "session_ref": "session-0123456789abcdef",
}
CLOSE_META = {
    "browser_result_kind": "browser_close",
    "session_ref": "session-0123456789abcdef",
    "cleanup_outcome": "cleaned",
}


def test_f3_d06_exact_positive_flow_passes_resource_gate() -> None:
    """A14-正向：exact start/stop + open/action/cleaned close → 资源项可 true。"""

    facts = (
        _managed_fact(
            "start", "managed_web_start", {"resource_ref": "r1", "status": "ready"}
        ),
        _browser_fact("open", OPEN_META),
        _browser_fact("act", ACTION_META),
        _managed_fact(
            "stop",
            "managed_web_stop",
            {"resource_ref": "r1", "cleanup": "confirmed"},
        ),
        _browser_fact("close", CLOSE_META),
    )
    state = replace(ConversationState.new("c"), facts=facts)
    started, stopped = _managed_web_receipts(state)
    assert started and stopped
    view = _browser_executed_facts(state)
    assert view["open"] and view["action_applied"] and view["closed"]
    assert _resource_closure(state) is True


def test_f3_d06_missing_or_unknown_cleanup_fails_resource_item() -> None:
    """A14：缺 cleanup 证据或 UNKNOWN → 资源项不通过（不得靠审批名单判通过）。"""

    start = _managed_fact(
        "start", "managed_web_start", {"resource_ref": "r1", "status": "ready"}
    )
    open_fact = _browser_fact("open", OPEN_META)
    act = _browser_fact("act", ACTION_META)
    # (a) 无任何 stop/close：门槛不解除。
    _assert_unclosed((start, open_fact, act))
    # (b) close 是 cleanup_unknown：门槛不解除（resource_lifecycle 只认 cleaned）。
    unknown_close = _browser_fact(
        "close-unknown",
        {**CLOSE_META, "cleanup_outcome": "cleanup_unknown"},
    )
    _assert_unclosed((start, open_fact, act, unknown_close))
    # (c) stop 未确认：门槛不解除。
    unconfirmed_stop = _managed_fact(
        "stop", "managed_web_stop", {"resource_ref": "r1", "cleanup": "unknown"}
    )
    _assert_unclosed((start, unconfirmed_stop))
