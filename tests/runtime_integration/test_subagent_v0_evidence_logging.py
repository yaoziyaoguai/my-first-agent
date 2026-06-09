"""RED guardrails for Sub-agent v0 evidence and logging."""

from __future__ import annotations

import json

import pytest

from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from tests.runtime_integration.subagent_v0_contract_helpers import route_v0

COMMON_LIFECYCLE_REQUIRED_EVENTS = (
    "subagent.request.created",
    "subagent.profile.selected",
    "subagent.context.built",
    "subagent.execution.started",
)

REQUIRED_V0_EVENTS = (
    *COMMON_LIFECYCLE_REQUIRED_EVENTS,
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
    *COMMON_LIFECYCLE_REQUIRED_EVENTS,
    "subagent.provider.called",
    "subagent.provider.completed",
    "subagent.result.produced",
    "subagent.parent_decision.pending",
)

PROVIDER_FAILURE_PATH_EVENTS = (
    *COMMON_LIFECYCLE_REQUIRED_EVENTS,
    "subagent.provider.called",
    "subagent.execution.failed",
)
SKIPPED_PATH_EVENTS = (
    *COMMON_LIFECYCLE_REQUIRED_EVENTS,
    "subagent.execution.skipped",
)
POLICY_BLOCKED_PATH_EVENTS = (
    *COMMON_LIFECYCLE_REQUIRED_EVENTS,
    "subagent.policy.blocked",
)
SUCCESS_FORBIDDEN_TERMINAL_EVENTS = (
    "subagent.execution.failed",
    "subagent.execution.skipped",
    "subagent.policy.blocked",
)
PROVIDER_FAILURE_FORBIDDEN_SUCCESS_EVENTS = (
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
SAFE_ERROR_FIELDS = {"error_type", "error_hash", "redacted"}

PATH_REQUIRED_EVENTS = {
    "success": SUCCESS_PATH_EVENTS,
    "provider_failure": PROVIDER_FAILURE_PATH_EVENTS,
    "skipped": SKIPPED_PATH_EVENTS,
    "policy_blocked": POLICY_BLOCKED_PATH_EVENTS,
}

MISSING_EVENT_CASES = (
    *(
        pytest.param(scenario, event_name, id=f"{scenario}-missing-{event_name}")
        for scenario, required_events in PATH_REQUIRED_EVENTS.items()
        for event_name in required_events
    ),
)


def _assert_safe_policy_metadata(metadata: dict[str, object]) -> None:
    assert set(metadata) >= SAFE_POLICY_FIELDS
    for field in SAFE_POLICY_FIELDS:
        assert metadata[field]
    assert "policy_path" not in metadata
    serialized = json.dumps(metadata, default=str)
    assert "policy_path" not in serialized
    assert "/tmp/raw-policy-path.yaml" not in serialized


def _assert_no_policy_path_leak(surface: object) -> None:
    serialized = json.dumps(surface, default=str)
    assert "policy_path" not in serialized
    assert "/tmp/raw-policy-path.yaml" not in serialized


def _redaction_surfaces(result) -> dict[str, object]:
    surfaces = {
        "evidence": result.evidence,
        "action_log": result.evidence["action_log"],
        "log_viewer": result.evidence["log_viewer"],
    }
    if "checkpoint_metadata" in result.evidence:
        surfaces["checkpoint_metadata"] = result.evidence["checkpoint_metadata"]
    return surfaces


def test_required_v0_lifecycle_event_catalog_is_declared() -> None:
    result = route_v0(payload={"introspect_lifecycle_catalog": True})

    assert set(REQUIRED_V0_EVENTS) <= set(result.evidence["lifecycle_event_catalog"])


def test_success_path_emits_success_lifecycle_events_only() -> None:
    result = route_v0(payload={"scenario": "success"})
    event_names = set(result.evidence["lifecycle_events"])

    assert set(SUCCESS_PATH_EVENTS) <= event_names
    for event_name in SUCCESS_FORBIDDEN_TERMINAL_EVENTS:
        assert event_name not in event_names
    for event in result.evidence["lifecycle_event_payloads"]:
        assert event["delegation_id"]
        assert event["parent_trace_id"] == "parent-trace"
        assert event["profile_id"]
        assert event["provider_mode"] in {"fake_local", "real_opt_in", "disabled"}
        assert event["redacted"] is True


def test_failure_path_emits_failed_event_without_success_path_forgery() -> None:
    result = route_v0(payload={
        "scenario": "provider_failure",
        "provider_failure": RuntimeError("RAW_FAILURE_SHOULD_NOT_LEAK sk-test-secret"),
    })
    event_names = set(result.evidence["lifecycle_events"])
    safe_error_metadata = result.evidence["safe_error_metadata"]

    assert set(PROVIDER_FAILURE_PATH_EVENTS) <= event_names
    for event_name in PROVIDER_FAILURE_FORBIDDEN_SUCCESS_EVENTS:
        assert event_name not in event_names
    assert "subagent.execution.skipped" not in event_names
    assert "subagent.policy.blocked" not in event_names
    assert result.evidence["target_module"] == "SubAgentV0Executor"
    assert result.evidence["contract_only"] is False
    assert result.evidence["not_implemented"] is False
    assert result.evidence["provider_adapter_type"] == "SubAgentV0ProviderAdapter"
    assert result.evidence["provider_called"] is True
    assert result.evidence["provider_completed"] is False
    assert result.evidence["failure_kind"] == "provider_failure"
    assert set(safe_error_metadata) >= SAFE_ERROR_FIELDS
    assert safe_error_metadata["error_type"] == "RuntimeError"
    assert safe_error_metadata["redacted"] is True
    assert "RAW_FAILURE_SHOULD_NOT_LEAK" not in repr(safe_error_metadata)
    assert "sk-test-secret" not in repr(safe_error_metadata)


def test_skipped_path_emits_skipped_event_with_complete_policy_identifiers() -> None:
    result = route_v0(payload={
        "scenario": "skipped",
        "raw_policy_path": "/tmp/raw-policy-path.yaml",
    })
    event_names = set(result.evidence["lifecycle_events"])
    skipped_metadata = result.evidence["skipped_policy_metadata"]

    assert set(SKIPPED_PATH_EVENTS) <= event_names
    _assert_safe_policy_metadata(skipped_metadata)
    _assert_no_policy_path_leak(result.evidence)


def test_policy_blocked_path_emits_policy_blocked_event() -> None:
    result = route_v0(payload={
        "scenario": "policy_blocked",
        "blocked_operation": "use_tool",
        "raw_policy_path": "/tmp/raw-policy-path.yaml",
    })
    event_names = set(result.evidence["lifecycle_events"])
    blocked_metadata = result.evidence["blocked_policy_metadata"]

    assert set(POLICY_BLOCKED_PATH_EVENTS) <= event_names
    assert result.evidence["blocked_operation"] == "use_tool"
    _assert_safe_policy_metadata(blocked_metadata)
    _assert_no_policy_path_leak(result.evidence)


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
    surfaces = _redaction_surfaces(result)
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


def test_skipped_policy_evidence_uses_safe_policy_identifiers_only() -> None:
    result = route_v0(payload={
        "scenario": "skipped",
        "raw_policy_path": "/tmp/raw-policy-path.yaml",
    })
    metadata = result.evidence["skipped_policy_metadata"]

    _assert_safe_policy_metadata(metadata)
    _assert_no_policy_path_leak(result.evidence)
    assert "sk-test-secret" not in repr(metadata)


@pytest.mark.parametrize(("scenario", "omitted_event"), MISSING_EVENT_CASES)
def test_missing_required_event_fails_v0_execution(
    scenario: str,
    omitted_event: str,
) -> None:
    result = route_v0(payload={
        "scenario": scenario,
        "omitted_lifecycle_event": omitted_event,
    })

    assert result.status in {"failed", "policy_blocked"}
    assert result.evidence["failure_kind"] == "missing_required_lifecycle_event"
    assert result.evidence["missing_lifecycle_event"] == omitted_event


def test_provider_error_raw_message_is_redacted_across_all_surfaces() -> None:
    result = route_v0(payload={
        "scenario": "provider_failure",
        "provider_failure": RuntimeError(
            "RAW_PROVIDER_EXCEPTION /tmp/raw-provider-path sk-test-secret"
        ),
    })
    surfaces = _redaction_surfaces(result)
    for name, surface in surfaces.items():
        assert surface, f"{name} must be non-empty"
    serialized = json.dumps(surfaces, default=str)

    assert result.evidence["provider_error_type"] == "RuntimeError"
    assert "RAW_PROVIDER_EXCEPTION" not in serialized
    assert "/tmp/raw-provider-path" not in serialized
    assert "sk-test-secret" not in serialized


def test_prepared_context_metadata_is_allowlisted_before_evidence_surfaces() -> None:
    dispatcher = build_phase1_dispatcher()
    request = RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="subagent-v0-redaction-test",
        parent_trace_id="parent-trace",
        payload={
            "profile_id": "default-v0",
            "provider_mode": "fake_local",
            "task": "summarize safely",
            "prepared_v0_context": {
                "metadata": {
                    "context_hash": "ctx-safe-hash",
                    "context_length": 42,
                    "context_file_count": 1,
                    "max_context_chars": 100,
                    "max_files": 2,
                    "policy_id": "policy-safe-id",
                    "policy_rule_id": "policy-safe-rule",
                    "policy_hash": "policy:safe-hash",
                    "policy_decision_source": "runtime_contract",
                    "policy_path": "/tmp/raw-policy-path.yaml",
                    "raw_context": "RAW_CONTEXT_SHOULD_NOT_LEAK",
                    "path": "/tmp/raw-context-path.txt",
                    "raw_prompt": "RAW_PROMPT_SHOULD_NOT_LEAK",
                    "api_key": "context-metadata-secret",
                },
            },
        },
    )

    result = dispatcher.route(request)
    metadata = result.evidence["context_metadata"]
    surfaces = _redaction_surfaces(result)
    serialized = json.dumps({
        "payload": result.payload,
        "surfaces": surfaces,
    }, default=str)

    assert metadata["context_hash"] == "ctx-safe-hash"
    assert metadata["context_length"] == 42
    assert metadata["context_file_count"] == 1
    assert metadata["max_context_chars"] == 100
    assert metadata["max_files"] == 2
    assert metadata["policy_id"] == "policy-safe-id"
    assert metadata["policy_rule_id"] == "policy-safe-rule"
    assert metadata["policy_hash"] == "policy:safe-hash"
    assert metadata["policy_decision_source"] == "runtime_contract"
    assert metadata["context_metadata_redacted"] is True
    assert metadata["dropped_context_metadata_count"] >= 4
    forbidden = (
        "policy_path",
        "/tmp/raw-policy-path.yaml",
        "RAW_CONTEXT_SHOULD_NOT_LEAK",
        "/tmp/raw-context-path.txt",
        "RAW_PROMPT_SHOULD_NOT_LEAK",
        "context-metadata-secret",
    )
    for token in forbidden:
        assert token not in serialized
