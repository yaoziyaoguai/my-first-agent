"""SubAgent Phase 9: Checkpoint / Resume Boundary tests."""

from __future__ import annotations

from dataclasses import asdict

from agent.subagent_system.checkpoint import (
    SubAgentCheckpointSummary,
    is_checkpoint_safe,
)


def test_checkpoint_summary_contains_only_bounded_correlation_metadata() -> None:
    """checkpoint 只保存恢复决策需要的摘要，不保存 raw prompt/transcript。"""

    summary = SubAgentCheckpointSummary(
        delegation_id="delegation-1",
        subagent_name="reviewer",
        status="interrupted",
        execution_mode="local_fake",
        iterations_used=1,
        max_iterations=3,
        parent_trace_id="trace-1",
        pending_confirmation=("shell_exec",),
        stop_reason="interrupted",
        revision_count=0,
    )
    data = asdict(summary)

    assert set(data) == {
        "delegation_id",
        "subagent_name",
        "status",
        "execution_mode",
        "iterations_used",
        "max_iterations",
        "parent_trace_id",
        "pending_confirmation",
        "stop_reason",
        "revision_count",
    }
    assert is_checkpoint_safe(data) is True


def test_checkpoint_safety_rejects_secrets_and_large_artifacts() -> None:
    """resume 不能通过 checkpoint 侧信道保存 secret 或大块上下文。"""

    assert is_checkpoint_safe({"summary": "sk-proj-abcdefghijklmnopqrstuvwxyz"}) is False
    assert is_checkpoint_safe({"raw_prompt": "x" * 60_000}) is False


def test_resume_summary_preserves_pending_confirmation_without_replay() -> None:
    """pending confirmation 只作为 parent re-adjudication 信号，不触发重放。"""

    summary = SubAgentCheckpointSummary(
        delegation_id="delegation-1",
        subagent_name="reviewer",
        status="needs_confirmation",
        execution_mode="local_fake",
        iterations_used=1,
        max_iterations=3,
        parent_trace_id="trace-1",
        pending_confirmation=("shell_exec",),
        stop_reason="needs_confirmation",
        revision_count=1,
    )

    assert summary.pending_confirmation == ("shell_exec",)
    assert summary.should_replay_tools is False

