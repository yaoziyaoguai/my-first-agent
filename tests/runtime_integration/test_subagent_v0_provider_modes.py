"""RED guardrails for Sub-agent v0 provider mode behavior."""

from __future__ import annotations

import json

import pytest

from agent.runtime_integration.schema import RuntimeActionResult
from tests.runtime_integration.subagent_v0_contract_helpers import (
    build_v0_dispatcher_and_handler,
    build_v0_request,
    route_v0,
    v0_action_type,
)


def test_default_provider_mode_is_fake_local_safe_and_explicit() -> None:
    result = route_v0()
    evidence = dict(result.evidence)

    assert result.action_type == v0_action_type()
    assert evidence["provider_mode"] == "fake_local"
    assert evidence["real_call_allowed"] is False
    assert evidence["network_allowed"] is False
    assert evidence["activated_from_environment"] is False


def test_real_provider_requires_explicit_parent_opt_in_not_environment_drift() -> None:
    result = route_v0(payload={
        "provider_mode": "real_opt_in",
        "parent_opt_in": False,
        "ambient_env": {"ANTHROPIC_API_KEY": "sk-test-secret"},
    })
    evidence = dict(result.evidence)

    assert result.status in {"rejected", "failed", "policy_blocked"}
    assert evidence["real_call_allowed"] is False
    assert evidence["provider_mode"] != "real_opt_in"
    assert evidence["provider_secret_present"] is True
    assert evidence["secret_material_exposed"] is False


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


def test_can_call_provider_false_blocks_adapter_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher, handler = build_v0_dispatcher_and_handler()

    def forbidden_provider_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("provider adapter must not run when can_call_provider=false")

    monkeypatch.setattr(handler, "_call_v0_provider_adapter", forbidden_provider_call)
    result = dispatcher.route(build_v0_request(payload={
        "profile_contract": {
            "provider_mode_allowed": "fake_only",
            "can_call_provider": False,
        },
    }))

    assert result.status in {"policy_blocked", "failed"}
    assert result.evidence["provider_call_allowed"] is False
    assert "provider_called" not in result.evidence
    assert "provider_completed" not in result.evidence
    assert "subagent.provider.called" not in result.evidence["lifecycle_events"]
    assert "subagent.provider.completed" not in result.evidence["lifecycle_events"]


def test_real_provider_without_explicit_opt_in_blocks_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher, handler = build_v0_dispatcher_and_handler()

    def forbidden_provider_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("real provider adapter must require explicit parent opt-in")

    monkeypatch.setattr(handler, "_call_v0_provider_adapter", forbidden_provider_call)
    result = dispatcher.route(build_v0_request(provider_mode="real_opt_in", payload={
        "provider_mode": "real_opt_in",
        "parent_opt_in": False,
        "profile_contract": {
            "provider_mode_allowed": "real_opt_in",
            "can_call_provider": True,
        },
    }))

    assert result.status in {"policy_blocked", "failed"}
    assert result.evidence["provider_call_allowed"] is False
    assert result.evidence["real_call_allowed"] is False
    assert "provider_called" not in result.evidence
    assert "provider_completed" not in result.evidence
    assert "subagent.provider.called" not in result.evidence["lifecycle_events"]


def test_demo_profile_cannot_execute_real_provider_even_with_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher, handler = build_v0_dispatcher_and_handler()

    def forbidden_provider_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("demo profile must not execute product real provider")

    monkeypatch.setattr(handler, "_call_v0_provider_adapter", forbidden_provider_call)
    result = dispatcher.route(build_v0_request(provider_mode="real_opt_in", payload={
        "provider_mode": "real_opt_in",
        "parent_opt_in": True,
        "profile_contract": {
            "status": "demo",
            "provider_mode_allowed": "real_opt_in",
            "can_call_provider": True,
        },
    }))

    assert result.status in {"policy_blocked", "failed"}
    assert result.evidence["product_capability"] is False
    assert result.evidence["provider_call_allowed"] is False
    assert "provider_called" not in result.evidence
    assert "provider_completed" not in result.evidence
