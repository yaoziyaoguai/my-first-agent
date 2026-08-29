from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path

import pytest

from agent.automation.workspace import (
    SourceBindingV1,
    WorkspaceBoundsV1,
)
from agent.automation_hosts.posix_storage import (
    PosixOwnedWorkspaceRepository,
    PosixWorkspaceCommitUnknownError,
    source_root_identity,
)


def _binding(source) -> SourceBindingV1:
    return SourceBindingV1(
        binding_id="source:workspace",
        root_identity_digest=source_root_identity(source),
        excluded_components=("private", "runtime"),
    )


def test_real_scan_capture_and_occurrence_use_a_fresh_pinned_copy(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    (source / "src").mkdir()
    (source / "src" / "app.py").write_text("before\n", encoding="utf-8")
    binding = _binding(source)
    repository = PosixOwnedWorkspaceRepository(
        tmp_path / "owned",
        {binding: source},
    )

    manifest = repository.scan_source(binding, WorkspaceBoundsV1())
    snapshot = repository.capture_source(
        binding,
        manifest,
        WorkspaceBoundsV1(),
        owner_automation_id="automation:one",
    )
    (source / "src" / "app.py").write_text("host changed\n", encoding="utf-8")
    workspace = repository.materialize_occurrence(snapshot, "occurrence:0000")

    assert repository.load_source_snapshot(
        manifest.manifest_digest,
        owner_automation_id="automation:one",
    ) == snapshot
    assert repository.load_occurrence_workspace(snapshot, "occurrence:0000") == workspace
    assert (repository.resolve_owned_path(workspace) / "src" / "app.py").read_text() == "before\n"
    assert (source / "src" / "app.py").read_text() == "host changed\n"
    assert repository.resolve_owned_path(workspace) != repository.resolve_owned_path(snapshot)


@pytest.mark.parametrize("node_kind", ["symlink", "fifo", "socket", "hardlink"])
def test_scan_rejects_symlink_fifo_and_hardlink_without_partial_capture(
    tmp_path, node_kind: str
) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    target = source / "target.txt"
    target.write_text("secret\n", encoding="utf-8")
    candidate = source / "candidate"
    if node_kind == "symlink":
        candidate.symlink_to(target)
    elif node_kind == "fifo":
        os.mkfifo(candidate)
    elif node_kind == "socket":
        server = socket.socket(socket.AF_UNIX)
        short_root = Path(tempfile.mkdtemp(prefix="mfa-socket-", dir="/tmp"))
        short_socket = short_root / "node"
        try:
            server.bind(str(short_socket))
        except PermissionError:
            server.close()
            short_root.rmdir()
            pytest.skip("test sandbox does not permit AF_UNIX socket creation")
        short_socket.rename(candidate)
        short_root.rmdir()
    else:
        os.link(target, candidate)
    binding = _binding(source)
    repository = PosixOwnedWorkspaceRepository(tmp_path / "owned", {binding: source})

    try:
        with pytest.raises(ValueError):
            repository.scan_source(binding, WorkspaceBoundsV1())
    finally:
        if node_kind == "socket":
            server.close()

    assert repository.owned_objects("automation:one") == ()


def test_owned_root_replacement_fails_closed(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    (source / "app.py").write_text("before\n", encoding="utf-8")
    binding = _binding(source)
    owned_root = tmp_path / "owned"
    repository = PosixOwnedWorkspaceRepository(owned_root, {binding: source})

    replaced = tmp_path / "owned.original"
    owned_root.rename(replaced)
    owned_root.mkdir(mode=0o700)
    for name in ("objects", "metadata", "temporary"):
        (owned_root / name).mkdir(mode=0o700)
    (owned_root / "workspace.lock").write_bytes(b"")
    os.chmod(owned_root / "workspace.lock", 0o600)

    with pytest.raises(ValueError, match="root.*identity"):
        repository.scan_source(binding, WorkspaceBoundsV1())


def test_scan_rejects_sensitive_excluded_and_bounded_inputs(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    (source / "private").mkdir()
    (source / "private" / "note.txt").write_text("x", encoding="utf-8")
    binding = _binding(source)
    repository = PosixOwnedWorkspaceRepository(tmp_path / "owned", {binding: source})
    with pytest.raises(ValueError, match="excluded"):
        repository.scan_source(binding, WorkspaceBoundsV1())

    (source / "private" / "note.txt").unlink()
    (source / "private").rmdir()
    (source / ".env").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="sensitive"):
        repository.scan_source(binding, WorkspaceBoundsV1())

    (source / ".env").unlink()
    (source / "large.bin").write_bytes(b"x" * 11)
    with pytest.raises(ValueError, match="file byte"):
        repository.scan_source(binding, WorkspaceBoundsV1(max_file_bytes=10))


def test_source_root_replacement_and_content_drift_fail_before_capture(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    (source / "app.py").write_text("before\n", encoding="utf-8")
    binding = _binding(source)
    repository = PosixOwnedWorkspaceRepository(tmp_path / "owned", {binding: source})
    manifest = repository.scan_source(binding, WorkspaceBoundsV1())

    (source / "app.py").write_text("after\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest drift"):
        repository.capture_source(
            binding,
            manifest,
            WorkspaceBoundsV1(),
            owner_automation_id="automation:one",
        )
    assert repository.owned_objects("automation:one") == ()

    replaced = tmp_path / "old-source"
    source.rename(replaced)
    source.mkdir(mode=0o700)
    (source / "app.py").write_text("before\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        repository.scan_source(binding, WorkspaceBoundsV1())


def test_post_replace_metadata_failure_is_unknown_and_retry_recovers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    (source / "app.py").write_text("before\n", encoding="utf-8")
    binding = _binding(source)
    repository = PosixOwnedWorkspaceRepository(tmp_path / "owned", {binding: source})
    manifest = repository.scan_source(binding, WorkspaceBoundsV1())

    def fail_metadata_fsync() -> None:
        raise OSError("injected metadata fsync failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(repository, "_fsync_metadata", fail_metadata_fsync)
        with pytest.raises(PosixWorkspaceCommitUnknownError, match="outcome is unknown"):
            repository.capture_source(
                binding,
                manifest,
                WorkspaceBoundsV1(),
                owner_automation_id="automation:one",
            )

    recovered = repository.capture_source(
        binding,
        manifest,
        WorkspaceBoundsV1(),
        owner_automation_id="automation:one",
    )
    assert repository.resolve_owned_path(recovered).is_dir()
