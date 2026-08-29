"""Descriptor-relative source traversal and copy operations for 019 workspaces."""

from __future__ import annotations

import hashlib
import os
import stat
from fnmatch import fnmatchcase
from pathlib import Path

from agent.automation.workspace import (
    SourceBindingV1,
    SourceManifestEntryV1,
    SourceManifestV1,
    VirtualNodeKind,
    VirtualSourceNodeV1,
    WorkspaceBoundsV1,
)
from agent.automation_hosts._posix_fs import (
    DIRECTORY,
    NOFOLLOW,
    NONBLOCK,
    directory_identity,
    fsync_directory,
    owner_uid,
    storage_identity,
    write_new_owner_file,
)

_SENSITIVE_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx")


class PosixWorkspaceFiles:
    """Internal mixin containing only no-follow traversal and immutable copy logic."""

    def _scan_tree(
        self,
        root: Path,
        binding: SourceBindingV1,
        bounds: WorkspaceBoundsV1,
        *,
        ignored_root_components: set[str] | None = None,
        expected_root_storage: str | None = None,
    ) -> tuple[VirtualSourceNodeV1, ...]:
        ignored = ignored_root_components or set()
        try:
            root_fd = os.open(root, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        except OSError as error:
            raise ValueError("source root identity unavailable") from error
        nodes: list[VirtualSourceNodeV1] = []
        total_bytes = 0

        def visit(directory_fd: int, prefix: str) -> None:
            nonlocal total_bytes
            entries = sorted(os.scandir(directory_fd), key=lambda item: item.name)
            for entry in entries:
                if not prefix and entry.name in ignored:
                    continue
                relative = entry.name if not prefix else f"{prefix}/{entry.name}"
                if len(relative.encode("utf-8")) > bounds.max_path_bytes:
                    raise ValueError("relative path exceeds byte bound")
                if self._forbidden_component(entry.name, binding):
                    if entry.name in binding.excluded_components:
                        raise ValueError("source path enters an excluded component")
                    raise ValueError("source path matches a sensitive filename pattern")
                info = entry.stat(follow_symlinks=False)
                if info.st_uid != owner_uid():
                    raise ValueError("source node owner mismatch")
                if stat.S_ISDIR(info.st_mode):
                    child_fd = os.open(
                        entry.name,
                        os.O_RDONLY | DIRECTORY | NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                    try:
                        opened = os.fstat(child_fd)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise ValueError("source directory identity drift")
                        nodes.append(
                            VirtualSourceNodeV1(
                                relative,
                                VirtualNodeKind.DIRECTORY,
                                0,
                                None,
                            )
                        )
                        if len(nodes) > bounds.max_entries:
                            raise ValueError("source entry bound exceeded")
                        visit(child_fd, relative)
                    finally:
                        os.close(child_fd)
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("source contains an unsupported node kind")
                if info.st_size > bounds.max_file_bytes:
                    raise ValueError("source file byte bound exceeded")
                total_bytes += info.st_size
                if total_bytes > bounds.max_total_bytes:
                    raise ValueError("source total byte bound exceeded")
                digest = self._hash_file_at(
                    directory_fd,
                    entry.name,
                    info,
                    bounds.max_file_bytes,
                )
                nodes.append(
                    VirtualSourceNodeV1(
                        relative,
                        VirtualNodeKind.FILE,
                        info.st_size,
                        digest,
                    )
                )
                if len(nodes) > bounds.max_entries:
                    raise ValueError("source entry bound exceeded")

        try:
            root_info = os.fstat(root_fd)
            if root_info.st_uid != owner_uid() or not stat.S_ISDIR(root_info.st_mode):
                raise ValueError("source root identity drift")
            if expected_root_storage is not None:
                if storage_identity(root_info) != expected_root_storage:
                    raise ValueError("owned root identity drift")
            elif directory_identity(root_info) != binding.root_identity_digest:
                raise ValueError("source root identity drift")
            visit(root_fd, "")
        finally:
            os.close(root_fd)
        return tuple(nodes)

    @staticmethod
    def _forbidden_component(component: str, binding: SourceBindingV1) -> bool:
        folded = component.casefold()
        return component in binding.excluded_components or any(
            fnmatchcase(folded, pattern) for pattern in _SENSITIVE_PATTERNS
        )

    @staticmethod
    def _hash_file_at(
        directory_fd: int,
        name: str,
        expected: os.stat_result,
        maximum: int,
    ) -> str:
        fd = os.open(name, os.O_RDONLY | NOFOLLOW | NONBLOCK, dir_fd=directory_fd)
        try:
            current = os.fstat(fd)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_uid != owner_uid()
                or current.st_nlink != 1
                or (current.st_dev, current.st_ino, current.st_size)
                != (expected.st_dev, expected.st_ino, expected.st_size)
            ):
                raise ValueError("source file identity drift")
            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = os.read(fd, min(65_536, maximum + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise ValueError("source file byte bound exceeded")
                digest.update(chunk)
            if total != expected.st_size:
                raise ValueError("source file size drift")
            return digest.hexdigest()
        finally:
            os.close(fd)

    def _copy_source_manifest(
        self,
        source_root: Path,
        binding: SourceBindingV1,
        manifest: SourceManifestV1,
        destination: Path,
    ) -> None:
        root_fd = self._open_bound_directory(
            source_root,
            expected_identity=binding.root_identity_digest,
            source_identity=True,
        )
        try:
            self._copy_manifest_from_fd(root_fd, manifest, destination)
        finally:
            os.close(root_fd)

    def _copy_owned_manifest(
        self,
        source_root: Path,
        manifest: SourceManifestV1,
        destination: Path,
        *,
        expected_root_storage: str,
    ) -> None:
        root_fd = self._open_bound_directory(
            source_root,
            expected_identity=expected_root_storage,
            source_identity=False,
        )
        try:
            self._copy_manifest_from_fd(root_fd, manifest, destination)
        finally:
            os.close(root_fd)

    def _copy_manifest_from_fd(
        self,
        root_fd: int,
        manifest: SourceManifestV1,
        destination: Path,
    ) -> None:
        for entry in manifest.entries:
            target = destination / entry.relative_path
            if entry.kind is VirtualNodeKind.DIRECTORY:
                target.mkdir(mode=0o700)
                continue
            payload = self._read_relative_file_at(root_fd, entry)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_new_owner_file(target, payload)
        fsync_directory(destination)

    @staticmethod
    def _open_bound_directory(
        path: Path,
        *,
        expected_identity: str,
        source_identity: bool,
    ) -> int:
        try:
            fd = os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW)
        except OSError as error:
            raise ValueError("bound root identity unavailable") from error
        info = os.fstat(fd)
        actual = directory_identity(info) if source_identity else storage_identity(info)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != owner_uid()
            or actual != expected_identity
        ):
            os.close(fd)
            raise ValueError("bound root identity drift")
        return fd

    @staticmethod
    def _read_relative_file_at(root_fd: int, entry: SourceManifestEntryV1) -> bytes:
        components = entry.relative_path.split("/")
        directory_fd = os.dup(root_fd)
        try:
            for component in components[:-1]:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | DIRECTORY | NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(
                components[-1],
                os.O_RDONLY | NOFOLLOW | NONBLOCK,
                dir_fd=directory_fd,
            )
            try:
                info = os.fstat(file_fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != owner_uid()
                    or info.st_nlink != 1
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or info.st_size != entry.size_bytes
                ):
                    raise ValueError("source file identity drift")
                payload = bytearray()
                while len(payload) <= entry.size_bytes:
                    chunk = os.read(
                        file_fd,
                        min(65_536, entry.size_bytes + 1 - len(payload)),
                    )
                    if not chunk:
                        break
                    payload.extend(chunk)
                value = bytes(payload)
                if (
                    len(value) != entry.size_bytes
                    or hashlib.sha256(value).hexdigest() != entry.content_digest
                ):
                    raise ValueError("source manifest drift")
                return value
            finally:
                os.close(file_fd)
        except OSError as error:
            raise ValueError("source path identity drift") from error
        finally:
            os.close(directory_fd)
