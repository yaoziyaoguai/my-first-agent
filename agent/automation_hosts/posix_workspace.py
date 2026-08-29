"""POSIX owned-workspace adapter for the optional 019 host profile.

该模块只实现 portable ports 的文件系统效果；它不解释 schedule、grant、Runtime
completion，也不调用 provider/tool。所有路径由 trusted composition 预绑定。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent.automation.contracts import PurgeCleanupOutcome, PurgeObjectKind, PurgeOwnedObjectV1
from agent.automation.workspace import (
    CleanupOutcome,
    CleanupResultV1,
    OwnedObjectKind,
    OwnedObjectV1,
    SourceBindingV1,
    SourceManifestV1,
    TerminalArtifactCandidateV1,
    TerminalCaptureV1,
    WorkspaceBoundsV1,
    _build_diff,
    _build_manifest,
    _owned_object_id,
)
from agent.automation_hosts._posix_fs import (
    DIRECTORY as _DIRECTORY,
)
from agent.automation_hosts._posix_fs import (
    NOFOLLOW as _NOFOLLOW,
)
from agent.automation_hosts._posix_fs import (
    NONBLOCK as _NONBLOCK,
)
from agent.automation_hosts._posix_fs import (
    PosixWorkspaceCommitUnknownError,
    PosixWorkspaceStorageError,
    source_root_identity,
)
from agent.automation_hosts._posix_fs import (
    absolute_unresolved as _absolute_unresolved,
)
from agent.automation_hosts._posix_fs import (
    ensure_owner_directory as _ensure_owner_directory,
)
from agent.automation_hosts._posix_fs import (
    fsync_directory as _fsync_directory,
)
from agent.automation_hosts._posix_fs import (
    owner_uid as _owner_uid,
)
from agent.automation_hosts._posix_fs import (
    read_bound_source_file_at as _read_bound_source_file_at,
)
from agent.automation_hosts._posix_fs import (
    read_owner_file as _read_owner_file,
)
from agent.automation_hosts._posix_fs import (
    storage_identity as _storage_identity,
)
from agent.automation_hosts._posix_fs import (
    validate_owner_file as _validate_owner_file,
)
from agent.automation_hosts._posix_fs import (
    write_new_owner_file as _write_new_owner_file,
)
from agent.automation_hosts._posix_workspace_codec import (
    METADATA_SCHEMA,
    WorkspaceMetadataCodec,
)
from agent.automation_hosts._posix_workspace_files import PosixWorkspaceFiles
from agent.runtime.contracts import canonical_json_digest

_MAX_METADATA_BYTES = 2 * 1024 * 1024
_INTERNAL_ARTIFACT_DIRECTORY = ".automation-artifacts"


class PosixOwnedWorkspaceRepository(WorkspaceMetadataCodec, PosixWorkspaceFiles):
    """Descriptor-checked source capture and owned-object storage."""

    def __init__(
        self,
        owned_root: Path,
        sources: dict[SourceBindingV1, Path],
    ) -> None:
        if _NOFOLLOW == 0 or _DIRECTORY == 0:
            raise PosixWorkspaceStorageError("POSIX no-follow storage is unavailable")
        self.root = _absolute_unresolved(owned_root)
        self._objects = self.root / "objects"
        self._metadata = self.root / "metadata"
        self._temporary = self.root / "temporary"
        self._lock_path = self.root / "workspace.lock"
        self._layout_identities: dict[Path, tuple[int, int]] = {}
        self._lock_identity: tuple[int, int] | None = None
        self._sources: dict[str, tuple[SourceBindingV1, Path]] = {}
        for binding, path in sources.items():
            if binding.binding_id in self._sources:
                raise ValueError("source binding ids must be unique")
            canonical = _absolute_unresolved(path)
            if source_root_identity(canonical) != binding.root_identity_digest:
                raise ValueError("source root identity drift")
            self._sources[binding.binding_id] = (binding, canonical)
        _ensure_owner_directory(self.root)
        for directory in (self._objects, self._metadata, self._temporary):
            _ensure_owner_directory(directory)
        for directory in (self.root, self._objects, self._metadata, self._temporary):
            info = directory.lstat()
            self._layout_identities[directory] = (info.st_dev, info.st_ino)
        self._ensure_lock()

    def _ensure_lock(self) -> None:
        try:
            fd = os.open(
                self._lock_path,
                os.O_RDWR | os.O_CREAT | _NOFOLLOW | _NONBLOCK,
                0o600,
            )
        except OSError as error:
            raise PosixWorkspaceStorageError("workspace lock is unavailable") from error
        try:
            info = os.fstat(fd)
            _validate_owner_file(info, "workspace lock")
            self._lock_identity = (info.st_dev, info.st_ino)
        finally:
            os.close(fd)

    def _validate_layout(self) -> None:
        for path, identity in self._layout_identities.items():
            try:
                info = path.lstat()
            except OSError as error:
                raise PosixWorkspaceStorageError(
                    "owned workspace root identity unavailable"
                ) from error
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != _owner_uid()
                or stat.S_IMODE(info.st_mode) != 0o700
                or (info.st_dev, info.st_ino) != identity
            ):
                raise PosixWorkspaceStorageError("owned workspace root identity drift")

    @contextmanager
    def _lease(self) -> Iterator[None]:
        self._validate_layout()
        try:
            fd = os.open(self._lock_path, os.O_RDWR | _NOFOLLOW | _NONBLOCK)
            lock_info = os.fstat(fd)
            _validate_owner_file(lock_info, "workspace lock")
            if self._lock_identity is None or (
                lock_info.st_dev,
                lock_info.st_ino,
            ) != self._lock_identity:
                raise PosixWorkspaceStorageError("workspace lock identity drift")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if "fd" in locals():
                os.close(fd)
            raise PosixWorkspaceStorageError("workspace lock is unavailable") from error
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def scan_source(
        self,
        binding: SourceBindingV1,
        bounds: WorkspaceBoundsV1,
    ) -> SourceManifestV1:
        self._validate_layout()
        configured, root = self._source(binding)
        if configured != binding or source_root_identity(root) != binding.root_identity_digest:
            raise ValueError("source root identity drift")
        nodes = self._scan_tree(root, binding, bounds)
        return _build_manifest(binding, nodes, bounds)

    def capture_source(
        self,
        binding: SourceBindingV1,
        expected_manifest: SourceManifestV1,
        bounds: WorkspaceBoundsV1,
        *,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1:
        actual = self.scan_source(binding, bounds)
        if actual != expected_manifest:
            raise ValueError("source manifest drift")
        object_id = _owned_object_id("snapshot", actual.manifest_digest, owner_automation_id)
        owned = OwnedObjectV1(
            object_id=object_id,
            kind=OwnedObjectKind.SOURCE_SNAPSHOT,
            identity_digest=canonical_json_digest(
                {
                    "kind": OwnedObjectKind.SOURCE_SNAPSHOT.value,
                    "manifest": actual.manifest_digest,
                    "owner_automation_id": owner_automation_id,
                }
            ),
            size_bytes=actual.total_bytes,
            manifest=actual,
            owner_automation_id=owner_automation_id,
        )
        with self._lease():
            existing = self._load_meta_optional(object_id)
            if existing is not None:
                if existing["object"] != owned or existing["cleaned"]:
                    raise ValueError("owned source snapshot identity conflict")
                self._validate_storage(existing)
                return owned
            temporary = Path(tempfile.mkdtemp(prefix="snapshot-", dir=self._temporary))
            try:
                _, source_root = self._source(binding)
                self._copy_source_manifest(source_root, binding, actual, temporary)
                self._install_directory_object(owned, temporary, source_object_id=None)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return owned

    def load_source_snapshot(
        self,
        manifest_digest: str,
        *,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1:
        object_id = _owned_object_id("snapshot", manifest_digest, owner_automation_id)
        meta = self._require_meta(object_id)
        owned = meta["object"]
        if (
            meta["cleaned"]
            or owned.kind is not OwnedObjectKind.SOURCE_SNAPSHOT
            or owned.manifest is None
            or owned.manifest.manifest_digest != manifest_digest
            or owned.owner_automation_id != owner_automation_id
        ):
            raise ValueError("owned source snapshot not found")
        self._validate_storage(meta)
        return owned

    def materialize_occurrence(
        self,
        source: OwnedObjectV1,
        occurrence_id: str,
    ) -> OwnedObjectV1:
        source_meta = self._require_exact(source)
        if source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT or source.manifest is None:
            raise ValueError("materialization requires a source snapshot")
        digest = canonical_json_digest(
            {
                "source_identity_digest": source.identity_digest,
                "occurrence_id": occurrence_id,
            }
        )
        workspace = OwnedObjectV1(
            object_id=f"workspace:{digest[:54]}",
            kind=OwnedObjectKind.OCCURRENCE_WORKSPACE,
            identity_digest=digest,
            size_bytes=source.size_bytes,
            source_identity_digest=source.identity_digest,
            owner_automation_id=source.owner_automation_id,
        )
        with self._lease():
            existing = self._load_meta_optional(workspace.object_id)
            if existing is not None:
                if existing["object"] != workspace:
                    raise ValueError("occurrence workspace identity conflict")
                if existing["cleaned"]:
                    raise ValueError("occurrence workspace is already terminal")
                self._validate_storage(existing)
                return workspace
            temporary = Path(tempfile.mkdtemp(prefix="workspace-", dir=self._temporary))
            try:
                self._copy_owned_manifest(
                    self.resolve_owned_path(source),
                    source.manifest,
                    temporary,
                    expected_root_storage=source_meta["storage_identity_digest"],
                )
                self._install_directory_object(
                    workspace,
                    temporary,
                    source_object_id=source_meta["object"].object_id,
                )
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        return workspace

    def load_occurrence_workspace(
        self,
        source: OwnedObjectV1,
        occurrence_id: str,
    ) -> OwnedObjectV1:
        self._require_exact(source)
        digest = canonical_json_digest(
            {
                "source_identity_digest": source.identity_digest,
                "occurrence_id": occurrence_id,
            }
        )
        meta = self._require_meta(f"workspace:{digest[:54]}")
        workspace = meta["object"]
        if (
            workspace.kind is not OwnedObjectKind.OCCURRENCE_WORKSPACE
            or workspace.source_identity_digest != source.identity_digest
        ):
            raise ValueError("occurrence workspace history not found")
        return workspace

    def resolve_owned_path(self, expected: OwnedObjectV1) -> Path:
        meta = self._require_exact(expected)
        relative = meta["relative_storage"]
        if relative is None:
            raise ValueError("owned object has no filesystem payload")
        return self.root / relative

    def capture_terminal_outputs(
        self,
        workspace: OwnedObjectV1,
        source: OwnedObjectV1,
        bounds: WorkspaceBoundsV1,
        *,
        artifacts: tuple[TerminalArtifactCandidateV1, ...],
    ) -> TerminalCaptureV1:
        workspace_meta = self._require_exact(workspace)
        self._require_exact(source)
        if workspace_meta["source_object_id"] != source.object_id or source.manifest is None:
            raise ValueError("workspace does not bind the source snapshot")
        if not isinstance(artifacts, tuple) or any(
            not isinstance(item, TerminalArtifactCandidateV1) for item in artifacts
        ):
            raise ValueError("artifacts must be a tuple of candidates")
        if len({item.artifact_id for item in artifacts}) != len(artifacts):
            raise ValueError("artifact ids must be unique")
        existing_capture = workspace_meta["capture"]
        if existing_capture is not None:
            return self._decode_capture(existing_capture)

        workspace_root = self.resolve_owned_path(workspace)
        binding = SourceBindingV1(
            binding_id="terminal:workspace",
            root_identity_digest=workspace.identity_digest,
            excluded_components=(),
        )
        nodes = self._scan_tree(
            workspace_root,
            binding,
            bounds,
            ignored_root_components={_INTERNAL_ARTIFACT_DIRECTORY},
            expected_root_storage=workspace_meta["storage_identity_digest"],
        )
        result_manifest = _build_manifest(binding, nodes, bounds)
        diff_entries = _build_diff(source.manifest, result_manifest)
        if len(diff_entries) > bounds.max_diff_entries:
            raise ValueError("diff entry bound exceeded")
        encoded_diff = json.dumps(
            [entry.identity_values() for entry in diff_entries],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded_diff) > bounds.max_diff_encoded_bytes:
            raise ValueError("diff encoded byte bound exceeded")
        artifact_bytes = sum(item.size_bytes for item in artifacts)
        if artifact_bytes > bounds.max_artifact_bytes_per_occurrence:
            raise ValueError("artifact bytes per occurrence exceeded")
        retained_bytes = sum(
            meta["object"].size_bytes
            for meta in self._all_metadata()
            if not meta["cleaned"]
            and meta["object"].kind is OwnedObjectKind.RETAINED_ARTIFACT
            and meta["object"].owner_automation_id == source.owner_automation_id
        )
        if retained_bytes + artifact_bytes > bounds.max_artifact_bytes_per_automation:
            raise ValueError("artifact bytes per automation exceeded")

        diff_digest = canonical_json_digest(
            [entry.identity_values() for entry in diff_entries]
        )
        diff_object = (
            None
            if not diff_entries
            else OwnedObjectV1(
                object_id=_owned_object_id(
                    "diff",
                    diff_digest,
                    source.owner_automation_id,
                ),
                kind=OwnedObjectKind.RETAINED_DIFF,
                identity_digest=diff_digest,
                size_bytes=len(encoded_diff),
                source_identity_digest=source.identity_digest,
                owner_automation_id=source.owner_automation_id,
            )
        )
        artifact_objects = tuple(
            OwnedObjectV1(
                object_id=(
                    item.artifact_id
                    if source.owner_automation_id is None
                    else _owned_object_id(
                        "artifact",
                        item.artifact_id,
                        source.owner_automation_id,
                    )
                ),
                kind=OwnedObjectKind.RETAINED_ARTIFACT,
                identity_digest=canonical_json_digest(
                    {
                        "artifact_id": item.artifact_id,
                        "content_digest": item.content_digest,
                        "size_bytes": item.size_bytes,
                        "owner_automation_id": source.owner_automation_id,
                    }
                ),
                size_bytes=item.size_bytes,
                source_identity_digest=source.identity_digest,
                owner_automation_id=source.owner_automation_id,
            )
            for item in artifacts
        )
        created: list[OwnedObjectV1] = []
        with self._lease():
            try:
                if diff_object is not None:
                    self._install_file_object(diff_object, encoded_diff)
                    created.append(diff_object)
                artifact_root = workspace_root / _INTERNAL_ARTIFACT_DIRECTORY
                for candidate, owned in zip(artifacts, artifact_objects, strict=True):
                    payload = self._read_exact_artifact(artifact_root, candidate)
                    self._install_file_object(owned, payload)
                    created.append(owned)
                capture = TerminalCaptureV1(
                    workspace_identity_digest=workspace.identity_digest,
                    source_identity_digest=source.identity_digest,
                    diff_entries=diff_entries,
                    diff_digest=diff_digest,
                    diff_object=diff_object,
                    artifacts=artifact_objects,
                )
                workspace_meta["capture"] = self._encode_capture(capture)
                self._write_meta(workspace_meta)
            except PosixWorkspaceCommitUnknownError:
                raise
            except Exception:
                for owned in reversed(created):
                    self._remove_installed_object(owned.object_id)
                raise
        return capture

    def delete_owned_object(self, expected: OwnedObjectV1) -> CleanupResultV1:
        with self._lease():
            meta = self._load_meta_optional(expected.object_id)
            if meta is None or meta["object"] != expected:
                return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANUP_UNKNOWN)
            if meta["cleaned"]:
                outcome = (
                    CleanupOutcome.UNLINKED
                    if expected.kind is OwnedObjectKind.GOVERNED_EXTERNAL_REFERENCE
                    else CleanupOutcome.CLEANED
                )
                return CleanupResultV1(expected.object_id, outcome)
            if (
                expected.kind is OwnedObjectKind.OCCURRENCE_WORKSPACE
                and meta["capture"] is None
            ):
                return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANUP_UNKNOWN)
            relative = meta["relative_storage"]
            if relative is not None:
                target = self.root / relative
                try:
                    self._validate_storage(meta)
                    self._remove_owned_payload(
                        target,
                        expected_storage_identity=meta["storage_identity_digest"],
                    )
                except (OSError, PosixWorkspaceStorageError, ValueError):
                    return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANUP_UNKNOWN)
            meta["cleaned"] = True
            self._write_meta(meta)
            outcome = (
                CleanupOutcome.UNLINKED
                if expected.kind is OwnedObjectKind.GOVERNED_EXTERNAL_REFERENCE
                else CleanupOutcome.CLEANED
            )
            return CleanupResultV1(expected.object_id, outcome)

    def owned_objects(self, automation_id: str) -> tuple[PurgeOwnedObjectV1, ...]:
        values = [
            PurgeOwnedObjectV1(
                object_id=meta["object"].object_id,
                kind=PurgeObjectKind(meta["object"].kind.value),
                identity_digest=meta["object"].identity_digest,
            )
            for meta in self._all_metadata()
            if not meta["cleaned"]
            and meta["object"].owner_automation_id == automation_id
        ]
        return tuple(sorted(values, key=lambda item: item.object_id))

    def admit_runtime_checkpoint(
        self,
        *,
        automation_id: str,
        occurrence_id: str,
        identity_digest: str,
    ) -> PurgeOwnedObjectV1:
        object_id = _owned_object_id("checkpoint", occurrence_id, automation_id)
        owned = OwnedObjectV1(
            object_id=object_id,
            kind=OwnedObjectKind.RUNTIME_CHECKPOINT,
            identity_digest=identity_digest,
            size_bytes=0,
            owner_automation_id=automation_id,
        )
        with self._lease():
            existing = self._load_meta_optional(object_id)
            if existing is not None and existing["object"] != owned:
                raise ValueError("runtime checkpoint identity conflict")
            if existing is None:
                self._write_meta(self._new_meta(owned, None, None, None))
        return PurgeOwnedObjectV1(
            object_id=object_id,
            kind=PurgeObjectKind.RUNTIME_CHECKPOINT,
            identity_digest=identity_digest,
        )

    def admit_external_reference(
        self,
        *,
        object_id: str,
        identity_digest: str,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1:
        owned = OwnedObjectV1(
            object_id=object_id,
            kind=OwnedObjectKind.GOVERNED_EXTERNAL_REFERENCE,
            identity_digest=identity_digest,
            size_bytes=0,
            owner_automation_id=owner_automation_id,
        )
        with self._lease():
            if self._load_meta_optional(object_id) is not None:
                raise ValueError("owned object id already exists")
            self._write_meta(self._new_meta(owned, None, None, None))
        return owned

    def delete_purge_object(
        self,
        expected: PurgeOwnedObjectV1,
        *,
        allow_missing_after_intent: bool,
    ) -> PurgeCleanupOutcome:
        meta = self._load_meta_optional(expected.object_id)
        expected_outcome = (
            PurgeCleanupOutcome.UNLINKED
            if expected.kind is PurgeObjectKind.GOVERNED_EXTERNAL_REFERENCE
            else PurgeCleanupOutcome.CLEANED
        )
        if meta is None or meta["cleaned"]:
            return (
                expected_outcome
                if allow_missing_after_intent
                else PurgeCleanupOutcome.CLEANUP_UNKNOWN
            )
        owned = meta["object"]
        if (
            owned.kind.value != expected.kind.value
            or owned.identity_digest != expected.identity_digest
        ):
            return PurgeCleanupOutcome.CLEANUP_UNKNOWN
        return PurgeCleanupOutcome(self.delete_owned_object(owned).outcome.value)

    def source_for_workspace(self, workspace: OwnedObjectV1) -> OwnedObjectV1:
        meta = self._require_exact(workspace)
        source_id = meta["source_object_id"]
        if source_id is None:
            raise ValueError("workspace source not found")
        return self._require_meta(source_id)["object"]

    def contains(self, object_id: str) -> bool:
        meta = self._load_meta_optional(object_id)
        return meta is not None and not meta["cleaned"]

    def _source(self, binding: SourceBindingV1) -> tuple[SourceBindingV1, Path]:
        configured = self._sources.get(binding.binding_id)
        if configured is None:
            raise ValueError("source binding not found")
        return configured

    def _install_directory_object(
        self,
        owned: OwnedObjectV1,
        temporary: Path,
        *,
        source_object_id: str | None,
    ) -> None:
        target = self._objects / owned.object_id
        if target.exists() or target.is_symlink():
            raise ValueError("owned object id already exists")
        os.replace(temporary, target)
        _fsync_directory(self._objects)
        info = target.lstat()
        meta = self._new_meta(
            owned,
            f"objects/{owned.object_id}",
            _storage_identity(info),
            source_object_id,
        )
        try:
            self._write_meta(meta)
        except PosixWorkspaceCommitUnknownError:
            raise
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def _install_file_object(self, owned: OwnedObjectV1, payload: bytes) -> None:
        target = self._objects / owned.object_id
        existing = self._load_meta_optional(owned.object_id)
        if existing is not None:
            if existing["object"] != owned or existing["cleaned"]:
                raise ValueError("owned object id already exists")
            self._validate_storage(existing)
            return
        if target.exists() or target.is_symlink():
            raise ValueError("owned object id already exists")
        _write_new_owner_file(target, payload)
        _fsync_directory(self._objects)
        meta = self._new_meta(
            owned,
            f"objects/{owned.object_id}",
            _storage_identity(target.lstat()),
            None,
        )
        try:
            self._write_meta(meta)
        except PosixWorkspaceCommitUnknownError:
            raise
        except Exception:
            target.unlink(missing_ok=True)
            raise

    def _read_exact_artifact(
        self,
        artifact_root: Path,
        candidate: TerminalArtifactCandidateV1,
    ) -> bytes:
        try:
            directory_fd = os.open(
                artifact_root,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
            )
        except OSError as error:
            raise ValueError("artifact staging is unavailable") from error
        try:
            info = os.fstat(directory_fd)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != _owner_uid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise ValueError("artifact staging is not owner-only")
            payload = _read_bound_source_file_at(
                directory_fd,
                candidate.artifact_id,
                maximum=candidate.size_bytes,
                label="terminal artifact",
            )
        finally:
            os.close(directory_fd)
        if (
            len(payload) != candidate.size_bytes
            or hashlib.sha256(payload).hexdigest() != candidate.content_digest
        ):
            raise ValueError("terminal artifact identity drift")
        return payload

    def _metadata_path(self, object_id: str) -> Path:
        return self._metadata / f"{object_id}.json"

    def _new_meta(
        self,
        owned: OwnedObjectV1,
        relative_storage: str | None,
        storage_identity_digest: str | None,
        source_object_id: str | None,
    ) -> dict[str, object]:
        return {
            "schema_version": METADATA_SCHEMA,
            "object": owned,
            "relative_storage": relative_storage,
            "storage_identity_digest": storage_identity_digest,
            "source_object_id": source_object_id,
            "cleaned": False,
            "capture": None,
        }

    def _write_meta(self, meta: dict[str, object]) -> None:
        owned = meta["object"]
        assert isinstance(owned, OwnedObjectV1)
        payload = json.dumps(
            self._encode_meta(meta),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = self._metadata / f".{owned.object_id}.{os.getpid()}.tmp"
        replaced = False
        try:
            _write_new_owner_file(temporary, payload)
            self._replace_metadata(temporary, self._metadata_path(owned.object_id))
            replaced = True
            self._fsync_metadata()
        except OSError as error:
            temporary.unlink(missing_ok=True)
            if replaced:
                raise PosixWorkspaceCommitUnknownError(
                    "owned metadata commit outcome is unknown"
                ) from error
            raise PosixWorkspaceStorageError("owned metadata commit failed") from error

    @staticmethod
    def _replace_metadata(source: Path, target: Path) -> None:
        os.replace(source, target)

    def _fsync_metadata(self) -> None:
        _fsync_directory(self._metadata)

    def _load_meta_optional(self, object_id: str) -> dict[str, object] | None:
        path = self._metadata_path(object_id)
        try:
            payload = _read_owner_file(path, maximum=_MAX_METADATA_BYTES, label="owned metadata")
        except PosixWorkspaceStorageError as error:
            if isinstance(error.__cause__, FileNotFoundError):
                return None
            raise
        try:
            value = json.loads(payload.decode("utf-8"), object_pairs_hook=self._strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PosixWorkspaceStorageError("owned metadata is malformed") from error
        return self._decode_meta(value)

    def _require_meta(self, object_id: str) -> dict[str, object]:
        meta = self._load_meta_optional(object_id)
        if meta is None:
            raise ValueError("owned object not found")
        return meta

    def _require_exact(self, expected: OwnedObjectV1) -> dict[str, object]:
        meta = self._require_meta(expected.object_id)
        if meta["object"] != expected:
            raise ValueError("owned object identity mismatch")
        if not meta["cleaned"]:
            self._validate_storage(meta)
        return meta

    def _validate_storage(self, meta: dict[str, object]) -> None:
        relative = meta["relative_storage"]
        if relative is None:
            return
        path = self.root / relative
        try:
            info = path.lstat()
        except OSError as error:
            raise PosixWorkspaceStorageError("owned payload is unavailable") from error
        if stat.S_ISLNK(info.st_mode) or _storage_identity(info) != meta["storage_identity_digest"]:
            raise PosixWorkspaceStorageError("owned payload identity drift")
        expected_mode = 0o700 if stat.S_ISDIR(info.st_mode) else 0o600
        if info.st_uid != _owner_uid() or stat.S_IMODE(info.st_mode) != expected_mode:
            raise PosixWorkspaceStorageError("owned payload is not owner-only")

    def _all_metadata(self) -> tuple[dict[str, object], ...]:
        result: list[dict[str, object]] = []
        for entry in sorted(os.scandir(self._metadata), key=lambda item: item.name):
            if not entry.name.endswith(".json") or not entry.is_file(follow_symlinks=False):
                raise PosixWorkspaceStorageError("unexpected owned metadata entry")
            object_id = entry.name[:-5]
            meta = self._load_meta_optional(object_id)
            if meta is None:
                raise PosixWorkspaceStorageError("owned metadata disappeared")
            result.append(meta)
        return tuple(result)

    def _remove_installed_object(self, object_id: str) -> None:
        meta = self._load_meta_optional(object_id)
        if meta is None:
            return
        relative = meta["relative_storage"]
        if relative is not None:
            target = self.root / relative
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        self._metadata_path(object_id).unlink(missing_ok=True)

    def _remove_owned_payload(
        self,
        target: Path,
        *,
        expected_storage_identity: str,
    ) -> None:
        if target.parent != self._objects:
            raise PosixWorkspaceStorageError("owned payload parent drift")
        parent_fd = os.open(self._objects, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
        try:
            parent_info = os.fstat(parent_fd)
            if (
                parent_info.st_dev,
                parent_info.st_ino,
            ) != self._layout_identities[self._objects]:
                raise PosixWorkspaceStorageError("owned payload parent identity drift")
            info = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
            if _storage_identity(info) != expected_storage_identity:
                raise PosixWorkspaceStorageError("owned payload identity drift")
            if stat.S_ISREG(info.st_mode):
                os.unlink(target.name, dir_fd=parent_fd)
                return
            if not stat.S_ISDIR(info.st_mode):
                raise PosixWorkspaceStorageError("owned payload kind drift")
            directory_fd = os.open(
                target.name,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                dir_fd=parent_fd,
            )
            try:
                if _storage_identity(os.fstat(directory_fd)) != expected_storage_identity:
                    raise PosixWorkspaceStorageError("owned payload identity drift")
                self._remove_directory_contents(directory_fd)
            finally:
                os.close(directory_fd)
            current = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
            if _storage_identity(current) != expected_storage_identity:
                raise PosixWorkspaceStorageError("owned payload identity drift")
            os.rmdir(target.name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)

    def _remove_directory_contents(self, directory_fd: int) -> None:
        for entry in list(os.scandir(directory_fd)):
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                os.unlink(entry.name, dir_fd=directory_fd)
            elif stat.S_ISDIR(info.st_mode):
                child_fd = os.open(
                    entry.name,
                    os.O_RDONLY | _DIRECTORY | _NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    self._remove_directory_contents(child_fd)
                finally:
                    os.close(child_fd)
                os.rmdir(entry.name, dir_fd=directory_fd)
            else:
                raise PosixWorkspaceStorageError("owned payload contains unsafe node")
