"""RED guardrails for the Sub-agent v0 runtime boundary.

These tests intentionally describe the approved v0 contract before production
code exists. Strict xfails must turn green only during U3/U3A/U4, not by
weakening the boundary.
"""

from __future__ import annotations

import inspect

import pytest

from agent.runtime_integration import schema as runtime_schema
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import (
    RuntimeActionType,
    runtime_action_support_status,
)

DEFERRED_SUBAGENT_ACTIONS = (
    RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST,
    RuntimeActionType.SUBAGENT_CHILD_RESULT,
    RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION,
    RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
    RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY,
)


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 action/handler not implemented yet")
def test_subagent_delegate_v0_is_the_only_product_v0_handler() -> None:
    action = RuntimeActionType.SUBAGENT_DELEGATE_V0
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


@pytest.mark.xfail(strict=True, reason="L2 still production-registered before U3A freeze")
def test_subagent_delegate_l2_is_not_registered_in_production_dispatcher() -> None:
    dispatcher = build_phase1_dispatcher()
    descriptor = runtime_action_support_status(RuntimeActionType.SUBAGENT_DELEGATE_L2)

    assert descriptor.production_supported is False
    assert descriptor.support_status in {"deferred", "experimental", "test_only"}
    assert dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L2) is None


@pytest.mark.xfail(strict=True, reason="SubAgentV0Handler not implemented yet")
def test_v0_handler_cannot_call_l1_l2_executor_or_delegation_helpers() -> None:
    from agent.runtime_integration import subagent_action

    handler_cls = subagent_action.SubAgentV0Handler
    source = inspect.getsource(handler_cls)

    forbidden = (
        "execute_l1",
        "execute_l2",
        "delegate_l1",
        "delegate_l2",
        "SubAgentDelegateL2Handler",
        "batch_memory",
        "request_revision",
    )
    for token in forbidden:
        assert token not in source


def test_child_actions_remain_deferred_reserved_and_unregistered() -> None:
    dispatcher = build_phase1_dispatcher()

    for action in DEFERRED_SUBAGENT_ACTIONS:
        descriptor = runtime_action_support_status(action)
        assert descriptor.support_status == "deferred"
        assert descriptor.production_supported is False
        assert descriptor.reserved is True
        assert descriptor.raw_child_payload_allowed is False
        assert dispatcher.get_handler(action) is None


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 RuntimeActionType not added yet")
def test_runtime_action_schema_declares_v0_without_l1_l2_co_production() -> None:
    assert hasattr(RuntimeActionType, "SUBAGENT_DELEGATE_V0")

    v0_action = RuntimeActionType.SUBAGENT_DELEGATE_V0
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


@pytest.mark.xfail(strict=True, reason="V0 one-runtime contract not implemented yet")
def test_v0_has_no_second_runtime_or_autonomous_child_loop_contract() -> None:
    from agent.runtime_integration import subagent_action

    handler_cls = subagent_action.SubAgentV0Handler
    source = inspect.getsource(handler_cls).lower()

    forbidden = (
        "while ",
        "for iteration",
        "max_revisions",
        "child_messages.append",
        "independent session",
        "checkpoint writer",
        "memory writer",
    )
    for token in forbidden:
        assert token not in source
    assert "max_turns" in source
    assert "= 1" in source or ": 1" in source


def test_no_v0_action_is_currently_hidden_under_existing_l1_l2_names() -> None:
    action_values = {item.value for item in RuntimeActionType}

    assert "subagent.delegate_v0" not in {
        RuntimeActionType.SUBAGENT_DELEGATE_L0.value,
        RuntimeActionType.SUBAGENT_DELEGATE_L1.value,
        RuntimeActionType.SUBAGENT_DELEGATE_L2.value,
    }
    assert "subagent.delegate_v0" not in action_values
    assert not hasattr(runtime_schema.RuntimeActionType, "SUBAGENT_DELEGATE_V0")
