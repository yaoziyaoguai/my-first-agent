from __future__ import annotations

import json
from dataclasses import replace

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore, _encode_state
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalPolicy,
    ContinuationPhase,
    ConversationState,
    ExecuteOperatorTool,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    InvocationOrigin,
    OutputPolicy,
    ResolveApproval,
    Resume,
    RunStatus,
    SideEffectClass,
    ToolExposure,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import accept_action
from agent.runtime.tools import KernelToolRuntime, RegisteredTool
from tests.kernel.fakes import CollectingSink, ScriptedProvider, conversation_with_active_goal


def _operator_action(state: ConversationState) -> ExecuteOperatorTool:
    return ExecuteOperatorTool(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        action_id="operator-action-1",
        tool_name="skill_package_stage",
        arguments={"source": {"kind": "local", "path": "private.skillpkg"}},
        submitted_at="2026-08-30T12:00:00Z",
    )


def _operator_runtime(store, provider, calls: list[str]) -> AgentRuntime:
    spec = ToolSpec(
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
        name="skill_package_stage",
        version="1",
        description="stage an operator-owned package",
        input_schema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["kind", "path"],
                    "additionalProperties": False,
                }
            },
            "required": ["source"],
            "additionalProperties": False,
        },
        risk=ToolRisk.HIGH,
        side_effect=SideEffectClass.WRITE,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.ALWAYS,
        safety_policy={},
        output_limit_chars=128,
    )
    return AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=100),
        ),
        tool_runtime=KernelToolRuntime(
            (
                RegisteredTool(
                    spec,
                    lambda intent: calls.append(intent.tool_call_id) or "staged",
                    exposure=ToolExposure.OPERATOR,
                ),
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-restarted",
    )


def _operator_tool_state() -> ConversationState:
    initial = replace(
        conversation_with_active_goal(),
        active_run=ActiveRun(run_id="run-operator"),
    )
    action = _operator_action(initial)
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


def test_operator_approval_restarts_from_checkpoint_and_invokes_once(tmp_path) -> None:
    initial = replace(
        conversation_with_active_goal(),
        active_run=ActiveRun(run_id="run-operator"),
    )
    path = tmp_path / "checkpoint.json"
    first_store = LocalCheckpointStore.initialize(path, initial)
    calls: list[str] = []
    first_provider = ScriptedProvider()
    first_runtime = _operator_runtime(first_store, first_provider, calls)

    pending = first_runtime.run_turn(_operator_action(initial), first_store.load())

    assert pending.status is RunStatus.AWAITING_APPROVAL
    assert pending.request is not None
    restarted_store = LocalCheckpointStore(path)
    restarted_provider = ScriptedProvider()
    restarted_runtime = _operator_runtime(restarted_store, restarted_provider, calls)
    snapshot = restarted_store.load()
    approval = ResolveApproval(
        conversation_id=snapshot.state.conversation_id,
        action_seq=snapshot.state.next_action_seq,
        expected_revision=snapshot.state.revision,
        request_id=pending.request.request_id,
        binding_digest=pending.request.binding_digest,
        approved=True,
    )

    completed = restarted_runtime.run_turn(approval, snapshot)
    replayed = restarted_runtime.run_turn(approval, restarted_store.load())

    assert completed.status is RunStatus.COMPLETED
    assert replayed.status is RunStatus.COMPLETED
    assert replayed.replayed is True
    assert calls == ["operator-action-1"]
    assert first_provider.calls == []
    assert restarted_provider.calls == []


def test_operator_executing_checkpoint_restarts_into_recovery_without_reinvoking(tmp_path) -> None:
    state = _operator_tool_state()
    active = state.active_run
    assert active is not None
    executing = replace(
        state,
        active_run=replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            phase=ContinuationPhase.EXECUTING,
            owner_invocation_id="crashed-invocation",
            executing_intent=ExecutingIntentRecord(
                tool_call_id="operator-action-1",
                intent_digest="operator-intent-digest",
                idempotency_key="operator-idempotency-key",
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            ),
        ),
    )
    path = tmp_path / "checkpoint.json"
    LocalCheckpointStore.initialize(path, executing)
    restarted_store = LocalCheckpointStore(path)
    calls: list[str] = []
    provider = ScriptedProvider()
    runtime = _operator_runtime(restarted_store, provider, calls)
    snapshot = restarted_store.load()

    result = runtime.run_turn(
        Resume(
            conversation_id=snapshot.state.conversation_id,
            action_seq=snapshot.state.next_action_seq,
            expected_revision=snapshot.state.revision,
        ),
        snapshot,
    )

    assert result.status is RunStatus.AWAITING_RECOVERY
    assert calls == []
    assert provider.calls == []


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
