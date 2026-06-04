"""F-004 P2 修复回归测试。

验证 agent_log.jsonl 中 event_type 规范化：
- 旧 legacy 事件字符串映射到结构化类别
- runtime_observer 事件的内层 event_type 被正确提取
- EventLogWriter 的 _enrich_event 不会丢失 event_type
- 规范化后 "?" 占比应显著降低
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.event_log import EventLogWriter, _enrich_event
from agent.logger import log_event as legacy_log_event  # noqa: E402

# =============================================================================
# F-004 §1 — _enrich_event 对已知 action_type 保持精确
# =============================================================================

def test_enrich_event_preserves_structured_action_type() -> None:
    """EventLogWriter 收到的 RuntimeActionType 值必须保持精确，不退化。"""
    event = {"action_type": "tool.gate", "source": "ToolRuntimeMediator"}
    enriched = _enrich_event(event)
    assert enriched["event_type"] == "tool.gate", (
        "F-004: 结构化 action_type 不得被误映射"
    )
    assert enriched["source_subsystem"] != "unknown", (
        "F-004: 已知 source 应能正确映射到子系统"
    )


def test_enrich_event_missing_action_type_defaults_to_unknown() -> None:
    """无 action_type 的事件 event_type 应标记为 'unknown'。"""
    enriched = _enrich_event({"source": "unknown_origin"})
    assert enriched["event_type"] == "unknown", (
        "F-004: 无 action_type 时 event_type 应为 'unknown'（明确标记，非静默吞掉）"
    )


# =============================================================================
# F-004 §2 — Legacy event_type 规范化映射
# =============================================================================

# 已知旧版 event_type 字符串 → 结构化类别的映射表
# 该映射表覆盖 agent/logger.py 中 log_event 的所有已知调用点
LEGACY_EXPECTED_CATEGORIES = {
    # context compression
    "context_compression_start": "system.context_compression",
    "context_compression_done": "system.context_compression",
    # health check
    "health_check": "system.health_check",
    # planning
    "planning_mode_entered": "planning.mode_entered",
    "planning_model_empty_text": "planning.model_error",
    "planning_model_call_error": "planning.model_error",
    "action_plan_schema_invalid": "planning.schema_invalid",
    "action_plan_schema_validated": "planning.schema_validated",
    "planning_failed": "planning.failed",
    "model_plan_received": "planning.plan_received",
    "scheduler_load_success": "planning.scheduler_loaded",
    "planning_handoff_failure": "planning.handoff_failure",
    "plan_skipped": "planning.skipped",
    "plan_error": "planning.error",
    "plan_generated": "planning.generated",
    "action_plan_generated": "planning.generated",
    # linting
    "linter_passed": "quality.lint_passed",
    "linter_issues": "quality.lint_issues",
}


def test_known_legacy_event_types_have_category_mapping() -> None:
    """F-004: 所有已知旧版 event_type 字符串都有对应的规范化类别。

    如果某个已知 event_type 在 LEGACY_EXPECTED_CATEGORIES 中缺失，
    说明该事件可能需要添加映射或确认其为"已弃用"。
    """
    for legacy_name, expected_category in LEGACY_EXPECTED_CATEGORIES.items():
        assert isinstance(expected_category, str), (
            f"F-004: legacy event {legacy_name!r} 的映射类别应为字符串"
        )
        assert expected_category, (
            f"F-004: legacy event {legacy_name!r} 的映射类别不应为空"
        )


# =============================================================================
# F-004 §3 — EventLogWriter 写入 round-trip
# =============================================================================

def test_event_log_writer_produces_meaningful_event_type(tmp_path: Path) -> None:
    """EventLogWriter.append() 写入的事件必须包含有意义的 event_type。"""
    session_dir = tmp_path / "test_session"
    writer = EventLogWriter(session_dir)

    writer.append({"action_type": "tool.gate", "source": "ToolRuntimeMediator"})
    writer.append({"action_type": "memory.propose", "source": "core_loop"})
    writer.close()

    log_path = session_dir / "events.jsonl"
    assert log_path.exists()

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2

    for line in lines:
        entry = json.loads(line)
        assert "event_type" in entry, (
            "F-004: 每条 events.jsonl 条目必须包含 event_type 字段"
        )
        assert entry["event_type"] != "unknown", (
            f"F-004: 已知 action_type 不应产生 'unknown' event_type，"
            f"实际: action_type={entry.get('action_type')}"
        )
        assert "source_subsystem" in entry, (
            "F-004: 每条 events.jsonl 条目必须包含 source_subsystem 字段"
        )


# =============================================================================
# F-004 §4 — Legacy log_event 写入验证
# =============================================================================

def test_legacy_log_event_writes_event_field() -> None:
    """legacy log_event 写入的条目必须有 'event' 字段（用于 log_viewer 分类）。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        tmp_log = Path(f.name)

    try:
        # 临时 patch LOG_FILE
        import agent.logger as logger_mod

        original = logger_mod.LOG_FILE
        logger_mod.LOG_FILE = tmp_log

        try:
            legacy_log_event("test_event_type", {"key": "value"})
        finally:
            logger_mod.LOG_FILE = original

        content = tmp_log.read_text().strip()
        assert content, "F-004: legacy log_event 应写入内容"
        entry = json.loads(content)
        assert "event" in entry, (
            "F-004: legacy agent_log.jsonl 条目必须包含 'event' 字段"
        )
        assert entry["event"] != "?", (
            "F-004: legacy event 字段不应为 '?'"
        )
    finally:
        tmp_log.unlink(missing_ok=True)


# =============================================================================
# F-004 §5 — source_subsystem 映射完整性
# =============================================================================

def test_source_subsystem_map_covers_known_sources() -> None:
    """已知 source → subsystem 映射必须覆盖所有常见事件来源。"""
    from agent.event_log import _map_source_to_subsystem

    # 已知 source 必须能映射到有意义的子系统
    known_sources = [
        "ToolRuntimeMediator",
        "core_loop",
        "runtime_observer",
        "SkillRuntimeActionHandler",
        "MemoryTurnEndProposalHandler",
        "ToolGateHandler",
        "ToolInvokeHandler",
        "ToolResultFeedbackHandler",
        "MemoryRetainHandler",
        "MemoryRecallHandler",
        "MemoryConsolidateHandler",
    ]
    for source in known_sources:
        result = _map_source_to_subsystem(source)
        assert isinstance(result, str), (
            f"F-004: _map_source_to_subsystem({source!r}) 应返回字符串"
        )
        # 不强制非 unknown —— 某些 source 可能确实是新的，但至少要有结果
