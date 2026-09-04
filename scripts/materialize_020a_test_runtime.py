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
    _qualify_pinned_runtime_closure,
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
            # 先完成 ownership 转移再关闭旧 fd：即使关闭旧 fd 报错，
            # child 也已由 current_fd 持有，outer except 会关闭它。
            previous_fd = current_fd
            current_fd = child_fd
            os.close(previous_fd)
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


def _close_all_descriptors(fds: tuple[int, ...]) -> None:
    # best-effort 多-FD 关闭：逐个尝试，记录第一个 BaseException，全部尝试完
    # 成后只抛第一个——任何一个 close 失败都不得短路其余描述符的关闭。
    failure: BaseException | None = None
    for fd in fds:
        try:
            os.close(fd)
        except BaseException as error:
            if failure is None:
                failure = error
    if failure is not None:
        raise failure


def _close_pinned(directories: tuple[_PinnedDirectory, ...]) -> None:
    _close_all_descriptors(tuple(directory.fd for directory in directories))


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
    # create→first-pin 窗口：捕获 mkdir 后 entry 的身份，open 之后 fd 必须仍是
    # 同一 owned 目录；open 成功后的任何失败都只关闭 fd 并封闭失败，
    # 绝不做任何名称删除。
    entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    fd = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        if not _same_owned_directory(entry, os.fstat(fd)):
            raise ValueError("created destination entry was replaced before first pin")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _same_owned_directory(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(after.st_mode)
        and after.st_uid == os.getuid()
        and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
    )


def _require_unaliased_destination(
    destination_fd: int,
    pinned: tuple[_PinnedDirectory, ...],
) -> None:
    # protected root 即便在 captured stat 之前就被搬进 destination，也会在这里被
    # pinned-fd 的 inode 别名比对捕获；复制任何字节之前必须完成这组比对。
    identity = os.fstat(destination_fd)
    for directory in pinned:
        pinned_identity = os.fstat(directory.fd)
        if (identity.st_dev, identity.st_ino) == (
            pinned_identity.st_dev,
            pinned_identity.st_ino,
        ):
            raise ValueError("created destination aliases a pinned admission directory")


def _require_joined_destination_name(
    parent_fd: int,
    name: str,
    destination_fd: int,
) -> None:
    # 路径/内容权威 joining：destination.name 必须仍指向 pinned 的同一 owned 目录；
    # 丢失或被替换即为封闭 ValueError，绝不返回路径字段可指向替换品的 closure。
    destination_info = os.fstat(destination_fd)
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        raise ValueError("created destination name is not joined to pinned directory") from error
    if not _same_owned_directory(destination_info, current):
        raise ValueError("created destination name is not joined to pinned directory")


def materialize_test_runtime(
    source_root: Path | str,
    destination_root: Path | str,
    *,
    protected_roots: tuple[Path | str, ...],
) -> HermeticRuntimeClosureV1:
    """仅从显式已认证 source 复制 manifest + exact inventory，并重新资格认证。

    调用方契约：destination parent 必须是 verifier 私有目录，且整个操作期间
    destination parent、admitted source tree 与所有 protected root 都不存在并发
    same-UID mutation（protected descendant 被并发搬入属契约外问题）。实现不枚举
    protected-root 内容来推断历史 inode provenance。
    """

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
        cleanup_fds = tuple(directory.fd for directory in protected)
        if "destination_parent" in locals():
            cleanup_fds = (destination_parent.fd, *cleanup_fds)
        _close_all_descriptors((*cleanup_fds, source.fd))
        raise ValueError("destination or protected directory admission failed") from error
    except ValueError:
        cleanup_fds = tuple(directory.fd for directory in protected)
        if "destination_parent" in locals():
            cleanup_fds = (destination_parent.fd, *cleanup_fds)
        _close_all_descriptors((*cleanup_fds, source.fd))
        raise
    destination_fd: int | None = None
    try:
        destination = _destination_path(destination_parent, destination_path.name)
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
        _require_unaliased_destination(
            destination_fd, (source, destination_parent, *protected)
        )
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
        # 冻结裁定：资格校验前后都要求 destination.name 与 pinned inode 仍然 join；
        # 任何创建后失败只关闭描述符，partial destination 留给 caller 拥有的私有 temp root 回收。
        _require_joined_destination_name(
            destination_parent.fd, destination.name, destination_fd
        )
        try:
            copied = _qualify_pinned_runtime_closure(destination_fd, destination)
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("materialized runtime did not requalify") from error
        _require_joined_destination_name(
            destination_parent.fd, destination.name, destination_fd
        )
        return copied
    finally:
        cleanup_fds = (
            source.fd,
            destination_parent.fd,
            *(directory.fd for directory in protected),
        )
        if destination_fd is not None:
            cleanup_fds = (destination_fd, *cleanup_fds)
        _close_all_descriptors(cleanup_fds)


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
