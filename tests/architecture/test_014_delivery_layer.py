"""014 delivery controls 必须闭合 ordinary tree，且不摄入 private/runtime 输入。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.verify_014_materialized_tree import derive_overlay

ROOT = Path(__file__).resolve().parents[2]


def _fixture_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture"], cwd=repo, check=True
    )
    (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored-private.txt\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, baseline


def test_014_delivery_controls_bind_013_parent() -> None:
    verifier = ROOT / "scripts" / "verify_014_materialized_tree.py"
    seal_path = ROOT / "docs" / "implementation" / "014_DELIVERY_SEAL.json"

    assert verifier.is_file()
    assert seal_path.is_file()
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    assert seal["schema"] == "my-first-agent/delivery-overlay-seal/v3"
    assert seal["parent_seal_sha256"]


def test_014_verifier_rejects_generate_mode() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_014_materialized_tree.py"),
            "--generate",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_014_overlay_excludes_private_ignored_and_loop_inputs(tmp_path: Path) -> None:
    repo, baseline = _fixture_repo(tmp_path)
    (repo / "ignored-private.txt").write_text("private\n", encoding="utf-8")
    (repo / ".codex-tmp-014-loop.prompt.md").write_text("loop\n", encoding="utf-8")
    (repo / "tui").mkdir()
    (repo / "tui" / "private.txt").write_text("private\n", encoding="utf-8")
    (repo / "ordinary-note.md").write_text("ordinary\n", encoding="utf-8")

    overlay = derive_overlay(
        {
            "baseline_commit": baseline,
            "entries": [],
            "control_files": [],
        },
        repo,
    )

    assert [entry["path"] for entry in overlay] == ["ordinary-note.md"]


def test_014_base_install_and_operator_docs_are_bounded() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    dependencies = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "httpx" in dependencies
    assert "tavily" not in dependencies.lower()
    assert "browser" not in dependencies.lower()
    assert "first-agent setup-web" in readme
    assert "/sources" in readme
    assert "Search 和 Extract" in readme
    assert "不承诺" in readme and "retention" in readme
