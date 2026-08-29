"""019 portable owned-workspace contracts and deterministic protocol adapter.

The module validates manifests, bounds and ownership transitions over opaque ids.  It never
walks or mutates a host filesystem; qualified host adapters implement those effects separately.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, replace
from enum import StrEnum
from fnmatch import fnmatchcase
from typing import Protocol

from agent.automation.contracts import (
    PurgeCleanupOutcome,
    PurgeObjectKind,
    PurgeOwnedObjectV1,
)
from agent.runtime.contracts import canonical_json_digest

_HEX64 = frozenset("0123456789abcdef")
_OPAQUE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
)
_SENSITIVE_PATTERNS = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx")


def _require_hex64(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX64 for character in value)
    ):
        raise ValueError(f"{field} must be bare hex64")
    return value


def _require_opaque(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 64
        or any(character not in _OPAQUE for character in value)
    ):
        raise ValueError(f"{field} must be an opaque id")
    return value


def _canonical_relative_path(value: object, *, max_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("relative path must be non-empty text")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("relative path must use NFC")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError("relative path exceeds byte bound")
    if value.startswith("/") or value.endswith("/") or "\\" in value or "//" in value:
        raise ValueError("relative path must be canonical POSIX-relative")
    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise ValueError("relative path must not contain dot components")
    return value


class VirtualNodeKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    UNSUPPORTED = "unsupported"


class OwnedObjectKind(StrEnum):
    SOURCE_SNAPSHOT = "source_snapshot"
    OCCURRENCE_WORKSPACE = "occurrence_workspace"
    RETAINED_DIFF = "retained_diff"
    RETAINED_ARTIFACT = "retained_artifact"
    RUNTIME_CHECKPOINT = "runtime_checkpoint"
    GOVERNED_EXTERNAL_REFERENCE = "governed_external_reference"


class DiffEntryKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class CleanupOutcome(StrEnum):
    CLEANED = "cleaned"
    UNLINKED = "unlinked"
    CLEANUP_UNKNOWN = "cleanup_unknown"


@dataclass(frozen=True, slots=True)
class WorkspaceBoundsV1:
    max_entries: int = 4_096
    max_total_bytes: int = 64 * 1024 * 1024
    max_file_bytes: int = 16 * 1024 * 1024
    max_path_bytes: int = 1_024
    max_diff_entries: int = 2_000
    max_diff_encoded_bytes: int = 4 * 1024 * 1024
    max_artifact_bytes_per_occurrence: int = 32 * 1024 * 1024
    max_artifact_bytes_per_automation: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive int")


@dataclass(frozen=True, slots=True)
class SourceBindingV1:
    binding_id: str
    root_identity_digest: str
    excluded_components: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_opaque(self.binding_id, "binding_id")
        _require_hex64(self.root_identity_digest, "root_identity_digest")
        if (
            not isinstance(self.excluded_components, tuple)
            or self.excluded_components != tuple(sorted(set(self.excluded_components)))
            or any(
                not component
                or "/" in component
                or "\\" in component
                or component in {".", ".."}
                for component in self.excluded_components
            )
        ):
            raise ValueError("excluded_components must be sorted unique path components")


@dataclass(frozen=True, slots=True)
class VirtualSourceNodeV1:
    relative_path: str
    kind: VirtualNodeKind
    size_bytes: int
    content_digest: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.relative_path, str) or not self.relative_path:
            raise ValueError("relative_path must be non-empty text")
        if not isinstance(self.kind, VirtualNodeKind):
            raise ValueError("kind must be a closed VirtualNodeKind")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("size_bytes must be an int")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if self.kind is VirtualNodeKind.FILE:
            _require_hex64(self.content_digest, "content_digest")
        elif self.content_digest is not None or self.size_bytes != 0:
            raise ValueError("non-file virtual nodes carry no content or size")


@dataclass(frozen=True, slots=True)
class SourceManifestEntryV1:
    relative_path: str
    kind: VirtualNodeKind
    size_bytes: int
    content_digest: str | None

    def __post_init__(self) -> None:
        _canonical_relative_path(self.relative_path, max_bytes=1_024)
        if self.kind not in {VirtualNodeKind.FILE, VirtualNodeKind.DIRECTORY}:
            raise ValueError("manifest entry kind must be file or directory")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative int")
        if self.kind is VirtualNodeKind.FILE:
            _require_hex64(self.content_digest, "content_digest")
        elif self.size_bytes != 0 or self.content_digest is not None:
            raise ValueError("directory entry carries no content or size")

    def identity_values(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind.value,
            "size_bytes": self.size_bytes,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class SourceManifestV1:
    binding_id: str
    root_identity_digest: str
    entries: tuple[SourceManifestEntryV1, ...]
    total_bytes: int
    manifest_digest: str = ""

    def __post_init__(self) -> None:
        _require_opaque(self.binding_id, "binding_id")
        _require_hex64(self.root_identity_digest, "root_identity_digest")
        if not isinstance(self.entries, tuple) or any(
            not isinstance(entry, SourceManifestEntryV1) for entry in self.entries
        ):
            raise ValueError("entries must be a tuple of manifest entries")
        paths = tuple(entry.relative_path for entry in self.entries)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("manifest entries must be sorted and unique")
        if self.total_bytes != sum(entry.size_bytes for entry in self.entries):
            raise ValueError("manifest total byte count mismatch")
        digest = canonical_json_digest(
            {
                "binding_id": self.binding_id,
                "root_identity_digest": self.root_identity_digest,
                "entries": [entry.identity_values() for entry in self.entries],
                "total_bytes": self.total_bytes,
            }
        )
        if self.manifest_digest and self.manifest_digest != digest:
            raise ValueError("source manifest digest mismatch")
        object.__setattr__(self, "manifest_digest", digest)


@dataclass(frozen=True, slots=True)
class OwnedObjectV1:
    object_id: str
    kind: OwnedObjectKind
    identity_digest: str
    size_bytes: int
    source_identity_digest: str | None = None
    manifest: SourceManifestV1 | None = None
    owner_automation_id: str | None = None

    def __post_init__(self) -> None:
        _require_opaque(self.object_id, "object_id")
        if not isinstance(self.kind, OwnedObjectKind):
            raise ValueError("kind must be a closed OwnedObjectKind")
        _require_hex64(self.identity_digest, "identity_digest")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("size_bytes must be an int")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if self.source_identity_digest is not None:
            _require_hex64(self.source_identity_digest, "source_identity_digest")
        if self.kind is OwnedObjectKind.SOURCE_SNAPSHOT and self.manifest is None:
            raise ValueError("source snapshot requires its manifest")
        if self.kind is not OwnedObjectKind.SOURCE_SNAPSHOT and self.manifest is not None:
            raise ValueError("only source snapshot carries a source manifest")
        if self.owner_automation_id is not None:
            _require_opaque(self.owner_automation_id, "owner_automation_id")


@dataclass(frozen=True, slots=True)
class TerminalArtifactCandidateV1:
    artifact_id: str
    size_bytes: int
    content_digest: str

    def __post_init__(self) -> None:
        _require_opaque(self.artifact_id, "artifact_id")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative int")
        _require_hex64(self.content_digest, "content_digest")


@dataclass(frozen=True, slots=True)
class DiffEntryV1:
    relative_path: str
    kind: DiffEntryKind
    source_digest: str | None
    result_digest: str | None

    def __post_init__(self) -> None:
        _canonical_relative_path(self.relative_path, max_bytes=1_024)
        if not isinstance(self.kind, DiffEntryKind):
            raise ValueError("kind must be a closed DiffEntryKind")
        for value, field in (
            (self.source_digest, "source_digest"),
            (self.result_digest, "result_digest"),
        ):
            if value is not None:
                _require_hex64(value, field)
        if self.kind is DiffEntryKind.ADDED and (
            self.source_digest is not None or self.result_digest is None
        ):
            raise ValueError("added diff entry has invalid digests")
        if self.kind is DiffEntryKind.DELETED and (
            self.source_digest is None or self.result_digest is not None
        ):
            raise ValueError("deleted diff entry has invalid digests")
        if self.kind is DiffEntryKind.MODIFIED and (
            self.source_digest is None
            or self.result_digest is None
            or self.source_digest == self.result_digest
        ):
            raise ValueError("modified diff entry has invalid digests")

    def identity_values(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "kind": self.kind.value,
            "source_digest": self.source_digest,
            "result_digest": self.result_digest,
        }


@dataclass(frozen=True, slots=True)
class TerminalCaptureV1:
    workspace_identity_digest: str
    source_identity_digest: str
    diff_entries: tuple[DiffEntryV1, ...]
    diff_digest: str
    diff_object: OwnedObjectV1 | None
    artifacts: tuple[OwnedObjectV1, ...]


@dataclass(frozen=True, slots=True)
class CleanupResultV1:
    object_id: str
    outcome: CleanupOutcome


class OwnedWorkspaceRepository(Protocol):
    def scan_source(
        self,
        binding: SourceBindingV1,
        bounds: WorkspaceBoundsV1,
    ) -> SourceManifestV1: ...

    def capture_source(
        self,
        binding: SourceBindingV1,
        expected_manifest: SourceManifestV1,
        bounds: WorkspaceBoundsV1,
        *,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1: ...

    def load_source_snapshot(
        self,
        manifest_digest: str,
        *,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1: ...

    def materialize_occurrence(
        self,
        source: OwnedObjectV1,
        occurrence_id: str,
    ) -> OwnedObjectV1: ...

    def load_occurrence_workspace(
        self,
        source: OwnedObjectV1,
        occurrence_id: str,
    ) -> OwnedObjectV1: ...

    def capture_terminal_outputs(
        self,
        workspace: OwnedObjectV1,
        source: OwnedObjectV1,
        bounds: WorkspaceBoundsV1,
        *,
        artifacts: tuple[TerminalArtifactCandidateV1, ...],
    ) -> TerminalCaptureV1: ...

    def delete_owned_object(self, expected: OwnedObjectV1) -> CleanupResultV1: ...

    def owned_objects(self, automation_id: str) -> tuple[PurgeOwnedObjectV1, ...]: ...

    def admit_runtime_checkpoint(
        self,
        *,
        automation_id: str,
        occurrence_id: str,
        identity_digest: str,
    ) -> PurgeOwnedObjectV1: ...

    def delete_purge_object(
        self,
        expected: PurgeOwnedObjectV1,
        *,
        allow_missing_after_intent: bool,
    ) -> PurgeCleanupOutcome: ...


class DeterministicOwnedWorkspaceRepository:
    """In-memory protocol adapter over immutable virtual metadata, not a host filesystem fake."""

    def __init__(
        self,
        sources: dict[SourceBindingV1, tuple[VirtualSourceNodeV1, ...]],
    ) -> None:
        self._sources = {
            binding.binding_id: [binding, tuple(nodes)] for binding, nodes in sources.items()
        }
        if len(self._sources) != len(sources):
            raise ValueError("source binding ids must be unique")
        self._owned: dict[str, OwnedObjectV1] = {}
        self._owned_nodes: dict[str, tuple[VirtualSourceNodeV1, ...]] = {}
        self._workspace_sources: dict[str, str] = {}
        self._terminal_captured: set[str] = set()
        self._workspace_history: dict[str, OwnedObjectV1] = {}
        self._terminal_captures: dict[str, TerminalCaptureV1] = {}
        self._terminal_candidates: dict[
            str, tuple[TerminalArtifactCandidateV1, ...]
        ] = {}
        self._cleanup_outcomes: dict[str, CleanupOutcome] = {}
        self._artifact_bytes = 0
        self._external_delete_count = 0

    @property
    def owned_object_count(self) -> int:
        return len(self._owned)

    @property
    def external_delete_count(self) -> int:
        return self._external_delete_count

    def scan_source(
        self,
        binding: SourceBindingV1,
        bounds: WorkspaceBoundsV1,
    ) -> SourceManifestV1:
        current, nodes = self._require_source(binding.binding_id)
        if current.root_identity_digest != binding.root_identity_digest:
            raise ValueError("source root identity drift")
        return _build_manifest(current, nodes, bounds)

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
        if owner_automation_id is not None:
            _require_opaque(owner_automation_id, "owner_automation_id")
        object_id = _owned_object_id(
            "snapshot",
            actual.manifest_digest,
            owner_automation_id,
        )
        identity = canonical_json_digest(
            {
                "kind": OwnedObjectKind.SOURCE_SNAPSHOT.value,
                "manifest": actual.manifest_digest,
                "owner_automation_id": owner_automation_id,
            }
        )
        captured = OwnedObjectV1(
            object_id=object_id,
            kind=OwnedObjectKind.SOURCE_SNAPSHOT,
            identity_digest=identity,
            size_bytes=actual.total_bytes,
            manifest=actual,
            owner_automation_id=owner_automation_id,
        )
        existing = self._owned.get(object_id)
        if existing is not None:
            if existing != captured:
                raise ValueError("owned source snapshot identity conflict")
            return existing
        self._admit(captured)
        _, nodes = self._require_source(binding.binding_id)
        self._owned_nodes[object_id] = nodes
        return captured

    def load_source_snapshot(
        self,
        manifest_digest: str,
        *,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1:
        _require_hex64(manifest_digest, "manifest_digest")
        if owner_automation_id is not None:
            _require_opaque(owner_automation_id, "owner_automation_id")
        object_id = _owned_object_id("snapshot", manifest_digest, owner_automation_id)
        source = self._owned.get(object_id)
        if (
            source is None
            or source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT
            or source.manifest is None
            or source.manifest.manifest_digest != manifest_digest
            or source.owner_automation_id != owner_automation_id
        ):
            raise ValueError("owned source snapshot not found")
        return source

    def materialize_occurrence(
        self,
        source: OwnedObjectV1,
        occurrence_id: str,
    ) -> OwnedObjectV1:
        _require_opaque(occurrence_id, "occurrence_id")
        current = self._require_owned(source)
        if current.kind is not OwnedObjectKind.SOURCE_SNAPSHOT:
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
        existing = self._owned.get(workspace.object_id)
        if existing is not None:
            if existing != workspace:
                raise ValueError("occurrence workspace identity conflict")
            return existing
        historical = self._workspace_history.get(workspace.object_id)
        if historical is not None:
            if historical != workspace:
                raise ValueError("occurrence workspace identity conflict")
            raise ValueError("occurrence workspace is already terminal")
        self._admit(workspace)
        self._workspace_history[workspace.object_id] = workspace
        self._owned_nodes[workspace.object_id] = self._owned_nodes[source.object_id]
        self._workspace_sources[workspace.object_id] = source.object_id
        return workspace

    def load_occurrence_workspace(
        self,
        source: OwnedObjectV1,
        occurrence_id: str,
    ) -> OwnedObjectV1:
        current_source = self._require_owned(source)
        if current_source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT:
            raise ValueError("workspace recovery requires a source snapshot")
        _require_opaque(occurrence_id, "occurrence_id")
        digest = canonical_json_digest(
            {
                "source_identity_digest": source.identity_digest,
                "occurrence_id": occurrence_id,
            }
        )
        workspace = self._workspace_history.get(f"workspace:{digest[:54]}")
        if workspace is None or workspace.source_identity_digest != source.identity_digest:
            raise ValueError("occurrence workspace history not found")
        return workspace

    def capture_terminal_outputs(
        self,
        workspace: OwnedObjectV1,
        source: OwnedObjectV1,
        bounds: WorkspaceBoundsV1,
        *,
        artifacts: tuple[TerminalArtifactCandidateV1, ...],
    ) -> TerminalCaptureV1:
        current_source = self._require_owned(source)
        if current_source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT:
            raise ValueError("terminal capture requires a source snapshot")
        existing_capture = self._terminal_captures.get(workspace.object_id)
        if existing_capture is not None:
            if self._workspace_history.get(workspace.object_id) != workspace:
                raise ValueError("terminal workspace identity drift")
            if existing_capture.source_identity_digest != source.identity_digest:
                raise ValueError("terminal source identity drift")
            if self._terminal_candidates.get(workspace.object_id) != artifacts:
                raise ValueError("terminal artifact candidates changed")
            return existing_capture
        current_workspace = self._require_owned(workspace)
        if current_workspace.kind is not OwnedObjectKind.OCCURRENCE_WORKSPACE:
            raise ValueError("terminal capture requires an occurrence workspace")
        if current_source.kind is not OwnedObjectKind.SOURCE_SNAPSHOT:
            raise ValueError("terminal capture requires a source snapshot")
        if self._workspace_sources.get(workspace.object_id) != source.object_id:
            raise ValueError("workspace does not bind the source snapshot")
        workspace_binding = SourceBindingV1(
            binding_id="terminal:workspace",
            root_identity_digest=workspace.identity_digest,
            excluded_components=(),
        )
        result_manifest = _build_manifest(
            workspace_binding,
            self._owned_nodes[workspace.object_id],
            bounds,
        )
        assert source.manifest is not None
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
        if not isinstance(artifacts, tuple) or any(
            not isinstance(item, TerminalArtifactCandidateV1) for item in artifacts
        ):
            raise ValueError("artifacts must be a tuple of candidates")
        artifact_ids = tuple(item.artifact_id for item in artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact ids must be unique")
        artifact_bytes = sum(item.size_bytes for item in artifacts)
        if artifact_bytes > bounds.max_artifact_bytes_per_occurrence:
            raise ValueError("artifact bytes per occurrence exceeded")
        if self._artifact_bytes + artifact_bytes > bounds.max_artifact_bytes_per_automation:
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
        pending = tuple(
            item for item in (diff_object, *artifact_objects) if item is not None
        )
        if any(item.object_id in self._owned for item in pending):
            raise ValueError("terminal owned object id already exists")
        for item in pending:
            self._owned[item.object_id] = item
        self._artifact_bytes += artifact_bytes
        self._terminal_captured.add(workspace.object_id)
        capture = TerminalCaptureV1(
            workspace_identity_digest=workspace.identity_digest,
            source_identity_digest=source.identity_digest,
            diff_entries=diff_entries,
            diff_digest=diff_digest,
            diff_object=diff_object,
            artifacts=artifact_objects,
        )
        self._terminal_captures[workspace.object_id] = capture
        self._terminal_candidates[workspace.object_id] = artifacts
        return capture

    def delete_owned_object(self, expected: OwnedObjectV1) -> CleanupResultV1:
        current = self._owned.get(expected.object_id)
        if current is None and self._workspace_history.get(expected.object_id) == expected:
            outcome = self._cleanup_outcomes.get(expected.object_id)
            if outcome is CleanupOutcome.CLEANED:
                return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANED)
        if current is None or current.identity_digest != expected.identity_digest:
            return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANUP_UNKNOWN)
        if (
            current.kind is OwnedObjectKind.OCCURRENCE_WORKSPACE
            and current.object_id not in self._terminal_captured
        ):
            return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANUP_UNKNOWN)
        if current.kind is OwnedObjectKind.GOVERNED_EXTERNAL_REFERENCE:
            self._owned.pop(current.object_id)
            return CleanupResultV1(expected.object_id, CleanupOutcome.UNLINKED)
        self._owned.pop(current.object_id)
        self._owned_nodes.pop(current.object_id, None)
        self._workspace_sources.pop(current.object_id, None)
        self._terminal_captured.discard(current.object_id)
        if current.kind is OwnedObjectKind.RETAINED_ARTIFACT:
            self._artifact_bytes -= current.size_bytes
        if current.kind is OwnedObjectKind.OCCURRENCE_WORKSPACE:
            self._cleanup_outcomes[current.object_id] = CleanupOutcome.CLEANED
        return CleanupResultV1(expected.object_id, CleanupOutcome.CLEANED)

    def owned_objects(self, automation_id: str) -> tuple[PurgeOwnedObjectV1, ...]:
        _require_opaque(automation_id, "automation_id")
        return tuple(
            sorted(
                (
                    PurgeOwnedObjectV1(
                        object_id=item.object_id,
                        kind=PurgeObjectKind(item.kind.value),
                        identity_digest=item.identity_digest,
                    )
                    for item in self._owned.values()
                    if item.owner_automation_id == automation_id
                ),
                key=lambda item: item.object_id,
            )
        )

    def admit_runtime_checkpoint(
        self,
        *,
        automation_id: str,
        occurrence_id: str,
        identity_digest: str,
    ) -> PurgeOwnedObjectV1:
        _require_opaque(automation_id, "automation_id")
        _require_opaque(occurrence_id, "occurrence_id")
        _require_hex64(identity_digest, "identity_digest")
        object_id = _owned_object_id("checkpoint", occurrence_id, automation_id)
        owned = OwnedObjectV1(
            object_id=object_id,
            kind=OwnedObjectKind.RUNTIME_CHECKPOINT,
            identity_digest=identity_digest,
            size_bytes=0,
            owner_automation_id=automation_id,
        )
        existing = self._owned.get(object_id)
        if existing is not None and existing != owned:
            raise ValueError("runtime checkpoint identity conflict")
        if existing is None:
            self._admit(owned)
        return PurgeOwnedObjectV1(
            object_id=object_id,
            kind=PurgeObjectKind.RUNTIME_CHECKPOINT,
            identity_digest=identity_digest,
        )

    def delete_purge_object(
        self,
        expected: PurgeOwnedObjectV1,
        *,
        allow_missing_after_intent: bool,
    ) -> PurgeCleanupOutcome:
        if not isinstance(expected, PurgeOwnedObjectV1):
            raise TypeError("expected must use PurgeOwnedObjectV1")
        if not isinstance(allow_missing_after_intent, bool):
            raise TypeError("allow_missing_after_intent must be bool")
        current = self._owned.get(expected.object_id)
        expected_outcome = (
            PurgeCleanupOutcome.UNLINKED
            if expected.kind is PurgeObjectKind.GOVERNED_EXTERNAL_REFERENCE
            else PurgeCleanupOutcome.CLEANED
        )
        if current is None:
            return (
                expected_outcome
                if allow_missing_after_intent
                else PurgeCleanupOutcome.CLEANUP_UNKNOWN
            )
        if (
            current.kind.value != expected.kind.value
            or current.identity_digest != expected.identity_digest
        ):
            return PurgeCleanupOutcome.CLEANUP_UNKNOWN
        result = self.delete_owned_object(current)
        return PurgeCleanupOutcome(result.outcome.value)

    def replace_source_identity(self, binding_id: str, identity_digest: str) -> None:
        current, nodes = self._require_source(binding_id)
        self._sources[binding_id] = [
            replace(current, root_identity_digest=identity_digest),
            nodes,
        ]

    def replace_source_nodes(
        self,
        binding_id: str,
        nodes: tuple[VirtualSourceNodeV1, ...],
    ) -> None:
        current, _ = self._require_source(binding_id)
        self._sources[binding_id] = [current, nodes]

    def replace_workspace_nodes(
        self,
        object_id: str,
        nodes: tuple[VirtualSourceNodeV1, ...],
    ) -> None:
        current = self._owned.get(object_id)
        if current is None or current.kind is not OwnedObjectKind.OCCURRENCE_WORKSPACE:
            raise ValueError("occurrence workspace not found")
        self._owned_nodes[object_id] = nodes

    def replace_owned_identity(self, object_id: str, identity_digest: str) -> None:
        current = self._owned.get(object_id)
        if current is None:
            raise ValueError("owned object not found")
        self._owned[object_id] = replace(current, identity_digest=identity_digest)

    def source_for_workspace(self, workspace: OwnedObjectV1) -> OwnedObjectV1:
        self._require_owned(workspace)
        source_id = self._workspace_sources.get(workspace.object_id)
        if source_id is None:
            raise ValueError("workspace source not found")
        return self._owned[source_id]

    def admit_external_reference(
        self,
        *,
        object_id: str,
        identity_digest: str,
        owner_automation_id: str | None = None,
    ) -> OwnedObjectV1:
        reference = OwnedObjectV1(
            object_id=object_id,
            kind=OwnedObjectKind.GOVERNED_EXTERNAL_REFERENCE,
            identity_digest=identity_digest,
            size_bytes=0,
            owner_automation_id=owner_automation_id,
        )
        self._admit(reference)
        return reference

    def contains(self, object_id: str) -> bool:
        return object_id in self._owned

    def _require_source(
        self,
        binding_id: str,
    ) -> tuple[SourceBindingV1, tuple[VirtualSourceNodeV1, ...]]:
        value = self._sources.get(binding_id)
        if value is None:
            raise ValueError("source binding not found")
        binding, nodes = value
        assert isinstance(binding, SourceBindingV1) and isinstance(nodes, tuple)
        return binding, nodes

    def _require_owned(self, expected: OwnedObjectV1) -> OwnedObjectV1:
        current = self._owned.get(expected.object_id)
        if current is None or current != expected:
            raise ValueError("owned object identity mismatch")
        return current

    def _admit(self, item: OwnedObjectV1) -> None:
        if item.object_id in self._owned:
            raise ValueError("owned object id already exists")
        self._owned[item.object_id] = item


def _owned_object_id(prefix: str, identity: str, owner_automation_id: str | None) -> str:
    if owner_automation_id is None:
        return f"{prefix}:{identity[: 63 - len(prefix)]}"
    digest = canonical_json_digest(
        {
            "prefix": prefix,
            "identity": identity,
            "owner_automation_id": owner_automation_id,
        }
    )
    return f"{prefix}:{digest[: 63 - len(prefix)]}"


def _build_manifest(
    binding: SourceBindingV1,
    nodes: tuple[VirtualSourceNodeV1, ...],
    bounds: WorkspaceBoundsV1,
) -> SourceManifestV1:
    if len(nodes) > bounds.max_entries:
        raise ValueError("source entry bound exceeded")
    entries: list[SourceManifestEntryV1] = []
    excluded = set(binding.excluded_components)
    total_bytes = 0
    for node in nodes:
        if not isinstance(node, VirtualSourceNodeV1):
            raise ValueError("source nodes must be virtual source nodes")
        path = _canonical_relative_path(node.relative_path, max_bytes=bounds.max_path_bytes)
        components = path.split("/")
        if any(component in excluded for component in components):
            raise ValueError("source path enters an excluded component")
        if any(
            fnmatchcase(component.casefold(), pattern)
            for component in components
            for pattern in _SENSITIVE_PATTERNS
        ):
            raise ValueError("source path matches a sensitive filename pattern")
        if node.kind not in {VirtualNodeKind.FILE, VirtualNodeKind.DIRECTORY}:
            raise ValueError("source contains an unsupported node kind")
        if node.kind is VirtualNodeKind.FILE and node.size_bytes > bounds.max_file_bytes:
            raise ValueError("source file byte bound exceeded")
        total_bytes += node.size_bytes
        if total_bytes > bounds.max_total_bytes:
            raise ValueError("source total byte bound exceeded")
        entries.append(
            SourceManifestEntryV1(
                relative_path=path,
                kind=node.kind,
                size_bytes=node.size_bytes,
                content_digest=node.content_digest,
            )
        )
    entries.sort(key=lambda entry: entry.relative_path)
    if len({entry.relative_path for entry in entries}) != len(entries):
        raise ValueError("source paths must be unique")
    return SourceManifestV1(
        binding_id=binding.binding_id,
        root_identity_digest=binding.root_identity_digest,
        entries=tuple(entries),
        total_bytes=total_bytes,
    )


def _entry_digest(entry: SourceManifestEntryV1) -> str:
    return canonical_json_digest(entry.identity_values())


def _build_diff(
    source: SourceManifestV1,
    result: SourceManifestV1,
) -> tuple[DiffEntryV1, ...]:
    source_entries = {entry.relative_path: entry for entry in source.entries}
    result_entries = {entry.relative_path: entry for entry in result.entries}
    output: list[DiffEntryV1] = []
    for path in sorted(set(source_entries) | set(result_entries)):
        before = source_entries.get(path)
        after = result_entries.get(path)
        if before is None:
            assert after is not None
            output.append(
                DiffEntryV1(path, DiffEntryKind.ADDED, None, _entry_digest(after))
            )
        elif after is None:
            output.append(
                DiffEntryV1(path, DiffEntryKind.DELETED, _entry_digest(before), None)
            )
        elif before != after:
            output.append(
                DiffEntryV1(
                    path,
                    DiffEntryKind.MODIFIED,
                    _entry_digest(before),
                    _entry_digest(after),
                )
            )
    return tuple(output)
