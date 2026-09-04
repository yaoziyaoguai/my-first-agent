"""Skill entrypoints 声明发现与固定（pin）合同测试。

覆盖：合法发现、无入口旧行为、unknown key / duplicate / traversal / symlink /
undeclared script / unsupported file / limit，以及 resolve_entrypoint 的
script drift 与 ancestor drift 重新校验。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

import agent.skill.catalog as catalog_module
from agent.skill.catalog import (
    SkillLimitError,
    SkillLimits,
    SkillSchemaError,
    SkillSecurityError,
    build_skill_catalog,
)

# root 指向 fixture skill 目录本身：tests/fixtures/skills 下另有历史遗留的空目录
# safe-writer（无 SKILL.md，会被 catalog 拒绝），不得纳入或删除。
_FIXTURE_SKILL_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "skills" / "text-stats"
_SCRIPT_BODY = "def run(arguments, inputs):\n    return None\n"


def _write_skill(
    root: Path,
    name: str,
    *,
    body: str = "Do the task step by step.\n",
    frontmatter: str = "",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    fm = f"name: {name}\ndescription: A skill for testing {name}.\n{frontmatter}"
    content = f"---\n{fm}---\n{body}"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def _write_scripts(skill_dir: Path, scripts: dict[str, str]) -> None:
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    for filename, content in scripts.items():
        (scripts_dir / filename).write_text(content, encoding="utf-8")


def _entrypoints_yaml(*pairs: tuple[str, str]) -> str:
    lines = ["entrypoints:"]
    for entrypoint_id, script in pairs:
        lines.append(f"  - id: {entrypoint_id}")
        lines.append(f"    script: {script}")
    return "\n".join(lines) + "\n"


def _make_declared_skill(root: Path, name: str = "text-tools") -> Path:
    skill_dir = _write_skill(
        root, name, frontmatter=_entrypoints_yaml(("count", "scripts/count.py"))
    )
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY})
    return skill_dir


def test_valid_entrypoint_discovery_pins_identity_and_resolves(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    script = _make_declared_skill(root)

    catalog = build_skill_catalog([root])

    assert len(catalog.descriptors) == 1
    descriptor = catalog.descriptor_for("text-tools")
    assert len(descriptor.entrypoints) == 1
    entrypoint = descriptor.entrypoints[0]
    assert entrypoint.id == "count"
    assert entrypoint.relative_path == "scripts/count.py"
    assert entrypoint.size == len(_SCRIPT_BODY.encode("utf-8"))
    assert len(entrypoint.digest) == 64
    assert entrypoint.identity.ino == os.stat(script / "scripts" / "count.py").st_ino
    assert catalog.resolve_entrypoint("text-tools", "count") == entrypoint


def test_skill_without_entrypoints_keeps_readonly_behavior(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review")

    catalog = build_skill_catalog([root])

    descriptor = catalog.descriptor_for("code-review")
    assert descriptor.entrypoints == ()
    assert "Do the task" in catalog.read_activation("code-review").body


def test_entrypoints_must_be_a_list(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "text-tools", frontmatter="entrypoints: count\n")

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_entrypoint_unknown_key_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "text-tools")
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY})
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: text-tools\n"
        "description: A skill for testing text-tools.\n"
        "entrypoints:\n"
        "  - id: count\n"
        "    script: scripts/count.py\n"
        "    command: python\n"
        "---\nbody\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_entrypoint_missing_required_key_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "text-tools", frontmatter="entrypoints:\n  - id: count\n")

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_duplicate_entrypoint_id_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(
        root,
        "text-tools",
        frontmatter=_entrypoints_yaml(
            ("count", "scripts/count.py"), ("count", "scripts/other.py")
        ),
    )
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY, "other.py": _SCRIPT_BODY})

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_duplicate_entrypoint_script_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(
        root,
        "text-tools",
        frontmatter=_entrypoints_yaml(
            ("count", "scripts/count.py"), ("other", "scripts/count.py")
        ),
    )
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY})

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_entrypoint_id_format_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(
        root, "text-tools", frontmatter=_entrypoints_yaml(("Count_Words", "scripts/count.py"))
    )
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY})

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


@pytest.mark.parametrize(
    "script",
    [
        "scripts/../count.py",
        "/etc/passwd.py",
        "scripts/sub/count.py",
        "count.py",
        "scripts/count.txt",
        "scripts\\count.py",
        "scripts/.count.py",
    ],
)
def test_non_canonical_script_path_rejected(tmp_path: Path, script: str) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(
        root, "text-tools", frontmatter=_entrypoints_yaml(("count", script))
    )
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY})

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_missing_script_file_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(
        root, "text-tools", frontmatter=_entrypoints_yaml(("count", "scripts/count.py"))
    )
    (skill_dir / "scripts").mkdir()

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_symlinked_script_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    (skill_dir / "scripts" / "count.py").unlink()
    outside = tmp_path / "outside.py"
    outside.write_text(_SCRIPT_BODY, encoding="utf-8")
    (skill_dir / "scripts" / "count.py").symlink_to(outside)

    with pytest.raises(SkillSecurityError):
        build_skill_catalog([root])


def test_non_regular_script_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    (skill_dir / "scripts" / "count.py").unlink()
    os.mkfifo(skill_dir / "scripts" / "count.py")

    try:
        with pytest.raises(SkillSecurityError):
            build_skill_catalog([root])
    finally:
        (skill_dir / "scripts" / "count.py").unlink()


def test_undeclared_script_file_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    (skill_dir / "scripts" / "hidden.py").write_text(_SCRIPT_BODY, encoding="utf-8")

    with pytest.raises(SkillSecurityError):
        build_skill_catalog([root])


def test_undeclared_scripts_subdirectory_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    (skill_dir / "scripts" / "sub").mkdir()

    with pytest.raises(SkillSecurityError):
        build_skill_catalog([root])


def test_scripts_directory_replacement_during_scan_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    original_open = catalog_module.os.open
    scripts_open_count = 0

    def replacing_open(path, flags, *args, **kwargs):  # noqa: ANN001, ANN202
        nonlocal scripts_open_count
        if path == "scripts" and kwargs.get("dir_fd") is not None:
            scripts_open_count += 1
            if scripts_open_count == 2:
                moved = skill_dir / "scripts-original"
                (skill_dir / "scripts").rename(moved)
                replacement = skill_dir / "scripts"
                replacement.mkdir()
                (replacement / "count.py").write_text(_SCRIPT_BODY, encoding="utf-8")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(catalog_module.os, "open", replacing_open)

    with pytest.raises(SkillSecurityError, match="changed during scan"):
        build_skill_catalog([root])


def test_scripts_dir_without_declaration_keeps_readonly_behavior(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "legacy.py").write_text(_SCRIPT_BODY, encoding="utf-8")

    catalog = build_skill_catalog([root])

    descriptor = catalog.descriptor_for("code-review")
    assert descriptor.entrypoints == ()
    assert "Do the task" in catalog.read_activation("code-review").body


def test_entrypoint_count_over_limit(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(
        root,
        "text-tools",
        frontmatter=_entrypoints_yaml(
            ("count", "scripts/count.py"), ("other", "scripts/other.py")
        ),
    )
    _write_scripts(skill_dir, {"count.py": _SCRIPT_BODY, "other.py": _SCRIPT_BODY})

    with pytest.raises(SkillLimitError):
        build_skill_catalog([root], limits=SkillLimits(max_entrypoints=1))


def test_entrypoints_participate_in_identity_digest(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)

    first = build_skill_catalog([root]).descriptor_for("text-tools")
    (skill_dir / "scripts" / "count.py").write_text(
        "def run(arguments, inputs):\n    return 1\n", encoding="utf-8"
    )
    second = build_skill_catalog([root]).descriptor_for("text-tools")

    assert first.identity_digest != second.identity_digest


def test_resolve_entrypoint_unknown_id_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _make_declared_skill(root)
    catalog = build_skill_catalog([root])

    with pytest.raises(SkillSchemaError):
        catalog.resolve_entrypoint("text-tools", "missing")


def test_resolve_entrypoint_detects_script_drift(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    catalog = build_skill_catalog([root])
    assert catalog.resolve_entrypoint("text-tools", "count").id == "count"

    (skill_dir / "scripts" / "count.py").write_text(
        "def run(arguments, inputs):\n    return 'tampered'\n", encoding="utf-8"
    )

    with pytest.raises(SkillSecurityError):
        catalog.resolve_entrypoint("text-tools", "count")


def test_resolve_entrypoint_detects_inode_replacement(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    script = skill_dir / "scripts" / "count.py"
    catalog = build_skill_catalog([root])
    original_ino = os.stat(script).st_ino

    # 相同内容、不同 inode（temp + atomic replace）。
    tmp_file = skill_dir / "scripts" / ".tmp_replace"
    tmp_file.write_bytes(script.read_bytes())
    os.replace(tmp_file, script)
    assert os.stat(script).st_ino != original_ino, "test setup: inode must differ"

    with pytest.raises(SkillSecurityError):
        catalog.resolve_entrypoint("text-tools", "count")


def test_resolve_entrypoint_detects_scripts_directory_replacement(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    script = skill_dir / "scripts" / "count.py"
    catalog = build_skill_catalog([root])
    original_file_ino = os.stat(script).st_ino

    replacement = tmp_path / "replacement-scripts"
    replacement.mkdir()
    os.replace(script, replacement / "count.py")
    (skill_dir / "scripts").rmdir()
    os.replace(replacement, skill_dir / "scripts")
    assert os.stat(script).st_ino == original_file_ino, "file inode must match"

    with pytest.raises(SkillSecurityError, match="directory identity drift"):
        catalog.resolve_entrypoint("text-tools", "count")


def test_resolve_entrypoint_detects_ancestor_drift(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _make_declared_skill(root)
    script = skill_dir / "scripts" / "count.py"
    catalog = build_skill_catalog([root])
    original_file_stat = os.stat(script)

    # 替换 skill 目录但保留 SKILL.md 与 script 的 inode：只有 ancestor identity 变了。
    stash = tmp_path / ".stash_skill"
    stash.mkdir()
    os.replace(skill_dir / "SKILL.md", stash / "_skill")
    scripts_stash = tmp_path / ".stash_scripts"
    scripts_stash.mkdir()
    os.replace(script, scripts_stash / "_script")
    (skill_dir / "scripts").rmdir()
    skill_dir.rmdir()
    skill_dir.mkdir()
    (skill_dir / "scripts").mkdir()
    os.replace(stash / "_skill", skill_dir / "SKILL.md")
    os.replace(scripts_stash / "_script", script)
    assert os.stat(script).st_ino == original_file_stat.st_ino, "file inode must match"

    with pytest.raises(SkillSecurityError):
        catalog.resolve_entrypoint("text-tools", "count")


def test_text_stats_fixture_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # copy 到 tmp root 再扫描：fixture 目录同时是 root 的一级 skill 目录
    # （scripts/ 会成为 root 的直接子目录），且避免 import 产物写回 fixture。
    monkeypatch.setattr(sys, "dont_write_bytecode", True, raising=False)
    root = tmp_path / "roots"
    root.mkdir()
    shutil.copytree(_FIXTURE_SKILL_ROOT, root / "text-stats")
    catalog = build_skill_catalog([root])

    descriptor = catalog.descriptor_for("text-stats")
    assert len(descriptor.entrypoints) == 1
    entrypoint = descriptor.entrypoints[0]
    assert entrypoint.id == "text-stats"
    assert entrypoint.relative_path == "scripts/text_stats.py"
    assert catalog.resolve_entrypoint("text-stats", "text-stats") == entrypoint

    # fixture 脚本合同：只导出 run(arguments, inputs)，返回 observation 形状。
    script_file = root / "text-stats" / "scripts" / "text_stats.py"
    spec = importlib.util.spec_from_file_location("text_stats_fixture", script_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert [name for name in vars(module) if not name.startswith("_")] == ["run"]
    result = module.run({"text": "hello world"}, {})
    assert set(result) == {"kind", "payload", "artifact"}
    assert result["kind"] == "observation"
    assert result["payload"] == {"characters": 11, "words": 2}
    assert result["artifact"] is None
