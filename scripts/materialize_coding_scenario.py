"""Copy one frozen fixture into a new candidate workspace without its grader."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-09-13-coding-autonomy-repair"
    / "TASK-MANIFEST.json"
)


def _prepare_d03_worktree(target: Path) -> None:
    commands = (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Dogfood Fixture"),
        ("git", "config", "user.email", "fixture@example.invalid"),
        ("git", "add", "."),
        ("git", "commit", "-qm", "fixture baseline"),
    )
    for command in commands:
        subprocess.run(command, cwd=target, check=True, capture_output=True)
    (target / "USER_NOTES.md").write_text(
        "User note baseline.\nKeep this user draft intact.\n",
        encoding="utf-8",
    )
    (target / "scratch.txt").write_text(
        "untracked user scratch\n",
        encoding="utf-8",
    )


def _prepare_d05_large_tree(target: Path) -> None:
    generated = target / "docs" / "generated"
    generated.mkdir(parents=True)
    for index in range(225):
        (generated / f"reference-{index:03d}.txt").write_text(
            f"Unrelated generated reference {index}.\n",
            encoding="utf-8",
        )


def materialize(scenario_id: str, destination: Path) -> dict[str, str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scenario = next(
        (
            item
            for item in manifest["scenarios"]
            if item.get("id") == scenario_id and isinstance(item.get("fixture"), str)
        ),
        None,
    )
    if scenario is None:
        raise ValueError(f"scenario is not materialized: {scenario_id}")
    source = ROOT / scenario["fixture"]
    target = Path(destination).absolute()
    if target.exists():
        raise FileExistsError("candidate destination must not already exist")
    shutil.copytree(source, target)
    if scenario_id == "D03":
        _prepare_d03_worktree(target)
    if scenario_id == "D05":
        _prepare_d05_large_tree(target)
    return {
        "scenario_id": scenario_id,
        "candidate": str(target),
        "task": scenario["task"],
        "grader_command": (
            f"{ROOT / '.venv/bin/python'} "
            f"{ROOT / 'scripts/grade_coding_scenario.py'} {scenario_id} {target}"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_id")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        result = materialize(args.scenario_id, args.destination)
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
