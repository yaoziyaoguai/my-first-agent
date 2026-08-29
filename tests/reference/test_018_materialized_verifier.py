"""018 materialized verifier 的 control/overlay/receipt 边界。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import run_018_e3 as runner
from scripts import verify_018_materialized_tree as verifier
from tests.reference.test_018_e3_harness import make_valid_receipt


def test_018_controls_are_detached_but_runner_and_fixture_are_sealed() -> None:
    if not (verifier.REPO / ".git").exists():
        pytest.skip("source overlay membership requires repository metadata")
    base = json.loads(verifier.BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in verifier.derive_overlay(base)}

    assert "scripts/run_018_e3.py" in paths
    assert "scripts/browser_e3_fixture.py" in paths
    assert "scripts/browser_e3_journeys.py" in paths
    assert "scripts/verify_018_materialized_tree.py" not in paths
    assert "docs/implementation/018_DELIVERY_SEAL.json" not in paths
    assert "docs/implementation/018_E3_RECEIPT.json" not in paths
    assert not any(path == "tui" or path.startswith("tui/") for path in paths)
    assert not any(path == "build" or path.startswith("build/") for path in paths)


def test_materialized_tree_omits_detached_mutable_018_evidence(tmp_path: Path) -> None:
    if not (verifier.REPO / ".git").exists():
        pytest.skip("source materialization requires repository metadata")
    base = json.loads(verifier.BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = verifier.derive_overlay(base)

    tree = tmp_path / "tree"
    errors = verifier.materialize_tree(entries, verifier.REPO, tree)
    if errors and all(
        "update-index failed" in error and "Operation not permitted" in error
        for error in errors
    ):
        pytest.skip("verification host exposes the repository object store read-only")
    assert errors == []
    for relative in verifier.DETACHED_MUTABLE_PATHS:
        assert not (tree / relative).exists(), relative


def test_verifier_uses_runner_reducer_without_importing_tests() -> None:
    source = verifier.VERIFIER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name == "tests" or name.startswith("tests.") for name in imports)
    assert runner.validate_receipt(make_valid_receipt()) == []


def test_wheel_artifact_schema_is_exact(tmp_path: Path) -> None:
    path = tmp_path / verifier.WHEEL_ARTIFACT_PATH.relative_to(verifier.REPO)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "wheel_sha256": "a" * 64,
                "materialized_root_sha256": "b" * 64,
                "overlay_root_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    assert verifier._wheel_identity(tmp_path)["wheel_sha256"] == "a" * 64

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["extra"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="keys must be exact"):
        verifier._wheel_identity(tmp_path)


def test_receipt_identity_mutation_fails_shared_reducer() -> None:
    receipt = make_valid_receipt()
    receipt["wheel_sha256"] = "not-a-digest"
    assert any("wheel_sha256" in error for error in runner.validate_receipt(receipt))
