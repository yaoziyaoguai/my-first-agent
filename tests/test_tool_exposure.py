"""Tool exposure / context budget 测试。

中文学习边界：
- 验证 get_model_visible_tools() 对 MCP tools 有硬限制。
- 验证 raw MCP descriptor 不进入 model-visible tools。
- 验证 get_tool_definitions() 不受影响（完整 introspection API）。
- 验证 core.py model call 使用 bounded API。
"""

from __future__ import annotations

import pytest

from agent.tool_registry import (
    TOOL_REGISTRY,
    get_model_visible_tool_limits,
    get_tool_definitions,
    get_model_visible_tools,
    set_model_visible_tool_limits,
)


def _ensure_tools_loaded():
    """确保内置工具已注册。"""
    import agent.tools  # noqa: F401


# ============================================================================
# get_tool_definitions 保持不变
# ============================================================================


def test_get_tool_definitions_unchanged():
    """get_tool_definitions 继续返回完整注册表（introspection API）。"""
    _ensure_tools_loaded()
    definitions = get_tool_definitions()
    names = {d["name"] for d in definitions}
    assert "read_file" in names
    assert "write_file" in names
    assert "mark_step_complete" in names


# ============================================================================
# get_model_visible_tools 基础行为
# ============================================================================


def test_model_visible_tools_includes_builtins():
    """默认情况下内置工具仍可见。"""
    _ensure_tools_loaded()
    tools = get_model_visible_tools()
    names = {t["name"] for t in tools}
    assert "read_file" in names
    assert "write_file" in names


def test_model_visible_tools_exclude_internal_underscore_tools_even_when_allowlisted():
    """内部 `_` 工具不得进入模型可见清单。

    中文学习边界：
    `_safe_noop` 是 Tool branch behavior validation 的内部工具。显式 allowlist
    可以收窄工具集合，但不能绕过 hidden/internal 过滤，否则测试工具会暴露给模型。
    """
    _ensure_tools_loaded()

    default_names = {t["name"] for t in get_model_visible_tools()}
    allowlisted_names = {
        t["name"]
        for t in get_model_visible_tools(explicit_allowlist=frozenset({"_safe_noop"}))
    }

    assert "_safe_noop" in TOOL_REGISTRY
    assert "_safe_noop" not in default_names
    assert allowlisted_names == set()


def test_model_visible_tools_max_total():
    """max_total 硬限制生效。"""
    _ensure_tools_loaded()
    tools = get_model_visible_tools(max_total=3)
    assert len(tools) <= 3


def test_model_visible_tool_limits_reject_invalid_values():
    """模型可见工具 budget 只能收紧数量，非法值不能改写全局配置。"""

    before = get_model_visible_tool_limits()

    with pytest.raises(ValueError, match="max_total"):
        set_model_visible_tool_limits(max_total=0)
    with pytest.raises(ValueError, match="max_mcp"):
        set_model_visible_tool_limits(max_mcp=-1)

    assert get_model_visible_tool_limits() == before


def test_model_visible_tools_max_mcp_tools():
    """max_mcp_tools 硬限制生效。"""
    _ensure_tools_loaded()
    # 当前没有 MCP tools，限制应正常工作
    tools = get_model_visible_tools(max_mcp_tools=0)
    mcp_names = [
        t["name"] for t in tools
        if t["name"].startswith("mcp__")
    ]
    assert len(mcp_names) == 0


def test_model_visible_tools_explicit_allowlist():
    """explicit allowlist 只返回指定工具。"""
    _ensure_tools_loaded()
    tools = get_model_visible_tools(
        explicit_allowlist=frozenset({"read_file", "write_file"}),
    )
    names = {t["name"] for t in tools}
    assert names == {"read_file", "write_file"}


def test_model_visible_tools_include_capabilities():
    """include_capabilities 过滤生效。"""
    _ensure_tools_loaded()
    tools = get_model_visible_tools(
        include_capabilities=frozenset({"file_read"}),
    )
    for t in tools:
        info = TOOL_REGISTRY.get(t["name"], {})
        assert info.get("capability") == "file_read"


def test_model_visible_tools_exclude_capabilities():
    """exclude_capabilities 过滤生效。"""
    _ensure_tools_loaded()
    tools = get_model_visible_tools(
        exclude_capabilities=frozenset({"runtime_control"}),
    )
    names = {t["name"] for t in tools}
    assert "mark_step_complete" not in names
    assert "request_user_input" not in names


def test_model_visible_tools_metatools_excluded_by_default():
    """元工具应可通过 exclude_capabilities 排除，但默认包含。"""
    _ensure_tools_loaded()
    tools_all = get_model_visible_tools()
    names_all = {t["name"] for t in tools_all}
    # 默认包含元工具
    assert "mark_step_complete" in names_all

    # 排除 runtime_control 后不包含
    tools_no_meta = get_model_visible_tools(
        exclude_capabilities=frozenset({"runtime_control"}),
    )
    names_no_meta = {t["name"] for t in tools_no_meta}
    assert "mark_step_complete" not in names_no_meta


# ============================================================================
# core.py model call 验证
# ============================================================================


def test_core_uses_bounded_tool_exposure():
    """core.py 的 _call_model 应使用 get_model_visible_tools 而非 get_tool_definitions。"""
    import ast
    from pathlib import Path

    core_path = Path(__file__).resolve().parents[1] / "agent" / "core.py"
    core_text = core_path.read_text(encoding="utf-8")

    # 验证 tools 参数使用 bounded API
    assert "get_model_visible_tools" in core_text

    # 验证 import
    tree = ast.parse(core_text)
    from_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "agent.tool_registry":
            from_imports = [alias.name for alias in node.names]
    assert "get_model_visible_tools" in from_imports
