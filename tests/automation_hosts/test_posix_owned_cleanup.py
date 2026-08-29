from __future__ import annotations

import hashlib

import pytest

from agent.automation.contracts import PurgeCleanupOutcome
from agent.automation.workspace import (
    CleanupOutcome,
    SourceBindingV1,
    TerminalArtifactCandidateV1,
    WorkspaceBoundsV1,
)
from agent.automation_hosts.posix_storage import (
    PosixOwnedWorkspaceRepository,
    PosixWorkspaceCommitUnknownError,
    source_root_identity,
)


def _materialized(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir(mode=0o700)
    (source_root / "report.md").write_text("before\n", encoding="utf-8")
    binding = SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest=source_root_identity(source_root),
        excluded_components=(),
    )
    repository = PosixOwnedWorkspaceRepository(tmp_path / "owned", {binding: source_root})
    manifest = repository.scan_source(binding, WorkspaceBoundsV1())
    source = repository.capture_source(
        binding,
        manifest,
        WorkspaceBoundsV1(),
        owner_automation_id="automation:one",
    )
    workspace = repository.materialize_occurrence(source, "occurrence:0000")
    return repository, source_root, source, workspace


def test_terminal_capture_persists_diff_and_artifact_before_safe_cleanup(tmp_path) -> None:
    repository, source_root, source, workspace = _materialized(tmp_path)
    workspace_root = repository.resolve_owned_path(workspace)
    (workspace_root / "report.md").write_text("after\n", encoding="utf-8")
    artifact_root = workspace_root / ".automation-artifacts"
    artifact_root.mkdir(mode=0o700)
    artifact = artifact_root / "artifact:report"
    artifact.write_bytes(b"bounded artifact")
    candidate = TerminalArtifactCandidateV1(
        artifact_id="artifact:report",
        size_bytes=artifact.stat().st_size,
        content_digest=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )

    capture = repository.capture_terminal_outputs(
        workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(candidate,),
    )
    result = repository.delete_owned_object(workspace)

    assert capture.diff_object is not None
    assert capture.artifacts[0].size_bytes == len(b"bounded artifact")
    assert result.outcome is CleanupOutcome.CLEANED
    assert not workspace_root.exists()
    assert (source_root / "report.md").read_text() == "before\n"
    assert {item.kind.value for item in repository.owned_objects("automation:one")} >= {
        "source_snapshot",
        "retained_diff",
        "retained_artifact",
    }


@pytest.mark.parametrize("node_kind", ["symlink", "hardlink"])
def test_terminal_artifact_cannot_escape_owned_staging(tmp_path, node_kind: str) -> None:
    repository, _source_root, source, workspace = _materialized(tmp_path)
    workspace_root = repository.resolve_owned_path(workspace)
    artifact_root = workspace_root / ".automation-artifacts"
    artifact_root.mkdir(mode=0o700)
    external = tmp_path / "outside-artifact"
    external.write_bytes(b"must not be retained")
    candidate_path = artifact_root / "artifact:escape"
    if node_kind == "symlink":
        candidate_path.symlink_to(external)
    else:
        candidate_path.hardlink_to(external)
    candidate = TerminalArtifactCandidateV1(
        artifact_id="artifact:escape",
        size_bytes=external.stat().st_size,
        content_digest=hashlib.sha256(external.read_bytes()).hexdigest(),
    )

    with pytest.raises(ValueError):
        repository.capture_terminal_outputs(
            workspace,
            source,
            WorkspaceBoundsV1(),
            artifacts=(candidate,),
        )

    assert not any(
        item.kind.value == "retained_artifact"
        for item in repository.owned_objects("automation:one")
    )


def test_workspace_cannot_be_deleted_before_terminal_capture(tmp_path) -> None:
    repository, _source_root, _source, workspace = _materialized(tmp_path)

    result = repository.delete_owned_object(workspace)

    assert result.outcome is CleanupOutcome.CLEANUP_UNKNOWN
    assert repository.resolve_owned_path(workspace).exists()


def test_replaced_owned_directory_is_cleanup_unknown_and_not_followed(tmp_path) -> None:
    repository, _source_root, source, workspace = _materialized(tmp_path)
    workspace_root = repository.resolve_owned_path(workspace)
    repository.capture_terminal_outputs(
        workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(),
    )
    original = workspace_root.with_name(workspace_root.name + ".replaced")
    workspace_root.rename(original)
    workspace_root.mkdir(mode=0o700)
    marker = workspace_root / "must-survive"
    marker.write_text("replacement", encoding="utf-8")

    result = repository.delete_owned_object(workspace)

    assert result.outcome is CleanupOutcome.CLEANUP_UNKNOWN
    assert marker.read_text() == "replacement"


def test_workspace_swap_after_validation_is_not_deleted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _source_root, source, workspace = _materialized(tmp_path)
    workspace_root = repository.resolve_owned_path(workspace)
    repository.capture_terminal_outputs(
        workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(),
    )
    original_validate = repository._validate_storage
    original = workspace_root.with_name(workspace_root.name + ".original")
    marker = workspace_root / "must-survive"
    swapped = False

    def validate_then_swap(meta) -> None:  # noqa: ANN001
        nonlocal swapped
        original_validate(meta)
        if not swapped and meta["object"] == workspace:
            workspace_root.rename(original)
            workspace_root.mkdir(mode=0o700)
            marker.write_text("replacement", encoding="utf-8")
            swapped = True

    monkeypatch.setattr(repository, "_validate_storage", validate_then_swap)

    result = repository.delete_owned_object(workspace)

    assert result.outcome is CleanupOutcome.CLEANUP_UNKNOWN
    assert marker.read_text(encoding="utf-8") == "replacement"
    assert workspace.object_id in {
        item.object_id for item in repository.owned_objects("automation:one")
    }


def test_terminal_capture_unknown_commit_is_retryable_without_orphans(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _source_root, source, workspace = _materialized(tmp_path)
    workspace_root = repository.resolve_owned_path(workspace)
    (workspace_root / "report.md").write_text("after\n", encoding="utf-8")

    def fail_metadata_fsync() -> None:
        raise OSError("injected metadata fsync failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(repository, "_fsync_metadata", fail_metadata_fsync)
        with pytest.raises(PosixWorkspaceCommitUnknownError, match="outcome is unknown"):
            repository.capture_terminal_outputs(
                workspace,
                source,
                WorkspaceBoundsV1(),
                artifacts=(),
            )

    capture = repository.capture_terminal_outputs(
        workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(),
    )
    assert capture.diff_object is not None
    assert repository.contains(capture.diff_object.object_id)


def test_external_reference_is_unlinked_and_checkpoint_cleanup_is_idempotent(tmp_path) -> None:
    repository, _source_root, _source, _workspace = _materialized(tmp_path)
    external = repository.admit_external_reference(
        object_id="external:artifact",
        identity_digest="4" * 64,
        owner_automation_id="automation:one",
    )
    checkpoint = repository.admit_runtime_checkpoint(
        automation_id="automation:one",
        occurrence_id="occurrence:0000",
        identity_digest="5" * 64,
    )

    assert repository.delete_owned_object(external).outcome is CleanupOutcome.UNLINKED
    assert (
        repository.delete_purge_object(checkpoint, allow_missing_after_intent=False)
        is PurgeCleanupOutcome.CLEANED
    )
    assert (
        repository.delete_purge_object(checkpoint, allow_missing_after_intent=True)
        is PurgeCleanupOutcome.CLEANED
    )
