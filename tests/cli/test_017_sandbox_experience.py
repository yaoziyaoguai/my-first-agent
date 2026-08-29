"""017 native sandbox 的 everyday UX。

启动一条 bounded 状态行（ready/unavailable/unsupported，无 traceback、
无 backend digest、无原始路径）；无 setup-sandbox/image digest/profile
持久化；restart 投影只保留 native execution_unknown（Docker 的
bundle_review/base_drift 已删除，不做 compatibility 映射）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import main as entrypoint
from agent.composition import SandboxReadiness
from agent.continuity.restart import SANDBOX_RECOVERY_KINDS


def _resources(readiness: SandboxReadiness, reason: str | None = None):
    return SimpleNamespace(readiness=readiness, reason_code=reason)


def test_ready_line_is_one_bounded_actionable_line():
    lines = entrypoint._sandbox_status_lines(
        _resources(SandboxReadiness.READY),
    )
    assert lines == [
        "Sandbox: ready (macOS Seatbelt; workspace-write, network off)",
    ]


def test_unavailable_lines_give_reason_without_traceback_or_digest():
    expectations = {
        "functional_probe_failed": "sandbox-exec functional probe failed",
        "sandbox_exec_missing": "sandbox-exec not found on this machine",
        "seatbelt_profile_refused": "sandbox-exec refused the probe profile",
    }
    for reason, text in expectations.items():
        lines = entrypoint._sandbox_status_lines(
            _resources(SandboxReadiness.TEMPORARILY_UNAVAILABLE, reason),
        )
        assert len(lines) == 1
        assert lines[0].startswith("Sandbox: unavailable ")
        assert text in lines[0]
        assert "confined commands will not run" in lines[0]
        # bounded：不出现 traceback/digest/原始绝对路径
        assert "Traceback" not in lines[0]
        assert "sha256" not in lines[0]
        assert "/usr/bin/" not in lines[0]


def test_unsupported_platform_line_is_closed():
    lines = entrypoint._sandbox_status_lines(
        _resources(SandboxReadiness.UNSUPPORTED),
    )
    assert lines == [
        "Sandbox: unsupported on this platform; confined commands will not run",
    ]


def test_setup_sandbox_subcommand_is_removed():
    parser = entrypoint.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["setup-sandbox"])


def test_main_no_longer_persists_docker_sandbox_profile():
    source = __import__("pathlib").Path(entrypoint.__file__).read_text(
        encoding="utf-8",
    )
    assert "load_sandbox_profile" not in source
    assert "save_sandbox_profile" not in source
    assert "FIRST_AGENT_017_E3_IMAGE_DIGEST" not in source


def test_recovery_kinds_are_native_only():
    assert frozenset({"execution_unknown"}) == SANDBOX_RECOVERY_KINDS


def test_docker_recovery_kinds_are_gone_not_remapped():
    import agent.continuity.restart as restart

    assert not hasattr(restart, "_BASE_DRIFT_CODES")
    assert restart.sandbox_recovery_kind.__doc__ is not None
    assert "bundle" not in restart.sandbox_recovery_kind.__doc__
