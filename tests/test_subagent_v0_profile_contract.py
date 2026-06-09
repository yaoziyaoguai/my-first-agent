"""RED guardrails for Sub-agent v0 profile capability contract."""

from __future__ import annotations

from tests.runtime_integration.subagent_v0_contract_helpers import route_v0


def test_v0_profile_capability_flags_default_safe() -> None:
    result = route_v0(payload={"introspect_profile": True})
    profile = result.evidence["profile_contract"]

    assert profile["status"] == "product"
    assert profile["max_turns"] == 1
    assert profile["allowed_tools"] == ()
    assert profile["can_use_tools"] is False
    assert profile["can_write_memory"] is False
    assert profile["can_write_checkpoint"] is False
    assert profile["can_spawn_child"] is False
    assert profile["can_modify_parent_context"] is False
    assert profile["can_emit_parent_action"] is False


def test_can_call_provider_obeys_provider_mode_allowed() -> None:
    fake_allowed = route_v0(payload={
        "profile_contract": {"provider_mode_allowed": "fake_only", "can_call_provider": True},
        "provider_mode": "fake_local",
    })
    fake_blocks_real = route_v0(payload={
        "profile_contract": {"provider_mode_allowed": "fake_only", "can_call_provider": True},
        "provider_mode": "real_opt_in",
    })
    real_allowed = route_v0(payload={
        "profile_contract": {"provider_mode_allowed": "real_opt_in", "can_call_provider": True},
        "provider_mode": "real_opt_in",
        "parent_opt_in": True,
    })

    assert fake_allowed.evidence["provider_call_allowed"] is True
    assert fake_blocks_real.status in {"failed", "policy_blocked", "rejected"}
    assert fake_blocks_real.evidence["provider_call_allowed"] is False
    assert real_allowed.evidence["provider_call_allowed"] is True


def test_demo_profile_is_not_product_capability_and_product_status_is_explicit() -> None:
    demo = route_v0(payload={"profile_contract": {"status": "demo"}})
    product = route_v0(payload={"profile_contract": {"status": "product"}})

    assert demo.evidence["product_capability"] is False
    assert product.evidence["product_capability"] is True
    assert product.evidence["profile_status"] == "product"


def test_capability_flags_are_execution_gates_not_descriptor_metadata_only() -> None:
    for operation, flag in (
        ("use_tool", "can_use_tools"),
        ("write_memory", "can_write_memory"),
        ("spawn_child", "can_spawn_child"),
    ):
        result = route_v0(payload={
            "requested_operation": operation,
            "profile_contract": {flag: False},
        })
        assert result.status in {"failed", "policy_blocked"}
        assert "subagent.policy.blocked" in result.evidence["lifecycle_events"]
        assert result.evidence["capability_flag"] == flag


def test_output_schema_constrains_safe_structured_result_and_invalid_output_fails_closed() -> None:
    output_schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }
    valid = route_v0(payload={
        "output_schema": output_schema,
        "provider_output": {
            "summary": (
                "RAW_PROVIDER_OUTPUT_SHOULD_NOT_LEAK "
                "api_key=provider-secret /tmp/raw-provider-output.txt"
            ),
        },
    })
    invalid = route_v0(payload={
        "output_schema": output_schema,
        "provider_output": {"raw": "RAW_OUTPUT"},
    })
    non_mapping = route_v0(payload={
        "output_schema": output_schema,
        "provider_output": "RAW_PROVIDER_TEXT_SHOULD_NOT_LEAK",
    })

    assert valid.status == "success"
    assert valid.evidence["provider_adapter_type"] == "SubAgentV0ProviderAdapter"
    assert valid.evidence["provider_called"] is True
    assert valid.evidence["provider_completed"] is True
    assert valid.evidence["output_schema_valid"] is True
    assert valid.evidence["safe_structured_result"] is True
    summary_projection = valid.payload["safe_output"]["summary"]
    assert summary_projection["type"] == "string"
    assert summary_projection["length"] > 0
    assert summary_projection["value_hash"]
    assert summary_projection["redacted"] is True
    serialized_valid = repr(valid.payload)
    assert "RAW_PROVIDER_OUTPUT_SHOULD_NOT_LEAK" not in serialized_valid
    assert "provider-secret" not in serialized_valid
    assert "/tmp/raw-provider-output.txt" not in serialized_valid
    assert invalid.status in {"failed", "policy_blocked"}
    assert invalid.evidence["failure_kind"] == "output_schema_validation_failed"
    assert invalid.evidence["provider_called"] is True
    assert invalid.evidence["provider_completed"] is False
    assert invalid.evidence["output_schema_valid"] is False
    assert "subagent.provider.called" in invalid.evidence["lifecycle_events"]
    assert "subagent.provider.completed" not in invalid.evidence["lifecycle_events"]
    assert "subagent.execution.failed" in invalid.evidence["lifecycle_events"]
    assert "RAW_OUTPUT" not in repr(invalid)
    assert non_mapping.status == "failed"
    assert non_mapping.evidence["failure_kind"] == "output_schema_validation_failed"
    assert non_mapping.evidence["provider_called"] is True
    assert non_mapping.evidence["provider_completed"] is False
    assert non_mapping.evidence["output_schema_valid"] is False
    assert "RAW_PROVIDER_TEXT_SHOULD_NOT_LEAK" not in repr(non_mapping)


def test_output_schema_sanitizes_nested_provider_output_without_raw_text() -> None:
    output_schema = {
        "type": "object",
        "required": ["items", "metadata"],
        "properties": {
            "items": {"type": "array"},
            "metadata": {"type": "object"},
            "safe_count": {"type": "integer"},
            "approved": {"type": "boolean"},
        },
    }
    result = route_v0(payload={
        "output_schema": output_schema,
        "provider_output": {
            "items": [
                "RAW_ARRAY_TEXT_SHOULD_NOT_LEAK",
                {"path": "/tmp/raw-nested-path.txt"},
            ],
            "metadata": {
                "raw_context": "RAW_CONTEXT_SHOULD_NOT_LEAK",
                "api_key": "nested-secret",
            },
            "safe_count": 2,
            "approved": True,
        },
    })

    assert result.status == "success"
    safe_output = result.payload["safe_output"]
    assert safe_output["items"]["type"] == "array"
    assert safe_output["items"]["length"] == 2
    assert safe_output["items"]["value_hash"]
    assert safe_output["items"]["redacted"] is True
    assert safe_output["metadata"]["type"] == "object"
    assert safe_output["metadata"]["key_count"] == 2
    assert safe_output["metadata"]["keys_hash"]
    assert safe_output["metadata"]["redacted"] is True
    assert safe_output["safe_count"]["value"] == 2
    assert safe_output["approved"]["value"] is True
    serialized = repr(result.payload)
    assert "RAW_ARRAY_TEXT_SHOULD_NOT_LEAK" not in serialized
    assert "/tmp/raw-nested-path.txt" not in serialized
    assert "RAW_CONTEXT_SHOULD_NOT_LEAK" not in serialized
    assert "nested-secret" not in serialized
    assert result.payload["status"] != "ok"
