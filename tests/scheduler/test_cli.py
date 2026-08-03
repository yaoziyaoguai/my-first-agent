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


def _real_provider_argv(tmp_path: Path, *, strict: bool) -> list[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    state_root = tmp_path / "state-root"
    state_root.mkdir(mode=0o700, exist_ok=True)
    argv = [
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
        "--schedule-id",
        "strict-schedule",
        "--occurrence-id",
        "2026-08-03T00:00:00Z",
        "--scheduled-for",
        "2026-08-03T00:00:00Z",
        "--message",
        "answer briefly without tools",
        "--provider",
        "openai_compatible",
        "--model",
        "fixture-model",
        "--base-url",
        "https://provider.invalid",
        "--credential-env",
        "FIXTURE_PROVIDER_KEY",
        "--thinking-mode",
        "disabled",
        "--request-path",
        "/chat/completions",
    ]
    if strict:
        argv.append("--strict-tools")
    return argv


def _run_schedule_capturing_composition(
    tmp_path: Path, monkeypatch, *, strict: bool
) -> tuple[int, list[str], dict]:
    # remote provider 的新 occurrence 在首次外发前停在 disclosure(needs_human,零发送),
    # 因此在该停点前捕获 composition 实参即可离线锁定 strict 组合合同。
    monkeypatch.setenv("FIXTURE_PROVIDER_KEY", "fixture-secret")
    captured: dict = {}
    real_build = entrypoint.build_composition

    def capture(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return real_build(**kwargs)

    monkeypatch.setattr(entrypoint, "build_composition", capture)
    output: list[str] = []
    code = entrypoint.run_schedule(
        _real_provider_argv(tmp_path, strict=strict), write_fn=output.append
    )
    return code, output, captured


def test_schedule_strict_tools_composes_strict_control_schema(
    tmp_path: Path, monkeypatch
) -> None:
    # F2 回归:schedule 入口启用 --strict-tools 时,composition 也必须请求
    # strict control schema,否则 strict wire 在首次组包即 missing_strict_control_schema。
    code, output, captured = _run_schedule_capturing_composition(
        tmp_path, monkeypatch, strict=True
    )

    assert code == 2, output
    assert '"run_status": "awaiting_disclosure"' in output[-1]
    assert captured.get("strict_control_schema") is True


def test_schedule_without_strict_tools_keeps_portable_control_schema(
    tmp_path: Path, monkeypatch
) -> None:
    code, output, captured = _run_schedule_capturing_composition(
        tmp_path, monkeypatch, strict=False
    )

    assert code == 2, output
    assert '"run_status": "awaiting_disclosure"' in output[-1]
    assert captured.get("strict_control_schema", False) is False


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
