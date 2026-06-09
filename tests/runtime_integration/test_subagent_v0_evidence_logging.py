"""RED guardrails for Sub-agent v0 evidence and logging."""

from __future__ import annotations

import json

import pytest

from tests.runtime_integration.subagent_v0_contract_helpers import V0_XFAIL, route_v0

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

SUCCESS_PATH_EVENTS = (
    "subagent.request.created",
    "subagent.profile.selected",
    "subagent.context.built",
    "subagent.execution.started",
    "subagent.provider.called",
    "subagent.provider.completed",
    "subagent.result.produced",
    "subagent.parent_decision.pending",
)

FAIL_CLOSED_REQUIRED_EVENTS = (
    "subagent.request.created",
    "subagent.profile.selected",
    "subagent.context.built",
    "subagent.execution.started",
    "subagent.provider.called",
    "subagent.provider.completed",
    "subagent.result.produced",
    "subagent.parent_decision.pending",
)

SAFE_POLICY_FIELDS = {
    "policy_id",
    "policy_rule_id",
    "policy_hash",
    "policy_decision_source",
}


@pytest.mark.xfail(**V0_XFAIL)
def test_required_v0_lifecycle_event_catalog_is_declared() -> None:
    result = route_v0(payload={"introspect_lifecycle_catalog": True})

    assert set(REQUIRED_V0_EVENTS) <= set(result.evidence["lifecycle_event_catalog"])


@pytest.mark.xfail(**V0_XFAIL)
def test_success_path_emits_success_lifecycle_events_only() -> None:
    result = route_v0(payload={"scenario": "success"})
    event_names = set(result.evidence["lifecycle_events"])

    assert set(SUCCESS_PATH_EVENTS) <= event_names
    assert "subagent.execution.failed" not in event_names
    assert "subagent.execution.skipped" not in event_names
    assert "subagent.policy.blocked" not in event_names
    for event in result.evidence["lifecycle_event_payloads"]:
        assert event["delegation_id"]
        assert event["parent_trace_id"] == "parent-trace"
        assert event["profile_id"]
        assert event["provider_mode"] in {"fake_local", "real_opt_in", "disabled"}
        assert event["redacted"] is True


@pytest.mark.xfail(**V0_XFAIL)
def test_failure_path_emits_failed_event_without_success_path_forgery() -> None:
    result = route_v0(payload={"scenario": "provider_failure"})
    event_names = set(result.evidence["lifecycle_events"])

    assert "subagent.execution.failed" in event_names
    assert "subagent.execution.skipped" not in event_names
    assert "subagent.policy.blocked" not in event_names


@pytest.mark.xfail(**V0_XFAIL)
def test_skipped_path_emits_skipped_event_with_complete_policy_identifiers() -> None:
    result = route_v0(payload={
        "scenario": "skipped",
        "raw_policy_path": "/tmp/raw-policy-path.yaml",
    })
    event_names = set(result.evidence["lifecycle_events"])
    skipped_metadata = result.evidence["skipped_policy_metadata"]

    assert "subagent.execution.skipped" in event_names
    assert set(skipped_metadata) >= SAFE_POLICY_FIELDS
    assert "policy_path" not in skipped_metadata
    assert "/tmp/raw-policy-path.yaml" not in repr(skipped_metadata)


@pytest.mark.xfail(**V0_XFAIL)
def test_policy_blocked_path_emits_policy_blocked_event() -> None:
    result = route_v0(payload={"scenario": "policy_blocked", "blocked_operation": "use_tool"})
    event_names = set(result.evidence["lifecycle_events"])

    assert "subagent.policy.blocked" in event_names
    assert result.evidence["blocked_operation"] == "use_tool"


@pytest.mark.xfail(**V0_XFAIL)
def test_no_raw_child_content_path_exception_or_secret_in_nonempty_surfaces() -> None:
    result = route_v0(payload={
        "scenario": "redaction_probe",
        "raw_prompt": "RAW_PROMPT_SHOULD_NOT_LEAK",
        "raw_output": "RAW_OUTPUT_SHOULD_NOT_LEAK",
        "raw_tool_result": "RAW_TOOL_RESULT_SHOULD_NOT_LEAK",
        "raw_context": "RAW_CONTEXT_SHOULD_NOT_LEAK",
        "raw_path": "/tmp/RAW_PATH_SHOULD_NOT_LEAK",
        "raw_exception": RuntimeError("RAW_EXCEPTION_SHOULD_NOT_LEAK"),
        "secret": "sk-test-secret",
    })
    surfaces = {
        "evidence": result.evidence,
        "action_log": result.evidence["action_log"],
        "log_viewer": result.evidence["log_viewer"],
        "checkpoint_metadata": result.evidence["checkpoint_metadata"],
    }
    for name, surface in surfaces.items():
        assert surface, f"{name} must be non-empty; empty surfaces cannot prove redaction"
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


@pytest.mark.xfail(**V0_XFAIL)
def test_skipped_policy_evidence_uses_safe_policy_identifiers_only() -> None:
    result = route_v0(payload={
        "scenario": "skipped",
        "raw_policy_path": "/tmp/raw-policy-path.yaml",
    })
    metadata = result.evidence["skipped_policy_metadata"]

    assert set(metadata) >= SAFE_POLICY_FIELDS
    assert "policy_path" not in metadata
    assert "/tmp/raw-policy-path.yaml" not in repr(metadata)
    assert "sk-test-secret" not in repr(metadata)


@pytest.mark.parametrize("omitted_event", FAIL_CLOSED_REQUIRED_EVENTS)
@pytest.mark.xfail(**V0_XFAIL)
def test_missing_required_event_fails_v0_execution(omitted_event: str) -> None:
    result = route_v0(payload={"omitted_lifecycle_event": omitted_event})

    assert result.status in {"failed", "policy_blocked"}
    assert result.evidence["failure_kind"] == "missing_required_lifecycle_event"
    assert result.evidence["missing_lifecycle_event"] == omitted_event
    assert result.evidence["provider_called"] is False


@pytest.mark.xfail(**V0_XFAIL)
def test_provider_error_raw_message_is_redacted_across_all_surfaces() -> None:
    result = route_v0(payload={
        "scenario": "provider_failure",
        "provider_failure": RuntimeError(
            "RAW_PROVIDER_EXCEPTION /tmp/raw-provider-path sk-test-secret"
        ),
    })
    surfaces = {
        "evidence": result.evidence,
        "action_log": result.evidence["action_log"],
        "log_viewer": result.evidence["log_viewer"],
        "checkpoint_metadata": result.evidence["checkpoint_metadata"],
    }
    for name, surface in surfaces.items():
        assert surface, f"{name} must be non-empty"
    serialized = json.dumps(surfaces, default=str)

    assert result.evidence["provider_error_type"] == "RuntimeError"
    assert "RAW_PROVIDER_EXCEPTION" not in serialized
    assert "/tmp/raw-provider-path" not in serialized
    assert "sk-test-secret" not in serialized
