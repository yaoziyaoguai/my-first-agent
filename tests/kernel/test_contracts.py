from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.runtime.contracts import (
    ActiveRunStatus,
    ConversationFact,
    ConversationState,
    FactKind,
    LoadedSnapshot,
    RunStatus,
    SubmitMessage,
    ToolCall,
    canonical_action_digest,
)


def test_contracts_are_immutable_and_action_digest_is_canonical() -> None:
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )

    assert canonical_action_digest(action) == canonical_action_digest(action)
    with pytest.raises(FrozenInstanceError):
        action.message = "changed"  # type: ignore[misc]


def test_durable_state_rejects_live_dependency_objects() -> None:
    with pytest.raises(TypeError, match="JSON-compatible"):
        ConversationFact(
            fact_id="fact-1",
            kind=FactKind.USER_MESSAGE,
            content={"callback": lambda: None},
        )


def test_loaded_snapshot_exposes_state_and_opaque_token_once() -> None:
    state = ConversationState.new("conversation-1")
    snapshot = LoadedSnapshot(state=state, token="sha256:fixture")

    assert snapshot.state.conversation_id == "conversation-1"
    assert snapshot.token == "sha256:fixture"
    assert ActiveRunStatus.RUNNABLE.value == "runnable"
    assert RunStatus.CONVERSATION_LIMIT_REACHED.value == "conversation_limit_reached"


def test_nested_json_payloads_reject_in_place_mutation() -> None:
    fact = ConversationFact(
        fact_id="fact-1",
        kind=FactKind.USER_MESSAGE,
        content={"nested": {"value": "original"}},
    )
    call = ToolCall(
        tool_call_id="call-1",
        name="fixture",
        arguments={"items": ["first"]},
    )

    with pytest.raises(TypeError, match="frozen JSON object"):
        fact.content["nested"]["value"] = "mutated"  # type: ignore[index]
    with pytest.raises(TypeError, match="frozen JSON array"):
        call.arguments["items"].append("second")  # type: ignore[union-attr]

    assert fact.content["nested"] == {"value": "original"}
    assert call.arguments["items"] == ["first"]
