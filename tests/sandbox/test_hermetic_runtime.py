"""hermetic skill-runtime closure 的 fail-closed 合同。"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

import agent.sandbox.hermetic_runtime as hermetic_runtime
import scripts.materialize_020a_test_runtime as materializer
from agent.runtime.contracts import KnownNotExecuted
from agent.sandbox.hermetic_runtime import (
    HermeticRuntimeFileV1,
    prepare_hermetic_skill_process,
    qualify_hermetic_runtime_closure,
)
from scripts.materialize_020a_test_runtime import materialize_test_runtime


def _canonical_digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_file(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


@dataclass(frozen=True, slots=True)
class RuntimeFixture:
    root: Path
    manifest_path: Path

    def copy(self, destination: Path) -> RuntimeFixture:
        shutil.copytree(self.root, destination)
        return RuntimeFixture(destination, destination / "runtime-closure-v1.json")

    def rewrite_manifest_noncanonically(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.manifest_path.chmod(0o644)
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.manifest_path.chmod(0o444)


def _make_runtime(
    root: Path, *, content_overrides: dict[str, bytes] | None = None
) -> RuntimeFixture:
    files = {
        "bin/python": ("interpreter", b"#!/bin/sh\nexit 0\n", 0o555),
        "lib/stdlib/os.py": ("stdlib", b"# synthetic stdlib\n", 0o444),
        "lib/runner/first_agent_skill_runner/__init__.py": ("runner", b"", 0o444),
        "lib/runner/first_agent_skill_runner/__main__.py": (
            "runner",
            b"# synthetic runner\n",
            0o444,
        ),
        "lib/distribution/example.py": ("distribution", b"# bundled dependency\n", 0o444),
    }
    overrides = content_overrides or {}
    effective = {
        relative: (role, overrides.get(relative, content), mode)
        for relative, (role, content, mode) in files.items()
    }
    for relative, (_, content, mode) in effective.items():
        _write_file(root / relative, content, mode)

    inventory = [
        asdict(
            HermeticRuntimeFileV1(
                path=relative,
                role=role,
                mode=mode,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
        for relative, (role, content, mode) in sorted(effective.items())
    ]
    manifest = {
        "schema": "first-agent-skill-runtime-closure/v1",
        "interpreter": "bin/python",
        "stdlib_roots": ["lib/stdlib"],
        "dynload_roots": [],
        "runner_roots": ["lib/runner"],
        "distribution_roots": ["lib/distribution"],
        "inventory_digest": _canonical_digest(inventory),
    }
    _write_file(
        root / "runtime-closure-v1.json",
        json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        0o444,
    )
    return RuntimeFixture(root, root / "runtime-closure-v1.json")


def _protected_roots(tmp_path: Path) -> tuple[Path, ...]:
    roots = tuple(tmp_path / name for name in ("product", "workspace", "state"))
    for root in roots:
        root.mkdir(parents=True)
    return roots


@pytest.fixture
def runtime_fixture(tmp_path: Path) -> RuntimeFixture:
    return _make_runtime(tmp_path / "skill-runtime-v1")


def test_fixed_command_contains_no_session_or_model_supplied_process_fields(
    runtime_fixture: RuntimeFixture, tmp_path: Path
) -> None:
    closure = qualify_hermetic_runtime_closure(runtime_fixture.root)
    assert not isinstance(closure, KnownNotExecuted)
    package_root = tmp_path / "package"
    package_root.mkdir()

    prepared = prepare_hermetic_skill_process(
        closure,
        package_root=package_root,
        package_digest="a" * 64,
        entrypoint_id="inspect",
    )

    assert not isinstance(prepared, KnownNotExecuted)
    assert prepared.command.argv == (
        "-I",
        "-m",
        "first_agent_skill_runner",
        "--package",
        "a" * 64,
        "--entrypoint",
        "inspect",
    )
    assert "fa-structured-" not in repr(prepared.command)
    assert prepared.command.executable_identity is not None
    assert prepared.command.executable_identity.resolved_path == closure.interpreter_path


@pytest.mark.parametrize("mutation", ("symlink", "unknown", "drift"))
def test_closure_rejects_symlink_unknown_file_and_digest_drift(
    runtime_fixture: RuntimeFixture, tmp_path: Path, mutation: str
) -> None:
    mutated = runtime_fixture.copy(tmp_path / f"mutated-{mutation}")
    target = mutated.root / "lib/stdlib/os.py"
    if mutation == "symlink":
        target.unlink()
        target.symlink_to("../runner/first_agent_skill_runner/__init__.py")
    elif mutation == "unknown":
        _write_file(mutated.root / "surprise.py", b"unexpected", 0o444)
    else:
        target.chmod(0o644)
        target.write_bytes(b"drifted")
        target.chmod(0o444)

    outcome = qualify_hermetic_runtime_closure(mutated.root)

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "hermetic_runtime_closure_invalid"


def test_manifest_is_excluded_from_inventory_but_bound_to_closure(
    runtime_fixture: RuntimeFixture,
) -> None:
    closure = qualify_hermetic_runtime_closure(runtime_fixture.root)
    assert not isinstance(closure, KnownNotExecuted)
    assert "runtime-closure-v1.json" not in {item.path for item in closure.inventory}
    assert closure.manifest_digest == hashlib.sha256(
        runtime_fixture.manifest_path.read_bytes()
    ).hexdigest()

    runtime_fixture.rewrite_manifest_noncanonically()

    assert isinstance(
        qualify_hermetic_runtime_closure(runtime_fixture.root), KnownNotExecuted
    )


def test_materializer_requires_explicit_qualified_source_and_requalifies_copy(
    runtime_fixture: RuntimeFixture, tmp_path: Path
) -> None:
    destination = tmp_path / "materialized-runtime"

    copied = materialize_test_runtime(
        runtime_fixture.root,
        destination,
        protected_roots=_protected_roots(tmp_path),
    )

    assert copied == qualify_hermetic_runtime_closure(destination)
    assert copied.runtime_root == str(destination.resolve())
    with pytest.raises(ValueError, match="qualified source"):
        materialize_test_runtime(
            tmp_path / "ordinary-venv",
            tmp_path / "rejected",
            protected_roots=_protected_roots(tmp_path / "rejected-roots"),
        )


def test_materializer_rejects_overlapping_destination(
    runtime_fixture: RuntimeFixture, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="overlap"):
        materialize_test_runtime(
            runtime_fixture.root,
            runtime_fixture.root / "copy",
            protected_roots=_protected_roots(tmp_path),
        )


def test_closure_rejects_declared_root_missing_from_pinned_runtime_tree(
    runtime_fixture: RuntimeFixture,
) -> None:
    manifest = json.loads(runtime_fixture.manifest_path.read_text(encoding="utf-8"))
    manifest["dynload_roots"] = ["lib/dynload"]
    runtime_fixture.manifest_path.chmod(0o600)
    runtime_fixture.manifest_path.write_bytes(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    runtime_fixture.manifest_path.chmod(0o444)

    outcome = qualify_hermetic_runtime_closure(runtime_fixture.root)

    assert isinstance(outcome, KnownNotExecuted)


def test_closure_rejects_directory_replacement_after_entries_are_scanned(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runtime_fixture.root / "lib/stdlib"
    original_identity = original.stat()
    replacement = tmp_path / "replacement"
    _write_file(replacement / "os.py", b"# synthetic stdlib\n", 0o444)
    _write_file(replacement / "evil.py", b"not inventoried\n", 0o444)
    real_scandir = hermetic_runtime.os.scandir
    swapped = False

    def swap_after_scan(fd: int):
        nonlocal swapped
        entries = list(real_scandir(fd))
        current = os.fstat(fd)
        if not swapped and (current.st_dev, current.st_ino) == (
            original_identity.st_dev,
            original_identity.st_ino,
        ):
            original.rename(tmp_path / "pinned-original")
            replacement.rename(original)
            swapped = True
        return entries

    monkeypatch.setattr(hermetic_runtime.os, "scandir", swap_after_scan)

    outcome = qualify_hermetic_runtime_closure(runtime_fixture.root)

    assert swapped
    assert isinstance(outcome, KnownNotExecuted)


@pytest.mark.parametrize("through_intermediate", (False, True))
def test_materializer_rejects_source_symlink_before_writing_destination(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    through_intermediate: bool,
) -> None:
    if through_intermediate:
        source_parent = tmp_path / "source-parent"
        runtime_fixture.copy(source_parent / "runtime")
        source_link = tmp_path / "source-link"
        source_link.symlink_to(source_parent, target_is_directory=True)
        source = source_link / "runtime"
    else:
        source = tmp_path / "source-link"
        source.symlink_to(runtime_fixture.root, target_is_directory=True)
    destination = tmp_path / "destination"

    with pytest.raises(ValueError):
        materialize_test_runtime(
            source,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert not destination.exists()


def test_materializer_rejects_destination_parent_symlink_before_external_write(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    destination_parent = tmp_path / "destination-parent"
    destination_parent.symlink_to(outside, target_is_directory=True)
    destination = destination_parent / "runtime"

    with pytest.raises(ValueError):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert not (outside / "runtime").exists()


def test_materializer_rejects_destination_inside_explicit_protected_root(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
) -> None:
    protected = tmp_path / "workspace"
    protected.mkdir()
    destination = protected / "runtime"

    with pytest.raises(ValueError, match="protected"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=(protected,),
        )

    assert not destination.exists()


def test_materializer_rejects_source_inside_explicit_protected_root(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "destination"

    with pytest.raises(ValueError, match="protected"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=(runtime_fixture.root,),
        )

    assert not destination.exists()


def test_materializer_requires_non_empty_explicit_protected_roots(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "destination"

    with pytest.raises(ValueError, match="protected roots"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=(),
        )

    assert not destination.exists()


@pytest.mark.parametrize(
    ("component", "create"),
    [("existing", False), ("missing", True)],
)
def test_open_relative_parent_closes_child_fd_when_first_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
    create: bool,
) -> None:
    root = tmp_path / "root"
    (root / "existing").mkdir(parents=True)
    before = len(os.listdir("/dev/fd"))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    child_fds: set[int] = set()
    real_open = os.open
    real_fstat = os.fstat

    def record_component_open(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if os.fspath(path) == component and flags & os.O_DIRECTORY:
            child_fds.add(fd)
        return fd

    def fail_fstat_once_for_child(fd: int) -> os.stat_result:
        if fd in child_fds:
            child_fds.clear()
            raise OSError(errno.EIO, "forced child fstat failure")
        return real_fstat(fd)

    monkeypatch.setattr(hermetic_runtime.os, "open", record_component_open)
    monkeypatch.setattr(hermetic_runtime.os, "fstat", fail_fstat_once_for_child)

    try:
        with pytest.raises(OSError, match="forced child fstat failure"):
            hermetic_runtime._open_relative_parent(root_fd, (component,), create=create)
    finally:
        os.close(root_fd)

    if create:
        assert (root / component).is_dir()
    assert len(os.listdir("/dev/fd")) == before


def test_close_pinned_continues_after_first_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = len(os.listdir("/dev/fd"))
    directories = []
    for index in range(3):
        path = tmp_path / f"pinned-{index}"
        path.mkdir()
        directories.append(materializer._pin_absolute_directory(path, label="test"))
    real_close = os.close
    fired = False

    def close_first_call_with_error(fd: int) -> None:
        nonlocal fired
        if not fired:
            fired = True
            real_close(fd)
            raise OSError(errno.EIO, "forced first close failure")
        real_close(fd)

    monkeypatch.setattr(materializer.os, "close", close_first_call_with_error)

    with pytest.raises(OSError, match="forced first close failure"):
        materializer._close_pinned(tuple(directories))

    assert len(os.listdir("/dev/fd")) == before


def test_materializer_final_cleanup_closes_every_descriptor_despite_destination_close_failure(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    before = len(os.listdir("/dev/fd"))
    destination_fds: set[int] = set()
    real_open = os.open
    real_close = os.close

    def record_destination_open(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if (
            os.fspath(path) == destination.name
            and flags & os.O_DIRECTORY
            and flags & os.O_NOFOLLOW
        ):
            destination_fds.add(fd)
        return fd

    def close_destination_once_with_error(fd: int) -> None:
        if fd in destination_fds:
            destination_fds.clear()
            real_close(fd)
            raise OSError(errno.EIO, "forced destination close failure")
        real_close(fd)

    monkeypatch.setattr(materializer.os, "open", record_destination_open)
    monkeypatch.setattr(materializer.os, "close", close_destination_once_with_error)

    with pytest.raises(OSError, match="forced destination close failure"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert len(os.listdir("/dev/fd")) == before


def test_materializer_admission_failure_closes_every_pinned_descriptor_despite_close_error(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    protected_roots = _protected_roots(tmp_path)
    workspace = protected_roots[1]
    workspace.rmdir()
    workspace.symlink_to(runtime_fixture.root, target_is_directory=True)
    before = len(os.listdir("/dev/fd"))
    real_pin = materializer._pin_absolute_directory
    real_close = os.close
    pinned_fds: set[int] = set()
    fired = False

    def record_pin_result(path: object, **kwargs: object) -> object:
        pinned = real_pin(path, **kwargs)
        pinned_fds.add(pinned.fd)
        return pinned

    def close_first_pinned_once_with_error(fd: int) -> None:
        nonlocal fired
        if fd in pinned_fds and not fired:
            fired = True
            real_close(fd)
            raise OSError(errno.EIO, "forced first close failure")
        real_close(fd)

    monkeypatch.setattr(materializer, "_pin_absolute_directory", record_pin_result)
    monkeypatch.setattr(materializer.os, "close", close_first_pinned_once_with_error)

    with pytest.raises(OSError, match="forced first close failure"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=protected_roots,
        )

    assert not destination.exists()
    assert len(os.listdir("/dev/fd")) == before


def test_pin_absolute_directory_closes_child_when_old_fd_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_fds: set[int] = set()
    real_open = os.open
    real_close = os.close
    before = len(os.listdir("/dev/fd"))

    def record_root_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if os.fspath(path) == "/" and flags & os.O_DIRECTORY:
            root_fds.add(fd)
        return fd

    def close_root_once_with_error(fd: int) -> None:
        if fd in root_fds:
            root_fds.clear()
            real_close(fd)
            raise OSError(errno.EIO, "forced ancestor close failure")
        real_close(fd)

    monkeypatch.setattr(materializer.os, "open", record_root_open)
    monkeypatch.setattr(materializer.os, "close", close_root_once_with_error)

    with pytest.raises(OSError, match="forced ancestor close failure"):
        materializer._pin_absolute_directory(tmp_path, label="test root")

    assert len(os.listdir("/dev/fd")) == before


def test_read_relative_file_closes_file_fd_when_parent_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "runtime-root"
    root.mkdir()
    (root / "leaf.bin").write_bytes(b"payload")
    before = len(os.listdir("/dev/fd"))
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    parent_fds: set[int] = set()
    real_dup = os.dup
    real_close = os.close

    def record_root_dup(fd: int) -> int:
        new_fd = real_dup(fd)
        if fd == root_fd:
            parent_fds.add(new_fd)
        return new_fd

    def close_parent_once_with_error(fd: int) -> None:
        if fd in parent_fds:
            parent_fds.clear()
            real_close(fd)
            raise OSError(errno.EIO, "forced parent close failure")
        real_close(fd)

    monkeypatch.setattr(hermetic_runtime.os, "dup", record_root_dup)
    monkeypatch.setattr(hermetic_runtime.os, "close", close_parent_once_with_error)

    try:
        with pytest.raises(OSError, match="forced parent close failure"):
            hermetic_runtime._read_relative_file(
                root_fd, "leaf.bin", cap=64 * 1024
            )
    finally:
        os.close(root_fd)

    assert len(os.listdir("/dev/fd")) == before


def test_materializer_closes_pinned_directories_when_destination_basename_is_invalid(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
) -> None:
    destination_parent = tmp_path / "destination-parent"
    destination_parent.mkdir()
    before = len(os.listdir("/dev/fd"))

    with pytest.raises(ValueError, match="single directory"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination_parent / "..",
            protected_roots=_protected_roots(tmp_path),
        )

    assert len(os.listdir("/dev/fd")) == before


def test_materializer_leaves_partial_destination_after_source_drift(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    source_file = runtime_fixture.root / "lib/stdlib/os.py"
    create_destination = materializer._create_destination

    def create_then_drift(parent_fd: int, name: str) -> int:
        destination_fd = create_destination(parent_fd, name)
        source_file.chmod(0o600)
        source_file.write_bytes(b"drifted after qualification")
        source_file.chmod(0o444)
        return destination_fd

    monkeypatch.setattr(materializer, "_create_destination", create_then_drift)

    with pytest.raises(ValueError, match="drifted"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert (destination / "bin/python").is_file()
    assert not (destination / "lib/stdlib/os.py").exists()


def test_materializer_rejects_and_preserves_destination_path_replacement(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    replacement = _make_runtime(
        tmp_path / "replacement",
        content_overrides={"lib/stdlib/os.py": b"# synthetic stdlib replacement\n"},
    )
    assert not isinstance(qualify_hermetic_runtime_closure(runtime_fixture.root), KnownNotExecuted)
    assert not isinstance(qualify_hermetic_runtime_closure(replacement.root), KnownNotExecuted)
    real_copy = materializer._copy_exact_file

    def swap_destination_path_after_manifest_copy(*args: object, **kwargs: object) -> None:
        real_copy(*args, **kwargs)
        if kwargs.get("path") == hermetic_runtime._MANIFEST_NAME:
            os.rename(destination, tmp_path / "moved-pinned-destination")
            os.rename(replacement.root, destination)

    monkeypatch.setattr(
        materializer, "_copy_exact_file", swap_destination_path_after_manifest_copy
    )

    with pytest.raises(ValueError, match="joined"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert (destination / "lib/stdlib/os.py").read_bytes() == b"# synthetic stdlib replacement\n"
    assert (tmp_path / "moved-pinned-destination").is_dir()


def test_materializer_leaves_partial_destination_after_final_requalification_failure(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"

    def fail_final_requalification(root_fd: int, runtime_root: Path) -> object:
        del root_fd, runtime_root
        raise OSError("forced final requalification failure")

    monkeypatch.setattr(
        materializer, "_qualify_pinned_runtime_closure", fail_final_requalification
    )

    with pytest.raises(ValueError, match="did not requalify"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert (destination / "bin/python").is_file()
    assert (destination / "runtime-closure-v1.json").is_file()


def test_materializer_leaves_created_destination_and_closes_fds_when_pin_open_fails(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    real_open = os.open
    before = len(os.listdir("/dev/fd"))

    def refuse_destination_pin_open(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        if (
            os.fspath(path) == destination.name
            and flags & os.O_DIRECTORY
            and flags & os.O_NOFOLLOW
        ):
            raise OSError(errno.ENOTDIR, "forced destination pin open failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(materializer.os, "open", refuse_destination_pin_open)

    with pytest.raises(OSError, match="forced destination pin open failure"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert destination.is_dir()
    assert len(os.listdir("/dev/fd")) == before


def test_materializer_rejects_destination_replacement_between_capture_and_first_pin(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    external = tmp_path / "external-replacement"
    external.mkdir()
    (external / "marker").write_bytes(b"external marker")
    before = len(os.listdir("/dev/fd"))
    real_open = os.open

    def swap_destination_then_open(
        path: object, flags: int, *args: object, **kwargs: object
    ) -> int:
        if (
            os.fspath(path) == destination.name
            and flags & os.O_DIRECTORY
            and flags & os.O_NOFOLLOW
        ):
            os.rename(destination, tmp_path / "moved-created")
            os.rename(external, destination)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(materializer.os, "open", swap_destination_then_open)

    with pytest.raises(ValueError, match="replaced before first pin"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert sorted(entry.name for entry in destination.iterdir()) == ["marker"]
    assert (destination / "marker").read_bytes() == b"external marker"
    assert (tmp_path / "moved-created").is_dir()
    assert len(os.listdir("/dev/fd")) == before


def test_materializer_rejects_protected_root_moved_onto_destination_before_first_pin(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    protected_roots = _protected_roots(tmp_path)
    workspace = protected_roots[1]
    marker = workspace / "marker"
    marker.write_bytes(b"protected marker")
    before = len(os.listdir("/dev/fd"))
    real_mkdir = os.mkdir

    def move_protected_root_after_mkdir(
        path: object, mode: int, *args: object, **kwargs: object
    ) -> None:
        real_mkdir(path, mode, *args, **kwargs)
        if os.fspath(path) == destination.name:
            os.rmdir(destination)
            os.rename(workspace, destination)

    monkeypatch.setattr(materializer.os, "mkdir", move_protected_root_after_mkdir)

    with pytest.raises(ValueError, match="aliases"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=protected_roots,
        )

    assert sorted(entry.name for entry in destination.iterdir()) == ["marker"]
    assert (destination / "marker").read_bytes() == b"protected marker"
    assert len(os.listdir("/dev/fd")) == before


def test_materializer_rejects_destination_replacement_after_pinned_qualification(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    replacement = _make_runtime(
        tmp_path / "replacement",
        content_overrides={"lib/stdlib/os.py": b"# synthetic stdlib replacement\n"},
    )
    real_seam = materializer._qualify_pinned_runtime_closure

    def qualify_then_replace(root_fd: int, runtime_root: Path) -> object:
        closure = real_seam(root_fd, runtime_root)
        # 同 UID actor 可自行放宽 0o555 后迁移目录（Darwin rename 需要目录写权限来更新 ..）。
        os.chmod(destination, 0o700)
        os.rename(destination, tmp_path / "moved-pinned")
        os.rename(replacement.root, destination)
        return closure

    monkeypatch.setattr(
        materializer, "_qualify_pinned_runtime_closure", qualify_then_replace
    )

    with pytest.raises(ValueError, match="joined"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert (destination / "lib/stdlib/os.py").read_bytes() == b"# synthetic stdlib replacement\n"
    assert (tmp_path / "moved-pinned/runtime-closure-v1.json").is_file()


def test_materializer_closes_destination_fd_when_first_pin_fstat_fails(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    before = len(os.listdir("/dev/fd"))
    destination_fd: list[int] = []
    real_open = os.open
    real_fstat = os.fstat

    def record_destination_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if (
            os.fspath(path) == destination.name
            and flags & os.O_DIRECTORY
            and flags & os.O_NOFOLLOW
        ):
            destination_fd.append(fd)
        return fd

    def fail_fstat_once_for_destination(fd: int) -> os.stat_result:
        if destination_fd and fd == destination_fd[0]:
            destination_fd.clear()
            raise OSError(errno.EIO, "forced destination fstat failure")
        return real_fstat(fd)

    monkeypatch.setattr(materializer.os, "open", record_destination_open)
    monkeypatch.setattr(materializer.os, "fstat", fail_fstat_once_for_destination)

    with pytest.raises(OSError, match="forced destination fstat failure"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert destination.is_dir()
    assert len(os.listdir("/dev/fd")) == before


def test_materializer_preserves_external_replacement_after_copy_failure(
    runtime_fixture: RuntimeFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "preserve-me"
    marker.write_bytes(b"external target")

    def replace_destination_then_fail(*_args: object, **_kwargs: object) -> None:
        os.rmdir(destination)
        destination.symlink_to(external, target_is_directory=True)
        raise ValueError("forced copy failure")

    monkeypatch.setattr(materializer, "_copy_exact_file", replace_destination_then_fail)

    with pytest.raises(ValueError, match="forced copy failure"):
        materialize_test_runtime(
            runtime_fixture.root,
            destination,
            protected_roots=_protected_roots(tmp_path),
        )

    assert destination.is_symlink()
    assert marker.read_bytes() == b"external target"
