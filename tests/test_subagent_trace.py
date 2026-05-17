"""SubAgent Phase 13: Trace / Observability tests."""

from __future__ import annotations

from agent.subagent_system.trace import (
    L0_TRACE_EVENTS,
    SubAgentTraceEvent,
    make_trace_event,
    sanitize_trace_data,
)


def test_l0_trace_event_set_matches_minimum_required_subset() -> None:
    """L0 只要求最小 trace subset，完整 production model 留给 gated/future。"""

    assert L0_TRACE_EVENTS == {
        "delegation_started",
        "context_packaged",
        "result_returned",
        "result_adjudicated",
        "delegation_failed",
    }


def test_trace_event_is_frozen_and_sanitizes_payload() -> None:
    """trace 是 audit trail，不能成为 secret/full prompt side channel。"""

    event = make_trace_event(
        "delegation_started",
        delegation_id="delegation-1",
        parent_trace_id="trace-1",
        data={"api_key": "sk-proj-abcdefghijklmnopqrstuvwxyz", "task": "review"},
    )

    assert isinstance(event, SubAgentTraceEvent)
    assert event.data["api_key"] == "<redacted>"
    assert event.data["task"] == "review"


def test_sanitize_trace_data_truncates_large_values() -> None:
    """大块 raw prompt/artifact 只能进入截断摘要。"""

    data = sanitize_trace_data({"raw_prompt": "x" * 20_000})

    assert len(data["raw_prompt"]) < 2000
    assert "<truncated>" in data["raw_prompt"]

