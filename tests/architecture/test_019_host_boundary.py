from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_macos_host_profile_delegates_to_existing_composition_without_a_second_loop() -> None:
    path = ROOT / "agent" / "automation_hosts" / "macos_profile.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    run_turn_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_turn"
    ]

    assert "build_composition" in called
    assert "AgentRuntime" not in source
    assert run_turn_calls == []
    assert ".generate(" not in source
    assert ".invoke(" not in source


def test_portable_automation_does_not_import_the_macos_host_profile() -> None:
    for path in (ROOT / "agent" / "automation").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "automation_hosts" not in source, path


def test_macos_occurrence_surface_contains_no_automation_management_tools() -> None:
    from agent.automation_hosts.macos_profile import BACKGROUND_TOOL_NAMES

    assert frozenset(
        {
            "sandbox_exec",
            "browser_open",
            "browser_observe",
            "browser_act",
            "browser_close",
            "browser_begin_takeover",
        }
    ) == BACKGROUND_TOOL_NAMES
