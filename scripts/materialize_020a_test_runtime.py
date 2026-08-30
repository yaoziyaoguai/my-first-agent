"""显式复制已资格认证的 synthetic ``skill-runtime-v1`` 闭包。"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from pathlib import Path

from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.hermetic_runtime import (
    _MANIFEST_NAME,
    _RUNTIME_FILE_MAX_BYTES,
    HermeticRuntimeClosureV1,
    _open_relative_parent,
    _open_root,
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


def _create_destination(destination: Path) -> int:
    supplied_parent = destination.parent.absolute()
    if supplied_parent.is_symlink() or not supplied_parent.is_dir():
        raise ValueError("destination parent must be a canonical directory")
    parent = supplied_parent.resolve(strict=True)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.mkdir(destination.name, 0o700, dir_fd=parent_fd)
        destination_fd = os.open(
            destination.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        return destination_fd
    finally:
        os.close(parent_fd)


def materialize_test_runtime(
    source_root: Path | str,
    destination_root: Path | str,
) -> HermeticRuntimeClosureV1:
    """仅从显式已认证 source 复制 manifest + exact inventory，并重新资格认证。"""

    try:
        source = Path(source_root).absolute().resolve(strict=True)
    except OSError as error:
        raise ValueError("source root is not a qualified source") from error
    supplied_destination = Path(destination_root).absolute()
    destination = supplied_destination.parent.resolve(strict=True) / supplied_destination.name
    if (
        source == destination
        or source.is_relative_to(destination)
        or destination.is_relative_to(source)
    ):
        raise ValueError("destination overlaps source root")
    closure = qualify_hermetic_runtime_closure(source)
    if isinstance(closure, KnownNotExecuted):
        raise ValueError("source root is not a qualified source")
    source_fd = _open_root(source)
    destination_fd = _create_destination(destination)
    try:
        manifest, _ = _read_relative_file(source_fd, _MANIFEST_NAME, cap=64 * 1024)
        if hashlib.sha256(manifest).hexdigest() != closure.manifest_digest:
            raise ValueError("qualified source manifest drifted while materializing")
        for item in closure.inventory:
            _copy_exact_file(
                source_fd,
                destination_fd,
                path=item.path,
                expected_size=item.size,
                expected_digest=item.sha256,
                mode=item.mode,
            )
        _copy_exact_file(
            source_fd,
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
        os.close(destination_fd)
        os.close(source_fd)
    copied = qualify_hermetic_runtime_closure(destination)
    if isinstance(copied, KnownNotExecuted):
        raise ValueError("materialized runtime did not requalify")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--destination-root", required=True, type=Path)
    args = parser.parse_args()
    materialize_test_runtime(args.source_root, args.destination_root)
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
