"""RED guardrails for Sub-agent v0 profile capability contract."""

from __future__ import annotations

import pytest

from agent.subagent_system.descriptor import SubAgentDescriptor


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 profile capability flags not implemented yet")
def test_v0_profile_capability_flags_default_safe() -> None:
    from agent.runtime_integration import subagent_action

    profile = subagent_action.default_subagent_v0_profile()

    assert profile.status == "product"
    assert profile.max_turns == 1
    assert profile.allowed_tools == ()
    assert profile.can_use_tools is False
    assert profile.can_write_memory is False
    assert profile.can_write_checkpoint is False
    assert profile.can_spawn_child is False
    assert profile.can_modify_parent_context is False
    assert profile.can_emit_parent_action is False


@pytest.mark.xfail(strict=True, reason="V0 provider capability gate not implemented yet")
def test_can_call_provider_obeys_provider_mode_allowed() -> None:
    from agent.runtime_integration import subagent_action

    fake_only = subagent_action.make_subagent_v0_profile(
        provider_mode_allowed="fake_only",
        can_call_provider=True,
    )
    real_capable = subagent_action.make_subagent_v0_profile(
        provider_mode_allowed="real_opt_in",
        can_call_provider=True,
    )

    assert subagent_action.can_call_provider(fake_only, provider_mode="fake_local") is True
    assert subagent_action.can_call_provider(fake_only, provider_mode="real_opt_in") is False
    assert subagent_action.can_call_provider(real_capable, provider_mode="real_opt_in") is True


@pytest.mark.xfail(strict=True, reason="Demo/product v0 profile separation not implemented yet")
def test_demo_profile_is_not_product_capability_and_product_status_is_explicit() -> None:
    from agent.runtime_integration import subagent_action

    demo = subagent_action.make_subagent_v0_profile(status="demo")
    product = subagent_action.make_subagent_v0_profile(status="product")

    assert subagent_action.is_product_subagent_v0_profile(demo) is False
    assert subagent_action.is_product_subagent_v0_profile(product) is True
    assert product.status == "product"


@pytest.mark.xfail(strict=True, reason="Capability flags are metadata only before U3/U4 gates")
def test_capability_flags_are_execution_gates_not_descriptor_metadata_only() -> None:
    from agent.runtime_integration import subagent_action

    profile = subagent_action.make_subagent_v0_profile(
        can_use_tools=False,
        can_write_memory=False,
        can_spawn_child=False,
    )

    for operation in ("use_tool", "write_memory", "spawn_child"):
        result = subagent_action.enforce_subagent_v0_capability(profile, operation)
        assert result.status in {"failed", "policy_blocked"}
        assert result.evidence["event"] == "subagent.policy.blocked"


@pytest.mark.xfail(strict=True, reason="V0 output_schema validation not implemented yet")
def test_output_schema_constrains_safe_structured_result_and_invalid_output_fails_closed() -> None:
    from agent.runtime_integration import subagent_action

    profile = subagent_action.make_subagent_v0_profile(
        output_schema={
            "type": "object",
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    )

    valid = subagent_action.validate_subagent_v0_output(profile, {"summary": "safe"})
    invalid = subagent_action.validate_subagent_v0_output(profile, {"raw": "RAW_OUTPUT"})

    assert valid.status == "ok"
    assert invalid.status in {"failed", "policy_blocked"}
    assert "RAW_OUTPUT" not in repr(invalid)


def test_existing_subagent_descriptor_has_no_v0_product_capability_flags_yet() -> None:
    descriptor = SubAgentDescriptor(
        name="demo-agent",
        description="demo",
        role="demo",
        status="active",
    )

    assert not hasattr(descriptor, "can_use_tools")
    assert not hasattr(descriptor, "can_write_memory")
    assert not hasattr(descriptor, "can_write_checkpoint")
    assert not hasattr(descriptor, "can_spawn_child")
    assert not hasattr(descriptor, "can_modify_parent_context")
    assert not hasattr(descriptor, "can_emit_parent_action")
