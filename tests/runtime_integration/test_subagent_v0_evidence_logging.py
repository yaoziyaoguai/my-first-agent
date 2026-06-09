"""RED guardrails for Sub-agent v0 evidence and logging."""

from __future__ import annotations

import json

import pytest

REQUIRED_V0_EVENTS = (
    "subagent.request.created",
    "subagent.profile.selected",
    "subagent.context.built",
    "subagent.execution.started",
    "subagent.provider.called",
    "subagent.provider.completed",
    "subagent.result.produced",
    "subagent.parent_decision.pending",
    "subagent.parent_decision.applied",
    "subagent.execution.failed",
    "subagent.execution.skipped",
    "subagent.policy.blocked",
)

SAFE_POLICY_FIELDS = {
    "policy_id",
    "policy_rule_id",
    "policy_hash",
    "policy_decision_source",
}


@pytest.mark.xfail(
    strict=True,
    reason="Sub-agent v0 lifecycle evidence contract not implemented yet",
)
def test_required_v0_lifecycle_events_are_declared_and_emitted() -> None:
    from agent.runtime_integration import subagent_action

    events = subagent_action.run_fake_subagent_v0_for_evidence_smoke(
        task="summarize safely",
        parent_trace_id="parent",
    )
    event_names = {event.name for event in events}

    assert set(REQUIRED_V0_EVENTS) <= event_names
    for event in events:
        assert event.metadata["delegation_id"]
        assert event.metadata["parent_trace_id"] == "parent"
        assert event.metadata["profile_id"]
        assert event.metadata["provider_mode"] in {"fake_local", "real_opt_in", "disabled"}
        assert event.metadata["redacted"] is True


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 redaction coverage not implemented yet")
def test_no_raw_child_content_path_exception_or_secret_in_evidence_action_log_or_viewer() -> None:
    from agent.runtime_integration import subagent_action

    surfaces = subagent_action.run_subagent_v0_redaction_probe(
        raw_prompt="RAW_PROMPT_SHOULD_NOT_LEAK",
        raw_output="RAW_OUTPUT_SHOULD_NOT_LEAK",
        raw_tool_result="RAW_TOOL_RESULT_SHOULD_NOT_LEAK",
        raw_context="RAW_CONTEXT_SHOULD_NOT_LEAK",
        raw_path="/tmp/RAW_PATH_SHOULD_NOT_LEAK",
        raw_exception=RuntimeError("RAW_EXCEPTION_SHOULD_NOT_LEAK"),
        secret="sk-test-secret",
    )
    serialized = json.dumps(surfaces, default=str)

    forbidden = (
        "RAW_PROMPT_SHOULD_NOT_LEAK",
        "RAW_OUTPUT_SHOULD_NOT_LEAK",
        "RAW_TOOL_RESULT_SHOULD_NOT_LEAK",
        "RAW_CONTEXT_SHOULD_NOT_LEAK",
        "RAW_PATH_SHOULD_NOT_LEAK",
        "RAW_EXCEPTION_SHOULD_NOT_LEAK",
        "sk-test-secret",
    )
    for token in forbidden:
        assert token not in serialized


@pytest.mark.xfail(
    strict=True,
    reason="Sub-agent v0 skipped/deferred policy evidence not implemented yet",
)
def test_skipped_policy_evidence_uses_safe_policy_identifiers_only() -> None:
    from agent.runtime_integration import subagent_action

    event = subagent_action.subagent_v0_skipped_policy_event(
        raw_policy_path="/tmp/raw-policy-path.yaml",
    )
    metadata = event.metadata

    assert SAFE_POLICY_FIELDS & set(metadata)
    assert "policy_path" not in metadata
    assert "/tmp/raw-policy-path.yaml" not in repr(metadata)


@pytest.mark.xfail(strict=True, reason="No uninstrumented v0 execution gate implemented yet")
def test_missing_required_event_fails_v0_execution() -> None:
    from agent.runtime_integration import subagent_action

    result = subagent_action.run_subagent_v0_with_event_recorder(
        omitted_event="subagent.provider.completed",
    )

    assert result.status in {"failed", "policy_blocked"}
    assert result.evidence["failure_kind"] == "missing_required_lifecycle_event"
    assert result.provider_called is False
