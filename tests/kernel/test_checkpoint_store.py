from __future__ import annotations

import multiprocessing
import os
import stat
from pathlib import Path

import pytest

from agent.runtime.checkpoint import (
    CheckpointConflictError,
    CheckpointSecurityError,
    LocalCheckpointStore,
)
from agent.runtime.contracts import ConversationState, SubmitMessage
from agent.runtime.state import accept_action


def _hold_lock(path: str, ready, release) -> None:
    store = LocalCheckpointStore(Path(path))
    lease = store.try_acquire("conversation-1")
    ready.put(lease is not None)
    release.get(timeout=10)
    if lease is not None:
        lease.release()


def test_local_store_create_load_cas_and_permissions(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "conversation.json"
    store = LocalCheckpointStore.initialize(
        state_path,
        ConversationState.new("conversation-1"),
    )
    snapshot = store.load()
    lease = store.try_acquire("conversation-1")
    assert lease is not None

    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="hello",
    )
    changed = accept_action(snapshot.state, action).state
    saved = store.compare_and_swap(snapshot, changed)

    assert saved.state == changed
    assert saved.token != snapshot.token
    assert stat.S_IMODE(state_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert state_path.stat().st_nlink == 1

    with pytest.raises(CheckpointConflictError):
        store.compare_and_swap(snapshot, changed)
    lease.release()


def test_fail_fast_cross_process_lock_has_one_owner(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "conversation.json"
    LocalCheckpointStore.initialize(state_path, ConversationState.new("conversation-1"))
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    release = ctx.Queue()
    process = ctx.Process(target=_hold_lock, args=(str(state_path), ready, release))
    process.start()
    try:
        assert ready.get(timeout=10) is True
        contender = LocalCheckpointStore(state_path)
        assert contender.try_acquire("conversation-1") is None
    finally:
        release.put(True)
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0


def test_store_capacity_admission_happens_before_effect_reserve(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "conversation.json"
    store = LocalCheckpointStore.initialize(
        state_path,
        ConversationState.new("conversation-1"),
        max_state_bytes=1_000,
    )
    snapshot = store.load()

    assert store.ensure_capacity(snapshot, reserve_bytes=100) is True
    assert store.ensure_capacity(snapshot, reserve_bytes=10_000) is False


def test_local_store_fails_closed_without_no_follow(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delattr(os, "O_NOFOLLOW")

    with pytest.raises(CheckpointSecurityError, match="no-follow"):
        LocalCheckpointStore(tmp_path / "state" / "conversation.json")
