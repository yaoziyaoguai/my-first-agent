from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent.composition import build_tool_registrations
from agent.skill.catalog import SkillCatalogError


def _make_skill(root: Path, name: str, body: str = "rules\n") -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A {name} skill.\n---\n{body}",
        encoding="utf-8",
    )


def test_no_skill_root_keeps_baseline_file_tools_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    registrations = build_tool_registrations(
        workspace=workspace, skill_roots=(), max_tool_result_chars=4_000
    )
    names = {registration.spec.name for registration in registrations}

    assert {"read_file", "write_file", "edit_file", "list_files"} <= names
    assert not any(name.startswith("skill__") for name in names)


def test_skill_root_adds_activation_and_resource_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "roots"
    root.mkdir()
    _make_skill(root, "code-review")

    registrations = build_tool_registrations(
        workspace=workspace, skill_roots=[root], max_tool_result_chars=4_000
    )
    names = {registration.spec.name for registration in registrations}

    assert "skill__code-review" in names
    assert "skill__read_resource" in names
    assert "read_file" in names


def test_repeated_skill_roots_compose_one_catalog(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root_a = tmp_path / "roots-a"
    root_b = tmp_path / "roots-b"
    root_a.mkdir()
    root_b.mkdir()
    _make_skill(root_a, "alpha")
    _make_skill(root_b, "beta")

    registrations = build_tool_registrations(
        workspace=workspace, skill_roots=[root_a, root_b], max_tool_result_chars=4_000
    )
    names = {registration.spec.name for registration in registrations}

    assert {"skill__alpha", "skill__beta"} <= names


def test_name_dir_mismatch_skill_root_fails_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "roots"
    root.mkdir()
    _make_skill(root, "code-review")
    (root / "code-review" / "SKILL.md").write_text(
        "---\nname: other\n---\nx", encoding="utf-8"
    )

    with pytest.raises(SkillCatalogError):
        build_tool_registrations(
            workspace=workspace, skill_roots=[root], max_tool_result_chars=4_000
        )


def test_missing_skill_root_dir_fails_startup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SkillCatalogError):
        build_tool_registrations(
            workspace=workspace,
            skill_roots=[tmp_path / "missing"],
            max_tool_result_chars=4_000,
        )


def test_composition_imports_without_pyyaml() -> None:
    # base 安装（无 skill extra）必须能 import composition；yaml 仅在配置 root 时才需要。
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['yaml'] = None; import agent.composition; print('OK')",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
