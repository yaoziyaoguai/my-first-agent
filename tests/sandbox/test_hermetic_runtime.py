"""hermetic skill-runtime closure 的 fail-closed 合同。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

import agent.sandbox.hermetic_runtime as hermetic_runtime
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


def _make_runtime(root: Path) -> RuntimeFixture:
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
    for relative, (_, content, mode) in files.items():
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
        for relative, (role, content, mode) in sorted(files.items())
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
