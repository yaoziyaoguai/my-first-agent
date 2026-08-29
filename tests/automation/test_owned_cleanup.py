from __future__ import annotations

from agent.automation.workspace import (
    CleanupOutcome,
    DeterministicOwnedWorkspaceRepository,
    OwnedObjectKind,
    SourceBindingV1,
    VirtualNodeKind,
    VirtualSourceNodeV1,
    WorkspaceBoundsV1,
)


def _repository_and_workspace():
    binding = SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest="1" * 64,
        excluded_components=(),
    )
    repository = DeterministicOwnedWorkspaceRepository(
        {
            binding: (
                VirtualSourceNodeV1(
                    relative_path="report.md",
                    kind=VirtualNodeKind.FILE,
                    size_bytes=10,
                    content_digest="2" * 64,
                ),
            )
        }
    )
    manifest = repository.scan_source(binding, WorkspaceBoundsV1())
    source = repository.capture_source(binding, manifest, WorkspaceBoundsV1())
    workspace = repository.materialize_occurrence(source, "occurrence:0000")
    return repository, workspace


def test_exact_owned_identity_is_deleted_only_after_terminal_capture() -> None:
    repository, workspace = _repository_and_workspace()
    source = repository.source_for_workspace(workspace)
    repository.capture_terminal_outputs(
        workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(),
    )

    result = repository.delete_owned_object(workspace)

    assert result.outcome is CleanupOutcome.CLEANED
    assert repository.contains(workspace.object_id) is False


def test_identity_replacement_is_cleanup_unknown_and_preserves_ownership() -> None:
    repository, workspace = _repository_and_workspace()
    repository.replace_owned_identity(workspace.object_id, "3" * 64)

    result = repository.delete_owned_object(workspace)

    assert result.outcome is CleanupOutcome.CLEANUP_UNKNOWN
    assert repository.contains(workspace.object_id) is True


def test_governed_external_reference_is_unlinked_never_deleted() -> None:
    repository, _ = _repository_and_workspace()
    reference = repository.admit_external_reference(
        object_id="external:artifact",
        identity_digest="4" * 64,
    )

    result = repository.delete_owned_object(reference)

    assert reference.kind is OwnedObjectKind.GOVERNED_EXTERNAL_REFERENCE
    assert result.outcome is CleanupOutcome.UNLINKED
    assert repository.external_delete_count == 0
