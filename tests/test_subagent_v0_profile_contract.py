"""RED guardrails for Sub-agent v0 profile capability contract."""

from __future__ import annotations

import pytest

from tests.runtime_integration.subagent_v0_contract_helpers import V0_XFAIL, route_v0


@pytest.mark.xfail(**V0_XFAIL)
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


@pytest.mark.xfail(**V0_XFAIL)
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


@pytest.mark.xfail(**V0_XFAIL)
def test_demo_profile_is_not_product_capability_and_product_status_is_explicit() -> None:
    demo = route_v0(payload={"profile_contract": {"status": "demo"}})
    product = route_v0(payload={"profile_contract": {"status": "product"}})

    assert demo.evidence["product_capability"] is False
    assert product.evidence["product_capability"] is True
    assert product.evidence["profile_status"] == "product"


@pytest.mark.xfail(**V0_XFAIL)
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


@pytest.mark.xfail(**V0_XFAIL)
def test_output_schema_constrains_safe_structured_result_and_invalid_output_fails_closed() -> None:
    output_schema = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }
    valid = route_v0(payload={
        "output_schema": output_schema,
        "provider_output": {"summary": "safe"},
    })
    invalid = route_v0(payload={
        "output_schema": output_schema,
        "provider_output": {"raw": "RAW_OUTPUT"},
    })

    assert valid.status == "ok"
    assert invalid.status in {"failed", "policy_blocked"}
    assert "RAW_OUTPUT" not in repr(invalid)
