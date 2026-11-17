from __future__ import annotations

import multiprocessing
import os
import stat
from pathlib import Path

import pytest

import agent.runtime.checkpoint as checkpoint_module
from agent.runtime.checkpoint import (
    CheckpointConflictError,
    CheckpointSecurityError,
    LocalCheckpointStore,
)
from agent.runtime.contracts import ConversationState, SubmitMessage
from agent.runtime.state import accept_action


def _temp_residues(directory: Path) -> list[str]:
    return [item.name for item in sorted(directory.iterdir()) if ".tmp-" in item.name]


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


def test_initialize_write_failure_leaves_no_partial_checkpoint(
    monkeypatch, tmp_path: Path
) -> None:
    """P2（2026-11-17）：initialize 中途写失败不得留下半写终名；重试可完整创建。"""

    state_path = tmp_path / "state" / "conversation.json"
    real_write_all = checkpoint_module._write_all

    def half_write_then_fail(fd: int, data: bytes) -> None:
        os.write(fd, data[: max(1, len(data) // 2)])
        raise OSError("simulated mid-write failure")

    monkeypatch.setattr(checkpoint_module, "_write_all", half_write_then_fail)
    with pytest.raises(OSError, match="simulated mid-write failure"):
        LocalCheckpointStore.initialize(state_path, ConversationState.new("c-init"))

    assert not state_path.exists()
    assert _temp_residues(state_path.parent) == []

    monkeypatch.setattr(checkpoint_module, "_write_all", real_write_all)
    store = LocalCheckpointStore.initialize(state_path, ConversationState.new("c-init"))
    assert store.load().state.conversation_id == "c-init"
    assert _temp_residues(state_path.parent) == []


def test_initialize_conflict_keeps_existing_checkpoint_and_cleans_temp(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state" / "conversation.json"
    first = LocalCheckpointStore.initialize(
        state_path, ConversationState.new("c-conflict")
    )
    before = state_path.read_bytes()

    with pytest.raises(CheckpointConflictError, match="already exists"):
        LocalCheckpointStore.initialize(
            state_path, ConversationState.new("c-conflict")
        )

    assert state_path.read_bytes() == before
    assert first.load().state.conversation_id == "c-conflict"
    assert state_path.stat().st_nlink == 1
    assert _temp_residues(state_path.parent) == []


def test_cas_sweeps_orphan_temp_residue_of_same_checkpoint(tmp_path: Path) -> None:
    """P1（2026-11-17）：SIGKILL 遗留的同名 tmp 由持锁 CAS 清扫；异常形态保守跳过。"""

    state_path = tmp_path / "state" / "conversation.json"
    store = LocalCheckpointStore.initialize(state_path, ConversationState.new("c-cas"))
    directory = state_path.parent
    orphan = directory / f".{state_path.name}.tmp-{'a' * 16}"
    orphan.write_bytes(b"partial")
    os.chmod(orphan, 0o600)
    malformed = directory / f".{state_path.name}.tmp-{'b' * 16}"
    malformed.write_bytes(b"partial")
    os.chmod(malformed, 0o666)

    snapshot = store.load()
    lease = store.try_acquire("c-cas")
    assert lease is not None
    try:
        action = SubmitMessage(
            conversation_id="c-cas",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        )
        changed = accept_action(snapshot.state, action).state
        store.compare_and_swap(snapshot, changed)
    finally:
        lease.release()

    assert not orphan.exists()
    # 异常形态（非 0600）残留不被清除，留给 fail-closed 读路径与人来处置。
    assert _temp_residues(directory) == [malformed.name]


def test_try_acquire_repairs_hardlink_pair_residue(tmp_path: Path) -> None:
    """P1 收尾（2026-11-17）：initialize 在 link 与 unlink 之间崩溃遗留
    终名 nlink==2 + tmp 硬链接对。读路径保持 fail-closed；持锁 try_acquire
    修复配对（unlink 与终名同 inode 的 tmp）恢复 nlink==1，之后 CAS 正常。"""

    state_path = tmp_path / "state" / "conversation.json"
    store = LocalCheckpointStore.initialize(state_path, ConversationState.new("c-pair"))
    directory = state_path.parent
    pair_tmp = directory / f".{state_path.name}.tmp-{'c' * 16}"
    os.link(state_path, pair_tmp)
    assert state_path.stat().st_nlink == 2

    # 只读路径在该残留下保持 fail-closed。
    with pytest.raises(CheckpointSecurityError, match="link count must be one"):
        store.load()

    lease = store.try_acquire("c-pair")
    assert lease is not None
    try:
        assert state_path.stat().st_nlink == 1
        assert not pair_tmp.exists()
        snapshot = store.load()
        action = SubmitMessage(
            conversation_id="c-pair",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        )
        changed = accept_action(snapshot.state, action).state
        store.compare_and_swap(snapshot, changed)
    finally:
        lease.release()
    assert store.load().state.revision == changed.revision


def test_initialize_tmp_vanished_before_link_maps_to_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1 收尾（2026-11-17）：并发持锁清扫者移除 initialize 在途 tmp 时，
    os.link ENOENT 映射为 CheckpointConflictError（tmp 消失 ⟹ 存在持锁者
    ⟹ 终名已存在），调用方按既有冲突分支回退，不产生笼统错误。"""

    state_path = tmp_path / "state" / "conversation.json"
    real_link = os.link

    def vanishing_link(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        if dst == state_path.name:
            os.unlink(src, dir_fd=src_dir_fd)
            raise FileNotFoundError()
        return real_link(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "link", vanishing_link)
    with pytest.raises(CheckpointConflictError, match="already exists"):
        LocalCheckpointStore.initialize(state_path, ConversationState.new("c-enoent"))
    monkeypatch.setattr(os, "link", real_link)

    assert not state_path.exists()
    assert _temp_residues(state_path.parent) == []
    # 同名重试在无清扫者干扰时正常落位。
    store = LocalCheckpointStore.initialize(state_path, ConversationState.new("c-enoent"))
    assert store.load().state.conversation_id == "c-enoent"
