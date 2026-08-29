from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTABLE = ROOT / "agent" / "automation"


def test_portable_automation_package_has_no_concrete_host_backend_import() -> None:
    forbidden = {
        "fcntl",
        "subprocess",
        "agent.process.group",
        "agent.sandbox.seatbelt",
        "agent.browser.playwright_adapter",
        "launchd",
        "systemd",
        "cron",
    }
    imported: set[str] = set()
    for path in PORTABLE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.casefold() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module.casefold())

    assert not any(
        item == blocked or item.startswith(f"{blocked}.")
        for item in imported
        for blocked in forbidden
    )


def test_reconciler_has_no_timer_loop_or_repository_cas_access() -> None:
    source = (PORTABLE / "reconcile.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "compare_and_swap" not in source
    assert "sleep(" not in source
    assert not any(isinstance(node, (ast.While, ast.AsyncFor)) for node in ast.walk(tree))


def test_only_controller_calls_repository_compare_and_swap() -> None:
    callers: list[str] = []
    for path in PORTABLE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compare_and_swap"
            for node in ast.walk(tree)
        ):
            callers.append(path.name)

    assert callers == ["controller.py"]


def test_portable_composition_exposes_no_management_tool_registration() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in PORTABLE.glob("*.py")
    )

    assert "build_tool_registrations" not in sources
    assert "ToolRegistration(" not in sources
    assert "time.sleep(" not in sources
    assert "asyncio.sleep(" not in sources
