"""Descriptor-relative workspace boundary for the four Kernel file tools."""

from __future__ import annotations

import hashlib
import heapq
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class WorkspaceSecurityError(RuntimeError):
    pass


_SENSITIVE_EXACT = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_SENSITIVE_COMPONENTS = frozenset(
    {
        ".aws",
        ".claude",
        ".codex",
        ".config",
        ".docker",
        ".git",
        ".gnupg",
        ".kube",
        ".opencode",
        ".ssh",
        ".ua",
        "graphify-out",
        "node_modules",
    }
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


@dataclass(frozen=True, slots=True)
class TraversalLimits:
    max_scan_entries: int = 5_000
    max_opened_files: int = 200
    max_total_bytes: int = 2_000_000
    max_single_file_bytes: int = 200_000
    max_depth: int = 12
    max_matches: int = 16
    max_snippet_chars: int = 600
    deadline_seconds: float = 5.0

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_scan_entries,
            self.max_opened_files,
            self.max_total_bytes,
            self.max_single_file_bytes,
            self.max_depth,
            self.max_matches,
            self.max_snippet_chars,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in integer_limits
        ) or self.deadline_seconds <= 0:
            raise ValueError("workspace traversal limits must be positive")


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    path: str
    content: str
    encoding: str
    content_digest: str
    snapshot_digest: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    path: str
    entries: tuple[str, ...]
    truncated: bool
    truncation_reason: str | None
    snapshot_digest: str


@dataclass(frozen=True, slots=True)
class PathMatch:
    path: str
    kind: str
    snapshot_digest: str
    observed_at: str


@dataclass(frozen=True, slots=True)
class TextMatch:
    path: str
    line: int
    snippet: str
    encoding: str
    content_digest: str
    snapshot_digest: str
    observed_at: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class WorkspaceSearchResult:
    matches: tuple[PathMatch | TextMatch, ...]
    truncated: bool
    truncation_reason: str | None
    scanned_entries: int
    opened_files: int
    total_bytes: int
    snapshot_digest: str


@dataclass(frozen=True, slots=True)
class FileChunk:
    path: str
    start_line: int
    end_line: int
    content: str
    encoding: str
    truncated: bool
    content_digest: str
    original_content_digest: str
    snapshot_digest: str
    observed_at: str


