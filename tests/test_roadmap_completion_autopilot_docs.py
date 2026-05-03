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
        "MCP_CONFIG_MANAGEMENT.md",
        "tests/fixtures/mcp_config/safe-mcp.json",
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
        "LOCAL_TRACE_FOUNDATION.md",
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
        "TOOL_RESULT_ENVELOPE.md",
        "classify_tool_result",
        "legacy string contract 仍兼容",
        "error taxonomy",
    )
    for phrase in required:
        assert phrase in roadmap or phrase in closure


def test_roadmap_records_local_config_foundation() -> None:
    """Stage 8 local productization 需要 safe-path config foundation。"""

    roadmap = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    closure = (PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md").read_text(
        encoding="utf-8"
    )

    required = (
        "Local Config Foundation 已完成",
        "agent.local_config",
        "ProjectProfile",
        "SafetyPolicy",
        "ModuleToggles",
        "ModelProviderConfig",
        "不读取真实 home config",
        "LOCAL_CONFIG_FOUNDATION.md",
        "tests/fixtures/local_config/agent.local.json",
    )
    for phrase in required:
        assert phrase in roadmap or phrase in closure


def test_roadmap_no_longer_lists_historical_xfails_as_open_backlog() -> None:
    """Roadmap 不能把已关闭的历史 XFAIL 再描述成待办。

    这个测试是 review remediation：XFAIL-1 / XFAIL-2 已通过显式
    ``awaiting_feedback_intent`` 与 TUI projection cancel 收口。Roadmap 可以保留
    历史来源和 provider-abort deferred 边界，但不能继续说它们仍是 open backlog，
    否则后续 agent 会重复进入已经关闭的 TUI/runtime 路径。
    """

    roadmap = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")

    assert "历史 XFAIL backlog 已收口" in roadmap
    assert "safe local roadmap closure final review" in roadmap
    assert "真实 provider stream abort / cancel_token 仍是后续单独 runtime lifecycle 设计" in roadmap
    stale_phrases = (
        "known XFAIL 收口",
        "XFAIL-1 / XFAIL-2 保留为独立 backlog",
        "XFAIL-1 / XFAIL-2 仍需单独立项",
        "不要处理 XFAIL-1 / XFAIL-2",
    )
    for phrase in stale_phrases:
        assert phrase not in roadmap


def test_autopilot_closure_doc_records_status_alignment_review() -> None:
    """Autopilot closure doc 要记录最终 review remediation。

    这是 evidence hygiene，不是新功能：当 ROADMAP 因强 review 修正文案后，closure
    doc 也要说明该修正属于 P3 docs drift，而不是新的 runtime/TUI work。否则后续
    agent 只能从 git log 推断为什么又有 docs commit。
    """

    closure = (
        PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")

    required = (
        "Roadmap Status Alignment Review",
        "P3 docs drift",
        "historical XFAIL backlog is closed",
        "no production/runtime change",
    )
    for phrase in required:
        assert phrase in closure
