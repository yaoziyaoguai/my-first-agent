"""015 U5：bounded POSIX process lifecycle（KTD6/KTD9）。

runner 只消费已准备好的 immutable spawn request，shell=False、closed stdin、no TTY、
new process group、bounded drain、TERM→KILL→reap，返回 closed ``ProcessExecutionDraftV1``。
下列 Red 在 runner 落地前因模块缺失而准确失败（guarded import → ``pytest.fail``）。
"""

from __future__ import annotations

import pytest

try:
    from agent.process.contracts import (
        ProcessDraftOutcome,
        ProcessExecutionDraftV1,
        ResourceProfile,
        ResourceProfileV1,
    )
    from agent.process.runner import run_local_process

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _require_runner():
    if not _AVAILABLE:
        pytest.fail("015 requires agent.process runner")


def test_runner_fast_exit_before_pgid_probe_is_exited(monkeypatch, tmp_path):
    """负载实测 race（E3 content 门 j1 flake）：超快进程（cat/echo）在 Popen 与
    pgid probe 之间已退出 → getpgid ESRCH。已退出的 leader 无可治理 group——仍须诚实
    drain pipes + reap + 分类为 EXITED，不得 ProcessCleanupError → unknown → MARK_FAILED。
    """

    _require_runner()
    import os as _os

    def _esrched(pid):
        raise ProcessLookupError(_os.strerror(3))

    monkeypatch.setattr("agent.process.runner.os.getpgid", _esrched)
    draft = run_local_process(
        resolved_executable="/bin/echo",
        argv=["probe-fast-exit"],
        cwd=str(tmp_path),
        profile=_fast_profile(),
        environment={},
    )
    assert draft.outcome is ProcessDraftOutcome.EXITED
    assert draft.exit_code == 0
    assert "probe-fast-exit" in draft.stdout_projection


def test_runner_pgid_probe_denied_still_fail_closed(monkeypatch, tmp_path):
    """EPERM（无法确认 group identity）必须保持 fail-closed ProcessCleanupError。"""

    _require_runner()
    import os as _os

    def _eperm(pid):
        raise PermissionError(_os.strerror(1))

    monkeypatch.setattr("agent.process.runner.os.getpgid", _eperm)
    with pytest.raises(Exception) as excinfo:  # noqa: B017, PT011 - closed failure
        run_local_process(
            resolved_executable="/bin/echo",
            argv=["x"],
            cwd=str(tmp_path),
            profile=_fast_profile(),
            environment={},
        )
    assert "cannot verify process group identity" in str(excinfo.value)


def _fast_profile(*, deadline: int = 2, cap: int = 4096) -> ResourceProfileV1:
    """测试用 profile：可控 deadline/cap，绕过固定 10s/256KiB 以加速与触发 truncation。"""

    return ResourceProfileV1(
        profile=ResourceProfile.SHORT,
        wall_deadline_seconds=deadline,
        term_grace_seconds=1,
        kill_grace_seconds=1,
        stdout_cap_bytes=cap,
        stderr_cap_bytes=cap,
        combined_cap_bytes=cap * 2,
        rendered_chars=cap,
        argv_max_items=128,
        argv_item_max_bytes=16 * 1024,
        argv_total_max_bytes=64 * 1024,
        executable_hash_max_bytes=256 * 1024 * 1024,
    )


def test_015_runner_exit_zero_classifies_exited(tmp_path) -> None:  # noqa: ANN001
    _require_runner()
    draft = run_local_process(
        resolved_executable="/bin/echo",
        argv=("hello-015",),
        cwd=str(tmp_path),
        profile=_fast_profile(),
        environment={},
    )
    assert isinstance(draft, ProcessExecutionDraftV1)
    assert draft.outcome is ProcessDraftOutcome.EXITED
    assert draft.exit_code == 0
    assert draft.group_reaped is True
    assert "hello-015" in draft.stdout_projection


def test_015_runner_nonzero_exit_classifies_exited(tmp_path) -> None:  # noqa: ANN001
    _require_runner()
    draft = run_local_process(
        resolved_executable="/bin/sh",
        argv=("-c", "exit 3"),
        cwd=str(tmp_path),
        profile=_fast_profile(),
        environment={},
    )
    assert draft.outcome is ProcessDraftOutcome.EXITED
    assert draft.exit_code == 3


def test_015_runner_passes_argv_literally_without_shell_parsing(tmp_path) -> None:  # noqa: ANN001
    """R4 / AE2：shell=False。argv 中的 ; | > $() 作为 literal bytes，不触发第二条命令。"""

    _require_runner()
    draft = run_local_process(
        resolved_executable="/bin/echo",
        argv=("a;b", "|c", "$d", "`e`", "f>g"),
        cwd=str(tmp_path),
        profile=_fast_profile(),
        environment={},
    )
    assert draft.outcome is ProcessDraftOutcome.EXITED
    projection = draft.stdout_projection
    for token in ("a;b", "|c", "$d", "`e`", "f>g"):
        assert token in projection


def test_015_runner_timeout_terminates_process_group(tmp_path) -> None:  # noqa: ANN001
    """R15 / F5 / AE8：超 deadline 后 TERM→KILL→reap，outcome=timed_out_reaped，无残留进程。"""

    _require_runner()
    draft = run_local_process(
        resolved_executable="/bin/sh",
        argv=("-c", "sleep 30"),
        cwd=str(tmp_path),
        profile=_fast_profile(deadline=1, cap=4096),
        environment={},
    )
    assert draft.outcome is ProcessDraftOutcome.TIMED_OUT_REAPED
    assert draft.group_reaped is True
    assert draft.term_sent is True


def test_015_runner_caps_output_and_marks_truncation(tmp_path) -> None:  # noqa: ANN001
    """R15 / AE8：stdout 超 cap 后 bounded，标记 truncated，内存不爆。"""

    _require_runner()
    draft = run_local_process(
        resolved_executable="/bin/sh",
        argv=("-c", "yes capped-015 || true"),
        cwd=str(tmp_path),
        profile=_fast_profile(deadline=3, cap=256),
        environment={},
    )
    # yes 持续输出直到 timeout 或 cap；stdout 被截断标记。
    assert draft.stdout_truncated is True
    assert draft.stdout_bytes <= 256


def test_015_runner_handles_invalid_utf8_without_crash(tmp_path) -> None:  # noqa: ANN001
    """R15 / §9.2：invalid UTF-8 用 deterministic replacement，不让 control char 进 projection。"""

    _require_runner()
    draft = run_local_process(
        resolved_executable="/bin/sh",
        argv=("-c", "printf '\\xff\\xfe\\x00bad'"),
        cwd=str(tmp_path),
        profile=_fast_profile(),
        environment={},
    )
    assert draft.outcome is ProcessDraftOutcome.EXITED
    # projection 必须是合法 str（deterministic replacement），不抛 UnicodeDecodeError。
    assert isinstance(draft.stdout_projection, str)
