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


def test_roadmap_records_observability_local_trace_foundation() -> None:
    """Stage 6 completion 需要记录 local-only trace 基础和真实日志边界。"""

    roadmap = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    closure = (PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md").read_text(
        encoding="utf-8"
    )

    required = (
        "Observability Local Trace Foundation 已完成",
        "agent.local_trace",
        "不读取真实 agent_log.jsonl",
        "不读取真实 sessions/runs",
        "local-only trace file",
    )
    for phrase in required:
        assert phrase in roadmap or phrase in closure


def test_roadmap_records_structured_tool_result_envelope_foundation() -> None:
    """Stage 7 要记录 ToolResult 结构化 seam，而不是只保留 prefix debt。"""

    roadmap = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    closure = (PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md").read_text(
        encoding="utf-8"
    )

    required = (
        "Structured ToolResult Envelope Foundation 已完成",
        "ToolResultEnvelope",
        "classify_tool_result",
        "legacy string contract 仍兼容",
        "error taxonomy",
    )
    for phrase in required:
        assert phrase in roadmap or phrase in closure
