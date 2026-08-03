"""显式路径、versioned、owner-only 的 Memory store。

create/load 互斥；load 不创建、不覆盖、不迁移旧格式。所有 mutation 在同一 stable lock
内完成 revision CAS、同目录 ``0600`` temp write+fsync、atomic replace 与 directory fsync。
锁获取使用 monotonic、不可延长的 finite deadline。store 与 workspace/checkpoint 不重叠。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import stat
import time
from pathlib import Path

from agent.memory.contracts import (
    MemoryBusyError,
    MemoryCasMismatchError,
    MemoryRecord,
    MemoryStoreError,
    ProviderTrustProfile,
)
from agent.runtime.contracts import FactAdmissionBinding

_SCHEMA_VERSION = 1
_LOCK_DEADLINE_SECONDS = 5.0
_MAX_CONTENT_CHARS = 20_000
_MAX_RECORDS = 1_000
# durable store 文件的 bounded read 上限（含所有 records）。需容纳 _MAX_RECORDS * 内容上限
# 的合法 store，同时仍对被篡改的巨大文件 fail closed（≈32 MiB 容纳 1000×20 KB + overhead）。
_MAX_STORE_BYTES = 32 * 1024 * 1024
_READ_CHUNK = 65_536
_KNOWN_TOP_LEVEL_KEYS = frozenset(
    {"version", "workspace_scope_digest", "provider_profile", "revision", "records"}
)
_KNOWN_RECORD_KEYS = frozenset(
    {
        "content",
        "content_digest",
        "created_at",
        "updated_at",
        "revision",
        "source_fact_id",
        "origin",
        "admission_binding_digest",
    }
)


class MemoryStore:
    def __init__(
        self,
        path: Path,
        *,
        workspace_scope_digest: str,
        profile: ProviderTrustProfile,
        revision: int,
        records: dict[str, MemoryRecord],
    ) -> None:
        self._path = path
        self._workspace_scope_digest = workspace_scope_digest
        self._profile = profile
        self._revision = revision
        self._records = dict(records)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def workspace_scope_digest(self) -> str:
        return self._workspace_scope_digest

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        workspace_scope_digest: str,
        profile: ProviderTrustProfile,
    ) -> MemoryStore:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError as error:
            raise MemoryStoreError("memory store target already exists") from error
        document = cls._serialize(workspace_scope_digest, profile, 0, {})
        try:
            os.write(fd, document)
            os.fsync(fd)
        finally:
            os.close(fd)
        cls._fsync_parent(path.parent)
        return cls(
            path,
            workspace_scope_digest=workspace_scope_digest,
            profile=profile,
            revision=0,
            records={},
        )

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        workspace_scope_digest: str,
        profile: ProviderTrustProfile,
    ) -> MemoryStore:
        # 009-gate：load 在 stable lock 内通过 no-follow opened handle 完成严格、bounded 读取。
        with cls._file_locked(path):
            document = cls._read_regular(path)
            revision, records = cls._parse_document(
                document, workspace_scope_digest=workspace_scope_digest, profile=profile
            )
        return cls(
            path,
            workspace_scope_digest=workspace_scope_digest,
            profile=profile,
            revision=revision,
            records=records,
        )

    def snapshot(self) -> tuple[MemoryRecord, ...]:
        # 009-gate：每次从 durable revision-consistent immutable view 构建，不复用进程内
        # _records 缓存（另一 conversation 的 approved mutation 必须立即可见）。
        with self._file_locked(self._path):
            document = self._read_regular(self._path)
            revision, records = self._parse_document(
                document,
                workspace_scope_digest=self._workspace_scope_digest,
                profile=self._profile,
            )
            self._revision = revision
            self._records = records
        return tuple(
            sorted(records.values(), key=lambda record: (-record.updated_at, record.record_id))
        )

    @staticmethod
    def _parse_document(
        document: bytes,
        *,
        workspace_scope_digest: str,
        profile: ProviderTrustProfile,
    ) -> tuple[int, dict[str, MemoryRecord]]:
        """严格解析 durable document：禁止 int()/float() 容错 coercion。

        version/scope/profile/revision 与每条 record 的 content/digest/timestamp/revision
        都做精确类型校验；unknown field、缺失字段、错误类型、digest 不一致一律 fail closed。
        """
        try:
            data = json.loads(document.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MemoryStoreError("memory store is malformed") from error
        if not isinstance(data, dict):
            raise MemoryStoreError("memory store is malformed")
        unknown_top = set(data) - _KNOWN_TOP_LEVEL_KEYS
        if unknown_top:
            raise MemoryStoreError("memory store has unknown fields")
        # version 必须是精确 int（字符串 "1" 不被 coerce）。
        if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool):
            raise MemoryStoreError("memory store version is unsupported")
        if data["version"] != _SCHEMA_VERSION:
            raise MemoryStoreError("memory store version is unsupported")
        if not isinstance(data.get("workspace_scope_digest"), str):
            raise MemoryStoreError("memory store scope is malformed")
        if data["workspace_scope_digest"] != workspace_scope_digest:
            raise MemoryStoreError("memory store scope does not match the workspace")
        stored_profile = data.get("provider_profile")
        if not isinstance(stored_profile, dict):
            raise MemoryStoreError("memory store profile is malformed")
        if (
            stored_profile.get("profile_id") != profile.profile_id
            or stored_profile.get("provider_family") != profile.provider_family
            or stored_profile.get("destination") != profile.destination
        ):
            raise MemoryStoreError("memory store provider profile does not match")
        if not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool):
            raise MemoryStoreError("memory store revision must be an integer")
        revision = data["revision"]
        records: dict[str, MemoryRecord] = {}
        raw_records = data.get("records")
        if not isinstance(raw_records, dict):
            raise MemoryStoreError("memory store records are malformed")
        for record_id, raw in raw_records.items():
            if not isinstance(raw, dict):
                raise MemoryStoreError("memory store record is malformed")
            unknown_rec = set(raw) - _KNOWN_RECORD_KEYS
            if unknown_rec:
                raise MemoryStoreError("memory store record has unknown fields")
            content = raw.get("content")
            content_digest = raw.get("content_digest")
            created_at = raw.get("created_at")
            updated_at = raw.get("updated_at")
            rec_revision = raw.get("revision")
            source_fact_id = raw.get("source_fact_id")
            origin = raw.get("origin")
            admission_binding_digest = raw.get("admission_binding_digest")
            if (
                not isinstance(content, str)
                or not isinstance(content_digest, str)
                or not _is_number(created_at)
                or not _is_number(updated_at)
                or not isinstance(rec_revision, int)
                or isinstance(rec_revision, bool)
            ):
                raise MemoryStoreError("memory store record has invalid types")
            provenance = (source_fact_id, origin, admission_binding_digest)
            if any(value is not None for value in provenance) and not all(
                isinstance(value, str) and value for value in provenance
            ):
                raise MemoryStoreError("memory store record provenance is malformed")
            if _content_digest(content) != content_digest:
                raise MemoryStoreError("memory store record content digest mismatch")
            record = MemoryRecord(
                record_id=str(record_id),
                workspace_scope_digest=workspace_scope_digest,
                content=content,
                content_digest=content_digest,
                created_at=float(created_at),
                updated_at=float(updated_at),
                revision=rec_revision,
                source_fact_id=source_fact_id,
                origin=origin,
                admission_binding_digest=admission_binding_digest,
            )
            records[record.record_id] = record
        return revision, records

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def remember(
        self,
        content: str,
        *,
        fact_admission: FactAdmissionBinding | None = None,
        clock=time.time,
    ) -> MemoryRecord:
        return self.remember_with_provenance(
            content,
            source_fact_id=(fact_admission.fact_id if fact_admission else None),
            origin=(fact_admission.fact_kind.value if fact_admission else None),
            admission_binding_digest=(
                fact_admission.binding_digest if fact_admission else None
            ),
            clock=clock,
        )

    def remember_with_provenance(
        self,
        content: str,
        *,
        source_fact_id: str | None,
        origin: str | None,
        admission_binding_digest: str | None,
        clock=time.time,
    ) -> MemoryRecord:
        _validate_content(content)
        with self._locked():
            if len(self._records) >= _MAX_RECORDS:
                raise MemoryStoreError("memory store is full")
            now = clock()
            record_id = secrets.token_hex(8)
            record = MemoryRecord(
                record_id=record_id,
                workspace_scope_digest=self._workspace_scope_digest,
                content=content,
                content_digest=_content_digest(content),
                created_at=now,
                updated_at=now,
                revision=self._revision + 1,
                source_fact_id=source_fact_id,
                origin=origin,
                admission_binding_digest=admission_binding_digest,
            )
            self._commit({**self._records, record_id: record}, self._revision + 1)
            return record

    def update(
        self,
        record_id: str,
        content: str,
        *,
        expected_record_revision: int,
        expected_content_digest: str,
        source_fact_id: str | None = None,
        origin: str | None = None,
        admission_binding_digest: str | None = None,
        clock=time.time,
    ) -> MemoryRecord:
        _validate_content(content)
        with self._locked():
            existing = self._records.get(record_id)
            if existing is None:
                raise MemoryCasMismatchError("record does not exist")
            if existing.revision != expected_record_revision:
                raise MemoryCasMismatchError("record revision mismatch")
            if existing.content_digest != expected_content_digest:
                raise MemoryCasMismatchError("record content digest mismatch")
            updated = MemoryRecord(
                record_id=existing.record_id,
                workspace_scope_digest=existing.workspace_scope_digest,
                content=content,
                content_digest=_content_digest(content),
                created_at=existing.created_at,
                updated_at=clock(),
                revision=self._revision + 1,
                source_fact_id=(source_fact_id or existing.source_fact_id),
                origin=(origin or existing.origin),
                admission_binding_digest=(
                    admission_binding_digest or existing.admission_binding_digest
                ),
            )
            records = {**self._records, record_id: updated}
            self._commit(records, self._revision + 1)
            return updated

    def forget(
        self,
        record_id: str,
        *,
        expected_record_revision: int,
        expected_content_digest: str,
    ) -> None:
        with self._locked():
            existing = self._records.get(record_id)
            if existing is None:
                raise MemoryCasMismatchError("record does not exist")
            if existing.revision != expected_record_revision:
                raise MemoryCasMismatchError("record revision mismatch")
            if existing.content_digest != expected_content_digest:
                raise MemoryCasMismatchError("record content digest mismatch")
            records = {key: value for key, value in self._records.items() if key != record_id}
            self._commit(records, self._revision + 1)

    def _commit(self, records: dict[str, MemoryRecord], revision: int) -> None:
        # 重新读取磁盘 revision，确保未被并发修改；再原子写入。
        on_disk = json.loads(self._read_regular(self._path).decode("utf-8"))
        if int(on_disk.get("revision", -1)) != self._revision:
            raise MemoryCasMismatchError("store revision changed")
        document = self._serialize(
            self._workspace_scope_digest, self._profile, revision, records
        )
        tmp_path = self._path.parent / f"{self._path.name}.tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, document)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._path)
        self._fsync_parent(self._path.parent)
        self._records = records
        self._revision = revision

    @staticmethod
    def _read_regular(path: Path) -> bytes:
        # identity-safe bounded read：单一 O_NOFOLLOW fd 同时 fstat 与读取，消除
        # stat-then-open TOCTOU；owner-only（UID + 无 group/other 权限）、regular-file、
        # bounded size 全部在同一 fd 上校验后再读。
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError as error:
            raise MemoryStoreError("memory store does not exist") from error
        except OSError as error:
            # O_NOFOLLOW 命中 symlink → ELOOP；其它 open 错误也 fail closed。
            raise MemoryStoreError("memory store is not an owner-only regular file") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise MemoryStoreError("memory store must be a regular file")
            if info.st_uid != os.getuid():
                raise MemoryStoreError("memory store must be owner-only")
            if info.st_mode & 0o077:
                raise MemoryStoreError("memory store must be owner-only")
            if info.st_size > _MAX_STORE_BYTES:
                raise MemoryStoreError("memory store exceeds the size limit")
            chunks: list[bytes] = []
            remaining = info.st_size
            while remaining > 0:
                chunk = os.read(fd, min(_READ_CHUNK, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    @staticmethod
    def _serialize(
        workspace_scope_digest: str,
        profile: ProviderTrustProfile,
        revision: int,
        records: dict[str, MemoryRecord],
    ) -> bytes:
        payload = {
            "version": _SCHEMA_VERSION,
            "workspace_scope_digest": workspace_scope_digest,
            "provider_profile": {
                "profile_id": profile.profile_id,
                "provider_family": profile.provider_family,
                "destination": profile.destination,
            },
            "revision": revision,
            "records": {
                record.record_id: {
                    "content": record.content,
                    "content_digest": record.content_digest,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "revision": record.revision,
                    "source_fact_id": record.source_fact_id,
                    "origin": record.origin,
                    "admission_binding_digest": record.admission_binding_digest,
                }
                for record in records.values()
            },
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _fsync_parent(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _locked(self):
        with self._file_locked(self._path):
            yield

    @staticmethod
    @contextlib.contextmanager
    def _file_locked(path: Path):
        import fcntl

        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_fd = MemoryStore._open_lock(lock_path)
        deadline = time.monotonic() + _LOCK_DEADLINE_SECONDS
        try:
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise MemoryBusyError("memory store lock deadline exceeded") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    @staticmethod
    def _open_lock(lock_path: Path) -> int:
        # owner-only、no-follow lock file：O_CREAT 创建 0600；已存在则必须是 owner-regular。
        # O_NOFOLLOW 拒绝 symlink；fstat 在同一 fd 上确认 regular + owner-only。
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as error:
            raise MemoryStoreError("memory store lock is unavailable") from error
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            os.close(fd)
            raise MemoryStoreError("memory store lock must be an owner-only regular file")
        return fd


def _validate_content(content: str) -> None:
    if not isinstance(content, str) or not content.strip():
        raise MemoryStoreError("memory content must be a non-empty string")
    if len(content) > _MAX_CONTENT_CHARS:
        raise MemoryStoreError("memory content exceeds the size limit")


def _is_number(value: object) -> bool:
    # JSON 数字可以是 int 或 float，但 bool 是 int 子类需排除；字符串不得被 coerce。
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    # timestamp 必须是 int 或 float，但 bool 是 int 子类需排除（True/False 不是合法时间戳）。
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
