"""RED guardrails for the Sub-agent v0 runtime boundary.

These tests intentionally describe the approved v0 contract before production
code exists. Strict xfails must turn green only during U3/U3A/U4, not by
weakening the boundary.
"""

from __future__ import annotations

import pytest

from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import (
    RuntimeActionRequest,
    RuntimeActionType,
    runtime_action_support_status,
)
from agent.subagent_system import delegation, executor
from tests.runtime_integration.subagent_v0_contract_helpers import (
    route_v0,
    v0_action_type,
)

DEFERRED_SUBAGENT_ACTIONS = (
    RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST,
    RuntimeActionType.SUBAGENT_CHILD_RESULT,
    RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION,
    RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
    RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY,
)


def test_subagent_delegate_v0_is_the_only_product_v0_handler() -> None:
    action = v0_action_type()
    descriptor = runtime_action_support_status(action)
    dispatcher = build_phase1_dispatcher()

    assert descriptor.production_supported is True
    assert descriptor.support_status == "production"
    assert type(dispatcher.get_handler(action)).__name__ == "SubAgentV0Handler"

    product_handlers = {
        candidate: dispatcher.get_handler(candidate)
        for candidate in (
            RuntimeActionType.SUBAGENT_DELEGATE_L0,
            RuntimeActionType.SUBAGENT_DELEGATE_L1,
            RuntimeActionType.SUBAGENT_DELEGATE_L2,
            action,
        )
        if runtime_action_support_status(candidate).production_supported
    }
    assert set(product_handlers) == {action}


def test_subagent_delegate_l2_is_not_registered_in_production_dispatcher() -> None:
    v0_action_type()
    dispatcher = build_phase1_dispatcher()
    descriptor = runtime_action_support_status(RuntimeActionType.SUBAGENT_DELEGATE_L2)

    assert descriptor.production_supported is False
    assert descriptor.support_status in {"deferred", "experimental", "test_only", "compat_only"}
    assert descriptor.add_handler_now is False
    assert dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L2) is None


