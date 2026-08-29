"""Strict bounded metadata codec for POSIX owned-workspace objects."""

from __future__ import annotations

from agent.automation.workspace import (
    DiffEntryKind,
    DiffEntryV1,
    OwnedObjectKind,
    OwnedObjectV1,
    SourceManifestEntryV1,
    SourceManifestV1,
    TerminalCaptureV1,
    VirtualNodeKind,
)
from agent.automation_hosts._posix_fs import PosixWorkspaceStorageError

METADATA_SCHEMA = 1


class WorkspaceMetadataCodec:
    """Implementation-only codec mixin; it owns no filesystem or lifecycle state."""

    @staticmethod
    def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate metadata field")
            value[key] = item
        return value

    def _encode_meta(self, meta: dict[str, object]) -> dict[str, object]:
        owned = meta["object"]
        assert isinstance(owned, OwnedObjectV1)
        return {
            "schema_version": METADATA_SCHEMA,
            "object": self._encode_owned(owned),
            "relative_storage": meta["relative_storage"],
            "storage_identity_digest": meta["storage_identity_digest"],
            "source_object_id": meta["source_object_id"],
            "cleaned": meta["cleaned"],
            "capture": meta["capture"],
        }

    def _decode_meta(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "object",
            "relative_storage",
            "storage_identity_digest",
            "source_object_id",
            "cleaned",
            "capture",
        }:
            raise PosixWorkspaceStorageError("owned metadata fields are invalid")
        if value["schema_version"] != METADATA_SCHEMA or not isinstance(
            value["cleaned"], bool
        ):
            raise PosixWorkspaceStorageError("owned metadata schema is invalid")
        return {**value, "object": self._decode_owned(value["object"])}

    @staticmethod
    def _encode_owned(owned: OwnedObjectV1) -> dict[str, object]:
        manifest = None
        if owned.manifest is not None:
            manifest = {
                "binding_id": owned.manifest.binding_id,
                "root_identity_digest": owned.manifest.root_identity_digest,
                "entries": [entry.identity_values() for entry in owned.manifest.entries],
                "total_bytes": owned.manifest.total_bytes,
                "manifest_digest": owned.manifest.manifest_digest,
            }
        return {
            "object_id": owned.object_id,
            "kind": owned.kind.value,
            "identity_digest": owned.identity_digest,
            "size_bytes": owned.size_bytes,
            "source_identity_digest": owned.source_identity_digest,
            "manifest": manifest,
            "owner_automation_id": owned.owner_automation_id,
        }

    @staticmethod
    def _decode_owned(value: object) -> OwnedObjectV1:
        if not isinstance(value, dict) or set(value) != {
            "object_id",
            "kind",
            "identity_digest",
            "size_bytes",
            "source_identity_digest",
            "manifest",
            "owner_automation_id",
        }:
            raise PosixWorkspaceStorageError("owned object fields are invalid")
        manifest_value = value["manifest"]
        manifest = None
        if manifest_value is not None:
            if not isinstance(manifest_value, dict) or set(manifest_value) != {
                "binding_id",
                "root_identity_digest",
                "entries",
                "total_bytes",
                "manifest_digest",
            }:
                raise PosixWorkspaceStorageError("source manifest fields are invalid")
            entries_value = manifest_value["entries"]
            if not isinstance(entries_value, list):
                raise PosixWorkspaceStorageError("source manifest entries are invalid")
            entries = tuple(
                SourceManifestEntryV1(
                    relative_path=item["relative_path"],
                    kind=VirtualNodeKind(item["kind"]),
                    size_bytes=item["size_bytes"],
                    content_digest=item["content_digest"],
                )
                for item in entries_value
                if isinstance(item, dict)
                and set(item)
                == {"relative_path", "kind", "size_bytes", "content_digest"}
            )
            if len(entries) != len(entries_value):
                raise PosixWorkspaceStorageError("source manifest entry fields are invalid")
            manifest = SourceManifestV1(
                binding_id=manifest_value["binding_id"],
                root_identity_digest=manifest_value["root_identity_digest"],
                entries=entries,
                total_bytes=manifest_value["total_bytes"],
                manifest_digest=manifest_value["manifest_digest"],
            )
        return OwnedObjectV1(
            object_id=value["object_id"],
            kind=OwnedObjectKind(value["kind"]),
            identity_digest=value["identity_digest"],
            size_bytes=value["size_bytes"],
            source_identity_digest=value["source_identity_digest"],
            manifest=manifest,
            owner_automation_id=value["owner_automation_id"],
        )

    @classmethod
    def _encode_capture(cls, capture: TerminalCaptureV1) -> dict[str, object]:
        return {
            "workspace_identity_digest": capture.workspace_identity_digest,
            "source_identity_digest": capture.source_identity_digest,
            "diff_entries": [entry.identity_values() for entry in capture.diff_entries],
            "diff_digest": capture.diff_digest,
            "diff_object": (
                None
                if capture.diff_object is None
                else cls._encode_owned(capture.diff_object)
            ),
            "artifacts": [cls._encode_owned(item) for item in capture.artifacts],
        }

    @classmethod
    def _decode_capture(cls, value: object) -> TerminalCaptureV1:
        if not isinstance(value, dict) or set(value) != {
            "workspace_identity_digest",
            "source_identity_digest",
            "diff_entries",
            "diff_digest",
            "diff_object",
            "artifacts",
        }:
            raise PosixWorkspaceStorageError("terminal capture fields are invalid")
        diff_values = value["diff_entries"]
        artifact_values = value["artifacts"]
        if not isinstance(diff_values, list) or not isinstance(artifact_values, list):
            raise PosixWorkspaceStorageError("terminal capture lists are invalid")
        diffs = tuple(
            DiffEntryV1(
                relative_path=item["relative_path"],
                kind=DiffEntryKind(item["kind"]),
                source_digest=item["source_digest"],
                result_digest=item["result_digest"],
            )
            for item in diff_values
        )
        diff_object_value = value["diff_object"]
        return TerminalCaptureV1(
            workspace_identity_digest=value["workspace_identity_digest"],
            source_identity_digest=value["source_identity_digest"],
            diff_entries=diffs,
            diff_digest=value["diff_digest"],
            diff_object=(
                None if diff_object_value is None else cls._decode_owned(diff_object_value)
            ),
            artifacts=tuple(cls._decode_owned(item) for item in artifact_values),
        )
