"""Descriptor-relative workspace boundary for the four Kernel file tools."""

from __future__ import annotations

import hashlib
import heapq
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath


class WorkspaceSecurityError(RuntimeError):
    pass


_SENSITIVE_EXACT = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


class WorkspaceBoundary:
    def __init__(
        self,
        root: Path,
        *,
        protected_paths: tuple[Path, ...] = (),
        private_roots: tuple[str, ...] = (),
    ) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise WorkspaceSecurityError("required POSIX no-follow flags are unavailable")
        self.root = Path(root).absolute()
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise WorkspaceSecurityError("workspace root must be a real directory")
        self._root_identity = (info.st_dev, info.st_ino)
        self._protected_identities: set[tuple[int, int]] = set()
        self._private_roots = frozenset(private_roots)
        self._private_roots_folded = frozenset(name.casefold() for name in private_roots)
        for path in protected_paths:
            protected = Path(path).absolute()
            if protected == self.root or protected.is_relative_to(self.root):
                raise WorkspaceSecurityError("protected state must remain outside the workspace")
            try:
                protected_info = protected.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(protected_info.st_mode):
                raise WorkspaceSecurityError("protected state path must not be a symlink")
            self._protected_identities.add((protected_info.st_dev, protected_info.st_ino))

    def validate_relative(self, raw_path: str, *, allow_root: bool = False) -> tuple[str, ...]:
        if not isinstance(raw_path, str) or any(
            not character.isprintable() for character in raw_path
        ):
            raise WorkspaceSecurityError("path must be a plain relative string")
        path = PurePosixPath(raw_path)
        if path.is_absolute():
            raise WorkspaceSecurityError("absolute paths are outside the workspace grant")
        parts = tuple(part for part in path.parts if part not in {""})
        if parts in {(), (".",)}:
            if allow_root:
                return ()
            raise WorkspaceSecurityError("path must name a workspace entry")
        if any(part in {".", ".."} for part in parts):
            raise WorkspaceSecurityError("path traversal is not allowed")
        if self._is_sensitive(parts):
            raise WorkspaceSecurityError("sensitive path class is denied")
        return parts

    def inspect_readable(self, raw_path: str) -> None:
        parts = self.validate_relative(raw_path)
        with self._open_parent(parts) as (parent_fd, name):
            fd = self._open_regular(parent_fd, name)
            os.close(fd)

    def inspect_directory(self, raw_path: str) -> None:
        parts = self.validate_relative(raw_path, allow_root=True)
        fd = self._open_directory_parts(parts)
        os.close(fd)

    def read_text(self, raw_path: str, *, max_bytes: int) -> str:
        parts = self.validate_relative(raw_path)
        with self._open_parent(parts) as (parent_fd, name):
            fd = self._open_regular(parent_fd, name)
            try:
                data = self._read_bounded(fd, max_bytes)
            finally:
                os.close(fd)
        return data.decode("utf-8", errors="replace")

    def list_entries(
        self,
        raw_path: str,
        *,
        max_entries: int,
    ) -> tuple[str, ...]:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        parts = self.validate_relative(raw_path, allow_root=True)
        directory_fd = self._open_directory_parts(parts)
        try:
            return tuple(
                heapq.nsmallest(
                    max_entries,
                    self._iter_visible_entries(parts, directory_fd),
                )
            )
        finally:
            os.close(directory_fd)

    def _iter_visible_entries(
        self,
        parts: tuple[str, ...],
        directory_fd: int,
    ) -> Iterator[str]:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                name = entry.name
                child_parts = (*parts, name)
                if self._is_sensitive(child_parts):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISLNK(info.st_mode):
                    continue
                if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                    continue
                if (info.st_dev, info.st_ino) in self._protected_identities:
                    continue
                yield name + ("/" if stat.S_ISDIR(info.st_mode) else "")

    def inspect_mutation(self, raw_path: str, *, max_bytes: int) -> tuple[dict, bytes | None]:
        parts = self.validate_relative(raw_path)
        target_digest = _sha256("/".join(parts).encode())
        with self._open_parent(parts) as (parent_fd, name):
            try:
                fd = self._open_regular(parent_fd, name, mutation=True)
            except FileNotFoundError:
                return (
                    {
                        "target_digest": target_digest,
                        "precondition_digest": _sha256(b"missing"),
                    },
                    None,
                )
            try:
                info = os.fstat(fd)
                data = self._read_bounded(fd, max_bytes)
            finally:
                os.close(fd)
        precondition = {
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "sha256": _sha256(data),
        }
        encoded = repr(sorted(precondition.items())).encode()
        return (
            {
                "target_digest": target_digest,
                "precondition_digest": _sha256(encoded),
            },
            data,
        )

    def atomic_replace(self, raw_path: str, data: bytes) -> None:
        parts = self.validate_relative(raw_path)
        with self._open_parent(parts) as (parent_fd, name):
            try:
                existing_fd = self._open_regular(parent_fd, name, mutation=True)
            except FileNotFoundError:
                existing_fd = None
            if existing_fd is not None:
                os.close(existing_fd)
            temp_name = f".{name}.tmp-{os.getpid()}-{hashlib.sha256(data).hexdigest()[:12]}"
            temp_fd: int | None = None
            try:
                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _o_nofollow(),
                    0o600,
                    dir_fd=parent_fd,
                )
                os.fchmod(temp_fd, 0o600)
                _write_all(temp_fd, data)
                os.fsync(temp_fd)
                os.close(temp_fd)
                temp_fd = None
                os.replace(temp_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.fsync(parent_fd)
            except Exception:
                if temp_fd is not None:
                    os.close(temp_fd)
                with suppress(FileNotFoundError):
                    os.unlink(temp_name, dir_fd=parent_fd)
                raise

    @contextmanager
    def _open_parent(self, parts: tuple[str, ...]) -> Iterator[tuple[int, str]]:
        parent_fd = self._open_directory_parts(parts[:-1])
        try:
            yield parent_fd, parts[-1]
        finally:
            os.close(parent_fd)

    def _open_directory_parts(self, parts: tuple[str, ...]) -> int:
        fd = os.open(
            self.root,
            os.O_RDONLY | os.O_DIRECTORY | _o_nofollow(),
        )
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != self._root_identity:
            os.close(fd)
            raise WorkspaceSecurityError("workspace root identity changed")
        for part in parts:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | _o_nofollow(),
                    dir_fd=fd,
                )
            except OSError as error:
                os.close(fd)
                raise WorkspaceSecurityError("directory traversal was denied") from error
            os.close(fd)
            fd = child
        return fd

    def _open_regular(self, parent_fd: int, name: str, *, mutation: bool = False) -> int:
        try:
            fd = os.open(name, os.O_RDONLY | _o_nofollow(), dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise WorkspaceSecurityError("file traversal was denied") from error
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise WorkspaceSecurityError("only regular files are allowed")
        if (info.st_dev, info.st_ino) in self._protected_identities:
            os.close(fd)
            raise WorkspaceSecurityError("protected file identity is denied")
        if info.st_nlink != 1:
            os.close(fd)
            raise WorkspaceSecurityError("multi-link file is denied")
        return fd

    @staticmethod
    def _read_bounded(fd: int, max_bytes: int) -> bytes:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(65_536, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise WorkspaceSecurityError("file exceeds the configured read bound")
        return b"".join(chunks)

    def _is_sensitive(self, parts: tuple[str, ...]) -> bool:
        for index, part in enumerate(parts):
            folded = part.casefold()
            if folded == ".git" or folded in _SENSITIVE_EXACT:
                return True
            if folded.startswith(".env.") or folded.endswith(_SENSITIVE_SUFFIXES):
                return True
            if folded.startswith("config.local."):
                return True
            if folded.startswith("agent_log.archived-") or folded.startswith(".tui_audit_log"):
                return True
            if index == 0 and folded in self._private_roots_folded:
                return True
        return False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _o_nofollow() -> int:
    return os.O_NOFOLLOW


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("file write made no progress")
        view = view[written:]
