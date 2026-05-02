"""Repo-level coding-agent guidance contract.

Roadmap Completion Autopilot 需要把反复出现的执行边界沉淀到 AGENTS.md，
这样后续 Coding Agent 不必依赖每轮超长 prompt 才知道安全边界、质量门和
push/tag 规则。本测试只约束 repo guidance 文档，不实现任何功能。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"


def test_agents_guidance_exists_with_project_specific_boundaries() -> None:
    """AGENTS.md 必须是本 repo 的可执行治理规则，不是泛泛 AI 编程建议。"""

    text = AGENTS_PATH.read_text(encoding="utf-8")

    required_phrases = (
        "/Users/jinkun.wang/work_space/my-first-agent",
        "my-first-agent",
        "no .env",
        "no agent_log.jsonl contents",
        "no real sessions/runs",
        "no real MCP config",
        "no real skill dirs",
        "no real subagent dirs",
        "no real LLM/provider/MCP",
        "git push origin main",
        "no push --tags",
        "no force push",
        "v0.8.0",
        "P0/P1/P2",
        "evidence packet",
        ".venv/bin/ruff check .",
        ".venv/bin/python -m pytest -q -rx",
    )
    for phrase in required_phrases:
        assert phrase in text


def test_agents_guidance_keeps_architecture_and_roadmap_boundaries() -> None:
    """指导文档必须防止重构漂移和 Skill/Subagent 越权。"""

    text = AGENTS_PATH.read_text(encoding="utf-8")

    required_phrases = (
        "no broad refactor",
        "no framework migration",
        "no LangGraph conversion",
        "no memory activation",
        "runtime/memory/tool executor",
        "fake-first",
        "local-only",
        "parent runtime remains in control",
        "Chinese learning comments/docstrings",
    )
    for phrase in required_phrases:
        assert phrase in text
