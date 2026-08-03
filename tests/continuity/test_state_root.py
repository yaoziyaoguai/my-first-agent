from __future__ import annotations

import stat
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import main as entrypoint
from agent.continuity import sessions
from agent.continuity.sessions import (
    StartupDisposition,
    open_workspace_session,
    select_workspace_session,
)
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import ConversationFact, ConversationState, FactKind, SelectGoal
from agent.runtime.state import create_goal
from tests.continuity.test_contracts import _goal


def test_default_start_creates_owner_only_product_state_root_outside_workspace(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    home.mkdir(mode=0o700)
    workspace.mkdir()

    opened = open_workspace_session(
        workspace,
        home=home,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000001",
    )

    expected_root = home / ".local" / "state" / "my-first-agent" / "v1"
    assert opened.disposition is StartupDisposition.CREATED
    assert opened.state_root == expected_root
    assert opened.checkpoint_path is not None
    assert opened.checkpoint_path.is_relative_to(expected_root)
    assert not opened.checkpoint_path.is_relative_to(workspace)
    assert stat.S_IMODE(expected_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(opened.checkpoint_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(opened.checkpoint_path.stat().st_mode) == 0o600
    assert opened.snapshot is not None
    assert opened.snapshot.state.conversation_id == "00000000-0000-4000-8000-000000000001"


def test_explicit_state_root_override_is_owner_only_and_no_follow(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    explicit_root = tmp_path / "explicit-state"

    opened = open_workspace_session(
        workspace,
        state_root=explicit_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000002",
    )

    assert opened.state_root == explicit_root
    assert stat.S_IMODE(explicit_root.stat().st_mode) == 0o700

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    alias = tmp_path / "state-alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="real directory"):
        open_workspace_session(
            workspace,
            state_root=alias / "nested-root",
            conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000003",
        )


def test_workspace_symlink_alias_resolves_same_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias = tmp_path / "workspace-alias"
    alias.symlink_to(workspace, target_is_directory=True)
    state_root = tmp_path / "state-root"

    first = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000004",
    )
    reopened = open_workspace_session(
        alias,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000005",
    )

    assert reopened.disposition is StartupDisposition.RESUMED
    assert reopened.workspace_identity == first.workspace_identity
    assert reopened.checkpoint_path == first.checkpoint_path
    assert reopened.snapshot is not None
    assert reopened.snapshot.state.conversation_id == first.snapshot.state.conversation_id


def test_replaced_or_drifted_workspace_never_auto_resumes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    first = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000006",
    )
    assert first.store is not None and first.snapshot is not None
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "生成一份可验收的报告"},
    )
    state_with_fact = replace(first.snapshot.state, facts=(source,))
    state_with_goal = create_goal(
        state_with_fact,
        _goal(workspace_identity_digest=first.workspace_identity.identity_digest),
    )
    lease = first.store.try_acquire(first.snapshot.state.conversation_id)
    assert lease is not None
    try:
        first.store.compare_and_swap(first.snapshot, state_with_goal)
    finally:
        lease.release()

    old_workspace = tmp_path / "workspace-old"
    workspace.rename(old_workspace)
    workspace.mkdir()

    reopened = open_workspace_session(workspace, state_root=state_root)

    assert reopened.workspace_identity.identity_digest != first.workspace_identity.identity_digest
    assert reopened.disposition is StartupDisposition.NEEDS_AUTHORITY
    assert reopened.snapshot is not None and reopened.snapshot.state.goal is not None
    assert reopened.snapshot.state.goal.status.value == "goal_ready"


def test_one_matching_nonterminal_goal_is_selected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    first = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000007",
    )
    assert first.store is not None and first.snapshot is not None
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "生成一份可验收的报告"},
    )
    state_with_goal = create_goal(
        replace(first.snapshot.state, facts=(source,)),
        _goal(workspace_identity_digest=first.workspace_identity.identity_digest),
    )
    lease = first.store.try_acquire(first.snapshot.state.conversation_id)
    assert lease is not None
    try:
        first.store.compare_and_swap(first.snapshot, state_with_goal)
    finally:
        lease.release()

    reopened = open_workspace_session(workspace, state_root=state_root)

    assert reopened.disposition is StartupDisposition.RESUMED
    assert reopened.checkpoint_path == first.checkpoint_path
    assert len(reopened.candidates) == 1
    assert reopened.candidates[0].goal_id == "goal:1"
    assert reopened.candidates[0].user_outcome == "生成一份可验收的报告"


