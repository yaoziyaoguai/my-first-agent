from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import main as entrypoint
from agent.continuity.archive import ArchiveConflictError
from agent.continuity.sessions import (
    StartupDisposition,
    archive_workspace_session,
    open_workspace_session,
    preview_workspace_archive,
    restore_workspace_session,
)
from agent.runtime.contracts import ConversationFact, FactKind, GoalStatus
from agent.runtime.state import create_goal
from tests.continuity.test_contracts import _goal


def _terminal_session(
    workspace: Path,
    state_root: Path,
    conversation_id: str,
    *,
    max_history: int = 2,
):
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: conversation_id,
        max_history_checkpoints=max_history,
        max_candidates=min(2, max_history),
        force_new=True,
    )
    assert opened.store is not None and opened.snapshot is not None
    source = ConversationFact(
        fact_id=f"user:{conversation_id}",
        kind=FactKind.USER_MESSAGE,
        content={"text": "finished task"},
    )
    state = create_goal(
        replace(opened.snapshot.state, facts=(source,)),
        _goal(
            goal_id=f"goal:{conversation_id}",
            workspace_identity_digest=opened.workspace_identity.identity_digest,
            created_from_fact_ids=(source.fact_id,),
        ),
    )
    state = replace(state, goal=replace(state.goal, status=GoalStatus.CANCELLED))
    lease = opened.store.try_acquire(conversation_id)
    assert lease is not None
    try:
        snapshot = opened.store.compare_and_swap(opened.snapshot, state)
    finally:
        lease.release()
    return opened, snapshot


def test_explicit_archive_is_lossless_releases_capacity_and_remains_restorable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    first_id = "00000000-0000-4000-8000-000000000101"
    second_id = "00000000-0000-4000-8000-000000000102"
    third_id = "00000000-0000-4000-8000-000000000103"
    _first, first_snapshot = _terminal_session(workspace, state_root, first_id)
    _terminal_session(workspace, state_root, second_id)

    full = open_workspace_session(
        workspace,
        state_root=state_root,
        force_new=True,
        max_history_checkpoints=2,
        max_candidates=2,
    )
    assert full.disposition is StartupDisposition.HISTORY_CAPACITY_EXCEEDED

    preview = preview_workspace_archive(
        workspace,
        conversation_id=first_id,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    assert preview.checkpoint_digest == first_snapshot.token
    record = archive_workspace_session(
        workspace,
        conversation_id=first_id,
        expected_checkpoint_digest=preview.checkpoint_digest,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    assert record.source_checkpoint_digest == first_snapshot.token

    created = open_workspace_session(
        workspace,
        state_root=state_root,
        force_new=True,
        conversation_id_factory=lambda: third_id,
        max_history_checkpoints=2,
        max_candidates=2,
    )
    assert created.disposition is StartupDisposition.CREATED

    # 当前容量再次满时，恢复不得覆盖或挤掉其它会话。
    with pytest.raises(ValueError, match="history capacity"):
        restore_workspace_session(
            workspace,
            conversation_id=first_id,
            source_checkpoint_digest=record.source_checkpoint_digest,
            state_root=state_root,
            max_history_checkpoints=2,
        )

    second_preview = preview_workspace_archive(
        workspace,
        conversation_id=second_id,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    archive_workspace_session(
        workspace,
        conversation_id=second_id,
        expected_checkpoint_digest=second_preview.checkpoint_digest,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    restored = restore_workspace_session(
        workspace,
        conversation_id=first_id,
        source_checkpoint_digest=record.source_checkpoint_digest,
        state_root=state_root,
        max_history_checkpoints=2,
    )
    assert restored.snapshot is not None
    assert restored.snapshot.state == first_snapshot.state


def test_archive_rejects_active_or_stale_conversation_without_removal(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    active_id = "00000000-0000-4000-8000-000000000111"
    active = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: active_id,
    )
    with pytest.raises(ValueError, match="terminal"):
        preview_workspace_archive(
            workspace,
            conversation_id=active_id,
            state_root=state_root,
        )
    assert active.checkpoint_path is not None and active.checkpoint_path.exists()

    terminal_id = "00000000-0000-4000-8000-000000000112"
    opened, snapshot = _terminal_session(
        workspace,
        state_root,
        terminal_id,
        max_history=4,
    )
    preview = preview_workspace_archive(
        workspace,
        conversation_id=terminal_id,
        state_root=state_root,
        max_history_checkpoints=4,
    )
    assert opened.store is not None
    lease = opened.store.try_acquire(terminal_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(
            snapshot,
            replace(snapshot.state, revision=snapshot.state.revision + 1),
        )
    finally:
        lease.release()

    with pytest.raises(ValueError, match="changed after preview"):
        archive_workspace_session(
            workspace,
            conversation_id=terminal_id,
            expected_checkpoint_digest=preview.checkpoint_digest,
            state_root=state_root,
            max_history_checkpoints=4,
        )
    assert opened.checkpoint_path is not None and opened.checkpoint_path.exists()


def test_cli_archive_and_restore_require_explicit_confirmation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    conversation_id = "00000000-0000-4000-8000-000000000121"
    opened, snapshot = _terminal_session(
        workspace,
        state_root,
        conversation_id,
        max_history=4,
    )
    assert opened.checkpoint_path is not None
    common = ["--workspace", str(workspace), "--state-root", str(state_root)]
    output: list[str] = []

    assert entrypoint.main([*common, "archive", conversation_id], write_fn=output.append) == 1
    assert opened.checkpoint_path.exists()
    assert "Nothing changed" in output[-1]

    output.clear()
    assert (
        entrypoint.main(
            [*common, "archive", conversation_id, "--yes"],
            write_fn=output.append,
        )
        == 0
    )
    assert not opened.checkpoint_path.exists()
    assert snapshot.token in output[-1]

    output.clear()
    assert (
        entrypoint.main(
            [*common, "restore", conversation_id, snapshot.token],
            write_fn=output.append,
        )
        == 1
    )
    assert not opened.checkpoint_path.exists()

    output.clear()
    assert (
        entrypoint.main(
            [*common, "restore", conversation_id, snapshot.token, "--yes"],
            write_fn=output.append,
        )
        == 0
    )
    assert opened.checkpoint_path.exists()


def test_restore_rejects_corrupt_archive_without_recreating_checkpoint(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    conversation_id = "00000000-0000-4000-8000-000000000122"
    opened, _snapshot = _terminal_session(
        workspace,
        state_root,
        conversation_id,
        max_history=4,
    )
    preview = preview_workspace_archive(
        workspace,
        conversation_id=conversation_id,
        state_root=state_root,
        max_history_checkpoints=4,
    )
    record = archive_workspace_session(
        workspace,
        conversation_id=conversation_id,
        expected_checkpoint_digest=preview.checkpoint_digest,
        state_root=state_root,
        max_history_checkpoints=4,
    )
    assert opened.checkpoint_path is not None and not opened.checkpoint_path.exists()
    record.path.write_bytes(b"corrupt archive")

    with pytest.raises(ArchiveConflictError, match="digest"):
        restore_workspace_session(
            workspace,
            conversation_id=conversation_id,
            source_checkpoint_digest=record.source_checkpoint_digest,
            state_root=state_root,
            max_history_checkpoints=4,
        )

    assert not opened.checkpoint_path.exists()
