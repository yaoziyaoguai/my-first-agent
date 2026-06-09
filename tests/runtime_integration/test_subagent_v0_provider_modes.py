"""RED guardrails for Sub-agent v0 provider mode behavior."""

from __future__ import annotations

import json

import pytest

from agent.runtime_integration.schema import RuntimeActionResult


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 provider mode contract not implemented yet")
def test_default_provider_mode_is_fake_local_safe_and_explicit() -> None:
    from agent.runtime_integration import subagent_action

    contract = subagent_action.SubAgentV0ProviderModeContract.default()

    assert contract.provider_mode == "fake_local"
    assert contract.real_call_allowed is False
    assert contract.network_allowed is False
    assert contract.activated_from_environment is False


@pytest.mark.xfail(strict=True, reason="Real provider opt-in gate not implemented yet")
def test_real_provider_requires_explicit_parent_opt_in_not_environment_drift() -> None:
    from agent.runtime_integration import subagent_action

    contract = subagent_action.SubAgentV0ProviderModeContract.from_runtime_config(
        {"ANTHROPIC_API_KEY": "sk-test-secret"},
        parent_opt_in=False,
    )

    assert contract.provider_mode != "real_opt_in"
    assert contract.real_call_allowed is False
    assert contract.provider_secret_present is True
    assert contract.secret_material_exposed is False


@pytest.mark.xfail(strict=True, reason="Unified fake/real v0 provider path not implemented yet")
def test_fake_and_real_share_request_handler_executor_parser_result_and_evidence_path() -> None:
    from agent.runtime_integration import subagent_action

    fake_path = subagent_action.describe_subagent_v0_execution_path(provider_mode="fake_local")
    real_path = subagent_action.describe_subagent_v0_execution_path(provider_mode="real_opt_in")

    shared_keys = (
        "request_type",
        "handler_type",
        "executor_type",
        "parser_type",
        "sanitizer_type",
        "result_type",
        "evidence_recorder_type",
    )
    for key in shared_keys:
        assert fake_path[key] == real_path[key]
    assert fake_path["provider_mode"] == "fake_local"
    assert real_path["provider_mode"] == "real_opt_in"


def test_runtime_action_result_rejects_secret_like_evidence() -> None:
    with pytest.raises(ValueError, match="secret-like"):
        RuntimeActionResult(
            action_type="subagent.delegate_v0",
            status="failed",
            evidence={"api_key": "sk-raw-secret-value"},
        )


@pytest.mark.xfail(strict=True, reason="Safe provider error metadata not implemented yet")
def test_provider_error_records_error_type_only_not_exception_string() -> None:
    from agent.runtime_integration import subagent_action

    result = subagent_action.safe_subagent_v0_provider_failure(
        RuntimeError("RAW_PROVIDER_FAILURE_WITH_SECRET_sk-test-secret"),
    )
    serialized = json.dumps(
        {"payload": result.payload, "evidence": result.evidence},
        default=str,
    )

    assert result.evidence["provider_error_type"] == "RuntimeError"
    assert "RAW_PROVIDER_FAILURE_WITH_SECRET" not in serialized
    assert "sk-test-secret" not in serialized
    assert "RuntimeError" in serialized


@pytest.mark.xfail(strict=True, reason="Fake/real provider result metadata not implemented yet")
def test_fake_result_is_not_labeled_as_real_and_secrets_stay_out_of_safe_surfaces() -> None:
    from agent.runtime_integration import subagent_action

    result = subagent_action.fake_subagent_v0_result(secret_marker="sk-test-secret")
    serialized = json.dumps(
        {
            "payload": result.payload,
            "evidence": result.evidence,
            "checkpoint_metadata": result.checkpoint_metadata,
        },
        default=str,
    )

    assert result.provider_mode == "fake_local"
    assert result.evidence["provider_mode"] == "fake_local"
    assert result.evidence["real_call_allowed"] is False
    assert "real_opt_in" not in serialized
    assert "sk-test-secret" not in serialized
