from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import main as entrypoint


def _argv(
    tmp_path: Path,
    *,
    message: str = "nightly check",
    occurrence: str = "2026-07-19T00:00:00Z",
) -> list[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    state_root = tmp_path / "state-root"
    state_root.mkdir(mode=0o700, exist_ok=True)
    return [
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
        "--schedule-id",
        "nightly",
        "--occurrence-id",
        occurrence,
        "--scheduled-for",
        "2026-07-19T00:00:00Z",
        "--message",
        message,
        "--provider",
        "fake",
    ]


def test_first_schedule_run_completes(tmp_path: Path) -> None:
    output: list[str] = []
    code = entrypoint.run_schedule(_argv(tmp_path), write_fn=output.append)
    assert code == 0
    report = json.loads(output[-1])
    assert report["occurrence_status"] == "completed"
    assert report["run_status"] == "completed"


def test_duplicate_schedule_run_replays_and_does_not_duplicate(tmp_path: Path) -> None:
    first: list[str] = []
    second: list[str] = []
    assert entrypoint.run_schedule(_argv(tmp_path), write_fn=first.append) == 0
    assert entrypoint.run_schedule(_argv(tmp_path), write_fn=second.append) == 0
    report = json.loads(second[-1])
    assert report["replayed"] is True


def test_overlapping_state_root_fails_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    output: list[str] = []
    code = entrypoint.run_schedule(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(workspace),
            "--schedule-id",
            "x",
            "--occurrence-id",
            "2026-07-19T00:00:00Z",
            "--scheduled-for",
            "2026-07-19T00:00:00Z",
            "--message",
            "overlap",
            "--provider",
            "fake",
        ],
        write_fn=output.append,
    )
    assert code == 2
    assert output[0].startswith("Schedule failed")


def test_scheduler_startup_failure_after_closeable_construction_reverse_closes_once(
    tmp_path: Path, monkeypatch
) -> None:
    """R20: scheduler 与 main 共用 close-stack owner；composition 构造后 startup 失败
    也要逆序关闭一次。"""
    import dataclasses

    closes: list[int] = []

    def fake_close() -> None:
        closes.append(1)

    real_build = entrypoint.build_composition

    def patched(*args, **kwargs):
        composition = real_build(*args, **kwargs)
        return dataclasses.replace(composition, close_stack=(fake_close, *composition.close_stack))

    monkeypatch.setattr(entrypoint, "build_composition", patched)

    def boom(self):
        raise ValueError("scheduler startup failure after closeable construction")

    monkeypatch.setattr(entrypoint.ScheduledOccurrenceCaller, "run_once", boom)

    output: list[str] = []
    code = entrypoint.run_schedule(_argv(tmp_path), write_fn=output.append)
    assert code == 2
    assert closes == [1], f"closeable must be closed exactly once, got {closes}"


# --- scheduler state-root usability: it must be as usable as `--state` ---
# `--state` auto-creates a locked 0700 parent dir on first use; the scheduler
# state-root must do the same so the documented invocation works without a
# manual `mkdir -m 700`, while still refusing a pre-existing non-private dir.


def _bare_argv(workspace: Path, state_root: Path) -> list[str]:
    return [
        "--workspace", str(workspace),
        "--state-root", str(state_root),
        "--schedule-id", "nightly",
        "--occurrence-id", "2026-07-19T00:00:00Z",
        "--scheduled-for", "2026-07-19T00:00:00Z",
        "--message", "nightly check",
        "--provider", "fake",
    ]


def test_absent_state_root_is_created_locked_and_used(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"  # intentionally NOT pre-created

    output: list[str] = []
    code = entrypoint.run_schedule(_bare_argv(workspace, state_root), write_fn=output.append)

    assert code == 0, output
    report = json.loads(output[-1])
    assert report["occurrence_status"] == "completed"
    # state-root is auto-created as a real, owner-only 0700 directory.
    info = os.stat(state_root)
    assert stat.S_ISDIR(info.st_mode)
    assert info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o700


def test_existing_world_readable_state_root_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    state_root.mkdir(mode=0o755)  # default permissive dir — operator forgot the -m 700

    output: list[str] = []
    code = entrypoint.run_schedule(_bare_argv(workspace, state_root), write_fn=output.append)

    assert code == 2
    assert output[0].startswith("Schedule failed: CheckpointSecurityError")


def test_absent_state_root_inside_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # A state-root that does not yet exist but is lexically inside the workspace
    # must still be rejected (the overlap guard cannot be bypassed by pointing
    # at a non-existent path).
    state_root = workspace / "leaked"

    output: list[str] = []
    code = entrypoint.run_schedule(_bare_argv(workspace, state_root), write_fn=output.append)

    assert code == 2
    assert output[0].startswith("Schedule failed: ValueError")
    assert not state_root.exists(), "overlap guard must reject before creating anything"
