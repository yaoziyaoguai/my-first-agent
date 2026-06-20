"""S5-G11 operator-facing ledger summary 测试。

锁定 AC-8/AC-10：一个紧凑、redacted 的 operator 摘要，包含 lifecycle/checkpoint refs，
排除 raw payload / secret。``render_ledger_summary`` 渲染人读视图，``ledger_summary_stats``
返回结构化计数；二者都只用 refs/counts/lifecycle，结构上 secret-free。

这些测试在 ``agent.ledger_summary`` 实现前必须失败（RED）。
"""

from __future__ import annotations

from agent.ledger_summary import ledger_summary_stats, render_ledger_summary
from agent.task_ledger import (
    CheckpointRefRecord,
    EvidenceRefRecord,
    StepProgressRecord,
    TaskLifecycleRecord,
)
from agent.task_ledger_store import TaskLedger

_SECRET = "sk-leaksurvives123456"


def _sample_records():
    return [
        TaskLifecycleRecord("t1", 1, "r1", "planning", "awaiting_plan_confirmation", "g", "p"),
        TaskLifecycleRecord("t1", 2, "r2", "running", "running", "g", "p"),
        StepProgressRecord("t1", 3, "r3", 0, "s0", "completed", "done 0"),
        CheckpointRefRecord("t1", 4, "r4", "/tmp/c1.json", "step_boundary", "running"),
        EvidenceRefRecord("t1", 5, "r5", "ev-1", "tool", "summary"),
        TaskLifecycleRecord("t1", 6, "r6", "done", "done", "g", "p"),
    ]


def test_render_ledger_summary_includes_lifecycle_and_checkpoint_refs():
    text = render_ledger_summary(_sample_records())
    assert "task=t1" in text
    assert "planning -> running -> done" in text
    assert "/tmp/c1.json" in text
    assert "completed_steps" in text


def test_ledger_summary_stats_counts_records():
    stats = ledger_summary_stats(_sample_records())
    assert set(stats) == {"t1"}
    s = stats["t1"]
    assert s["record_count"] == 6
    assert s["lifecycle_transitions"] == 3
    assert s["checkpoint_ref_count"] == 1
    assert s["latest_checkpoint_ref"] == "/tmp/c1.json"
    assert s["completed_step_count"] == 1
    assert s["evidence_ref_count"] == 1


def test_render_ledger_summary_handles_empty_ledger():
    text = render_ledger_summary([])
    assert "empty" in text
    assert ledger_summary_stats([]) == {}


def test_render_ledger_summary_groups_multiple_tasks():
    records = _sample_records() + [
        TaskLifecycleRecord("t2", 1, "r1", "running", "running", "g2", "p2"),
        CheckpointRefRecord("t2", 2, "r2", "/tmp/c2.json", "step_boundary", "running"),
    ]
    stats = ledger_summary_stats(records)
    assert set(stats) == {"t1", "t2"}
    text = render_ledger_summary(records)
    assert "task=t1" in text
    assert "task=t2" in text


def test_render_ledger_summary_excludes_raw_secrets(tmp_path):
    # 注入合成 secret 到 safe_summary，经 append redact；渲染摘要不得出现 secret。
    ledger = TaskLedger(tmp_path / "l.jsonl")
    ledger.append(
        EvidenceRefRecord("t1", 1, "r1", "ev-1", "tool", f"preview {_SECRET}")
    )
    records = ledger.read_all()
    # 持久化记录的 safe_summary 已被 redact。
    assert _SECRET not in (records[0].safe_summary or "")
    assert "[REDACTED]" in records[0].safe_summary
    # 摘要结构上只用 refs/counts/lifecycle —— 不含 secret。
    text = render_ledger_summary(records)
    assert _SECRET not in text
