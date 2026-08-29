"""Crash-safe owner-only AutomationStore adapter for POSIX hosts."""

from __future__ import annotations

import fcntl
import os
import stat
from contextlib import AbstractContextManager, suppress
from pathlib import Path

from agent.automation.contracts import AutomationSnapshotV1
from agent.automation.store import (
    MAX_AUTOMATION_STORE_BYTES,
    AutomationRepositoryBusyError,
    AutomationRepositoryConflictError,
    AutomationRepositoryError,
    AutomationRepositoryLease,
    AutomationRepositoryUnknownCommitError,
    decode_snapshot,
    encode_snapshot,
)
from agent.automation_hosts._posix_fs import (
    DIRECTORY,
    NOFOLLOW,
    NONBLOCK,
    PosixWorkspaceStorageError,
    absolute_unresolved,
    ensure_owner_directory,
    owner_uid,
    read_owner_file_at,
    write_new_owner_file_at,
)


class _PosixLease(AbstractContextManager["_PosixLease"]):
    def __init__(self, repository: PosixAutomationRepository, fd: int) -> None:
        self._repository = repository
        self._fd = fd
        self._released = False

    def __enter__(self) -> _PosixLease:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        if self._released:
            return
        self._released = True
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._repository._lease_fd = None


class PosixAutomationRepository:
    """One canonical snapshot under a short nonblocking POSIX lease."""

    def __init__(
        self,
        root: Path,
        *,
        initial_snapshot: AutomationSnapshotV1 | None = None,
    ) -> None:
        if NOFOLLOW == 0 or DIRECTORY == 0:
            raise AutomationRepositoryError("POSIX no-follow storage is unavailable")
        self.root = absolute_unresolved(root)
        self.state_path = self.root / "snapshot.json"
        self.lock_path = self.root / "store.lock"
        self._lease_fd: int | None = None
        self._root_device_inode: tuple[int, int] | None = None
        self._lock_device_inode: tuple[int, int] | None = None
        try:
            ensure_owner_directory(self.root)
            root_info = self.root.lstat()
            self._root_device_inode = (root_info.st_dev, root_info.st_ino)
            self._ensure_lock_file()
            root_fd = self._open_root_fd()
            try:
                try:
                    state_info = os.stat(
                        self.state_path.name,
                        dir_fd=root_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    state_info = None
                if state_info is None:
                    if initial_snapshot is None:
                        raise AutomationRepositoryError("automation snapshot is missing")
                    write_new_owner_file_at(
                        root_fd,
                        self.state_path.name,
                        encode_snapshot(initial_snapshot),
                    )
                    os.fsync(root_fd)
                elif initial_snapshot is not None:
                    raise AutomationRepositoryError(
                        "initial snapshot cannot replace existing state"
                    )
            finally:
                os.close(root_fd)
            self.load()
        except PosixWorkspaceStorageError as error:
            raise AutomationRepositoryError(
                f"automation repository root is invalid: {error}"
            ) from error

    def _owner_uid(self) -> int:
        return owner_uid()

    def _validate_root(self) -> None:
        fd = self._open_root_fd()
        os.close(fd)

    def _open_root_fd(self) -> int:
        try:
            fd = os.open(self.root, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        except OSError as error:
            raise AutomationRepositoryError(
                "automation repository root is unavailable"
            ) from error
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != self._owner_uid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            os.close(fd)
            raise AutomationRepositoryError("automation repository root must be owner-only")
        if self._root_device_inode is not None and (
            info.st_dev,
            info.st_ino,
        ) != self._root_device_inode:
            os.close(fd)
            raise AutomationRepositoryError("automation repository root identity drift")
        return fd

    def _ensure_lock_file(self) -> None:
        root_fd = self._open_root_fd()
        try:
            fd = os.open(
                self.lock_path.name,
                os.O_RDWR | os.O_CREAT | NOFOLLOW | NONBLOCK,
                0o600,
                dir_fd=root_fd,
            )
        except OSError as error:
            raise AutomationRepositoryError(
                "automation repository lock is unavailable"
            ) from error
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self._owner_uid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise AutomationRepositoryError(
                    "automation repository lock must be owner-only regular file"
                )
            self._lock_device_inode = (info.st_dev, info.st_ino)
        finally:
            if "fd" in locals():
                os.close(fd)
            os.close(root_fd)

    def load(self) -> AutomationSnapshotV1:
        root_fd = self._open_root_fd()
        try:
            payload = read_owner_file_at(
                root_fd,
                self.state_path.name,
                maximum=MAX_AUTOMATION_STORE_BYTES,
                label="automation repository state",
            )
            return decode_snapshot(payload)
        except (PosixWorkspaceStorageError, ValueError) as error:
            raise AutomationRepositoryError(
                f"automation snapshot is invalid: {error}"
            ) from error
        finally:
            os.close(root_fd)

    def try_acquire(self) -> AutomationRepositoryLease:
        if self._lease_fd is not None:
            raise AutomationRepositoryBusyError("automation repository lease is busy")
        root_fd = self._open_root_fd()
        try:
            fd = os.open(
                self.lock_path.name,
                os.O_RDWR | NOFOLLOW | NONBLOCK,
                dir_fd=root_fd,
            )
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self._owner_uid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise AutomationRepositoryError(
                    "automation repository lock must be owner-only regular file"
                )
            if self._lock_device_inode is None or (
                info.st_dev,
                info.st_ino,
            ) != self._lock_device_inode:
                raise AutomationRepositoryError("automation repository lock identity drift")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            if "fd" in locals():
                os.close(fd)
            raise AutomationRepositoryBusyError(
                "automation repository lease is busy"
            ) from error
        except OSError as error:
            if "fd" in locals():
                os.close(fd)
            raise AutomationRepositoryError(
                "automation repository lock is unavailable"
            ) from error
        except Exception:
            if "fd" in locals():
                os.close(fd)
            raise
        finally:
            os.close(root_fd)
        self._lease_fd = fd
        return _PosixLease(self, fd)

    def compare_and_swap(
        self,
        *,
        expected_snapshot_token: str,
        next_snapshot: AutomationSnapshotV1,
    ) -> None:
        if self._lease_fd is None:
            raise AutomationRepositoryError("compare_and_swap requires the short lease")
        current = self.load()
        if expected_snapshot_token != current.snapshot_token:
            raise AutomationRepositoryConflictError("automation snapshot token conflict")
        if next_snapshot.revision != current.revision + 1:
            raise AutomationRepositoryConflictError("automation snapshot revision conflict")
        if next_snapshot.snapshot_token == current.snapshot_token:
            raise AutomationRepositoryConflictError("next snapshot token must change")
        payload = encode_snapshot(next_snapshot)
        temporary_name = f".snapshot.{os.getpid()}.{next_snapshot.snapshot_token}.tmp"
        replaced = False
        root_fd = self._open_root_fd()
        try:
            write_new_owner_file_at(root_fd, temporary_name, payload)
            self._replace_state(root_fd, temporary_name)
            replaced = True
            self._fsync_root()
        except OSError as error:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=root_fd)
            if replaced:
                raise AutomationRepositoryUnknownCommitError(
                    "automation snapshot commit outcome is unknown"
                ) from error
            raise AutomationRepositoryError("automation snapshot commit failed") from error
        finally:
            os.close(root_fd)

    def _fsync_root(self) -> None:
        root_fd = self._open_root_fd()
        try:
            os.fsync(root_fd)
        finally:
            os.close(root_fd)

    def _replace_state(self, root_fd: int, temporary_name: str) -> None:
        os.replace(
            temporary_name,
            self.state_path.name,
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
        )
