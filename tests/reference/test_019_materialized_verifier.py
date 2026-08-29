"""019 materialized verifier 的 overlay、boundary 与 receipt gates。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import verify_019_materialized_tree as verifier
from tests.reference.test_019_core_e3_harness import make_valid_receipt


def test_019_controls_are_detached_but_runner_is_sealed() -> None:
    if not (verifier.REPO / ".git").exists():
        pytest.skip("source overlay membership requires repository metadata")
    base = json.loads(verifier.BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in verifier.derive_overlay(base)}

    assert "scripts/run_019_core_e3.py" in paths
    assert "scripts/verify_019_materialized_tree.py" not in paths
    assert "docs/acceptance/019_CORE_SEAL.json" not in paths
    assert "docs/acceptance/019_CORE_RECEIPT.json" not in paths
    assert not any(path == "tui" or path.startswith("tui/") for path in paths)


def test_materialized_tree_omits_detached_mutable_019_evidence(tmp_path: Path) -> None:
    if not (verifier.REPO / ".git").exists():
        pytest.skip("source materialization requires repository metadata")
    base = json.loads(verifier.BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = verifier.derive_overlay(base)
    tree = tmp_path / "tree"

    assert verifier.materialize_tree(entries, verifier.REPO, tree) == []
    # 019 overlay 只记录相对 009 candidate 的 delta；materializer 仍必须恢复
    # 未在 delta 中重列、但已由 009 manifest 验收的父阶段文件。
    assert not any(entry["path"] == "agent/tools/edit.py" for entry in entries)
    assert (tree / "agent/tools/edit.py").read_bytes() == (
        verifier.REPO / "agent/tools/edit.py"
    ).read_bytes()
    assert (tree / "scripts/verify_019_materialized_tree.py").is_file()
    assert (tree / "docs/implementation/009_DELIVERY_MANIFEST.json").is_file()
    for relative in verifier.DETACHED_MUTABLE_PATHS:
        assert not (tree / relative).exists(), relative


def test_portable_boundary_rejects_concrete_backend_import_and_token(
    tmp_path: Path,
) -> None:
    package = tmp_path / "agent" / "automation"
    package.mkdir(parents=True)
    module = package / "bad.py"
    module.write_text("import subprocess\n", encoding="utf-8")
    assert any("subprocess" in item for item in verifier.portable_boundary_errors(tmp_path))

    module.write_text("BACKEND = 'launchd'\n", encoding="utf-8")
    assert any("launchd" in item for item in verifier.portable_boundary_errors(tmp_path))


def test_current_portable_boundary_is_green() -> None:
    assert verifier.portable_boundary_errors(verifier.REPO) == []


def test_wheel_artifact_schema_is_exact(tmp_path: Path) -> None:
    path = tmp_path / verifier.WHEEL_ARTIFACT_PATH.relative_to(verifier.REPO)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "wheel_sha256": "a" * 64,
                "materialized_root_sha256": "b" * 64,
                "overlay_root_sha256": "c" * 64,
                "materialized_full_count": 1,
            }
        ),
        encoding="utf-8",
    )
    assert verifier._wheel_identity(tmp_path)["materialized_full_count"] == 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["extra"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="keys must be exact"):
        verifier._wheel_identity(tmp_path)


def test_materialized_pytest_count_ignores_terminal_color_codes() -> None:
    assert verifier._passed_count("\x1b[32m2486 passed\x1b[0m, 8 skipped") == 2486


def test_receipt_identity_mutation_fails_shared_reducer() -> None:
    receipt = make_valid_receipt()
    receipt["wheel_sha256"] = "not-a-digest"
    from scripts.run_019_core_e3 import validate_receipt

    assert any("wheel_sha256" in item for item in validate_receipt(receipt))
