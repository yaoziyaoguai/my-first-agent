from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore, _encode_state
from agent.runtime.contracts import (
    ActiveRun,
    ConversationState,
    ExecuteOperatorTool,
    InvocationOrigin,
)
from agent.runtime.state import accept_action
from tests.kernel.fakes import conversation_with_active_goal


def _operator_tool_state() -> ConversationState:
    initial = replace(
        conversation_with_active_goal(),
        active_run=ActiveRun(run_id="run-operator"),
    )
    action = ExecuteOperatorTool(
        conversation_id=initial.conversation_id,
        action_seq=initial.next_action_seq,
        expected_revision=initial.revision,
        action_id="operator-action-1",
        tool_name="skill_package_stage",
        arguments={"source": {"kind": "local", "path": "private.skillpkg"}},
        submitted_at="2026-08-30T12:00:00Z",
    )
    transition = accept_action(initial, action)
    assert transition.reason is None
    return transition.state


def test_operator_origin_and_private_arguments_round_trip_owner_checkpoint(tmp_path) -> None:
    state = _operator_tool_state()
    store = LocalCheckpointStore.initialize(tmp_path / "checkpoint.json", state)
    restored = store.load()
    assert restored.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    assert restored.state.active_run.tool_calls[0].arguments["source"]["path"] == "private.skillpkg"
    assert restored.token.startswith("sha256:")


_BACKGROUND_ACTIVE_KEYS = {
    "provider_call_intent",
    "persisted_model_response",
    "model_calls_used",
    "tool_calls_used",
    "sandbox_commands_used",
    "browser_actions_used",
    "input_tokens_used",
    "output_tokens_used",
}


def _historical_active_document(source_version):
    expected = replace(
        ConversationState.new("conversation-historical"),
        active_run=ActiveRun(run_id="run-historical"),
    )
    document = json.loads(_encode_state(expected).decode("utf-8"))
    assert document["schema_version"] == 9
    document["schema_version"] = source_version
    active = document["state"]["active_run"]
    active.pop("invocation_origin")
    if source_version < 8:
        document["state"].pop("background_occurrence_binding")
        for key in _BACKGROUND_ACTIVE_KEYS:
            active.pop(key)
    if source_version < 7:
        document["state"].pop("browser_leases")
        document["state"].pop("browser_takeover_pending")
    if source_version < 6:
        document["state"].pop("sandbox_leases")
    if source_version < 4:
        document["state"].pop("process_leases")
    if source_version == 2:
        document["state"].pop("workspace_binding")
    return document, expected


@pytest.mark.parametrize("source_version", [2, 3, 4, 5, 6, 7, 8])
def test_v2_through_v8_active_run_migrate_to_model_without_losing_state(
    tmp_path,
    source_version,
):
    path = tmp_path / "checkpoint.json"
    document, expected = _historical_active_document(source_version)
    assert "invocation_origin" not in document["state"]["active_run"]
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    path.chmod(0o600)
    restored = LocalCheckpointStore(path).load()
    assert restored.state.active_run.invocation_origin is InvocationOrigin.MODEL
    assert restored.state == expected
