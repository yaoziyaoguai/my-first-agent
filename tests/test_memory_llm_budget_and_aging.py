"""LLM evidence budget 与 recency aging signal 的 P3 hardening 测试。

这些测试验证轻量 char budget guard 和 recency_factor 的公开边界：
budget 只影响 LLM prompt 输入，不改变 validator / T1 pending；recency_factor
只影响 consolidation confidence，不会修改已持久化 memory。
"""

from __future__ import annotations

from pathlib import Path

from agent.memory_consolidation import EpisodicEvidence
from agent.memory_consolidation_engine import compute_recency_factor
from agent.memory_consolidation_llm import (
    EvidenceBudgetConfig,
    apply_evidence_budget,
    _build_evidence_context,
)
from agent.memory_fs_store import parse_memory_file, write_memory_section


def _evidence(record_id: str, content: str, created_at: str = "2026-05-16T00:00:00Z") -> EpisodicEvidence:
    return EpisodicEvidence(
        record_id=record_id,
        content=content,
        confidence=0.8,
        created_at=created_at,
        tags=("budget",),
    )


def test_apply_evidence_budget_limits_items_and_chars_without_raw_summary_leakage():
    """超预算 evidence 会被确定性限制，summary 只给计数不泄露正文。"""
    secret_like = "FAKE_API_KEY_DO_NOT_USE_123"
    evidence = [
        _evidence("ep1", "A" * 60),
        _evidence("ep2", f"B {secret_like} " + "B" * 60),
        _evidence("ep3", "C" * 60),
    ]

    result = apply_evidence_budget(
        evidence,
        EvidenceBudgetConfig(max_evidence_items=2, max_chars_per_evidence=10, max_total_chars=18),
    )

    assert [item.record_id for item in result.evidence] == ["ep1", "ep2"]
    assert all(len(item.content) <= 10 for item in result.evidence)
    assert result.summary.evidence_input_count == 3
    assert result.summary.evidence_used_count == 2
    assert result.summary.truncated_count == 3
    assert result.summary.total_chars_used <= 18
    assert result.summary.budget_applied is True
    assert secret_like not in result.summary.to_safe_dict().values()


def test_build_evidence_context_uses_budgeted_source_evidence_only():
    """LLM prompt context 只包含实际使用的 evidence，避免超预算输入进入 prompt。"""
    evidence = [_evidence(f"ep{i}", f"content-{i}" * 20) for i in range(5)]

    context = _build_evidence_context(
        evidence,
        budget=EvidenceBudgetConfig(max_evidence_items=2, max_chars_per_evidence=12, max_total_chars=30),
    )

    assert "record_id=ep0" in context
    assert "record_id=ep1" in context
    assert "record_id=ep2" not in context
    assert len(context) < 220


def test_small_input_budget_summary_reports_not_applied():
    """正常小输入不应被截断，budget summary 明确 budget_applied=false。"""
    evidence = [_evidence("ep1", "short"), _evidence("ep2", "small")]

    result = apply_evidence_budget(evidence)

    assert [item.content for item in result.evidence] == ["short", "small"]
    assert result.summary.budget_applied is False
    assert result.summary.truncated_count == 0


def test_recency_factor_newer_evidence_scores_higher_than_older():
    """recency_factor 是最小 aging signal：只影响 scoring，不写 store。"""
    now = 1_779_000_000.0
    newer = [_evidence("new", "new", created_at="2026-05-16T00:00:00Z")]
    older = [_evidence("old", "old", created_at="2025-05-16T00:00:00Z")]

    assert compute_recency_factor(newer, now_epoch=now) > compute_recency_factor(older, now_epoch=now)
    assert 0.0 <= compute_recency_factor(older, now_epoch=now) <= 1.0


def test_recency_factor_does_not_modify_persisted_records(tmp_path: Path):
    """aging policy 当前不做后台 decay，不修改已批准 memory record。"""
    filepath = tmp_path / "memory" / "semantic" / "user_preferences.md"
    write_memory_section(
        filepath,
        {
            "id": "rec-a",
            "memory_type": "semantic",
            "scope": "user",
            "approval_status": "approved",
            "confidence": 0.9,
        },
        "synthetic approved memory",
    )
    before = filepath.read_text(encoding="utf-8")

    compute_recency_factor([_evidence("old", "old", created_at="2025-05-16T00:00:00Z")])

    assert filepath.read_text(encoding="utf-8") == before
    assert parse_memory_file(filepath)[0]["approval_status"] == "approved"

