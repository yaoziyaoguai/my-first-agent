from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.skill.catalog import (
    SkillCatalogError,
    SkillDescriptor,
    SkillLimits,
    SkillSchemaError,
    SkillSecurityError,
    build_skill_catalog,
)


def _write_skill(
    root: Path,
    name: str,
    *,
    body: str = "Do the task step by step.\n",
    frontmatter: str = "",
    raw: str | None = None,
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    if raw is not None:
        (skill_dir / "SKILL.md").write_text(raw, encoding="utf-8")
        return skill_dir
    fm = f"name: {name}\ndescription: A skill for testing {name}.\n{frontmatter}"
    content = f"---\n{fm}---\n{body}"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def test_valid_skill_exposes_name_description_and_digests(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review", body="Review the diff carefully.\n")

    catalog = build_skill_catalog([root])

    assert len(catalog.descriptors) == 1
    descriptor = catalog.descriptor_for("code-review")
    assert isinstance(descriptor, SkillDescriptor)
    assert descriptor.name == "code-review"
    assert "Review the diff" in descriptor.description or "testing" in descriptor.description
    assert descriptor.body_digest
    assert descriptor.resource_inventory_digest
    assert descriptor.identity_digest
    assert descriptor.policy_version


def test_name_dir_mismatch_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review", frontmatter="name: other-name\n")

    with pytest.raises(SkillSchemaError):
        build_skill_catalog([root])


def test_duplicate_name_across_roots_fails_closed(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _write_skill(root_a, "code-review")
    _write_skill(root_b, "code-review")

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root_a, root_b])


def test_duplicate_yaml_key_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(
        root,
        "code-review",
        raw=(
            "---\n"
            "name: code-review\n"
            "description: one\n"
            "description: two\n"
            "---\nbody\n"
        ),
    )

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root])


def test_yaml_alias_bomb_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    bomb = "---\nname: code-review\ndescription: &a x\nmeta: *a\n---\nbody\n"
    _write_skill(root, "code-review", raw=bomb)

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root])


def test_yaml_custom_tag_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    tagged = (
        "---\n"
        "name: code-review\n"
        "description: x\n"
        "evil: !python/object/apply:os.system []\n"
        "---\nbody\n"
    )
    _write_skill(root, "code-review", raw=tagged)

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root])


def test_symlinked_skill_dir_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    real = tmp_path / "real-skill"
    real.mkdir()
    (real / "SKILL.md").write_text(
        "---\nname: real-skill\ndescription: x\n---\nbody\n", encoding="utf-8"
    )
    (root / "code-review").symlink_to(real)

    with pytest.raises(SkillSecurityError):
        build_skill_catalog([root])


def test_resource_traversal_rejected(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review")
    references = skill_dir / "references"
    references.mkdir()
    (references / "guide.md").write_text("guide body", encoding="utf-8")
    # symlink escaping references/ -> outside
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (references / "escape.md").symlink_to(outside)

    with pytest.raises(SkillSecurityError):
        build_skill_catalog([root])


def test_non_utf8_skill_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = root / "code-review"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_bytes(b"---\nname: code-review\ndescription: x\n---\n\xff\xfe\n")

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root])


def test_body_over_limit_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review", body="x" * 200)

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root], limits=SkillLimits(max_body_chars=100))


def test_too_many_skills_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    for index in range(3):
        _write_skill(root, f"skill-{index}")

    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root], limits=SkillLimits(max_skills=2))


