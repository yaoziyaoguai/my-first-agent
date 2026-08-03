"""013 delivery controls 必须可执行，且继承已冻结的 012 control。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.verify_013_materialized_tree import derive_overlay

ROOT = Path(__file__).resolve().parents[2]


def test_013_delivery_controls_are_materialized_and_bind_012() -> None:
    verifier = ROOT / "scripts" / "verify_013_materialized_tree.py"
    seal_path = ROOT / "docs" / "implementation" / "013_DELIVERY_SEAL.json"

    assert verifier.is_file()
    assert seal_path.is_file()
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    assert seal["parent_seal_sha256"]


def test_013_verifier_rejects_generate_mode() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_013_materialized_tree.py"),
            "--generate",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_013_overlay_includes_tracked_file_added_after_009_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    baseline_file = repo / "baseline.txt"
    baseline_file.write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    added = repo / "tracked-after-baseline.py"
    added.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", added.name], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add tracked file"], cwd=repo, check=True)

    overlay = derive_overlay(
        {
            "baseline_commit": baseline,
            "entries": [],
            "control_files": [],
        },
        repo,
    )

    assert [entry["path"] for entry in overlay] == [added.name]
    assert overlay[0]["operation"] == "add"


def test_013_overlay_denies_repo_root_loop_temp_files(tmp_path: Path) -> None:
    """Loop 约定的仓库根临时文件(.codex-tmp-*)必须在读取/hash 前被拒绝,
    且拒绝规则保持窄范围:普通未跟踪用户文件仍照常进入 overlay。"""

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    (repo / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "baseline.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    baseline = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    loop_temp = repo / ".codex-tmp-013-fresh-review.prompt.md"
    loop_temp.write_text("ephemeral loop prompt\n", encoding="utf-8")
    # 读权限被拿掉:一旦 overlay 试图读取/hash 该文件,derive 会直接 PermissionError。
    loop_temp.chmod(0o000)
    ordinary = repo / "ordinary-note.md"
    ordinary.write_text("a normal untracked user file\n", encoding="utf-8")

    try:
        overlay = derive_overlay(
            {
                "baseline_commit": baseline,
                "entries": [],
                "control_files": [],
            },
            repo,
        )
    finally:
        loop_temp.chmod(0o600)

    assert [entry["path"] for entry in overlay] == [ordinary.name]
