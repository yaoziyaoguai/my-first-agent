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


def test_deferred_roadmap_boundaries_doc_exists() -> None:
    """只剩 planning-only 边界时，也要用文档说明为什么不能自动实现。"""

    text = (PROJECT_ROOT / "docs" / "DEFERRED_ROADMAP_BOUNDARIES.md").read_text(
        encoding="utf-8"
    )

    required = (
        "real MCP external integration",
        "runtime trace wiring",
        "ToolResult executor migration",
        "real Skill install/execution",
        "real Subagent provider delegation",
        "release/tag",
        "planning-only",
        "no real external integration",
        "no broad runtime/tool executor migration",
    )
    for phrase in required:
        assert phrase in text


def test_safe_local_release_readiness_doc_exists() -> None:
    """最终 release readiness 只能是可审计清单，不是 tag 授权。"""

    text = (PROJECT_ROOT / "docs" / "SAFE_LOCAL_RELEASE_READINESS.md").read_text(
        encoding="utf-8"
    )

    required = (
        "safe-local release readiness",
        "manual smoke checklist",
        "known limitations",
        "no tag authorization",
        "no real external integration",
        "verify v0.8.0 unchanged",
        "git push origin main only",
        "full pytest",
    )
    for phrase in required:
        assert phrase in text


