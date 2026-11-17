"""SessionPathAdmissions：会话内子进程 PATH 前缀准入表（/env-path 的单一变更点）。

准入只放宽 local_process 子进程的 bare 可执行文件名解析；每条命令仍按
resolved 可执行文件逐条审批。覆盖：注册表单元校验（零残留/幂等/上限）、
registration 级集成（准入翻转 bare token 解析）、executor 漂移探针
（approval 后 PATH 变更 → environment_policy_changed）与 admissions=None
的既有路径对照。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.process.admission import build_environment_plan
from agent.process.preparation import SessionPathAdmissions
from agent.process.tools import build_local_process_registration
from agent.runtime.contracts import KnownNotExecuted


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _fake_venv_bin(workspace: Path) -> Path:
    bin_dir = workspace / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    tool = bin_dir / "fake-tool"
    tool.write_bytes(b"#!/bin/sh\necho fake-venv-tool\n")
    tool.chmod(0o755)
    return bin_dir


class _Intent:
    """executor 直调所需的最小 intent 形状（与 test_preparation 同式）。"""

    def __init__(self, arguments: dict, binding: dict) -> None:
        self.arguments = arguments
        self.safety_binding = binding


# --- 注册表单元 ---


@pytest.mark.parametrize(
    "raw_dir",
    [
        "",  # 空
        "bi\x00n",  # NUL
        "/usr/bin",  # 绝对路径：必须 workspace 相对
        "../outside",  # 父级逃逸
        "sub/../bin",  # 分段含 ..
        "does-not-exist",  # 不存在（strict resolve 失败）
    ],
)
def test_admit_rejects_every_denied_category(tmp_path, raw_dir) -> None:  # noqa: ANN001
    admissions = SessionPathAdmissions(workspace=_workspace(tmp_path))

    with pytest.raises(ValueError):
        admissions.admit(raw_dir)
    assert admissions.snapshot() == ()


def test_admit_rejects_non_directory_entries(tmp_path) -> None:  # noqa: ANN001
    workspace = _workspace(tmp_path)
    (workspace / "plain-file").write_text("not a directory\n", encoding="utf-8")
    admissions = SessionPathAdmissions(workspace=workspace)

    with pytest.raises(ValueError, match="directory"):
        admissions.admit("plain-file")
    assert admissions.snapshot() == ()


def test_admit_rejects_symlinks_resolving_outside_the_workspace(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside-bin"
    outside.mkdir()
    os.symlink(outside, workspace / "link-bin")
    admissions = SessionPathAdmissions(workspace=workspace)

    with pytest.raises(ValueError, match="workspace"):
        admissions.admit("link-bin")
    assert admissions.snapshot() == ()


def test_admit_enforces_the_entry_limit(tmp_path) -> None:  # noqa: ANN001
    workspace = _workspace(tmp_path)
    for index in range(3):
        (workspace / f"bin-{index}").mkdir()
    admissions = SessionPathAdmissions(workspace=workspace, max_entries=2)

    admissions.admit("bin-0")
    admissions.admit("bin-1")
    before = admissions.snapshot()

    with pytest.raises(ValueError, match="limit"):
        admissions.admit("bin-2")
    # 超限拒绝零残留：表保持拒绝前的内容。
    assert admissions.snapshot() == before
    assert len(before) == 2


def test_admit_returns_the_resolved_absolute_directory(tmp_path) -> None:  # noqa: ANN001
    workspace = _workspace(tmp_path)
    (workspace / "sub" / "bin").mkdir(parents=True)
    admissions = SessionPathAdmissions(workspace=workspace)

    resolved = admissions.admit("sub/bin")

    assert resolved == str((workspace / "sub" / "bin").resolve())
    assert admissions.snapshot() == (resolved,)


def test_admit_is_idempotent_across_repeat_and_case_variants(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "bin").mkdir()
    admissions = SessionPathAdmissions(workspace=workspace)

    first = admissions.admit("bin")
    again = admissions.admit("./bin")
    assert again == first
    assert admissions.snapshot() == (first,)

    # casefold 幂等：大小写不敏感文件系统（macOS/APFS）上 resolve 保留输入
    # 大小写，重复准入不得追加条目，返回串与已存条目 casefold 相等。
    if not (workspace / "BIN").exists():
        pytest.skip("filesystem is case-sensitive; casefold dedup is unobservable")
    folded = admissions.admit("BIN")
    assert folded.casefold() == first.casefold()
    assert admissions.snapshot() == (first,)


def test_effective_path_prefixes_newest_admission_first(tmp_path) -> None:  # noqa: ANN001
    workspace = _workspace(tmp_path)
    (workspace / "old-bin").mkdir()
    (workspace / "new-bin").mkdir()
    admissions = SessionPathAdmissions(workspace=workspace)
    base = "/usr/bin:/bin"

    assert admissions.effective_captured_path(base) == base

    old = admissions.admit("old-bin")
    new = admissions.admit("new-bin")
    # 最新准入在最前：PATH 首匹配优先。
    assert admissions.effective_captured_path(base) == (
        os.pathsep.join((new, old)) + os.pathsep + base
    )


# --- 注册级集成 ---


def test_registration_resolves_bare_token_only_after_admission(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    bin_dir = _fake_venv_bin(workspace)
    admissions = SessionPathAdmissions(workspace=workspace)
    registration = build_local_process_registration(
        workspace=workspace,
        captured_path="/usr/bin:/bin",
        path_admissions=admissions,
    )
    arguments = {"executable": "fake-tool", "argv": [], "cwd": "."}

    with pytest.raises(ValueError, match="preparation not admitted"):
        registration.prepare_binding(dict(arguments))

    admissions.admit(".venv/bin")
    binding = registration.prepare_binding(dict(arguments))

    assert binding["resolved_executable_path"] == str(bin_dir / "fake-tool")
    # digest 反映含准入目录的 child_path（准入目录在系统目录之前）。
    expected = build_environment_plan(
        captured_path=os.pathsep.join((str(bin_dir), "/usr/bin", "/bin"))
    )
    assert binding["environment_policy_digest"] == expected.policy_digest


def test_executor_runs_bare_token_through_admitted_directory(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    _fake_venv_bin(workspace)
    admissions = SessionPathAdmissions(workspace=workspace)
    registration = build_local_process_registration(
        workspace=workspace,
        captured_path="/usr/bin:/bin",
        path_admissions=admissions,
    )
    admissions.admit(".venv/bin")
    arguments = {"executable": "fake-tool", "argv": [], "cwd": "."}
    binding = registration.prepare_binding(dict(arguments))

    draft = registration.func(_Intent(dict(arguments), binding))

    assert draft.outcome.value == "exited"
    assert "fake-venv-tool" in draft.stdout_projection


# --- executor 漂移探针（钉新不变式） ---


def test_executor_blocks_when_admissions_change_the_path_after_approval(
    tmp_path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "other-bin").mkdir()
    admissions = SessionPathAdmissions(workspace=workspace)
    registration = build_local_process_registration(
        workspace=workspace,
        captured_path="/usr/bin:/bin",
        path_admissions=admissions,
    )
    # binding 来自无准入时的 prepare：executable 用绝对路径 token，identity
    # 不随 PATH 变化。
    arguments = {"executable": "/usr/bin/true", "argv": [], "cwd": "."}
    binding = registration.prepare_binding(dict(arguments))

    # approval 后 admit 一个不含该可执行文件的目录：PATH 串变、identity 不变。
    admissions.admit("other-bin")

    outcome = registration.func(_Intent(dict(arguments), binding))

    assert isinstance(outcome, KnownNotExecuted)
    assert outcome.code == "environment_policy_changed"
    assert outcome.message == (
        "prepared environment changed; prepare and review the command again"
    )


# --- 对照：admissions=None 时既有执行路径不变 ---


def test_executor_without_admissions_keeps_the_existing_behaviour(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    registration = build_local_process_registration(
        workspace=workspace,
        captured_path="/usr/bin:/bin",
    )
    arguments = {"executable": "/usr/bin/true", "argv": [], "cwd": "."}
    binding = registration.prepare_binding(dict(arguments))

    draft = registration.func(_Intent(dict(arguments), binding))

    assert draft.outcome.value == "exited"
