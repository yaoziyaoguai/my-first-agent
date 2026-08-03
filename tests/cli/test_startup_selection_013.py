"""013 多任务启动选择必须可读，并映射 exact SelectGoal。"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import main as entrypoint
from agent.continuity.sessions import open_workspace_session
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.contracts import ConversationFact, ConversationState, FactKind
from agent.runtime.state import create_goal
from tests.continuity.test_contracts import _goal


def _two_goal_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000031",
    )
    assert opened.store is not None
    assert opened.snapshot is not None
    assert opened.checkpoint_path is not None

    first_fact = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "整理现有说明"},
    )
    first_state = create_goal(
        replace(opened.snapshot.state, facts=(first_fact,)),
        _goal(
            goal_id="goal:first",
            user_outcome="整理现有说明",
            workspace_identity_digest=opened.workspace_identity.identity_digest,
        ),
    )
    lease = opened.store.try_acquire(opened.snapshot.state.conversation_id)
    assert lease is not None
    try:
        opened.store.compare_and_swap(opened.snapshot, first_state)
    finally:
        lease.release()

    second_id = "00000000-0000-4000-8000-000000000032"
    second_fact = ConversationFact(
        fact_id="fact:user:1",
        kind=FactKind.USER_MESSAGE,
        content={"text": "写一份项目摘要"},
    )
    second_state = create_goal(
        ConversationState(conversation_id=second_id, facts=(second_fact,)),
        _goal(
            goal_id="goal:second",
            user_outcome="写一份项目摘要",
            workspace_identity_digest=opened.workspace_identity.identity_digest,
        ),
    )
    LocalCheckpointStore.initialize(
        opened.checkpoint_path.parent / f"{second_id}.json",
        second_state,
    )
    return workspace, state_root


def _checkpoint_digests(state_root: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in state_root.glob("workspaces/*/*.json")
    }


def test_numbered_startup_choice_selects_exact_goal_without_provider_or_tool(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, state_root = _two_goal_workspace(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        entrypoint.FakeProvider,
        "generate",
        lambda *_args, **_kwargs: calls.append("provider") or None,
    )
    output: list[str] = []
    inputs = iter(("2", "/exit"))

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
        ],
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    assert calls == []
    rendered = "\n".join(output)
    assert "1." in rendered and "2." in rendered
    assert "整理现有说明" in rendered and "写一份项目摘要" in rendered
    assert "Resuming task: 写一份项目摘要" in output
    assert "goal:second" not in rendered
    assert "00000000-0000-4000-8000-000000000032" not in rendered


def test_invalid_numbered_choice_has_zero_effect_and_does_not_guess(
    tmp_path: Path, monkeypatch
) -> None:
    workspace, state_root = _two_goal_workspace(tmp_path)
    before = _checkpoint_digests(state_root)
    calls: list[str] = []
    monkeypatch.setattr(
        entrypoint.FakeProvider,
        "generate",
        lambda *_args, **_kwargs: calls.append("provider") or None,
    )
    output: list[str] = []

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
        ],
        input_fn=lambda _: "9",
        write_fn=output.append,
    )

    assert exit_code == 2
    assert calls == []
    assert _checkpoint_digests(state_root) == before
    assert output[-1] == "That choice is not available; no task was selected."


def test_selection_and_resume_summaries_escape_terminal_controls(tmp_path: Path) -> None:
    workspace, state_root = _two_goal_workspace(tmp_path)
    checkpoint = next(
        path
        for path in state_root.glob("workspaces/*/*.json")
        if LocalCheckpointStore(path).load().state.goal.goal_id == "goal:second"
    )
    store = LocalCheckpointStore(checkpoint)
    snapshot = store.load()
    assert snapshot.state.goal is not None
    unsafe_state = replace(
        snapshot.state,
        goal=replace(
            snapshot.state.goal,
            user_outcome="summary\n\x1b[2J",
            progress_summary="progress\u202ereversed",
        ),
    )
    lease = store.try_acquire(snapshot.state.conversation_id)
    assert lease is not None
    try:
        store.compare_and_swap(snapshot, unsafe_state)
    finally:
        lease.release()
    output: list[str] = []
    inputs = iter(("2", "/exit"))

    exit_code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
        ],
        input_fn=lambda _prompt: next(inputs),
        write_fn=output.append,
    )

    assert exit_code == 0
    rendered = "\n".join(output)
    assert "\x1b" not in rendered and "\u202e" not in rendered
    assert "\\u000a" in rendered
    assert "\\u001b" in rendered
    assert "\\u202e" in rendered
