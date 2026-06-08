"""RuntimeAction deferred/reserved ownership guardrails."""

from __future__ import annotations

import json

from agent.runtime_integration import (
    RuntimeActionDispatcher,
    RuntimeActionRequest,
    RuntimeActionType,
)
from agent.runtime_integration import schema as runtime_schema
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

DEFERRED_SUBAGENT_ACTIONS = (
    RuntimeActionType.SUBAGENT_CHILD_TOOL_REQUEST,
    RuntimeActionType.SUBAGENT_CHILD_RESULT,
    RuntimeActionType.SUBAGENT_PARENT_ADJUDICATION,
    RuntimeActionType.SUBAGENT_CHILD_MEMORY_REQUEST,
    RuntimeActionType.SUBAGENT_CHILD_BATCH_MEMORY,
)


def test_subagent_child_actions_are_explicitly_deferred_not_production_supported() -> None:
    """Reserved Sub-agent actions must not overclaim production handler support."""
    dispatcher = build_phase1_dispatcher()
    runtime_action_support_status = getattr(
        runtime_schema,
        "runtime_action_support_status",
        None,
    )
    assert callable(runtime_action_support_status)

    for action_type in DEFERRED_SUBAGENT_ACTIONS:
        descriptor = runtime_action_support_status(action_type)
        assert descriptor.support_status == "deferred"
        assert descriptor.production_supported is False
        assert descriptor.reserved is True
        assert descriptor.raw_child_payload_allowed is False
        assert descriptor.subagent_v0_owner
        assert dispatcher.get_handler(action_type) is None


def test_deferred_subagent_direct_dispatch_is_not_supported_and_redacted() -> None:
    """Direct dispatch of reserved child actions is unsupported and cannot leak raw payload."""
    raw_payload = "RAW_CHILD_PAYLOAD_SHOULD_NOT_APPEAR"
    dispatcher = RuntimeActionDispatcher()

    for action_type in DEFERRED_SUBAGENT_ACTIONS:
        result = dispatcher.route(RuntimeActionRequest(
            action_type=action_type,
            source="test",
            parent_trace_id="parent",
            payload={"child_payload": raw_payload, "summary": raw_payload},
        ))
        serialized = json.dumps(
            {
                "payload": result.payload,
                "evidence": result.evidence,
                "error_safe_preview": result.error_safe_preview,
            },
            ensure_ascii=False,
            default=str,
        )

        assert result.status == "not_supported"
        assert result.payload["reason"] in {"deferred_action", "no handler registered"}
        assert raw_payload not in serialized
