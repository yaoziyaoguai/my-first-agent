from __future__ import annotations

from dataclasses import replace

import pytest

from agent.automation.workspace import (
    DeterministicOwnedWorkspaceRepository,
    SourceBindingV1,
    SourceManifestEntryV1,
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


def _file(path: str, *, size: int = 10, digest: str = "2" * 64) -> VirtualSourceNodeV1:
    return VirtualSourceNodeV1(
        relative_path=path,
        kind=VirtualNodeKind.FILE,
        size_bytes=size,
        content_digest=digest,
    )


def _repository(*nodes: VirtualSourceNodeV1) -> DeterministicOwnedWorkspaceRepository:
    return DeterministicOwnedWorkspaceRepository({_binding(): tuple(nodes)})


def test_scan_and_capture_bind_the_same_complete_manifest() -> None:
    repository = _repository(
        VirtualSourceNodeV1(
            relative_path="src",
            kind=VirtualNodeKind.DIRECTORY,
            size_bytes=0,
            content_digest=None,
        ),
        _file("src/app.py"),
    )

    preview = repository.scan_source(_binding(), WorkspaceBoundsV1())
    captured = repository.capture_source(_binding(), preview, WorkspaceBoundsV1())

    assert captured.manifest == preview
    assert captured.identity_digest
    assert repository.owned_object_count == 1


@pytest.mark.parametrize(
    "nodes",
    [
        tuple(_file(f"src/f{index:04d}.py") for index in range(4_097)),
        (_file("large.bin", size=16 * 1024 * 1024 + 1),),
        (_file("a.bin", size=64 * 1024 * 1024 + 1),),
        (_file("a" * 1_025),),
        (
            VirtualSourceNodeV1(
                relative_path="linked",
                kind=VirtualNodeKind.SYMLINK,
                size_bytes=0,
                content_digest=None,
            ),
        ),
        (
            VirtualSourceNodeV1(
                relative_path="device",
                kind=VirtualNodeKind.UNSUPPORTED,
                size_bytes=0,
                content_digest=None,
            ),
        ),
        (_file("private/report.txt"),),
        (_file("src/.env.production"),),
        (_file("keys/service.pem"),),
    ],
)
def test_scan_rejects_bounds_unsupported_nodes_and_private_names(
    nodes: tuple[VirtualSourceNodeV1, ...],
) -> None:
    repository = _repository(*nodes)

    with pytest.raises(ValueError):
        repository.scan_source(_binding(), WorkspaceBoundsV1())

    assert repository.owned_object_count == 0


def test_capture_rejects_root_identity_replacement_without_partial_object() -> None:
    repository = _repository(_file("src/app.py"))
    preview = repository.scan_source(_binding(), WorkspaceBoundsV1())
    repository.replace_source_identity(_binding().binding_id, "3" * 64)

    with pytest.raises(ValueError, match="root identity"):
        repository.capture_source(_binding(), preview, WorkspaceBoundsV1())

    assert repository.owned_object_count == 0


def test_capture_rejects_content_drift_without_partial_object() -> None:
    repository = _repository(_file("src/app.py"))
    preview = repository.scan_source(_binding(), WorkspaceBoundsV1())
    repository.replace_source_nodes(
        _binding().binding_id,
        (replace(_file("src/app.py"), content_digest="4" * 64),),
    )

    with pytest.raises(ValueError, match="manifest drift"):
        repository.capture_source(_binding(), preview, WorkspaceBoundsV1())

    assert repository.owned_object_count == 0


def test_manifest_entry_rejects_noncanonical_path_and_missing_file_digest() -> None:
    with pytest.raises(ValueError, match="dot components"):
        SourceManifestEntryV1(
            relative_path="../outside",
            kind=VirtualNodeKind.FILE,
            size_bytes=1,
            content_digest="2" * 64,
        )
    with pytest.raises(ValueError, match="content_digest"):
        SourceManifestEntryV1(
            relative_path="inside.txt",
            kind=VirtualNodeKind.FILE,
            size_bytes=1,
            content_digest=None,
        )
