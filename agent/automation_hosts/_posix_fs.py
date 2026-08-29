"""Small no-follow primitives shared by the optional POSIX host adapters."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from agent.runtime.contracts import canonical_json_digest

NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)
NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class PosixWorkspaceStorageError(ValueError):
    """POSIX host storage cannot prove a safe result."""


class PosixWorkspaceCommitUnknownError(PosixWorkspaceStorageError):
    """A metadata replace happened but directory durability is not known."""


def absolute_unresolved(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def owner_uid() -> int:
    return os.geteuid()


def reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise PosixWorkspaceStorageError("path contains a symlink component")


def directory_identity(info: os.stat_result) -> str:
    return canonical_json_digest(
        {
            "device": info.st_dev,
            "inode": info.st_ino,
            "owner": info.st_uid,
            "mode": stat.S_IMODE(info.st_mode),
            "kind": "directory",
        }
    )


def storage_identity(info: os.stat_result) -> str:
    kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
    return canonical_json_digest(
        {
            "device": info.st_dev,
            "inode": info.st_ino,
            "owner": info.st_uid,
            "mode": stat.S_IMODE(info.st_mode),
            "kind": kind,
        }
    )


def source_root_identity(path: Path) -> str:
    """Return the exact no-follow root identity bound by ``SourceBindingV1``."""

    root = absolute_unresolved(path)
    reject_symlink_components(root)
    try:
        info = root.lstat()
    except OSError as error:
        raise PosixWorkspaceStorageError("source root is unavailable") from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid():
        raise PosixWorkspaceStorageError("source root identity is not owner directory")
    return directory_identity(info)


def ensure_owner_directory(path: Path) -> None:
    path = absolute_unresolved(path)
    reject_symlink_components(path)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise PosixWorkspaceStorageError("owner root cannot be created") from error
    try:
        info = path.lstat()
    except OSError as error:
        raise PosixWorkspaceStorageError("owner root is unavailable") from error
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner_uid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PosixWorkspaceStorageError("owner root must be owner-only directory")


def validate_owner_file(info: os.stat_result, label: str) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != owner_uid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise PosixWorkspaceStorageError(f"{label} must be owner-only regular file")


def read_owner_file(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | NOFOLLOW | NONBLOCK)
    except OSError as error:
        raise PosixWorkspaceStorageError(f"{label} is unavailable") from error
    try:
        validate_owner_file(os.fstat(fd), label)
        return _read_bounded(fd, maximum=maximum, label=label)
    finally:
        os.close(fd)


def read_owner_file_at(
    directory_fd: int,
    name: str,
    *,
    maximum: int,
    label: str,
) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | NOFOLLOW | NONBLOCK, dir_fd=directory_fd)
    except OSError as error:
        raise PosixWorkspaceStorageError(f"{label} is unavailable") from error
    try:
        validate_owner_file(os.fstat(fd), label)
        return _read_bounded(fd, maximum=maximum, label=label)
    finally:
        os.close(fd)


def read_bound_source_file(path: Path, *, maximum: int, label: str) -> bytes:
    """Read a bound checkout/workspace file without imposing a 0600 checkout mode."""

    try:
        fd = os.open(path, os.O_RDONLY | NOFOLLOW | NONBLOCK)
    except OSError as error:
        raise PosixWorkspaceStorageError(f"{label} is unavailable") from error
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise PosixWorkspaceStorageError(
                f"{label} must be owner-controlled regular file"
            )
        return _read_bounded(fd, maximum=maximum, label=label)
    finally:
        os.close(fd)


def read_bound_source_file_at(
    directory_fd: int,
    name: str,
    *,
    maximum: int,
    label: str,
) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | NOFOLLOW | NONBLOCK, dir_fd=directory_fd)
    except OSError as error:
        raise PosixWorkspaceStorageError(f"{label} is unavailable") from error
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise PosixWorkspaceStorageError(
                f"{label} must be owner-controlled regular file"
            )
        return _read_bounded(fd, maximum=maximum, label=label)
    finally:
        os.close(fd)


def _read_bounded(fd: int, *, maximum: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65_536, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise PosixWorkspaceStorageError(f"{label} exceeds byte bound")
    return b"".join(chunks)


def write_new_owner_file(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new_owner_file_at(directory_fd: int, name: str, payload: bytes) -> None:
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