def test_release_tag_preparation_doc_is_planning_only() -> None:
    """release/tag 准备只能形成 preflight evidence，不能变成实际打 tag。

    Remaining Roadmap 阶段允许继续推进 release readiness，但硬边界仍是：没有
    用户显式授权前不创建 tag、不发布 release、不 push tags。这个文档测试把
    preparation 与 execution 分开，避免后续 agent 把 checklist 误当授权。
    """

    prep = (PROJECT_ROOT / "docs" / "RELEASE_TAG_PREPARATION.md").read_text(
        encoding="utf-8"
    )
    readiness = (PROJECT_ROOT / "docs" / "SAFE_LOCAL_RELEASE_READINESS.md").read_text(
        encoding="utf-8"
    )
    closure = (
        PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")

    required = (
        "planning-only",
        "no tag creation",
        "no release creation",
        "no push tags",
        "pre-tag verification commands",
        "human authorization checklist",
        "rollback plan",
        "v0.8.0 unchanged",
    )
    for phrase in required:
        assert phrase in prep
    assert "RELEASE_TAG_PREPARATION.md" in readiness
    assert "RELEASE_TAG_PREPARATION.md" in closure


def test_mcp_external_integration_readiness_doc_is_fake_first() -> None:
    """真实 MCP external integration 之前，必须先有 fake-first readiness 证据。

    Remaining Roadmap 阶段允许把外部集成推进到 readiness，但不能偷换成真实
    endpoint/auth/network。这个测试要求文档说明 dry-run skeleton、opt-in guardrails
    和授权清单，确保下一步不会绕过 MCP config/service/tool registry 边界。
    """

    readiness = (
        PROJECT_ROOT / "docs" / "MCP_EXTERNAL_INTEGRATION_READINESS.md"
    ).read_text(encoding="utf-8")
    config_doc = (PROJECT_ROOT / "docs" / "MCP_CONFIG_MANAGEMENT.md").read_text(
        encoding="utf-8"
    )
    deferred = (PROJECT_ROOT / "docs" / "DEFERRED_ROADMAP_BOUNDARIES.md").read_text(
        encoding="utf-8"
    )

    required = (
        "fake-first",
        "dry-run only",
        "agent.mcp_external_readiness",
        "build_mcp_external_readiness_report",
        "no real MCP endpoint",
        "no network reachability check",
        "no secret read",
        "explicit opt-in guardrails",
        "local stdio fixture",
        "authorization checklist",
    )
    for phrase in required:
        assert phrase in readiness
    assert "MCP_EXTERNAL_INTEGRATION_READINESS.md" in config_doc
    assert "MCP_EXTERNAL_INTEGRATION_READINESS.md" in deferred


def test_runtime_trace_toolresult_migration_doc_is_compatibility_first() -> None:
    """runtime trace / ToolResult 剩余工作要先走 compatibility ledger。

    这两个方向都可能触碰 runtime hot path 或 tool executor，因此 Remaining Roadmap
    只能先记录 non-invasive adapter、compatibility shim、分阶段 stop condition，
    不能把 migration plan 误执行成 broad rewrite。
    """

    migration = (
        PROJECT_ROOT / "docs" / "RUNTIME_TRACE_TOOLRESULT_MIGRATION.md"
    ).read_text(encoding="utf-8")
    local_trace = (PROJECT_ROOT / "docs" / "LOCAL_TRACE_FOUNDATION.md").read_text(
        encoding="utf-8"
    )
    tool_result = (PROJECT_ROOT / "docs" / "TOOL_RESULT_ENVELOPE.md").read_text(
        encoding="utf-8"
    )

    required = (
        "runtime trace wiring",
        "ToolResult migration",
        "migration ledger",
        "non-invasive adapter",
        "compatibility shim",
        "LocalTraceRecorder",
        "ToolResultEnvelope",
        "no broad runtime rewrite",
        "no broad tool_executor rewrite",
    )
    for phrase in required:
        assert phrase in migration
    assert "RUNTIME_TRACE_TOOLRESULT_MIGRATION.md" in local_trace
    assert "RUNTIME_TRACE_TOOLRESULT_MIGRATION.md" in tool_result


def test_remaining_roadmap_completion_doc_records_final_authorization_boundaries() -> None:
    """Remaining Roadmap closure 要说明“已推进到 readiness”和“仍需授权”。

    这不是 release/tag，也不是真实外部集成；它把本阶段执行过的 bounded packs
    收束成 evidence packet，防止后续 agent 重复做已完成的 planning/readiness，
    或把仍需授权的真实动作误当成自动任务。
    """

    remaining = (
        PROJECT_ROOT / "docs" / "REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")
    roadmap = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    closure = (
        PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")

    required = (
        "Remaining Roadmap Completion Autopilot",
        "safe-local closure accepted",
        "release/tag preparation planning complete",
        "MCP external integration readiness complete",
        "runtime trace / ToolResult migration planning complete",
        "no tag",
        "no real MCP endpoint",
        "no broad runtime rewrite",
        "requires explicit user authorization",
        "human review ready",
    )
    for phrase in required:
        assert phrase in remaining
    assert "REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md" in roadmap
    assert "REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md" in closure


def test_human_review_packet_is_actionable_without_authorizing_release() -> None:
    """human review packet 要可执行 review，但不能授权 tag/release/真实集成。"""

    packet = (PROJECT_ROOT / "docs" / "HUMAN_REVIEW_PACKET.md").read_text(
        encoding="utf-8"
    )
    remaining = (
        PROJECT_ROOT / "docs" / "REMAINING_ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")
    closure = (
        PROJECT_ROOT / "docs" / "ROADMAP_COMPLETION_AUTOPILOT.md"
    ).read_text(encoding="utf-8")

    required = (
        "Human Review Packet",
        "review-only",
        "no tag authorization",
        "no release authorization",
        "no real MCP endpoint authorization",
        "review checklist",
        "quality gate evidence",
        "authorization decision matrix",
        "P0/P1/P2 stop conditions",
    )
    for phrase in required:
        assert phrase in packet
    assert "HUMAN_REVIEW_PACKET.md" in remaining
    assert "HUMAN_REVIEW_PACKET.md" in closure


def test_roadmap_near_term_plan_is_historical_not_active_menu() -> None:
    """旧 Near-term table 不能再诱导 agent 输出菜单而停止推进。"""

    roadmap = (PROJECT_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")

    assert "Historical Near-term Execution Plan" in roadmap
    assert "not an active menu" in roadmap
    assert "输出 + ask_user" not in roadmap
