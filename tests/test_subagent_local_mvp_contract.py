"""Subagent System Safe Local MVP contract tests.

Subagent MVP 只能提供 fake/local profile 和 delegation request/result contract：
- 不启动真实 LLM；
- 不 spawn 外部进程；
- 不让 child 自主调用工具；
- parent runtime/tool policy 始终保留控制权；
- 输出必须 redacted。
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "agent" / "subagents" / "local.py"
FIXTURE_PROFILE = PROJECT_ROOT / "tests" / "fixtures" / "subagents" / "code-reviewer"


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_valid_local_fixture_subagent_profile_is_descriptor_only() -> None:
    """valid profile 只生成 metadata，不启动 child agent。"""

    from agent.subagents.local import load_local_subagent_profile

    result = load_local_subagent_profile(FIXTURE_PROFILE)

    assert result.ok is True
    assert result.profile is not None
    assert result.profile.name == "code-reviewer"
    assert result.profile.model == "fake"
    assert result.profile.allowed_tools == ("read_file",)
    assert result.profile.policy.local_only is True
    assert result.profile.policy.real_llm_delegation_allowed is False
    assert result.profile.policy.external_process_allowed is False
    assert result.profile.policy.autonomous_tool_execution_allowed is False


def test_invalid_profile_and_unsafe_paths_are_rejected(tmp_path) -> None:
    """subagent loader 不读真实用户 profile 目录，也不碰敏感路径。"""

    from agent.subagents.local import load_local_subagent_profile

    invalid_profile = tmp_path / "bad-profile"
    invalid_profile.mkdir()
    (invalid_profile / "SUBAGENT.md").write_text(
        "---\nname: Bad Name\n---\nbody",
        encoding="utf-8",
    )
    unsafe_paths = (
        Path.home() / ".claude" / "agents" / "private-agent",
        tmp_path / ".env",
        tmp_path / "sessions" / "agent",
        tmp_path / "secret-agent",
    )

    assert load_local_subagent_profile(invalid_profile).errors[0].code == "invalid_profile"
    for path in unsafe_paths:
        result = load_local_subagent_profile(path)
        assert result.ok is False
        assert result.errors[0].code == "unsafe_path"


def test_real_llm_process_and_tool_bypass_profiles_are_rejected(tmp_path) -> None:
    """local MVP 不能悄悄变成真实 LLM delegation 或 child process。"""

    from agent.subagents.local import load_local_subagent_profile

    cases = {
        "real-llm": (
            "---\nname: real-llm\n"
            "description: bad\nrole: reviewer\nmodel: claude-sonnet\n---\n"
            "Delegate to a real provider."
        ),
        "process-agent": (
            "---\nname: process-agent\n"
            "description: bad\nrole: runner\nmodel: fake\n"
            "metadata:\n  command: python child.py\n---\n"
            "Spawn a subprocess."
        ),
        "tool-bypass": (
            "---\nname: tool-bypass\n"
            "description: bad\nrole: runner\nmodel: fake\n"
            "allowed-tools:\n  - run_shell\n---\n"
            "Call tool directly without parent policy."
        ),
    }
    expected_codes = {"real_llm_delegation", "external_process", "policy_bypass"}

    for name, content in cases.items():
        profile_dir = tmp_path / name
        profile_dir.mkdir()
        (profile_dir / "SUBAGENT.md").write_text(content, encoding="utf-8")

        result = load_local_subagent_profile(profile_dir)

        assert result.ok is False
        assert result.errors[0].code in expected_codes


def test_delegation_request_result_are_parent_controlled_and_redacted() -> None:
    """delegation 只是结构化请求/结果；parent policy 决定能否使用。"""

    from agent.subagents.local import build_delegation_request
    from agent.subagents.local import complete_fake_delegation
    from agent.subagents.local import format_delegation_result_for_display
    from agent.subagents.local import load_local_subagent_profile

    profile_result = load_local_subagent_profile(FIXTURE_PROFILE)
    profile = profile_result.profile

    blocked = build_delegation_request(
        profile,
        task="review this file",
        parent_allowed_tools=(),
    )
    assert blocked.ok is False
    assert blocked.errors[0].code == "policy_bypass"

    request_result = build_delegation_request(
        profile,
        task="review this file",
        parent_allowed_tools=("read_file",),
    )
    assert request_result.ok is True
    assert request_result.request is not None
    assert request_result.request.parent_controlled is True
    assert request_result.request.allowed_tools == ("read_file",)

    result = complete_fake_delegation(
        request_result.request,
        summary="Looks safe. API_KEY=literal-secret-value should not print.",
    )
    rendered = format_delegation_result_for_display(result)
    combined = f"{result!r}\n{rendered}"
    assert result.ok is True
    assert "literal-secret-value" not in combined
    assert "API_KEY" in combined
    assert "<redacted>" in combined


def test_subagent_local_mvp_has_no_runtime_network_process_or_provider_dependencies() -> None:
    """subagent MVP 不能 import runtime/provider/process/network。"""

    forbidden_modules = {
        "subprocess",
        "socket",
        "http.client",
        "urllib",
        "requests",
        "agent.core",
        "agent.tool_executor",
        "agent.tools",
        "llm",
    }

    assert _module_imports(MODULE_PATH).isdisjoint(forbidden_modules)


def test_subagent_local_mvp_docs_record_non_goals() -> None:
    """docs 必须说明 Subagent MVP 不是真实 LLM/进程/remote delegation。"""

    text = (PROJECT_ROOT / "docs" / "SUBAGENT_LOCAL_MVP.md").read_text(encoding="utf-8")

    for phrase in (
        "fake/local profile + delegation contract",
        "no real subagent dirs",
        "no real LLM/provider",
        "no external process spawn",
        "no remote delegation",
        "no autonomous child tool execution",
        "parent runtime remains in control",
        "does not import runtime",
    ):
        assert phrase in text
