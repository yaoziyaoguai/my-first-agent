from __future__ import annotations

import os
import stat
from dataclasses import replace

import pytest

from agent.automation.contracts import AutomationSnapshotV1
from agent.automation.store import (
    AutomationRepositoryBusyError,
    AutomationRepositoryConflictError,
    AutomationRepositoryError,
    AutomationRepositoryUnknownCommitError,
)
from agent.automation_hosts.posix_storage import PosixAutomationRepository


def _snapshot(*, revision: int = 0, token: str = "snapshot-token-0000") -> AutomationSnapshotV1:
    return AutomationSnapshotV1(
        revision=revision,
        snapshot_token=token,
        records=(),
        tombstones=(),
    )


def test_repository_creates_owner_only_state_and_round_trips_cas(tmp_path) -> None:
    root = tmp_path / "automation-state"
    repository = PosixAutomationRepository(root, initial_snapshot=_snapshot())
    next_snapshot = replace(_snapshot(), revision=1, snapshot_token="snapshot-token-0001")

    with repository.try_acquire():
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=next_snapshot,
        )

    reopened = PosixAutomationRepository(root)
    assert reopened.load() == next_snapshot
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(repository.state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(repository.lock_path.stat().st_mode) == 0o600


def test_repository_lock_is_nonblocking_across_instances(tmp_path) -> None:
    root = tmp_path / "automation-state"
    first = PosixAutomationRepository(root, initial_snapshot=_snapshot())
    second = PosixAutomationRepository(root)

    with first.try_acquire(), pytest.raises(AutomationRepositoryBusyError):
        second.try_acquire()


def test_repository_rejects_stale_cas_and_requires_held_lease(tmp_path) -> None:
    repository = PosixAutomationRepository(
        tmp_path / "automation-state",
        initial_snapshot=_snapshot(),
    )
    next_snapshot = replace(_snapshot(), revision=1, snapshot_token="snapshot-token-0001")

    with pytest.raises(AutomationRepositoryError, match="short lease"):
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=next_snapshot,
        )
    with repository.try_acquire(), pytest.raises(AutomationRepositoryConflictError):
        repository.compare_and_swap(
            expected_snapshot_token="stale-token",
            next_snapshot=next_snapshot,
        )


def test_repository_rejects_root_state_and_lock_symlinks(tmp_path) -> None:
    real_root = tmp_path / "real"
    PosixAutomationRepository(real_root, initial_snapshot=_snapshot())
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(AutomationRepositoryError, match="root"):
        PosixAutomationRepository(linked_root)

    state_target = tmp_path / "state-target"
    state_target.write_bytes(b"{}")
    repository = PosixAutomationRepository(tmp_path / "state-link", initial_snapshot=_snapshot())
    repository.state_path.unlink()
    repository.state_path.symlink_to(state_target)
    with pytest.raises(AutomationRepositoryError, match="state"):
        repository.load()

    lock_target = tmp_path / "lock-target"
    lock_target.write_bytes(b"")
    repository = PosixAutomationRepository(tmp_path / "lock-link", initial_snapshot=_snapshot())
    repository.lock_path.unlink()
    repository.lock_path.symlink_to(lock_target)
    with pytest.raises(AutomationRepositoryError, match="lock"):
        repository.try_acquire()


def test_repository_rejects_replaced_root_and_lock_identity(tmp_path) -> None:
    root = tmp_path / "automation-state"
    repository = PosixAutomationRepository(root, initial_snapshot=_snapshot())

    original_root = tmp_path / "automation-state.original"
    root.rename(original_root)
    root.mkdir(mode=0o700)
    (root / "snapshot.json").write_bytes((original_root / "snapshot.json").read_bytes())
    (root / "store.lock").write_bytes(b"")
    os.chmod(root / "snapshot.json", 0o600)
    os.chmod(root / "store.lock", 0o600)
    with pytest.raises(AutomationRepositoryError, match="root.*identity"):
        repository.load()

    second_root = tmp_path / "second-state"
    second = PosixAutomationRepository(second_root, initial_snapshot=_snapshot())
    original_lock = second.lock_path.with_name("store.lock.original")
    second.lock_path.rename(original_lock)
    second.lock_path.write_bytes(b"")
    os.chmod(second.lock_path, 0o600)
    with pytest.raises(AutomationRepositoryError, match="lock.*identity"):
        second.try_acquire()


def test_pre_replace_failure_preserves_previous_snapshot(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = PosixAutomationRepository(
        tmp_path / "automation-state",
        initial_snapshot=_snapshot(),
    )
    next_snapshot = replace(_snapshot(), revision=1, snapshot_token="snapshot-token-0001")

    def fail_before_replace(_root_fd: int, _temporary_name: str) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(repository, "_replace_state", fail_before_replace)
    with repository.try_acquire(), pytest.raises(
        AutomationRepositoryError,
        match="commit failed",
    ):
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=next_snapshot,
        )

    assert repository.load() == _snapshot()


def test_repository_rejects_wrong_mode_malformed_and_oversized_state(tmp_path) -> None:
    repository = PosixAutomationRepository(
        tmp_path / "automation-state",
        initial_snapshot=_snapshot(),
    )
    os.chmod(repository.state_path, 0o644)
    with pytest.raises(AutomationRepositoryError, match="owner-only"):
        repository.load()

    os.chmod(repository.state_path, 0o600)
    repository.state_path.write_bytes(b"not-json")
    with pytest.raises(AutomationRepositoryError, match="snapshot"):
        repository.load()

    repository.state_path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(AutomationRepositoryError, match="snapshot"):
        repository.load()


def test_post_replace_failure_is_unknown_and_reload_reveals_commit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = PosixAutomationRepository(
        tmp_path / "automation-state",
        initial_snapshot=_snapshot(),
    )
    next_snapshot = replace(_snapshot(), revision=1, snapshot_token="snapshot-token-0001")

    def fail_after_replace() -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(repository, "_fsync_root", fail_after_replace)
    with repository.try_acquire(), pytest.raises(AutomationRepositoryUnknownCommitError):
        repository.compare_and_swap(
            expected_snapshot_token="snapshot-token-0000",
            next_snapshot=next_snapshot,
        )

    assert PosixAutomationRepository(repository.root).load() == next_snapshot


def test_owner_identity_mismatch_fails_closed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = PosixAutomationRepository(
        tmp_path / "automation-state",
        initial_snapshot=_snapshot(),
    )
    monkeypatch.setattr(repository, "_owner_uid", lambda: os.geteuid() + 1)

    with pytest.raises(AutomationRepositoryError, match="owner"):
        repository.load()
