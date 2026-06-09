"""RED guardrails for Sub-agent v0 provider mode behavior."""

from __future__ import annotations

import json

import pytest

from agent.runtime_integration.schema import RuntimeActionResult
from tests.runtime_integration.subagent_v0_contract_helpers import (
    V0_XFAIL,
    build_v0_request,
    route_v0,
    v0_action_type,
)


@pytest.mark.xfail(**V0_XFAIL)
def test_default_provider_mode_is_fake_local_safe_and_explicit() -> None:
    result = route_v0()
    evidence = dict(result.evidence)

    assert result.action_type == v0_action_type()
    assert evidence["provider_mode"] == "fake_local"
    assert evidence["real_call_allowed"] is False
    assert evidence["network_allowed"] is False
    assert evidence["activated_from_environment"] is False


@pytest.mark.xfail(**V0_XFAIL)
def test_real_provider_requires_explicit_parent_opt_in_not_environment_drift() -> None:
    result = route_v0(payload={
        "provider_mode": "real_opt_in",
        "parent_opt_in": False,
        "ambient_env": {"ANTHROPIC_API_KEY": "sk-test-secret"},
    })
    evidence = dict(result.evidence)

    assert result.status in {"rejected", "failed"}
    assert evidence["real_call_allowed"] is False
    assert evidence["provider_mode"] != "real_opt_in"
    assert evidence["provider_secret_present"] is True
    assert evidence["secret_material_exposed"] is False


@pytest.mark.xfail(**V0_XFAIL)
def test_fake_and_real_share_request_handler_executor_parser_result_and_evidence_path() -> None:
    fake_request = build_v0_request(provider_mode="fake_local")
    real_request = build_v0_request(provider_mode="real_opt_in")
    fake_result = route_v0(provider_mode="fake_local")
    real_result = route_v0(provider_mode="real_opt_in")
    shared_evidence_keys = (
        "request_type",
        "handler_type",
        "executor_type",
        "parser_type",
        "sanitizer_type",
        "result_type",
        "evidence_recorder_type",
    )

    assert fake_request.action_type == real_request.action_type == v0_action_type()
    assert fake_result.evidence["handler_name"] == real_result.evidence["handler_name"]
    for key in shared_evidence_keys:
        assert fake_result.evidence[key] == real_result.evidence[key]
    assert fake_result.evidence["provider_mode"] == "fake_local"
    assert real_result.evidence["provider_mode"] == "real_opt_in"


def test_runtime_action_result_rejects_secret_like_evidence() -> None:
    with pytest.raises(ValueError, match="secret-like"):
        RuntimeActionResult(
            action_type="subagent.delegate_v0",
            status="failed",
            evidence={"api_key": "sk-raw-secret-value"},
        )


@pytest.mark.xfail(**V0_XFAIL)
def test_provider_error_records_error_type_only_not_exception_string() -> None:
    result = route_v0(payload={
        "provider_failure": RuntimeError(
            "RAW_PROVIDER_FAILURE_WITH_SECRET_sk-test-secret /tmp/raw-path"
        ),
    })
    serialized = json.dumps(
        {
            "payload": result.payload,
            "evidence": result.evidence,
            "action_log": result.evidence.get("action_log", ()),
            "log_viewer": result.evidence.get("log_viewer", {}),
            "checkpoint_metadata": result.evidence.get("checkpoint_metadata", {}),
        },
        default=str,
    )

    assert result.evidence["provider_error_type"] == "RuntimeError"
    assert "RAW_PROVIDER_FAILURE_WITH_SECRET" not in serialized
    assert "sk-test-secret" not in serialized
    assert "/tmp/raw-path" not in serialized
    assert "RuntimeError" in serialized


@pytest.mark.xfail(**V0_XFAIL)
def test_fake_result_is_not_labeled_as_real_and_secrets_stay_out_of_safe_surfaces() -> None:
    result = route_v0(payload={"secret_marker": "sk-test-secret"})
    serialized = json.dumps(
        {
            "payload": result.payload,
            "evidence": result.evidence,
            "checkpoint_metadata": result.evidence.get("checkpoint_metadata", {}),
        },
        default=str,
    )

    assert result.evidence["provider_mode"] == "fake_local"
    assert result.evidence["real_call_allowed"] is False
    assert "real_opt_in" not in serialized
    assert "sk-test-secret" not in serialized