def test_multiple_candidates_require_exact_select_goal_action(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    first = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000008",
    )
    assert first.checkpoint_path is not None
    source = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "完成第二个目标"},
    )
    second_conversation = "00000000-0000-4000-8000-000000000009"
    second_state = create_goal(
        ConversationState(conversation_id=second_conversation, facts=(source,)),
        _goal(
            goal_id="goal:2",
            user_outcome="完成第二个目标",
            workspace_identity_digest=first.workspace_identity.identity_digest,
        ),
    )
    LocalCheckpointStore.initialize(
        first.checkpoint_path.parent / f"{second_conversation}.json",
        second_state,
    )

    ambiguous = open_workspace_session(workspace, state_root=state_root)

    assert ambiguous.disposition is StartupDisposition.SELECT_REQUIRED
    assert ambiguous.store is None and ambiguous.snapshot is None
    assert {item.goal_id for item in ambiguous.candidates} == {None, "goal:2"}
    with pytest.raises(ValueError, match="exact"):
        select_workspace_session(
            ambiguous,
            SelectGoal(
                conversation_id=second_conversation,
                action_seq=1,
                expected_revision=0,
                goal_id="goal:2",
            ),
        )

    selected = select_workspace_session(
        ambiguous,
        SelectGoal(
            conversation_id=second_conversation,
            action_seq=1,
            expected_revision=second_state.revision,
            goal_id="goal:2",
        ),
    )

    assert selected.disposition is StartupDisposition.RESUMED
    assert selected.snapshot is not None
    assert selected.snapshot.state.conversation_id == second_conversation
    assert selected.snapshot.state.goal is not None
    assert selected.snapshot.state.goal.goal_id == "goal:2"


def test_bounded_workspace_state_enumeration_rejects_unknown_entries_and_overflow(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    unknown_root = tmp_path / "unknown-root"
    opened = open_workspace_session(
        workspace,
        state_root=unknown_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000010",
    )
    assert opened.checkpoint_path is not None
    (opened.checkpoint_path.parent / "unexpected.txt").write_text("not a checkpoint")

    with pytest.raises(ValueError, match="unknown entry"):
        open_workspace_session(workspace, state_root=unknown_root)

    overflow_root = tmp_path / "overflow-root"
    first = open_workspace_session(
        workspace,
        state_root=overflow_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000011",
    )
    assert first.checkpoint_path is not None
    for suffix in (12, 13):
        conversation_id = f"00000000-0000-4000-8000-{suffix:012d}"
        LocalCheckpointStore.initialize(
            first.checkpoint_path.parent / f"{conversation_id}.json",
            ConversationState.new(conversation_id),
        )

    with pytest.raises(ValueError, match="candidate count"):
        open_workspace_session(workspace, state_root=overflow_root, max_candidates=2)


def test_concurrent_first_start_creates_one_valid_checkpoint_per_identity(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"

    def _open(conversation_id: str):
        def _delayed_id() -> str:
            time.sleep(0.1)
            return conversation_id

        return open_workspace_session(
            workspace,
            state_root=state_root,
            conversation_id_factory=_delayed_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                _open,
                (
                    "00000000-0000-4000-8000-000000000014",
                    "00000000-0000-4000-8000-000000000015",
                ),
            )
        )

    assert {item.disposition for item in results} == {
        StartupDisposition.CREATED,
        StartupDisposition.RESUMED,
    }
    assert results[0].checkpoint_path == results[1].checkpoint_path
    assert results[0].checkpoint_path is not None
    checkpoint_files = tuple(results[0].checkpoint_path.parent.glob("*.json"))
    assert len(checkpoint_files) == 1
    assert LocalCheckpointStore(checkpoint_files[0]).load().state.conversation_id


def test_startup_does_not_scan_workspace_or_secret_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("MUST_NOT_BE_READ=1")
    (workspace / "private").mkdir()
    state_root = tmp_path / "state-root"
    scanned: list[Path] = []
    real_scandir = sessions.os.scandir

    def _record_scandir(path):  # noqa: ANN001
        scanned.append(Path(path))
        return real_scandir(path)

    monkeypatch.setattr(sessions.os, "scandir", _record_scandir)

    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000016",
    )

    assert opened.disposition is StartupDisposition.CREATED
    assert scanned
    assert all(path.is_relative_to(state_root) for path in scanned)
    assert workspace not in scanned


def test_product_entry_uses_default_durable_session_without_manual_state_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    product_root = tmp_path / "product-state"
    captured = {}

    monkeypatch.setattr(
        sessions,
        "default_state_root",
        lambda _home=None: product_root,
    )

    def _capture_repl(_runtime, store, **_kwargs):  # noqa: ANN001
        captured["store"] = store
        return 0

    monkeypatch.setattr(entrypoint, "run_repl", _capture_repl)
    output: list[str] = []

    exit_code = entrypoint.main(
        ["--workspace", str(workspace), "--provider", "fake"],
        write_fn=output.append,
    )

    assert exit_code == 0
    assert isinstance(captured["store"], LocalCheckpointStore)
    assert tuple(product_root.glob("workspaces/*/*.json"))
    assert all("not durable" not in line.lower() for line in output)
