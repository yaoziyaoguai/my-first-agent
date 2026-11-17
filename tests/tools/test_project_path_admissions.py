"""ProjectPathAdmissions：会话内保留路径准入表（/project-path 的单一变更点）。

准入只放宽文件工具的读可见性，与启动期 --project-path 旗标完全同边界：
不改 sandbox/local_process/managed web 边界，不写 checkpoint 或 durable
state。本文件同时覆盖共享的重叠拒绝 helper 与 composition 注入的翻转行为。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.composition import build_tool_registrations
from agent.runtime.contracts import (
    ExecutionIntent,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import DEFAULT_PRIVATE_ROOTS
from agent.tools.path_safety import (
    ProjectPathAdmissions,
    WorkspaceBoundary,
    WorkspaceSecurityError,
    reject_project_path_overlap,
    validate_project_paths,
)


def _context() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 1)


def _workspace_with_config(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    (workspace / "config" / "app.yaml").write_text("mode: fixture\n", encoding="utf-8")
    (workspace / "config" / "other.yaml").write_text("hidden fixture\n", encoding="utf-8")
    return workspace


# --- 注册表 ---


def test_admissions_validate_the_initial_set_and_casefold_components() -> None:
    admissions = ProjectPathAdmissions(("Config/App.yaml", "pytest.ini"))

    assert admissions.snapshot() == validate_project_paths(
        ("Config/App.yaml", "pytest.ini")
    )


def test_admissions_reject_invalid_paths_in_the_initial_set() -> None:
    with pytest.raises(WorkspaceSecurityError):
        ProjectPathAdmissions(("docs/readme.md",))


@pytest.mark.parametrize(
    "raw_path",
    [
        "",  # malformed：空
        "config/app\x00name",  # malformed：不可打印字符
        "config/*.yaml",  # malformed：glob 元字符
        "/etc/passwd",  # 绝对路径
        "config/../secret",  # traversal
        "docs/readme.md",  # 首组件不在保留名集合
        "config/.env",  # 敏感组件不可被普通例外放行
    ],
)
def test_admit_rejects_every_denied_category(raw_path: str) -> None:
    admissions = ProjectPathAdmissions()

    with pytest.raises(WorkspaceSecurityError):
        admissions.admit(raw_path)
    assert admissions.snapshot() == ()


def test_admit_is_idempotent_across_case_variants() -> None:
    admissions = ProjectPathAdmissions()
    admissions.admit("Config/App.yaml")
    admissions.admit("config/app.yaml")

    assert admissions.snapshot() == (("config", "app.yaml"),)


def test_admit_rolls_back_when_overlap_rejection_fires() -> None:
    seen: list[tuple[tuple[str, ...], ...]] = []

    def reject(snapshot: tuple[tuple[str, ...], ...]) -> None:
        seen.append(snapshot)
        raise ValueError("--project-path overlaps a configured private runtime path.")

    admissions = ProjectPathAdmissions(("config/app.yaml",), reject_overlap=reject)

    with pytest.raises(ValueError):
        admissions.admit("workspace/notes.txt")
    # 拒绝回调收到的是追加后的完整准入快照；回滚后表内不留被拒绝路径。
    assert seen == [(("config", "app.yaml"), ("workspace", "notes.txt"))]
    assert admissions.snapshot() == (("config", "app.yaml"),)


def test_snapshot_is_stable_after_later_admits() -> None:
    admissions = ProjectPathAdmissions()
    earlier = admissions.snapshot()
    admissions.admit("config/app.yaml")

    assert earlier == ()
    assert admissions.snapshot() == (("config", "app.yaml"),)


# --- WorkspaceBoundary 注入 ---


def test_boundary_visibility_flips_with_admission(tmp_path: Path) -> None:
    workspace = _workspace_with_config(tmp_path)
    admissions = ProjectPathAdmissions()
    boundary = WorkspaceBoundary(
        workspace,
        private_roots=DEFAULT_PRIVATE_ROOTS,
        project_path_admissions=admissions,
    )

    with pytest.raises(WorkspaceSecurityError):
        boundary.inspect_readable("config/app.yaml")
    admissions.admit("config/app.yaml")
    boundary.inspect_readable("config/app.yaml")

    # 准入是精确路径级：未准入的同目录文件仍不可读。
    with pytest.raises(WorkspaceSecurityError):
        boundary.inspect_readable("config/other.yaml")


def test_boundary_without_admissions_keeps_static_project_paths(tmp_path: Path) -> None:
    workspace = _workspace_with_config(tmp_path)
    boundary = WorkspaceBoundary(
        workspace,
        private_roots=DEFAULT_PRIVATE_ROOTS,
        project_paths=("config/app.yaml",),
    )

    boundary.inspect_readable("config/app.yaml")
    with pytest.raises(WorkspaceSecurityError):
        boundary.inspect_readable("config/other.yaml")


# --- 共享重叠拒绝 helper ---


def test_reject_project_path_overlap_denies_private_runtime_overlap(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)

    # private 是 admitted 的祖先（旗标放行整个 config 会覆盖 ledger）。
    with pytest.raises(
        ValueError, match="overlaps a configured private runtime path"
    ):
        reject_project_path_overlap(
            (("config", "app.yaml"),), [workspace / "config"], workspace
        )
    # private 是 admitted 的后代（放行 config/app.yaml 再被 ledger 占用）。
    with pytest.raises(
        ValueError, match="overlaps a configured private runtime path"
    ):
        reject_project_path_overlap(
            (("config",),),
            [workspace / "config" / "app.yaml" / "attempts.jsonl"],
            workspace,
        )


def test_reject_project_path_overlap_allows_disjoint_and_outside_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    (workspace / "workspace").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    reject_project_path_overlap(
        (("config", "app.yaml"),),
        [
            None,
            workspace / "workspace" / "notes.txt",
            outside / "attempts.jsonl",
        ],
        workspace,
    )


# --- composition 注入（走 registration prepare/invoke 的最短真实路径） ---


def test_build_tool_registrations_read_visibility_flips_with_admit(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_config(tmp_path)
    admissions = ProjectPathAdmissions()
    runtime = KernelToolRuntime(
        build_tool_registrations(
            workspace=workspace,
            max_tool_result_chars=4_000,
            project_path_admissions=admissions,
        )
    )

    denied = runtime.prepare(
        ToolCall("read-1", "read_file", {"path": "config/app.yaml"}), _context()
    )
    assert isinstance(denied, ToolResult) and denied.is_error
    assert "fixture" not in denied.content

    admissions.admit("config/app.yaml")
    prepared = runtime.prepare(
        ToolCall("read-2", "read_file", {"path": "config/app.yaml"}), _context()
    )
    assert isinstance(prepared, ExecutionIntent)
    result = runtime.invoke(prepared)
    assert result.content == "mode: fixture\n"
