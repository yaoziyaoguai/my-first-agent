from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_single_runtime_provider_and_tool_call_sites_remain_in_agent_runtime() -> None:
    production = tuple((ROOT / "agent").rglob("*.py")) + (ROOT / "main.py",)
    provider_calls: list[Path] = []
    tool_calls: list[Path] = []
    runtime_definitions: list[Path] = []
    for path in production:
        source = path.read_text(encoding="utf-8")
        if "._provider.generate(" in source:
            provider_calls.append(path)
        if "._tool_runtime.invoke(" in source:
            tool_calls.append(path)
        if "def run_turn(" in source:
            runtime_definitions.append(path)

    expected = ROOT / "agent" / "runtime" / "loop.py"
    assert provider_calls == [expected]
    assert tool_calls == [expected]
    assert runtime_definitions == [expected]


def test_public_schedule_script_points_only_to_portable_cli() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'first-agent-schedule = "agent.automation.cli:main"' in pyproject
    assert 'first-agent-schedule = "main:run_schedule"' not in pyproject
