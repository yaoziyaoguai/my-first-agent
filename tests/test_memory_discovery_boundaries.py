"""Stage 3 Memory Discovery boundary tests.

这些测试不是 Memory implementation，也不读取真实 `memory/` 数据。它们只把
post-tools 之后第一组 readiness 边界钉住：Memory Discovery 必须先解释
memory / checkpoint / session summary / skills / MCP 的边界，不能一开始就把
runtime、TUI、MCP、checkpoint schema 或真实历史数据拉进来。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMORY_MODULE = PROJECT_ROOT / "agent" / "memory.py"
ROADMAP = PROJECT_ROOT / "docs" / "ROADMAP.md"


def _agent_imports(path: Path) -> set[str]:
    """用 AST 收集 agent.* imports，避免用脆弱 grep 判断架构依赖。"""

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


def _called_names(path: Path) -> set[str]:
    """收集源码中的 call 名称，确认 discovery 不读取真实 artifact。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_memory_module_does_not_import_runtime_checkpoint_tui_or_mcp_layers() -> None:
    """Memory Discovery 不能反向依赖 runtime hot path。

    Memory 是长期语义层；checkpoint 是崩溃/恢复层；TUI/input backend 是交互
    adapter；MCP client 是外部 tool protocol seam。Discovery 阶段若让
    `agent.memory` import 这些层，会在设计还没完成前制造新巨石。
    """

    imports = _agent_imports(MEMORY_MODULE)

    forbidden = {
        "agent.core",
        "agent.checkpoint",
        "agent.input_backends",
        "agent.mcp",
        "agent.mcp_stdio",
        "agent.tool_executor",
        "agent.tools",
    }
    assert imports.isdisjoint(forbidden), imports & forbidden


def test_memory_module_does_not_read_or_write_real_memory_artifacts() -> None:
    """Discovery readiness 不允许偷偷读取真实 `memory/` 数据。

    当前 `agent.memory` 只能处理 in-memory messages 和静态 prompt section；
    retain/recall/update/forget、artifact migration、privacy policy 都还没有
    设计完成。因此这里先用 AST 钉住：不能出现 open/read_text/write_text/glob
    等文件 IO 入口，避免把历史 memory 数据当作实现捷径。
    """

    calls = _called_names(MEMORY_MODULE)

    assert {"open", "read_text", "write_text", "glob", "iterdir"}.isdisjoint(calls)


def test_build_memory_section_is_static_placeholder_not_real_memory_reader() -> None:
    """当前 memory section 只是占位，不代表长期记忆已经实现。

    这个断言保护的是诚实边界：system prompt 可以说明“当前未注入长期记忆”，
    但不能在没有 approval / privacy / provider seam 前读取真实记忆并注入。
    """

    from agent.memory import build_memory_section

    assert build_memory_section() == "[Memory]\n当前未注入长期记忆。"


def test_roadmap_records_memory_discovery_questions_before_implementation() -> None:
    """Roadmap 必须先记录 discovery 问题，再允许实现 Memory。

    如果后续有人直接加 embedding、RAG、vector DB 或自动 retain 逻辑，却没有
    先回答这些问题，本测试会提醒：Stage 3 的第一步是 architecture discovery，
    不是 provider-first implementation。
    """

    text = ROADMAP.read_text(encoding="utf-8")

    required_markers = [
        "Memory **不是 checkpoint**",
        "What should be remembered?",
        "retain / recall / update / forget",
        "provider seam",
        "不直接做 RAG / retrieval / embedding / vector DB",
    ]
    for marker in required_markers:
        assert marker in text
