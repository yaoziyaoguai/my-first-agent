"""SubAgent Phase 2: Filesystem Registry tests.

Registry 是 runtime/session scoped metadata index：
- roots 必须显式传入；
- 扫描顺序 deterministic；
- duplicate name fail closed；
- disabled/deprecated 不出现在 visible 列表；
- 不加载 body、不使用 module-level global singleton。
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from agent.subagent_system.errors import SubAgentLoadError
from agent.subagent_system.registry import SubAgentRegistry


def _write_subagent(
    root: Path,
    name: str,
    *,
    status: str = "active",
    role: str = "reviewer",
) -> None:
    subagent_dir = root / name
    subagent_dir.mkdir(parents=True, exist_ok=True)
    (subagent_dir / "SUBAGENT.md").write_text(
        dedent(
            f"""\
            ---
            name: {name}
            description: {name} description.
            role: {role}
            model: fake
            status: {status}
            risk_level: low
            version: 0.1.0
            allowed_tools:
              - read_file
            allowed_skills: []
            memory_scope: none
            max_iterations_default: 1
            confirmation_policy: inherit_tool_policy
            supported_modes:
              - local_fake
            ---
            # {name}
            """
        ),
        encoding="utf-8",
    )


def test_registry_uses_explicit_roots_and_deterministic_order(tmp_path: Path) -> None:
    """显式 roots + stable sort 是防止读取真实 subagent dirs 的第一道边界。"""

    root = tmp_path / "subagents"
    for name in ("z-reviewer", "a-reviewer", "m-reviewer"):
        _write_subagent(root, name)

    registry = SubAgentRegistry(roots=[root])

    assert [item.name for item in registry.list_visible()] == [
        "a-reviewer",
        "m-reviewer",
        "z-reviewer",
    ]


def test_registry_is_session_scoped_and_reloadable(tmp_path: Path) -> None:
    """两个 registry instance 互不共享 mutable global state。"""

    root = tmp_path / "subagents"
    _write_subagent(root, "first-reviewer")
    first = SubAgentRegistry(roots=[root])

    _write_subagent(root, "second-reviewer")
    second = SubAgentRegistry(roots=[root])

    assert first.get_descriptor("second-reviewer") is None
    first.reload()
    assert first.get_descriptor("second-reviewer") is not None
    assert len(second.list_visible()) == 2


def test_duplicate_names_fail_closed_across_roots(tmp_path: Path) -> None:
    """重复 name 不能 silent shadow，否则 parent 可能委派给错误 descriptor。"""

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _write_subagent(root_a, "dup-reviewer")
    _write_subagent(root_b, "dup-reviewer")

    with pytest.raises(SubAgentLoadError) as exc_info:
        SubAgentRegistry(roots=[root_a, root_b])

    assert exc_info.value.code == "DUPLICATE_NAME"


def test_disabled_and_deprecated_descriptors_are_registered_but_not_visible(
    tmp_path: Path,
) -> None:
    """不可见不等于不存在；内部 audit 仍可查询，但模型可见列表不包含。"""

    root = tmp_path / "subagents"
    _write_subagent(root, "active-reviewer", status="active")
    _write_subagent(root, "disabled-reviewer", status="disabled")
    _write_subagent(root, "deprecated-reviewer", status="deprecated")

    registry = SubAgentRegistry(roots=[root])

    assert [item.name for item in registry.list_visible()] == ["active-reviewer"]
    assert registry.get_descriptor("disabled-reviewer") is not None
    assert registry.get_descriptor("deprecated-reviewer") is not None


def test_find_by_role_filters_visible_descriptors(tmp_path: Path) -> None:
    """role lookup 只能返回 active descriptors，不能泄漏 disabled agent。"""

    root = tmp_path / "subagents"
    _write_subagent(root, "code-reviewer", role="reviewer")
    _write_subagent(root, "hidden-reviewer", status="disabled", role="reviewer")
    _write_subagent(root, "test-agent", role="tester")

    registry = SubAgentRegistry(roots=[root])

    assert [item.name for item in registry.find_by_role("reviewer")] == ["code-reviewer"]
    assert registry.find_by_role("missing") == ()


# ==================================================================
# 诊断：无效 SubAgent 不再静默跳过
# ==================================================================

def test_get_load_errors_surfaces_missing_description(tmp_path: Path) -> None:
    """缺 description 时 get_load_errors() 必须包含错误信息，不再静默丢弃。"""
    root = tmp_path / "subagents"
    _write_subagent(root, "valid-agent")

    # 写入缺少 description 的 SUBAGENT.md
    bad_dir = root / "bad-agent"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "SUBAGENT.md").write_text(
        "---\nname: bad-agent\nrole: reviewer\nmodel: fake\nstatus: active\n---\n# bad\n",
        encoding="utf-8",
    )

    registry = SubAgentRegistry(roots=[root])
    errors = registry.get_load_errors()
    assert len(errors) == 1, (
        f"缺 description 应产生 1 个错误，实际: {len(errors)}"
    )
    assert errors[0].code == "MISSING_DESCRIPTION"
    assert "description" in errors[0].safe_preview.lower()


def test_get_load_errors_cleared_on_reload(tmp_path: Path) -> None:
    """reload() 后重新扫描，load_errors 应该反映最新状态。"""
    root = tmp_path / "subagents"

    bad_dir = root / "bad-agent"
    bad_dir.mkdir(parents=True, exist_ok=True)
    bad_md = bad_dir / "SUBAGENT.md"
    bad_md.write_text(
        "---\nname: bad-agent\nrole: reviewer\nmodel: fake\nstatus: active\n---\n# bad\n",
        encoding="utf-8",
    )

    registry = SubAgentRegistry(roots=[root])
    assert len(registry.get_load_errors()) == 1

    # 修复 SUBAGENT.md 后 reload——错误应清空
    bad_md.write_text(
        dedent(
            """\
            ---
            name: bad-agent
            description: now has description.
            role: reviewer
            model: fake
            status: active
            risk_level: low
            version: 0.1.0
            allowed_tools:
              - read_file
            allowed_skills: []
            memory_scope: none
            max_iterations_default: 1
            confirmation_policy: inherit_tool_policy
            supported_modes:
              - local_fake
            ---
            # bad-agent
            """
        ),
        encoding="utf-8",
    )
    registry.reload()
    assert len(registry.get_load_errors()) == 0
    assert registry.get_descriptor("bad-agent") is not None


def test_get_load_errors_empty_when_all_valid(tmp_path: Path) -> None:
    """所有 SUBAGENT.md 合法时 get_load_errors() 返回空列表。"""
    root = tmp_path / "subagents"
    _write_subagent(root, "agent-a")
    _write_subagent(root, "agent-b")

    registry = SubAgentRegistry(roots=[root])
    assert registry.get_load_errors() == []
    assert len(registry.list_visible()) == 2

