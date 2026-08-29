from __future__ import annotations

import pytest

from agent.automation.workspace import (
    DeterministicOwnedWorkspaceRepository,
    SourceBindingV1,
    TerminalArtifactCandidateV1,
    VirtualNodeKind,
    VirtualSourceNodeV1,
    WorkspaceBoundsV1,
)


def _binding() -> SourceBindingV1:
    return SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest="1" * 64,
        excluded_components=("private", "runtime"),
    )


def _node(path: str, digest: str) -> VirtualSourceNodeV1:
    return VirtualSourceNodeV1(
        relative_path=path,
        kind=VirtualNodeKind.FILE,
        size_bytes=10,
        content_digest=digest * 64,
    )


def _materialized() -> tuple[DeterministicOwnedWorkspaceRepository, object, object]:
    repository = DeterministicOwnedWorkspaceRepository(
        {_binding(): (_node("report.md", "2"), _node("old.txt", "3"))}
    )
    manifest = repository.scan_source(_binding(), WorkspaceBoundsV1())
    source = repository.capture_source(_binding(), manifest, WorkspaceBoundsV1())
    workspace = repository.materialize_occurrence(source, "occurrence:0000")
    return repository, source, workspace


def test_materialization_is_a_fresh_owned_copy_bound_to_the_source() -> None:
    repository, source, workspace = _materialized()

    assert workspace.source_identity_digest == source.identity_digest
    assert workspace.identity_digest != source.identity_digest
    assert repository.owned_object_count == 2


def test_terminal_capture_produces_sorted_bounded_diff_and_owned_artifacts() -> None:
    repository, source, workspace = _materialized()
    repository.replace_workspace_nodes(
        workspace.object_id,
        (_node("new.txt", "4"), _node("report.md", "5")),
    )

    result = repository.capture_terminal_outputs(
        workspace,
        source,
        WorkspaceBoundsV1(),
        artifacts=(
            TerminalArtifactCandidateV1(
                artifact_id="artifact:report",
                size_bytes=1_024,
                content_digest="6" * 64,
            ),
        ),
    )

    assert tuple(entry.relative_path for entry in result.diff_entries) == (
        "new.txt",
        "old.txt",
        "report.md",
    )
    assert result.diff_digest
    assert result.artifacts[0].object_id == "artifact:report"


def test_diff_entry_bound_fails_before_terminal_capture_is_admitted() -> None:
    repository, source, workspace = _materialized()
    repository.replace_workspace_nodes(
        workspace.object_id,
        tuple(_node(f"generated/{index:04d}.txt", "4") for index in range(2_001)),
    )

    with pytest.raises(ValueError, match="diff entry"):
        repository.capture_terminal_outputs(
            workspace,
            source,
            WorkspaceBoundsV1(),
            artifacts=(),
        )

    assert repository.owned_object_count == 2


def test_artifact_bounds_fail_before_any_artifact_is_admitted() -> None:
    repository, source, workspace = _materialized()

    with pytest.raises(ValueError, match="artifact bytes"):
        repository.capture_terminal_outputs(
            workspace,
            source,
            WorkspaceBoundsV1(),
            artifacts=(
                TerminalArtifactCandidateV1(
                    artifact_id="artifact:oversized",
                    size_bytes=32 * 1024 * 1024 + 1,
                    content_digest="6" * 64,
                ),
            ),
        )

    assert repository.owned_object_count == 2


def test_duplicate_artifact_ids_fail_before_any_terminal_object_is_admitted() -> None:
    repository, source, workspace = _materialized()
    before = repository.owned_object_count
    artifact = TerminalArtifactCandidateV1(
        artifact_id="artifact:duplicate",
        size_bytes=1,
        content_digest="6" * 64,
    )

    with pytest.raises(ValueError, match="artifact id"):
        repository.capture_terminal_outputs(
            workspace,
            source,
            WorkspaceBoundsV1(),
            artifacts=(artifact, artifact),
        )

    assert repository.owned_object_count == before
