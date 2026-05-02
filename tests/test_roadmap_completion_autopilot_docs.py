"""Roadmap Completion Autopilot docs closure tests.

Pack 8 不实现新功能；它把本轮 MCP/Governance/Skill/Subagent fake-first 成果
写回 roadmap/release readiness 文档，避免后续误以为 Skill/Subagent 已经是真实
外部集成或 production activation。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_roadmap_records_safe_local_skill_and_subagent_mvp_status() -> None:
    """canonical roadmap 要记录 fake/local MVP 已完成和真实集成 deferred。"""

    text = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")

    required = (
        "MCP CLI Config Management safe apply governance 已完成",
        "Coding-agent execution governance 已落地 AGENTS.md",
        "Skill System Safe Local MVP 已完成",
        "Subagent System Safe Local MVP 已完成",
        "Skill/Subagent Integration Boundary 已完成",
        "真实 Skill install / execution 仍 deferred",
        "真实 LLM subagent delegation 仍 deferred",
    )
    for phrase in required:
        assert phrase in text


def test_roadmap_completion_autopilot_doc_has_release_readiness_packet() -> None:
    """总 closure doc 必须包含 completion matrix、packs、non-goals 和 tag policy。"""

    text = (PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md").read_text(
        encoding="utf-8"
    )

    required = (
        "Roadmap Completion Autopilot",
        "Completion matrix",
        "MCP CLI Config Management",
        "Coding-Agent Execution Governance",
        "Skill System Safe Local MVP",
        "Subagent System Safe Local MVP",
        "Skill/Subagent Integration Boundary",
        "Release readiness",
        "no tag",
        "no real external integration",
        "human review before release/tag",
    )
    for phrase in required:
        assert phrase in text
