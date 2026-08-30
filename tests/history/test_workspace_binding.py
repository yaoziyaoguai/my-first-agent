from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from agent.continuity.identity import WorkspaceIdentityV1
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.runtime.checkpoint import CheckpointInvariantError, LocalCheckpointStore
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    BlockedClaim,
    ConversationFact,
    ConversationState,
    ConversationWorkspaceBindingV1,
    FactKind,
    ModelResponse,
    ProposedCriterion,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.state import create_goal
from agent.runtime.tools import KernelToolRuntime
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import CollectingSink, ScriptedProvider, goal_noop_response


def _legacy_goal_state(identity: WorkspaceIdentityV1, conversation_id: str):
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "finish the bound legacy task"},
    )
    goal = _goal(workspace_identity_digest=identity.identity_digest)
    goal = replace(
        goal,
        proposed_criteria=tuple(
            ProposedCriterion(item.criterion_id, item.description)
            for item in goal.proposed_criteria
        ),
    )
    return create_goal(
        ConversationState(conversation_id=conversation_id, facts=(source,)),
        goal,
    )


def _legacy_path(state_root, identity, conversation_id):  # noqa: ANN001
    workspace_root = state_root / "workspaces" / identity.scope_digest
    workspace_root.mkdir(mode=0o700, parents=True)
    state_root.chmod(0o700)
    (state_root / "workspaces").chmod(0o700)
    workspace_root.chmod(0o700)
    return workspace_root / f"{conversation_id}.json"


def test_new_workspace_session_is_bound_and_written_as_v4(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000101",
        bound_at_factory=lambda: "2026-08-04T01:00:00Z",
    )

    assert opened.disposition is StartupDisposition.CREATED
    assert opened.snapshot is not None
    binding = opened.snapshot.state.workspace_binding
    assert binding is not None
    assert binding.workspace_scope_digest == opened.workspace_identity.scope_digest
    assert binding.workspace_identity_digest == opened.workspace_identity.identity_digest
    assert binding.bound_at == "2026-08-04T01:00:00Z"
    assert opened.workspace_binding == binding
    document = json.loads(opened.checkpoint_path.read_text())
    # 020a：current writer 统一写 v9；v6-v8 继续作为 migration source。
    assert document["schema_version"] == 9


def test_goal_bound_v2_is_lazily_migrated_inside_runtime_lease(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    identity = WorkspaceIdentityV1.resolve(workspace)
    state_root = tmp_path / "state"
    conversation_id = "00000000-0000-4000-8000-000000000102"
    path = _legacy_path(state_root, identity, conversation_id)
    legacy = _legacy_goal_state(identity, conversation_id)
    LocalCheckpointStore.initialize(path, legacy)
    before = json.loads(path.read_text())
    assert before["schema_version"] == 2

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        bound_at_factory=lambda: "2026-08-04T01:01:00Z",
    )
    assert opened.disposition is StartupDisposition.RESUMED
    assert opened.snapshot is not None and opened.store is not None
    assert opened.snapshot.state.workspace_binding is None
    assert legacy.goal is not None
    provider = ScriptedProvider(
        goal_noop_response("workspace-migration-user-supplement"),
        ModelResponse(
            (),
            control=BlockedClaim(
                correlation_id="blocked-after-migration",
                goal_id=legacy.goal.goal_id,
                goal_revision=legacy.goal.revision,
                blocker="migration evidence collected",
                safe_attempts=("loaded the legacy checkpoint",),
                resume_condition="resume the original task",
            ),
        )
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=opened.store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        workspace_binding=opened.workspace_binding,
    )
    action = SubmitMessage(
        conversation_id=conversation_id,
        action_seq=legacy.next_action_seq,
        expected_revision=legacy.revision,
        run_id="run-migration",
        message="continue",
    )

    result = runtime.run_turn(action, opened.snapshot)

    assert result.status is RunStatus.COMPLETED
    restored = opened.store.load().state
    assert restored.workspace_binding == opened.workspace_binding
    assert json.loads(path.read_text())["schema_version"] == 9


def test_goal_less_v2_is_excluded_without_mutation_and_new_bound_session_is_created(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    identity = WorkspaceIdentityV1.resolve(workspace)
    state_root = tmp_path / "state"
    legacy_id = "00000000-0000-4000-8000-000000000103"
    legacy_path = _legacy_path(state_root, identity, legacy_id)
    LocalCheckpointStore.initialize(legacy_path, ConversationState.new(legacy_id))
    legacy_digest = hashlib.sha256(legacy_path.read_bytes()).hexdigest()

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000104",
        bound_at_factory=lambda: "2026-08-04T01:02:00Z",
    )

    assert opened.disposition is StartupDisposition.CREATED
    assert opened.snapshot is not None
    assert opened.snapshot.state.conversation_id.endswith("104")
    assert opened.snapshot.state.workspace_binding is not None
    assert opened.legacy_unbound_count == 1
    assert hashlib.sha256(legacy_path.read_bytes()).hexdigest() == legacy_digest


def test_bound_checkpoint_rejects_binding_mutation(tmp_path) -> None:
    binding = ConversationWorkspaceBindingV1.create(
        workspace_scope_digest="scope-1",
        workspace_identity_digest="workspace:v1:identity-1",
        bound_at="2026-08-04T01:03:00Z",
    )
    store = LocalCheckpointStore.initialize(
        tmp_path / "conversation.json",
        ConversationState.new("conversation-1", workspace_binding=binding),
    )
    snapshot = store.load()
    lease = store.try_acquire("conversation-1")
    assert lease is not None
    try:
        with pytest.raises(CheckpointInvariantError, match="binding cannot change"):
            store.compare_and_swap(
                snapshot,
                replace(
                    snapshot.state,
                    workspace_binding=ConversationWorkspaceBindingV1.create(
                        workspace_scope_digest="scope-1",
                        workspace_identity_digest="workspace:v1:identity-2",
                        bound_at="2026-08-04T01:03:00Z",
                    ),
                ),
            )
    finally:
        lease.release()
