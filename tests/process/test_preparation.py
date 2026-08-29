"""017 Task 3：exact process preparation 共享 seam 的 characterization 与合同。

Part A（characterization，抽取前必须 Green）：local_process 的 executable
identity、cwd descriptor、argv/profile 上限、PATH 清洗、封闭 env 隔离、
approval→spawn 漂移拒绝与 preview——保护抽取不改变行为。
Part B（seam 合同，Red→Green）：``prepare_process``/``revalidate_process``/
``closed_process_environment`` 公共接口。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agent.process.tools import build_local_process_registration


def _registration(tmp_path: Path, captured_path: str = "/usr/bin:/bin"):
    return build_local_process_registration(
        workspace=tmp_path,
        captured_path=captured_path,
    )


def _binding(registration, arguments: dict) -> dict:
    return registration.spec, registration.prepare_binding(arguments)


# --------------------------------------------------------------------------- #
# Part A：characterization（抽取前 Green）
# --------------------------------------------------------------------------- #


def test_prepare_binding_binds_identity_cwd_and_profile(tmp_path):
    registration = _registration(tmp_path)
    _spec, binding = _binding(
        registration,
        {"executable": "/usr/bin/true", "argv": ["--help"], "cwd": "."},
    )
    assert binding["resolved_executable_path"] == "/usr/bin/true"
    assert binding["executable_digest"]
    assert binding["command_fingerprint"]
    assert binding["cwd_descriptor"]
    assert binding["resource_profile"] == "standard"
    assert binding["trust_notice_digest"]


def test_argument_limits_and_cwd_rules_fail_closed(tmp_path):
    registration = _registration(tmp_path)
    with pytest.raises(ValueError, match="argv"):
        registration.prepare_binding(
            {"executable": "/usr/bin/true", "argv": ["x" * 20_001]},
        )
    with pytest.raises(ValueError, match="workspace-relative"):
        registration.prepare_binding({"executable": "/usr/bin/true", "cwd": "/abs"})
    with pytest.raises(ValueError, match="workspace-relative"):
        registration.prepare_binding({"executable": "/usr/bin/true", "cwd": "../up"})
    with pytest.raises(ValueError, match="profile"):
        registration.prepare_binding(
            {"executable": "/usr/bin/true", "profile": "epic"},
        )


def test_captured_path_is_sanitized_to_absolute_dirs(tmp_path):
    registration = _registration(
        tmp_path, captured_path="relative:/usr/bin:/bin:/usr/bin",
    )
    _spec, binding = _binding(registration, {"executable": "true"})
    # 相对/重复项被清洗，token 仍可在剩余 search path 中解析
    assert binding["resolved_executable_path"] == "/usr/bin/true"


def test_executor_uses_isolated_closed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FA_TEST_SECRET_ENV", "leak-me")
    registration = _registration(tmp_path)
    spec = registration.spec
    _spec, binding = _binding(
        registration, {"executable": "/usr/bin/printenv"},
    )

    class _Intent:
        arguments = {"executable": "/usr/bin/printenv"}
        safety_binding = binding

    result = spec  # keep linters calm about unused spec
    draft = registration.func(_Intent())
    assert draft.outcome.value == "exited"
    output = draft.stdout_projection
    assert "FA_TEST_SECRET_ENV" not in output
    for key in ("HOME=", "TMPDIR=", "PATH=", "LANG=", "LC_CTYPE=", "TZ="):
        assert key in output, key
    assert "HOME=/Users/" not in output
    del result


def test_executable_identity_drift_after_approval_fails_closed(tmp_path):
    target = tmp_path / "tool.sh"
    shutil.copy("/bin/sh", target)
    target.chmod(0o755)
    registration = _registration(tmp_path)
    _spec, binding = _binding(
        registration, {"executable": str(target), "argv": ["-c", "true"]},
    )
    # approval 后改写同一 path 的内容 → identity digest 漂移
    target.write_bytes(b"#!/bin/sh\nexit 0\n")
    target.chmod(0o755)

    class _Intent:
        arguments = {"executable": str(target), "argv": ["-c", "true"]}
        safety_binding = binding

    from agent.runtime.contracts import KnownNotExecuted

    outcome = registration.func(_Intent())
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "executable_identity_changed"


def test_cwd_replacement_after_approval_fails_closed(tmp_path):
    workdir = tmp_path / "sub"
    workdir.mkdir()
    registration = _registration(tmp_path)
    _spec, binding = _binding(
        registration, {"executable": "/usr/bin/true", "cwd": "sub"},
    )
    shutil.rmtree(workdir)
    workdir.mkdir()

    class _Intent:
        arguments = {"executable": "/usr/bin/true", "cwd": "sub"}
        safety_binding = binding

    from agent.runtime.contracts import KnownNotExecuted

    outcome = registration.func(_Intent())
    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "cwd_identity_changed"


def test_preview_is_closed_and_literal(tmp_path):
    registration = _registration(tmp_path)
    _spec, binding = _binding(
        registration,
        {"executable": "/usr/bin/true", "argv": ["a b", '"q"'], "cwd": "."},
    )
    preview = binding["effect_preview"]
    assert "environment: closed allowlist" in preview
    assert '"a b"' in preview and '"\\"q\\""' in preview
    assert "same-UID" in preview or "trust" in preview.lower()


# --------------------------------------------------------------------------- #
# Part B：共享 seam 合同（Red → Green）
# --------------------------------------------------------------------------- #


def test_prepare_process_returns_command_and_cwd(tmp_path):
    from agent.process.preparation import prepare_process

    prepared = prepare_process(
        {"executable": "/usr/bin/true", "argv": ["--help"], "cwd": "."},
        workspace=tmp_path,
        captured_path="/usr/bin:/bin",
    )
    assert prepared.command.executable_identity is not None
    assert prepared.command.executable_identity.resolved_path == "/usr/bin/true"
    assert prepared.cwd_path == str(tmp_path)
    assert prepared.child_path == "/usr/bin:/bin"
    assert prepared.command.command_fingerprint


def test_prepare_process_returns_known_not_executed_for_bad_executable(tmp_path):
    from agent.process.preparation import prepare_process
    from agent.runtime.contracts import KnownNotExecuted

    outcome = prepare_process(
        {"executable": "/definitely/not/here", "cwd": "."},
        workspace=tmp_path,
        captured_path="/usr/bin:/bin",
    )
    assert isinstance(outcome, KnownNotExecuted)


def test_revalidate_process_detects_identity_and_cwd_drift(tmp_path):
    from agent.process.preparation import prepare_process, revalidate_process
    from agent.runtime.contracts import KnownNotExecuted

    workdir = tmp_path / "sub"
    workdir.mkdir()
    prepared = prepare_process(
        {"executable": "/usr/bin/true", "cwd": "sub"},
        workspace=tmp_path,
        captured_path="/usr/bin:/bin",
    )
    ok = revalidate_process(prepared)
    assert ok.command.executable_identity.resolved_path == "/usr/bin/true"
    assert ok.cwd_path == str(workdir)

    shutil.rmtree(workdir)
    workdir.mkdir()
    drift = revalidate_process(prepared)
    assert isinstance(drift, KnownNotExecuted)
    assert drift.code == "cwd_identity_changed"


def test_closed_process_environment_uses_temp_root_and_allowlist(tmp_path):
    from agent.process.preparation import closed_process_environment

    env = closed_process_environment(str(tmp_path), "/usr/bin:/bin")
    assert set(env) == {"HOME", "TMPDIR", "PATH", "LANG", "LC_CTYPE", "TZ"}
    assert env["HOME"].startswith(str(tmp_path))
    assert env["TMPDIR"].startswith(str(tmp_path))
    assert env["PATH"] == "/usr/bin:/bin"
    assert os.path.isdir(env["HOME"]) and os.path.isdir(env["TMPDIR"])
