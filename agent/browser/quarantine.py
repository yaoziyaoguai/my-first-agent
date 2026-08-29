"""018 browser-owned upload staging 与 download quarantine。

这里拥有文件描述符级 no-follow、bounded streaming hash 与 owner-only storage；
不认识 Provider、Goal、approval、checkpoint，也不把内部路径放进 durable receipt。
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from agent.browser.staging import BrowserUploadStagingV1
from agent.runtime.contracts import canonical_json_digest
from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError

UPLOAD_MAX_BYTES = 25 * 1024 * 1024
DOWNLOAD_MAX_BYTES = 100 * 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_SESSION_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,160}")
_HEX64_PATTERN = re.compile(r"[0-9a-f]{64}")
_PRIVATE_ROOTS = (
    "private",
    "runtime",
    "secret",
    "secrets",
    "credential",
    "credentials",
)


class BrowserQuarantineError(RuntimeError):
    """文件 identity、边界或 cleanup 无法证明时 fail closed。"""


def _require_hex64(value: str, field: str) -> None:
    if not isinstance(value, str) or _HEX64_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be 64 lowercase hex chars")


def _session_key(session_ref: str) -> str:
    if not isinstance(session_ref, str) or _SESSION_PATTERN.fullmatch(session_ref) is None:
        raise ValueError("session_ref must be a bounded opaque identifier")
    return "session-" + hashlib.sha256(session_ref.encode()).hexdigest()[:24]


def _normalized_download_name(quarantine_id: str, suggested_name: str) -> str:
    suffix = Path(suggested_name).suffix.lower()
    if (
        not suffix
        or len(suffix) > 10
        or any(character not in ".abcdefghijklmnopqrstuvwxyz0123456789" for character in suffix)
    ):
        suffix = ".bin"
    return f"{quarantine_id}{suffix}"


def _receipt_payload(receipt: QuarantinedDownloadV1) -> dict:
    return {
        "quarantine_id": receipt.quarantine_id,
        "session_ref": receipt.session_ref,
        "action_digest": receipt.action_digest,
        "browser_identity_digest": receipt.browser_identity_digest,
        "source_origin": receipt.source_origin,
        "suggested_name_digest": receipt.suggested_name_digest,
        "normalized_name": receipt.normalized_name,
        "mime_type": receipt.mime_type,
        "byte_size": receipt.byte_size,
        "sha256": receipt.sha256,
    }


@dataclass(frozen=True, slots=True)
class QuarantinedDownloadV1:
    """可消费的 bounded download receipt；不携带内部 host path。"""

    quarantine_id: str
    session_ref: str
    action_digest: str
    browser_identity_digest: str
    source_origin: str
    suggested_name_digest: str
    normalized_name: str
    mime_type: str
    byte_size: int
    sha256: str
    receipt_digest: str = ""

    def __post_init__(self) -> None:
        if re.fullmatch(r"download-[0-9a-f]{16}", self.quarantine_id) is None:
            raise ValueError("quarantine_id must be opaque")
        _session_key(self.session_ref)
        _require_hex64(self.action_digest, "action_digest")
        _require_hex64(self.browser_identity_digest, "browser_identity_digest")
        _require_hex64(self.suggested_name_digest, "suggested_name_digest")
        _require_hex64(self.sha256, "sha256")
        if not self.source_origin.startswith("https://"):
            raise ValueError("download source_origin must be HTTPS")
        if self.normalized_name != _normalized_download_name(
            self.quarantine_id, self.normalized_name
        ):
            raise ValueError("normalized_name must bind the opaque quarantine id")
        if not isinstance(self.mime_type, str) or not self.mime_type or len(self.mime_type) > 255:
            raise ValueError("mime_type must be bounded")
        if (
            isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or self.byte_size < 0
            or self.byte_size > DOWNLOAD_MAX_BYTES
        ):
            raise ValueError("download byte_size is outside the closed cap")
        computed = canonical_json_digest(_receipt_payload(self))
        if self.receipt_digest not in ("", computed):
            raise ValueError("download receipt digest does not match its fields")
        object.__setattr__(self, "receipt_digest", computed)


@dataclass(frozen=True, slots=True)
class UploadFileSnapshotV1:
    """approval 前的 workspace file identity；仅进程内使用。"""

    workspace_root: Path
    relative_path: str
    expected_sha256: str
    device: int
    inode: int
    byte_size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class UploadStagingV1:
    """approval 后的一次性 browser-owned staging；路径禁止序列化。"""

    staging_id: str
    session_ref: str
    action_digest: str
    path: Path
    byte_size: int
    sha256: str

    @property
    def capability(self) -> BrowserUploadStagingV1:
        return BrowserUploadStagingV1(
            staging_id=self.staging_id,
            session_ref=self.session_ref,
            action_digest=self.action_digest,
            byte_size=self.byte_size,
            sha256=self.sha256,
        )


class BrowserQuarantine:
    """owner-only quarantine；所有文件以 no-follow descriptor 操作。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()
        self._ensure_directory(self.root)
        self._downloads = self.root / "downloads"
        self._staging = self.root / "staging"
        self._incoming = self.root / "incoming"
        self._ensure_directory(self._downloads)
        self._ensure_directory(self._staging)
        self._ensure_directory(self._incoming)

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise BrowserQuarantineError("quarantine path must be absolute")
        try:
            directory_fd = os.open(
                candidate.anchor,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as error:
            raise BrowserQuarantineError(
                "quarantine path must be a real directory"
            ) from error
        parts = candidate.parts[1:]
        try:
            for index, part in enumerate(parts):
                created = False
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory_fd)
                    created = True
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                except OSError as error:
                    raise BrowserQuarantineError(
                        "quarantine path must be a real directory"
                    ) from error
                os.close(directory_fd)
                directory_fd = next_fd
                if created or index == len(parts) - 1:
                    info = os.fstat(directory_fd)
                    if info.st_mode & 0o077:
                        os.fchmod(directory_fd, 0o700)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _open_regular(path: Path) -> int:
        candidate = Path(path).absolute()
        parts = candidate.parts[1:]
        if not parts:
            raise BrowserQuarantineError("source must be a regular no-follow file")
        try:
            directory_fd = os.open(
                candidate.anchor,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as error:
            raise BrowserQuarantineError("source must be a regular no-follow file") from error
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise BrowserQuarantineError(
                "source must be a regular no-follow file"
            ) from error
        finally:
            os.close(directory_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise BrowserQuarantineError("source must be a regular no-follow file")
        return fd

    @staticmethod
    def _hash_fd(fd: int, *, cap: int, label: str) -> tuple[str, int]:
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise BrowserQuarantineError(f"{label} exceeds the closed size cap")
            digest.update(chunk)
        return digest.hexdigest(), total

    @staticmethod
    def _copy_fd(source_fd: int, target_fd: int, *, cap: int, label: str) -> tuple[str, int]:
        os.lseek(source_fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source_fd, _COPY_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise BrowserQuarantineError(f"{label} exceeds the closed size cap")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target_fd, view)
                view = view[written:]
        return digest.hexdigest(), total

    def _session_directory(self, session_ref: str) -> Path:
        path = self._downloads / _session_key(session_ref)
        self._ensure_directory(path)
        return path

    def store(
        self,
        source_path: Path,
        *,
        session_ref: str,
        action_digest: str,
        browser_identity_digest: str,
        source_origin: str,
        suggested_name: str,
        mime_type: str,
    ) -> QuarantinedDownloadV1:
        _require_hex64(action_digest, "action_digest")
        _require_hex64(browser_identity_digest, "browser_identity_digest")
        source_fd = self._open_regular(Path(source_path))
        target_fd = -1
        temporary: Path | None = None
        try:
            source_info = os.fstat(source_fd)
            if source_info.st_size > DOWNLOAD_MAX_BYTES:
                raise BrowserQuarantineError("download exceeds the closed size cap")
            quarantine_id = f"download-{secrets.token_hex(8)}"
            normalized_name = _normalized_download_name(quarantine_id, suggested_name)
            directory = self._session_directory(session_ref)
            temporary = directory / f".{quarantine_id}.partial"
            target_fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            digest, byte_size = self._copy_fd(
                source_fd,
                target_fd,
                cap=DOWNLOAD_MAX_BYTES,
                label="download",
            )
            after = os.fstat(source_fd)
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                source_info.st_dev,
                source_info.st_ino,
                source_info.st_size,
                source_info.st_mtime_ns,
            ):
                raise BrowserQuarantineError("download source changed while quarantining")
            os.fsync(target_fd)
            os.close(target_fd)
            target_fd = -1
            final = directory / normalized_name
            try:
                os.link(temporary, final, follow_symlinks=False)
            except FileExistsError as error:
                raise BrowserQuarantineError(
                    "quarantine download already exists"
                ) from error
            except OSError as error:
                raise BrowserQuarantineError(
                    "quarantine download finalization is unknown"
                ) from error
            temporary.unlink()
            temporary = None
            return QuarantinedDownloadV1(
                quarantine_id=quarantine_id,
                session_ref=session_ref,
                action_digest=action_digest,
                browser_identity_digest=browser_identity_digest,
                source_origin=source_origin,
                suggested_name_digest=hashlib.sha256(suggested_name.encode()).hexdigest(),
                normalized_name=normalized_name,
                mime_type=mime_type,
                byte_size=byte_size,
                sha256=digest,
            )
        finally:
            if target_fd >= 0:
                os.close(target_fd)
            os.close(source_fd)
            if temporary is not None:
                with suppress(FileNotFoundError):
                    temporary.unlink()

    def _download_path(self, receipt: QuarantinedDownloadV1) -> Path:
        if receipt.normalized_name != _normalized_download_name(
            receipt.quarantine_id, receipt.normalized_name
        ):
            raise BrowserQuarantineError("download receipt path binding changed")
        return self._downloads / _session_key(receipt.session_ref) / receipt.normalized_name

    def inspect(self, receipt: QuarantinedDownloadV1) -> QuarantinedDownloadV1:
        path = self._download_path(receipt)
        try:
            fd = self._open_regular(path)
        except BrowserQuarantineError as error:
            raise BrowserQuarantineError("download is unavailable") from error
        try:
            digest, byte_size = self._hash_fd(fd, cap=DOWNLOAD_MAX_BYTES, label="download")
        finally:
            os.close(fd)
        if digest != receipt.sha256 or byte_size != receipt.byte_size:
            raise BrowserQuarantineError("download identity changed")
        return receipt

    def delete(self, receipt: QuarantinedDownloadV1) -> None:
        path = self._download_path(receipt)
        self.inspect(receipt)
        try:
            path.unlink()
        except OSError as error:
            raise BrowserQuarantineError("download cleanup is unknown") from error

    def clear_session(self, session_ref: str) -> None:
        session_key = _session_key(session_ref)
        try:
            downloads_fd = os.open(
                self._downloads,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as error:
            raise BrowserQuarantineError("session quarantine cleanup is unknown") from error
        session_fd = -1
        try:
            try:
                session_fd = os.open(
                    session_key,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=downloads_fd,
                )
            except FileNotFoundError:
                return
            except OSError as error:
                raise BrowserQuarantineError(
                    "session quarantine cleanup is unknown"
                ) from error
            names = os.listdir(session_fd)
            for name in names:
                info = os.stat(name, dir_fd=session_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise BrowserQuarantineError("session quarantine contains an unknown entry")
            for name in names:
                os.unlink(name, dir_fd=session_fd)
            os.close(session_fd)
            session_fd = -1
            os.rmdir(session_key, dir_fd=downloads_fd)
        except OSError as error:
            raise BrowserQuarantineError("session quarantine cleanup is unknown") from error
        finally:
            if session_fd >= 0:
                os.close(session_fd)
            os.close(downloads_fd)

    @staticmethod
    def _open_workspace_file(workspace: Path, relative_path: str) -> tuple[int, str]:
        try:
            boundary = WorkspaceBoundary(
                workspace,
                protected_paths=(),
                private_roots=_PRIVATE_ROOTS,
            )
            parts = boundary.validate_relative(relative_path)
        except (OSError, WorkspaceSecurityError) as error:
            raise BrowserQuarantineError(
                "upload path is outside the closed workspace boundary"
            ) from error
        directory_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise BrowserQuarantineError(
                "upload source must be a regular no-follow file"
            ) from error
        finally:
            os.close(directory_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise BrowserQuarantineError("upload source must be a regular no-follow file")
        return fd, "/".join(parts)

    def inspect_upload(
        self,
        workspace: Path,
        relative_path: str,
        *,
        expected_sha256: str,
    ) -> UploadFileSnapshotV1:
        _require_hex64(expected_sha256, "expected_sha256")
        root = Path(workspace).absolute()
        fd, normalized = self._open_workspace_file(root, relative_path)
        try:
            info = os.fstat(fd)
            if info.st_size > UPLOAD_MAX_BYTES:
                raise BrowserQuarantineError("upload exceeds the closed size cap")
            digest, byte_size = self._hash_fd(fd, cap=UPLOAD_MAX_BYTES, label="upload")
        finally:
            os.close(fd)
        if digest != expected_sha256:
            raise BrowserQuarantineError("upload digest does not match the approved digest")
        return UploadFileSnapshotV1(
            workspace_root=root,
            relative_path=normalized,
            expected_sha256=expected_sha256,
            device=info.st_dev,
            inode=info.st_ino,
            byte_size=byte_size,
            mtime_ns=info.st_mtime_ns,
        )

    def stage_upload(
        self,
        snapshot: UploadFileSnapshotV1,
        *,
        session_ref: str,
        action_digest: str,
    ) -> UploadStagingV1:
        _session_key(session_ref)
        _require_hex64(action_digest, "action_digest")
        fd, normalized = self._open_workspace_file(
            snapshot.workspace_root, snapshot.relative_path
        )
        target_fd = -1
        target: Path | None = None
        try:
            before = os.fstat(fd)
            if normalized != snapshot.relative_path or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                snapshot.device,
                snapshot.inode,
                snapshot.byte_size,
                snapshot.mtime_ns,
            ):
                raise BrowserQuarantineError("upload source changed after approval")
            staging_id = f"upload-{secrets.token_hex(8)}"
            target = self._staging / staging_id
            target_fd = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            digest, byte_size = self._copy_fd(
                fd,
                target_fd,
                cap=UPLOAD_MAX_BYTES,
                label="upload",
            )
            after = os.fstat(fd)
            if (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) != (
                snapshot.device,
                snapshot.inode,
                snapshot.byte_size,
                snapshot.mtime_ns,
            ) or digest != snapshot.expected_sha256:
                raise BrowserQuarantineError("upload source changed after approval")
            os.fsync(target_fd)
            return UploadStagingV1(
                staging_id=staging_id,
                session_ref=session_ref,
                action_digest=action_digest,
                path=target,
                byte_size=byte_size,
                sha256=digest,
            )
        except Exception:
            if target is not None:
                with suppress(FileNotFoundError):
                    target.unlink()
            raise
        finally:
            if target_fd >= 0:
                os.close(target_fd)
            os.close(fd)

    def delete_staging(self, staging: UploadStagingV1) -> None:
        if staging.path.parent != self._staging or staging.path.name != staging.staging_id:
            raise BrowserQuarantineError("staging identity changed")
        try:
            info = staging.path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise BrowserQuarantineError("staging identity changed")
            staging.path.unlink()
        except FileNotFoundError as error:
            raise BrowserQuarantineError("staging is unavailable") from error
        except OSError as error:
            raise BrowserQuarantineError("staging cleanup is unknown") from error

    def resolve_staging(self, capability: BrowserUploadStagingV1) -> Path:
        """在 owner 内把 opaque capability 解析为已重验的 canonical path。"""

        if not isinstance(capability, BrowserUploadStagingV1):
            raise BrowserQuarantineError("upload staging capability is invalid")
        candidate = self._staging / capability.staging_id
        try:
            fd = self._open_regular(candidate)
            try:
                digest, byte_size = self._hash_fd(
                    fd, cap=UPLOAD_MAX_BYTES, label="upload"
                )
            finally:
                os.close(fd)
        except (OSError, BrowserQuarantineError) as error:
            raise BrowserQuarantineError("upload staging is unavailable") from error
        if byte_size != capability.byte_size or digest != capability.sha256:
            raise BrowserQuarantineError("upload staging identity changed")
        return candidate

    def allocate_incoming(self, *, session_ref: str, action_digest: str) -> Path:
        _session_key(session_ref)
        _require_hex64(action_digest, "action_digest")
        return self._incoming / f"incoming-{secrets.token_hex(8)}"

    def discard_incoming(self, path: Path) -> None:
        candidate = Path(path)
        if candidate.parent != self._incoming or not candidate.name.startswith("incoming-"):
            raise BrowserQuarantineError("incoming download path is outside the owned root")
        try:
            candidate.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise BrowserQuarantineError("incoming download cleanup is unknown") from error


__all__ = [
    "DOWNLOAD_MAX_BYTES",
    "UPLOAD_MAX_BYTES",
    "BrowserQuarantine",
    "BrowserQuarantineError",
    "QuarantinedDownloadV1",
    "UploadFileSnapshotV1",
    "UploadStagingV1",
]
