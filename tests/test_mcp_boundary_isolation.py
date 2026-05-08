"""MCP 模块边界隔离测试。

中文学习边界：
- 本文件确保 MCP 相关模块（policy / sanitizer / audit / models / config）
  不会反向 import Runtime 主循环模块。
- 边界规则：MCP 层只能依赖 data models、token 工具、registry（薄依赖），
  不能依赖 core.py、checkpoint、confirm_handlers、response_handlers、
  task_runtime、planner、session、input_backends、display_events。
- 这些测试使用 AST 扫描，防止随重构意外引入 runtime 依赖。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = {
    "agent.core",
    "agent.checkpoint",
    "agent.confirm_handlers",
    "agent.response_handlers",
    "agent.task_runtime",
    "agent.planner",
    "agent.session",
    "agent.input_backends",
    "agent.display_events",
}


def _collect_agent_imports(path: Path) -> set[str]:
    """AST 扫描收集所有 agent.* imports。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name
                for alias in node.names
                if alias.name.startswith("agent")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(
                    f"agent.{alias.name}" for alias in node.names
                )
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


# ============================================================================
# policy / sanitizer / audit
# ============================================================================


def test_mcp_policy_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "mcp_policy.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"mcp_policy.py 不应 import: {bad}"


def test_mcp_sanitizer_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "mcp_sanitizer.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"mcp_sanitizer.py 不应 import: {bad}"


def test_mcp_audit_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "mcp_audit.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"mcp_audit.py 不应 import: {bad}"


def test_mcp_models_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "mcp_models.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"mcp_models.py 不应 import: {bad}"


def test_tool_audit_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "tool_audit.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"tool_audit.py 不应 import: {bad}"


def test_mcp_config_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "mcp_config.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"mcp_config.py 不应 import: {bad}"


def test_mcp_config_service_does_not_import_runtime():
    path = PROJECT_ROOT / "agent" / "mcp_config_service.py"
    bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
    assert bad == set(), f"mcp_config_service.py 不应 import: {bad}"


# ============================================================================
# MCP 模块整体互引用审计
# ============================================================================


def test_mcp_modules_have_clean_import_graph():
    """MCP 相关模块的导入图不应包含 runtime 跨层依赖。

    本测试只查 MCP 层 → runtime 层的单向依赖，不要求无环（mcp_models
    已打破之前的 mcp↔mcp_policy 循环）。
    """
    mcp_modules = [
        "agent/mcp_models.py",
        "agent/mcp_policy.py",
        "agent/mcp_sanitizer.py",
        "agent/mcp_audit.py",
        "agent/mcp.py",
        "agent/mcp_stdio.py",
        "agent/mcp_config.py",
        "agent/mcp_config_service.py",
        "agent/tool_audit.py",
    ]
    offenders: dict[str, set[str]] = {}
    for rel_path in mcp_modules:
        path = PROJECT_ROOT / rel_path
        if not path.exists():
            continue
        bad = _collect_agent_imports(path) & FORBIDDEN_IMPORTS
        if bad:
            offenders[rel_path] = bad
    assert offenders == {}, f"MCP/tool 模块不应 import runtime 模块: {offenders}"