@dataclass(slots=True)
class _TraversalBudget:
    limits: TraversalLimits
    deadline: float
    scanned_entries: int = 0
    opened_files: int = 0
    total_bytes: int = 0
    reason: str | None = None

    def stop(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason


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

    def resolve_directory(self, raw_path: str) -> tuple[Path, str]:
        """返回经统一 boundary 验证的目录路径与 descriptor identity。"""

        parts = self.validate_relative(raw_path, allow_root=True)
        fd = self._open_directory_parts(parts)
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        return self.root.joinpath(*parts), f"{info.st_dev}:{info.st_ino}"

    def read_text(self, raw_path: str, *, max_bytes: int) -> str:
        return self.read_document(raw_path, max_bytes=max_bytes).content

    def read_document(self, raw_path: str, *, max_bytes: int) -> WorkspaceDocument:
        parts = self.validate_relative(raw_path)
        with self._open_parent(parts) as (parent_fd, name):
            fd = self._open_regular(parent_fd, name)
            try:
                info = os.fstat(fd)
                data = self._read_bounded(fd, max_bytes)
            finally:
                os.close(fd)
        content, encoding = _decode_text(data)
        path = "/".join(parts)
        digest = _sha256(data)
        return WorkspaceDocument(
            path=path,
            content=content,
            encoding=encoding,
            content_digest=digest,
            snapshot_digest=_file_snapshot_digest(path, info, digest),
            observed_at=f"mtime_ns:{info.st_mtime_ns}",
        )

    def list_entries(
        self,
        raw_path: str,
        *,
        max_entries: int,
    ) -> tuple[str, ...]:
        return self.list_entries_bounded(
            raw_path,
            max_entries=max_entries,
            max_scan_entries=max(max_entries, 5_000),
        ).entries

    def list_entries_bounded(
        self,
        raw_path: str,
        *,
        max_entries: int,
        max_scan_entries: int,
        max_output_chars: int = 50_000,
    ) -> DirectoryListing:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_scan_entries < 1 or max_output_chars < 1:
            raise ValueError("listing limits must be positive")
        parts = self.validate_relative(raw_path, allow_root=True)
        directory_fd = self._open_directory_parts(parts)
        try:
            visible: list[str] = []
            scanned = 0
            scan_truncated = False
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    if scanned >= max_scan_entries:
                        scan_truncated = True
                        break
                    scanned += 1
                    projected = self._visible_entry(parts, entry)
                    if projected is not None:
                        visible.append(projected[0])
        finally:
            os.close(directory_fd)
        selected = heapq.nsmallest(max_entries, visible)
        reason = "scan_entries" if scan_truncated else None
        if len(visible) > len(selected) and reason is None:
            reason = "matches"
        bounded: list[str] = []
        output_chars = 0
        for entry in selected:
            added = len(entry) + (1 if bounded else 0)
            if output_chars + added > max_output_chars:
                reason = reason or "output_chars"
                break
            bounded.append(entry)
            output_chars += added
        path = "/".join(parts) or "."
        values = {
            "path": path,
            "entries": bounded,
            "truncated": reason is not None,
            "truncation_reason": reason,
        }
        return DirectoryListing(
            path=path,
            entries=tuple(bounded),
            truncated=reason is not None,
            truncation_reason=reason,
            snapshot_digest=_digest_values(values),
        )

    def search_paths(
        self,
        query: str,
        *,
        root: str,
        max_results: int,
        limits: TraversalLimits,
    ) -> WorkspaceSearchResult:
        normalized_query = _validate_search_query(query)
        if not 1 <= max_results <= limits.max_matches:
            raise ValueError("max_results exceeds the workspace search cap")
        root_parts = self.validate_relative(root, allow_root=True)
        budget = _TraversalBudget(limits, time.monotonic() + limits.deadline_seconds)
        matches: list[PathMatch] = []

        def visit(parts: tuple[str, ...], directory_fd: int, depth: int) -> None:
            if budget.reason is not None:
                return
            entries = self._scan_directory(parts, directory_fd, budget)
            for name, info, kind in entries:
                if budget.reason not in {None, "scan_entries"}:
                    return
                locator_parts = (*parts, name)
                locator = "/".join(locator_parts)
                if normalized_query in locator.casefold():
                    matches.append(
                        PathMatch(
                            path=locator,
                            kind=kind,
                            snapshot_digest=_entry_snapshot_digest(locator, info),
                            observed_at=f"mtime_ns:{info.st_mtime_ns}",
                        )
                    )
                    if len(matches) >= max_results:
                        budget.stop("matches")
                        return
                if kind == "directory":
                    if budget.reason is not None:
                        continue
                    if depth >= limits.max_depth:
                        budget.stop("depth")
                        return
                    child_fd = self._open_directory_entry(directory_fd, name, info)
                    try:
                        visit(locator_parts, child_fd, depth + 1)
                    finally:
                        os.close(child_fd)

        root_fd = self._open_directory_parts(root_parts)
        try:
            visit(root_parts, root_fd, 0)
        finally:
            os.close(root_fd)
        matches.sort(key=lambda item: item.path)
        return _search_result(matches, budget)

    def search_text(
        self,
        query: str,
        *,
        root: str,
        max_results: int,
        limits: TraversalLimits,
    ) -> WorkspaceSearchResult:
        normalized_query = _validate_search_query(query)
        if not 1 <= max_results <= limits.max_matches:
            raise ValueError("max_results exceeds the workspace search cap")
        root_parts = self.validate_relative(root, allow_root=True)
        budget = _TraversalBudget(limits, time.monotonic() + limits.deadline_seconds)
        matches: list[TextMatch] = []

        def visit(parts: tuple[str, ...], directory_fd: int, depth: int) -> None:
            if budget.reason is not None:
                return
            entries = self._scan_directory(parts, directory_fd, budget)
            for name, info, kind in entries:
                if budget.reason not in {None, "scan_entries"}:
                    return
                locator_parts = (*parts, name)
                if kind == "directory":
                    if budget.reason is not None:
                        continue
                    if depth >= limits.max_depth:
                        budget.stop("depth")
                        return
                    child_fd = self._open_directory_entry(directory_fd, name, info)
                    try:
                        visit(locator_parts, child_fd, depth + 1)
                    finally:
                        os.close(child_fd)
                    continue
                if budget.opened_files >= limits.max_opened_files:
                    budget.stop("opened_files")
                    return
                fd = self._open_regular(directory_fd, name, expected=info)
                budget.opened_files += 1
                try:
                    data, bounded_reason = self._read_search_bytes(fd, budget)
                finally:
                    os.close(fd)
                locator = "/".join(locator_parts)
                if _is_binary(data):
                    if bounded_reason is not None:
                        budget.stop(bounded_reason)
                    continue
                content, encoding = _decode_text(data)
                file_digest = _sha256(data)
                snapshot_digest = _file_snapshot_digest(locator, info, file_digest)
                for line_number, line in enumerate(content.splitlines(), start=1):
                    if normalized_query not in line.casefold():
                        continue
                    snippet = line
                    snippet_truncated = len(snippet) > limits.max_snippet_chars
                    if snippet_truncated:
                        snippet = snippet[: limits.max_snippet_chars]
                    matches.append(
                        TextMatch(
                            path=locator,
                            line=line_number,
                            snippet=snippet,
                            encoding=encoding,
                            content_digest=_sha256(snippet.encode("utf-8")),
                            snapshot_digest=snapshot_digest,
                            observed_at=f"mtime_ns:{info.st_mtime_ns}",
                            truncated=snippet_truncated or bounded_reason is not None,
                        )
                    )
                    if len(matches) >= max_results:
                        budget.stop("matches")
                        return
                if bounded_reason is not None:
                    budget.stop(bounded_reason)
                    return

        root_fd = self._open_directory_parts(root_parts)
        try:
            visit(root_parts, root_fd, 0)
        finally:
            os.close(root_fd)
        matches.sort(key=lambda item: (item.path, item.line, item.snippet))
        return _search_result(matches, budget)

    def read_file_chunk(
        self,
        raw_path: str,
        *,
        start_line: int,
        max_lines: int,
        max_bytes: int,
        max_line_cap: int,
    ) -> FileChunk:
        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or start_line < 1
            or not isinstance(max_lines, int)
            or isinstance(max_lines, bool)
            or not 1 <= max_lines <= max_line_cap
        ):
            raise ValueError("line window is outside the configured bounds")
        document = self.read_document(raw_path, max_bytes=max_bytes)
        lines = document.content.splitlines(keepends=True)
        start_index = start_line - 1
        selected = lines[start_index : start_index + max_lines]
        content = "".join(selected)
        end_line = start_line + len(selected) - 1 if selected else start_line - 1
        truncated = start_line > 1 or end_line < len(lines)
        return FileChunk(
            path=document.path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            encoding=document.encoding,
            truncated=truncated,
            content_digest=_sha256(content.encode("utf-8")),
            original_content_digest=document.content_digest,
            snapshot_digest=document.snapshot_digest,
            observed_at=document.observed_at,
        )

    def _scan_directory(
        self,
        parts: tuple[str, ...],
        directory_fd: int,
        budget: _TraversalBudget,
    ) -> list[tuple[str, os.stat_result, str]]:
        visible: list[tuple[str, os.stat_result, str]] = []
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                if time.monotonic() > budget.deadline:
                    budget.stop("deadline")
                    break
                if budget.scanned_entries >= budget.limits.max_scan_entries:
                    budget.stop("scan_entries")
                    break
                budget.scanned_entries += 1
                projected = self._visible_entry(parts, entry)
                if projected is None:
                    continue
                _display_name, info, kind = projected
                visible.append((entry.name, info, kind))
        visible.sort(key=lambda item: item[0])
        return visible

    def _visible_entry(
        self,
        parts: tuple[str, ...],
        entry: os.DirEntry,
    ) -> tuple[str, os.stat_result, str] | None:
        name = entry.name
        child_parts = (*parts, name)
        # 名称级拒绝必须先于 stat/open，避免遍历 private subtree。
        if self._is_sensitive(child_parts):
            return None
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        if stat.S_ISLNK(info.st_mode):
            return None
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                return None
            kind = "file"
        elif stat.S_ISDIR(info.st_mode):
            kind = "directory"
        else:
            return None
        if (info.st_dev, info.st_ino) in self._protected_identities:
            return None
        return name + ("/" if kind == "directory" else ""), info, kind

    @staticmethod
    def _open_directory_entry(
        parent_fd: int,
        name: str,
        expected: os.stat_result,
    ) -> int:
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | _o_nofollow(),
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise WorkspaceSecurityError("directory traversal was denied") from error
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            os.close(fd)
            raise WorkspaceSecurityError("directory identity changed during traversal")
        return fd

    @staticmethod
    def _read_search_bytes(
        fd: int,
        budget: _TraversalBudget,
    ) -> tuple[bytes, str | None]:
        remaining_total = budget.limits.max_total_bytes - budget.total_bytes
        if remaining_total <= 0:
            return b"", "total_bytes"
        read_limit = min(budget.limits.max_single_file_bytes, remaining_total)
        chunks: list[bytes] = []
        total = 0
        reason: str | None = None
        while total <= read_limit:
            chunk = os.read(fd, min(65_536, read_limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > read_limit:
                reason = (
                    "total_bytes"
                    if read_limit == remaining_total
                    else "single_file_bytes"
                )
                break
        data = b"".join(chunks)[:read_limit]
        budget.total_bytes += len(data)
        return data, reason

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

    def _open_regular(
        self,
        parent_fd: int,
        name: str,
        *,
        expected: os.stat_result | None = None,
        mutation: bool = False,
    ) -> int:
        try:
            fd = os.open(name, os.O_RDONLY | _o_nofollow(), dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError as error:
            raise WorkspaceSecurityError("file traversal was denied") from error
        info = os.fstat(fd)
        if expected is not None and (info.st_dev, info.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            os.close(fd)
            raise WorkspaceSecurityError("file identity changed during traversal")
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
            if folded in _SENSITIVE_COMPONENTS or folded in _SENSITIVE_EXACT:
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


def _digest_values(value: object) -> str:
    return _sha256(repr(value).encode("utf-8"))


def _entry_snapshot_digest(path: str, info: os.stat_result) -> str:
    return _digest_values(
        {
            "path": path,
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IFMT(info.st_mode),
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
        }
    )


def _file_snapshot_digest(path: str, info: os.stat_result, content_digest: str) -> str:
    return _digest_values(
        {
            "entry": _entry_snapshot_digest(path, info),
            "content_digest": content_digest,
        }
    )


def _validate_search_query(query: str) -> str:
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 256
        or any(not character.isprintable() for character in query)
    ):
        raise ValueError("workspace search query must be non-empty and bounded")
    return query.casefold()


def _decode_text(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), "utf-8-replacement"


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    if not data:
        return False
    controls = sum(byte < 9 or 13 < byte < 32 for byte in data)
    return controls * 20 > len(data)


def _search_result(
    matches: list[PathMatch] | list[TextMatch],
    budget: _TraversalBudget,
) -> WorkspaceSearchResult:
    values = {
        "matches": [
            {
                "path": match.path,
                "snapshot_digest": match.snapshot_digest,
                "line": match.line if isinstance(match, TextMatch) else None,
            }
            for match in matches
        ],
        "truncated": budget.reason is not None,
        "truncation_reason": budget.reason,
        "scanned_entries": budget.scanned_entries,
        "opened_files": budget.opened_files,
        "total_bytes": budget.total_bytes,
    }
    return WorkspaceSearchResult(
        matches=tuple(matches),
        truncated=budget.reason is not None,
        truncation_reason=budget.reason,
        scanned_entries=budget.scanned_entries,
        opened_files=budget.opened_files,
        total_bytes=budget.total_bytes,
        snapshot_digest=_digest_values(values),
    )


def _o_nofollow() -> int:
    return os.O_NOFOLLOW


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("file write made no progress")
        view = view[written:]
