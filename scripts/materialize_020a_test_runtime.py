"""显式复制已资格认证的 synthetic ``skill-runtime-v1`` 闭包。"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.hermetic_runtime import (
    _MANIFEST_NAME,
    _RUNTIME_FILE_MAX_BYTES,
    HermeticRuntimeClosureV1,
    _open_relative_parent,
    _read_relative_file,
    _stat_is_stable,
    qualify_hermetic_runtime_closure,
)


def _write_all(fd: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        offset += os.write(fd, raw[offset:])


def _copy_exact_file(
    source_fd: int,
    destination_fd: int,
    *,
    path: str,
    expected_size: int,
    expected_digest: str,
    mode: int,
) -> None:
    raw, source_info = _read_relative_file(source_fd, path, cap=_RUNTIME_FILE_MAX_BYTES)
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("qualified source drifted while materializing")
    parts = tuple(path.split("/"))
    parent_fd = _open_relative_parent(destination_fd, parts[:-1], create=True)
    try:
        target_fd = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=parent_fd,
        )
        try:
            os.fchmod(target_fd, mode)
            _write_all(target_fd, raw)
            os.fsync(target_fd)
            target_info = os.fstat(target_fd)
        finally:
            os.close(target_fd)
    finally:
        os.close(parent_fd)
    if (
        not stat.S_ISREG(target_info.st_mode)
        or stat.S_IMODE(target_info.st_mode) != mode
        or target_info.st_size != expected_size
        or target_info.st_nlink != 1
        or target_info.st_uid != os.getuid()
    ):
        raise ValueError("materialized runtime file identity is invalid")
    _, source_after = _read_relative_file(source_fd, path, cap=_RUNTIME_FILE_MAX_BYTES)
    if not _stat_is_stable(source_info, source_after):
        raise ValueError("qualified source drifted while materializing")


@dataclass(slots=True)
class _PinnedDirectory:
    path: Path
    fd: int
    identities: tuple[tuple[int, int], ...]


def _pin_absolute_directory(value: Path | str, *, label: str) -> _PinnedDirectory:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be an absolute canonical directory")
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("required no-follow directory support is unavailable")
    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    identities: list[tuple[int, int]] = []
    try:
        root_info = os.fstat(current_fd)
        identities.append((root_info.st_dev, root_info.st_ino))
        for part in path.parts[1:]:
            child_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
            info = os.fstat(current_fd)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"{label} is not a directory")
            identities.append((info.st_dev, info.st_ino))
        info = os.fstat(current_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError(f"{label} is not an owned regular directory")
        return _PinnedDirectory(path, current_fd, tuple(identities))
    except BaseException:
        os.close(current_fd)
        raise


def _close_pinned(directories: tuple[_PinnedDirectory, ...]) -> None:
    for directory in directories:
        os.close(directory.fd)


def _descends_from(
    child: tuple[tuple[int, int], ...], parent: tuple[tuple[int, int], ...]
) -> bool:
    return len(child) >= len(parent) and child[: len(parent)] == parent


def _path_descends_from(child: Path, parent: Path) -> bool:
    return (
        len(child.parts) >= len(parent.parts)
        and child.parts[: len(parent.parts)] == parent.parts
    )


def _destination_path(destination_parent: _PinnedDirectory, name: str) -> Path:
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise ValueError("destination root must name a single directory")
    return destination_parent.path / name


def _destination_overlaps_directory(
    destination_parent: _PinnedDirectory,
    destination: Path,
    directory: _PinnedDirectory,
) -> bool:
    return (
        _descends_from(destination_parent.identities, directory.identities)
        or _path_descends_from(destination, directory.path)
        or _path_descends_from(directory.path, destination)
    )


def _create_destination(parent_fd: int, name: str) -> int:
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    return os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )


def materialize_test_runtime(
    source_root: Path | str,
    destination_root: Path | str,
    *,
    protected_roots: tuple[Path | str, ...],
) -> HermeticRuntimeClosureV1:
    """仅从显式已认证 source 复制 manifest + exact inventory，并重新资格认证。"""

    if not isinstance(protected_roots, tuple) or not protected_roots:
        raise ValueError("protected roots must be explicit and non-empty")
    try:
        source = _pin_absolute_directory(source_root, label="source root")
    except OSError as error:
        raise ValueError("source root is not a qualified source") from error
    destination_path = Path(destination_root)
    if not destination_path.is_absolute():
        os.close(source.fd)
        raise ValueError("destination root must be an absolute canonical directory")
    protected: list[_PinnedDirectory] = []
    try:
        destination_parent = _pin_absolute_directory(
            destination_path.parent, label="destination parent"
        )
        for root in protected_roots:
            protected.append(_pin_absolute_directory(root, label="protected root"))
    except OSError as error:
        if "destination_parent" in locals():
            os.close(destination_parent.fd)
        _close_pinned(tuple(protected))
        os.close(source.fd)
        raise ValueError("destination or protected directory admission failed") from error
    except ValueError:
        if "destination_parent" in locals():
            os.close(destination_parent.fd)
        _close_pinned(tuple(protected))
        os.close(source.fd)
        raise
    destination = _destination_path(destination_parent, destination_path.name)
    destination_fd: int | None = None
    try:
        if (
            _path_descends_from(source.path, destination)
            or _path_descends_from(destination, source.path)
        ):
            raise ValueError("destination overlaps source root")
        for protected_root in protected:
            if _descends_from(source.identities, protected_root.identities) or _descends_from(
                protected_root.identities, source.identities
            ):
                raise ValueError("source overlaps protected root")
            if _destination_overlaps_directory(
                destination_parent, destination, protected_root
            ):
                raise ValueError("destination overlaps protected root")
        closure = qualify_hermetic_runtime_closure(source.path)
        if isinstance(closure, KnownNotExecuted):
            raise ValueError("source root is not a qualified source")
        destination_fd = _create_destination(destination_parent.fd, destination.name)
        manifest, _ = _read_relative_file(source.fd, _MANIFEST_NAME, cap=64 * 1024)
        if hashlib.sha256(manifest).hexdigest() != closure.manifest_digest:
            raise ValueError("qualified source manifest drifted while materializing")
        for item in closure.inventory:
            _copy_exact_file(
                source.fd,
                destination_fd,
                path=item.path,
                expected_size=item.size,
                expected_digest=item.sha256,
                mode=item.mode,
            )
        _copy_exact_file(
            source.fd,
            destination_fd,
            path=_MANIFEST_NAME,
            expected_size=len(manifest),
            expected_digest=closure.manifest_digest,
            mode=0o444,
        )
        directory_parts = {tuple()}
        for item in closure.inventory:
            parts = tuple(item.path.split("/"))
            directory_parts.update(parts[:index] for index in range(1, len(parts)))
        for parts in sorted(directory_parts, key=lambda item: (-len(item), item)):
            directory_fd = _open_relative_parent(destination_fd, parts)
            try:
                os.fchmod(directory_fd, 0o555)
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        os.fsync(destination_fd)
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        _close_pinned((source, destination_parent, *protected))
    copied = qualify_hermetic_runtime_closure(destination)
    if isinstance(copied, KnownNotExecuted):
        raise ValueError("materialized runtime did not requalify")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--destination-root", required=True, type=Path)
    parser.add_argument("--protected-root", action="append", required=True, type=Path)
    args = parser.parse_args()
    materialize_test_runtime(
        args.source_root,
        args.destination_root,
        protected_roots=tuple(args.protected_root),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
