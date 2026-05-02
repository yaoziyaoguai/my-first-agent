"""Tooling responsibility boundary characterization tests.

这些测试只用 AST 扫描依赖方向，防止 Tooling Foundation 后续演进时把工具逻辑
塞回 core.py、display、checkpoint 或具体工具模块。它们不是重构实现，也不创建
gateway；只是先把 seam / 防火墙钉住。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _agent_imports(path: Path) -> set[str]:
    """收集 agent.* imports，避免用字符串 grep 误判注释和文档。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def test_concrete_tool_modules_do_not_depend_on_runtime_or_checkpoint_layers() -> None:
    """具体工具模块不应反向依赖 runtime orchestration。

    工具模块可以做本地 IO/safety helper，但不能 import core、response handlers、
    checkpoint 或 executor；否则未来 MCP/ToolSpec 接入会让具体工具倒灌 runtime。
    """

    forbidden = {
        "agent.core",
        "agent.response_handlers",
        "agent.confirm_handlers",
        "agent.tool_executor",
        "agent.checkpoint",
    }
    tool_paths = [
        path
        for path in (PROJECT_ROOT / "agent" / "tools").glob("*.py")
        if path.name != "__init__.py"
    ]

    offenders = {
        path.relative_to(PROJECT_ROOT).as_posix(): _agent_imports(path) & forbidden
        for path in tool_paths
        if _agent_imports(path) & forbidden
    }

    assert offenders == {}


def test_tool_executor_depends_on_registry_not_concrete_tool_modules() -> None:
    """executor 负责执行流程，但不能知道具体工具实现模块。

    这保护低耦合方向：executor 可以调用 registry 暴露的 execute/confirmation
    seam，但不能 import file_ops/shell/web 等具体工具，否则会成为新巨石。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "tool_executor.py")
    concrete_tool_imports = {
        import_name
        for import_name in imports
        if import_name.startswith("agent.tools.")
    }

    assert "agent.tool_registry" in imports
    assert "agent.tool_result_contract" in imports
    assert concrete_tool_imports == set()


def test_display_layer_does_not_execute_or_register_tools() -> None:
    """display layer 只能投影 RuntimeEvent，不能做工具决策。

    TUI/display 不应 import registry/executor/checkpoint 来直接执行或持久化工具状态；
    它只消费 runtime 给出的 display events。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "display_events.py")

    forbidden = {
        "agent.tool_registry",
        "agent.tool_executor",
        "agent.checkpoint",
        "agent.core",
    }
    assert imports.isdisjoint(forbidden)


def test_input_backends_do_not_touch_tool_execution_or_confirmation_layers() -> None:
    """input backend 只提交 UserInputEvent，不拥有工具确认或执行语义。

    这保护用户输入与工具确认的边界：simple/textual backend 可以收集文本、
    保留多行语义、渲染输入 UI，但不能 import tool_registry、tool_executor、
    confirm_handlers 或 checkpoint 来直接驱动 runtime state。
    """

    forbidden = {
        "agent.tool_registry",
        "agent.tool_executor",
        "agent.confirm_handlers",
        "agent.checkpoint",
        "agent.core",
    }
    backend_paths = (
        PROJECT_ROOT / "agent" / "input_backends" / "simple.py",
        PROJECT_ROOT / "agent" / "input_backends" / "textual.py",
    )

    offenders = {
        path.relative_to(PROJECT_ROOT).as_posix(): _agent_imports(path) & forbidden
        for path in backend_paths
        if _agent_imports(path) & forbidden
    }

    assert offenders == {}


def test_core_imports_registry_schema_but_not_concrete_tool_modules() -> None:
    """core.py 只做 orchestration，不知道具体工具实现。

    当前允许 core import `agent.tools` 触发注册，并从 `agent.tool_registry`
    读取 schema；但它不能 import `agent.tools.shell` 这类具体模块，也不能承载
    MCP 或具体工具业务逻辑。
    """

    imports = _agent_imports(PROJECT_ROOT / "agent" / "core.py")
    concrete_tool_imports = {
        import_name
        for import_name in imports
        if import_name.startswith("agent.tools.") and import_name != "agent.tools"
    }

    assert "agent.tools" in imports
    assert "agent.tool_registry" in imports
    assert concrete_tool_imports == set()


def test_mcp_is_not_wired_into_core_executor_or_registry_yet() -> None:
    """MCP 仍应停留在 Roadmap/discovery，不进入 runtime hot path。

    Tooling Foundation 还在收敛本地 ToolSpec/ToolResult/Safety；此时若 core、
    executor 或 registry 直接 import MCP，会过早污染本地工具 contract。
    """

    for relative_path in (
        "agent/core.py",
        "agent/tool_executor.py",
        "agent/tool_registry.py",
    ):
        imports = _agent_imports(PROJECT_ROOT / relative_path)
        assert all("mcp" not in import_name.lower() for import_name in imports)