def test_v0_product_route_does_not_call_l1_l2_executor_or_delegation_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_execute_l1(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("product v0 path must not call execute_l1")

    def forbid_execute_l2(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("product v0 path must not call execute_l2")

    def forbid_delegate_l1(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("product v0 path must not call delegate_l1")

    def forbid_delegate_l2(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("product v0 path must not call delegate_l2")

    monkeypatch.setattr(executor, "execute_l1", forbid_execute_l1)
    monkeypatch.setattr(executor, "execute_l2", forbid_execute_l2)
    monkeypatch.setattr(delegation, "execute_l1", forbid_execute_l1)
    monkeypatch.setattr(delegation, "execute_l2", forbid_execute_l2)
    monkeypatch.setattr(delegation, "delegate_l1", forbid_delegate_l1)
    monkeypatch.setattr(delegation, "delegate_l2", forbid_delegate_l2)

    result = route_v0()

    assert result.status in {"success", "rejected", "failed"}
    assert result.evidence.get("action_type") == v0_action_type().value
    assert result.evidence.get("handler_name") == "SubAgentV0Handler"


def test_child_actions_remain_deferred_reserved_and_unregistered() -> None:
    dispatcher = build_phase1_dispatcher()

    for action in DEFERRED_SUBAGENT_ACTIONS:
        descriptor = runtime_action_support_status(action)
        assert descriptor.support_status == "deferred"
        assert descriptor.production_supported is False
        assert descriptor.reserved is True
        assert descriptor.raw_child_payload_allowed is False
        assert dispatcher.get_handler(action) is None


def test_runtime_action_schema_declares_v0_without_l1_l2_co_production() -> None:
    v0_action = v0_action_type()
    legacy_actions = (
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
        RuntimeActionType.SUBAGENT_DELEGATE_L1,
        RuntimeActionType.SUBAGENT_DELEGATE_L2,
    )
    assert runtime_action_support_status(v0_action).production_supported is True
    assert all(
        runtime_action_support_status(action).production_supported is False
        for action in legacy_actions
    )


def test_v0_has_no_second_runtime_or_autonomous_child_loop_contract() -> None:
    result = route_v0(payload={"max_turns": 1})

    assert result.evidence.get("max_turns") == 1
    assert result.evidence.get("second_runtime_created") is False
    assert result.evidence.get("autonomous_child_loop") is False
    assert result.evidence.get("l2_revision_loop") is False
    assert result.evidence.get("batch_memory_seen") is False


def test_no_v0_action_is_currently_hidden_under_existing_l1_l2_names() -> None:
    assert "subagent.delegate_v0" not in {
        RuntimeActionType.SUBAGENT_DELEGATE_L0.value,
        RuntimeActionType.SUBAGENT_DELEGATE_L1.value,
        RuntimeActionType.SUBAGENT_DELEGATE_L2.value,
    }


def test_subagent_delegate_l1_is_not_product_v0_production_handler() -> None:
    v0_action_type()
    descriptor = runtime_action_support_status(RuntimeActionType.SUBAGENT_DELEGATE_L1)
    dispatcher = build_phase1_dispatcher()

    assert descriptor.production_supported is False
    assert descriptor.support_status in {"deferred", "experimental", "test_only", "compat_only"}
    assert descriptor.add_handler_now is False
    assert dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L1) is None


def test_product_v0_delegation_never_falls_back_to_l1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_delegate_l1(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("delegate_l1 fallback was used by product v0 delegation")

    monkeypatch.setattr(delegation, "delegate_l1", forbidden_delegate_l1)

    result = route_v0(payload={"requested_profile_status": "product"})

    assert result.evidence.get("action_type") == v0_action_type().value
    assert result.evidence.get("legacy_fallback_used") is False


def test_product_v0_delegation_never_triggers_l2_handler_or_l2_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.runtime_integration import subagent_delegate_l2

    def forbidden_l2(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy L2 path was used by product v0 delegation")

    monkeypatch.setattr(subagent_delegate_l2.SubAgentDelegateL2Handler, "handle", forbidden_l2)
    monkeypatch.setattr(executor, "execute_l2", forbidden_l2)
    monkeypatch.setattr(delegation, "delegate_l2", forbidden_l2)

    result = route_v0(payload={"requested_profile_status": "product"})

    assert result.evidence.get("action_type") == v0_action_type().value
    assert result.evidence.get("legacy_fallback_used") is False


def test_subagent_delegate_l1_direct_production_route_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.runtime_integration import subagent_action

    v0_action_type()

    def forbidden_l1_handler(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("SubAgentDelegateL1Handler was invoked from production dispatcher")

    def forbidden_l1_execution(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy L1 execution was invoked from production dispatcher")

    monkeypatch.setattr(
        subagent_action.SubAgentDelegateL1Handler,
        "handle",
        forbidden_l1_handler,
    )
    monkeypatch.setattr(executor, "execute_l1", forbidden_l1_execution)
    monkeypatch.setattr(delegation, "delegate_l1", forbidden_l1_execution)
    dispatcher = build_phase1_dispatcher()

    assert dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L1) is None
    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L1,
        source="subagent-v0-red-guardrail",
        parent_trace_id="parent",
        payload={
            "subagent_name": "code-reviewer",
            "delegation_goal": "must not run /tmp/raw-secret.txt",
            "api_key": "sk-live-u3a-freeze-secret",
        },
    ))

    assert result.status == "not_supported"
    assert result.payload == {"reason": "no handler registered"}
    assert result.evidence["target_handler_invoked"] is False
    assert result.evidence["module_invoked"] is False
    assert result.evidence["result_returned_to_parent_runtime"] is True
    surfaces = repr({"payload": result.payload, "evidence": result.evidence})
    assert "/tmp/raw-secret.txt" not in surfaces
    assert "sk-live-u3a-freeze-secret" not in surfaces


def test_subagent_delegate_l2_direct_production_route_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent.runtime_integration import subagent_delegate_l2

    v0_action_type()

    def forbidden_l2_handler(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("SubAgentDelegateL2Handler was invoked from production dispatcher")

    monkeypatch.setattr(
        subagent_delegate_l2.SubAgentDelegateL2Handler,
        "handle",
        forbidden_l2_handler,
    )
    monkeypatch.setattr(executor, "execute_l2", forbidden_l2_handler)
    monkeypatch.setattr(delegation, "delegate_l2", forbidden_l2_handler)
    dispatcher = build_phase1_dispatcher()

    assert dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L2) is None
    result = dispatcher.route(RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
        source="subagent-v0-red-guardrail",
        parent_trace_id="parent",
        payload={
            "task": "must not run RAW_PROMPT_SHOULD_NOT_LEAK",
            "policy_path": "/tmp/raw-policy-path",
        },
    ))
    assert result.status == "not_supported"
    assert result.payload == {"reason": "no handler registered"}
    assert result.evidence["target_handler_invoked"] is False
    assert result.evidence["module_invoked"] is False
    assert result.evidence["result_returned_to_parent_runtime"] is True
    surfaces = repr({"payload": result.payload, "evidence": result.evidence})
    assert "RAW_PROMPT_SHOULD_NOT_LEAK" not in surfaces
    assert "/tmp/raw-policy-path" not in surfaces