def test_deterministic_per_resource_digest(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review")
    references = skill_dir / "references"
    references.mkdir()
    (references / "guide.md").write_text("guide body", encoding="utf-8")
    (references / "assets").mkdir()

    first = build_skill_catalog([root])
    second = build_skill_catalog([root])

    assert first.catalog_digest == second.catalog_digest
    descriptor = first.descriptor_for("code-review")
    assert [r.relative_path for r in descriptor.resources] == ["references/guide.md"]
    assert all(r.digest for r in descriptor.resources)


def test_activation_detects_body_drift(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review", body="original body\n")
    catalog = build_skill_catalog([root])
    descriptor = catalog.descriptor_for("code-review")

    body, provenance = catalog.read_activation("code-review")
    assert "original body" in body
    assert provenance["body_digest"] == descriptor.body_digest

    # 修改 SKILL.md 内容；identity/digest 漂移必须被检测。
    (root / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: A skill for testing code-review.\n---\ntampered\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillSecurityError):
        catalog.read_activation("code-review")


def test_error_messages_do_not_leak_absolute_paths(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "other-name", frontmatter="name: code-review\n")

    with pytest.raises(SkillCatalogError) as info:
        build_skill_catalog([root])

    assert str(root) not in str(info.value)


def test_missing_dependency_error_only_when_configured(tmp_path: Path) -> None:
    # 在子进程中屏蔽 yaml，验证仅在配置了 root 时才报缺失依赖。
    code = (
        "import sys\n"
        "sys.modules['yaml'] = None  # type: ignore[assignment]\n"
        "from agent.skill.catalog import build_skill_catalog\n"
        "try:\n"
        "    build_skill_catalog([])\n"
        "except Exception:\n"
        "    print('UNCONFIGURED_RAISED')\n"
        "    raise\n"
        "print('UNCONFIGURED_OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=os.environ
    )
    assert result.returncode == 0, result.stderr
    assert "UNCONFIGURED_OK" in result.stdout

    code_configured = (
        "import sys\n"
        "sys.modules['yaml'] = None  # type: ignore[assignment]\n"
        "import pathlib\n"
        "from agent.skill.catalog import build_skill_catalog, SkillDependencyError\n"
        "root = pathlib.Path(sys.argv[1])\n"
        "try:\n"
        "    build_skill_catalog([root])\n"
        "except SkillDependencyError:\n"
        "    print('DEPENDENCY_ERROR')\n"
    )
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review")
    result = subprocess.run(
        [sys.executable, "-c", code_configured, str(root)],
        capture_output=True,
        text=True,
        env=os.environ,
    )
    assert result.returncode == 0, result.stderr
    assert "DEPENDENCY_ERROR" in result.stdout


def test_frontmatter_rejects_unknown_and_ambiguous_yaml(tmp_path: Path) -> None:
    """A19: frontmatter must reject unknown top-level keys (strict allowlist)."""
    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = root / "code-review"
    skill_dir.mkdir()
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: code-review\ndescription: A skill.\nev1l_field: true\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillCatalogError):
        build_skill_catalog([root])


def test_activation_revalidates_metadata_and_file_identity(tmp_path: Path) -> None:
    """A13: activation must revalidate file identity (digest) after scan; content drift
    must be detected and rejected."""
    root = tmp_path / "roots"
    root.mkdir()
    _write_skill(root, "code-review", body="original body\n")
    catalog = build_skill_catalog([root])
    descriptor = catalog.descriptor_for("code-review")
    assert descriptor.body_digest
    assert descriptor.file_digest

    body, provenance = catalog.read_activation("code-review")
    assert "original body" in body
    assert provenance["body_digest"] == descriptor.body_digest

    # tamper → drift detected
    (root / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: A skill for testing code-review.\n---\ntampered\n",
        encoding="utf-8",
    )
    with pytest.raises(SkillSecurityError):
        catalog.read_activation("code-review")


def test_same_content_inode_replacement_is_drift(tmp_path: Path) -> None:
    """F7/R18: same-content inode replacement must be detected as drift, not accepted.
    The catalog must revalidate both digest AND file identity (dev/ino) at activation."""
    import os as _os

    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review", body="unchanged body\n")
    skill_file = skill_dir / "SKILL.md"
    original_stat = _os.stat(skill_file)

    catalog = build_skill_catalog([root])

    # Read original activation succeeds.
    body, _provenance = catalog.read_activation("code-review")
    assert "unchanged body" in body

    # Replace with same content but different inode (atomic temp+rename).
    original_content = skill_file.read_bytes()
    tmp_file = skill_dir / ".tmp_replace"
    tmp_file.write_bytes(original_content)
    _os.replace(tmp_file, skill_file)
    new_stat = _os.stat(skill_file)

    # Same content (same digest) but different inode.
    assert new_stat.st_ino != original_stat.st_ino, "test setup: inode must differ"

    # read_activation must detect identity drift and fail closed.
    with pytest.raises(SkillSecurityError, match="identity drift|file identity"):
        catalog.read_activation("code-review")


def test_resource_same_content_inode_replacement_is_drift(tmp_path: Path) -> None:
    """G1 resource replacement：resource read 必须在同一 opened fd 上重新校验 file
    identity（dev/ino），不只 digest。相同内容、不同 inode 的 resource 替换是 drift。"""
    import os as _os

    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review", body="body\n")
    references = skill_dir / "references"
    references.mkdir()
    guide = references / "guide.md"
    guide.write_text("resource body", encoding="utf-8")
    catalog = build_skill_catalog([root])

    assert catalog.read_resource("code-review", "references/guide.md") == "resource body"
    original_stat = _os.stat(guide)

    # 相同内容、不同 inode（temp + atomic replace）。
    tmp_file = references / ".tmp_replace"
    tmp_file.write_bytes(guide.read_bytes())
    _os.replace(tmp_file, guide)
    new_stat = _os.stat(guide)
    assert new_stat.st_ino != original_stat.st_ino, "test setup: resource inode must differ"

    with pytest.raises(SkillSecurityError):
        catalog.read_resource("code-review", "references/guide.md")


def _swap_skill_dir_keeping_inodes(skill_dir: Path, files: list[str], tmp_path: Path) -> None:
    """原子替换 skill 目录树，但保留指定相对文件的 inode（move 出再 move 回）。"""
    import os as _os

    stash = {rel: tmp_path / f".stash_{rel.replace('/', '_')}" for rel in files}
    for rel, stashed in stash.items():
        _os.replace(skill_dir / rel, stashed)
    # 重建子目录结构（files 形如 ["SKILL.md", "references/guide.md"]）。
    subdirs = { (skill_dir / rel).parent for rel in files }
    for sd in sorted(subdirs, key=lambda p: len(p.parts), reverse=True):
        if sd != skill_dir:
            sd.rmdir()
    skill_dir.rmdir()
    skill_dir.mkdir()
    for sd in sorted(subdirs, key=lambda p: len(p.parts)):
        if sd != skill_dir:
            sd.mkdir()
    for rel, stashed in stash.items():
        _os.replace(stashed, skill_dir / rel)


def test_activation_detects_skill_dir_ancestor_replacement(tmp_path: Path) -> None:
    """G1 trust-root identity：替换 skill 目录（经 move 保留 SKILL.md inode）在 activation
    必须被检测为 drift——文件 inode 未变，只有 ancestor（目录）identity 变了。"""
    import os as _os

    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review", body="body\n")
    skill_file = skill_dir / "SKILL.md"
    original_dir_stat = _os.stat(skill_dir)
    original_file_stat = _os.stat(skill_file)
    catalog = build_skill_catalog([root])
    assert "body" in catalog.read_activation("code-review").body

    _swap_skill_dir_keeping_inodes(skill_dir, ["SKILL.md"], tmp_path)
    new_dir_stat = _os.stat(skill_dir)
    new_file_stat = _os.stat(skill_file)
    assert new_dir_stat.st_ino != original_dir_stat.st_ino, "test setup: dir inode must differ"
    assert new_file_stat.st_ino == original_file_stat.st_ino, "test setup: file inode must match"

    with pytest.raises(SkillSecurityError):
        catalog.read_activation("code-review")


def test_resource_read_detects_skill_dir_ancestor_replacement(tmp_path: Path) -> None:
    """G1 trust-root identity：resource read 同样必须检测 skill 目录 ancestor 替换——
    resource 文件 inode 未变、digest 未变，只有目录 ancestor 变了。"""
    import os as _os

    root = tmp_path / "roots"
    root.mkdir()
    skill_dir = _write_skill(root, "code-review", body="body\n")
    references = skill_dir / "references"
    references.mkdir()
    guide = references / "guide.md"
    guide.write_text("resource body", encoding="utf-8")
    original_guide_stat = _os.stat(guide)
    catalog = build_skill_catalog([root])
    assert catalog.read_resource("code-review", "references/guide.md") == "resource body"

    _swap_skill_dir_keeping_inodes(skill_dir, ["SKILL.md", "references/guide.md"], tmp_path)
    assert _os.stat(guide).st_ino == original_guide_stat.st_ino, "resource inode must match"

    with pytest.raises(SkillSecurityError):
        catalog.read_resource("code-review", "references/guide.md")

