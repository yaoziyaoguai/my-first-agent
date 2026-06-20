"""S5-G11 operator-facing ledger summary（紧凑、redacted 的人读 + 结构化摘要）。

把 durable ledger 渲染成 operator 可快速浏览的视图：按 task 分组的 lifecycle 链、
checkpoint refs、已完成步骤数、evidence ref 数。**只**用 refs / counts / lifecycle 值，
不渲染任何 summary / preview 文本——结构上 secret-free（AC-7/AC-8/AC-10）。记录在落盘
时已由 ``redact_ledger_record`` 脱敏，本模块只做只读投影。
"""

from __future__ import annotations

from agent.task_ledger import (
    CheckpointRefRecord,
    EvidenceRefRecord,
    LedgerRecord,
    StepProgressRecord,
    TaskLifecycleRecord,
)


def ledger_summary_stats(records: list[LedgerRecord]) -> dict:
    """按 task_id 聚合的结构化计数（全为 refs/counts/lifecycle，无 content）。"""

    per_task: dict[str, dict] = {}
    for record in records:
        bucket = per_task.setdefault(
            record.task_id,
            {
                "record_count": 0,
                "lifecycles": [],
                "checkpoint_refs": [],
                "completed_steps": set(),
                "evidence_refs": [],
            },
        )
        bucket["record_count"] += 1
        if isinstance(record, TaskLifecycleRecord):
            bucket["lifecycles"].append(record.lifecycle)
        elif isinstance(record, StepProgressRecord):
            if record.step_status == "completed":
                bucket["completed_steps"].add(record.step_index)
        elif isinstance(record, CheckpointRefRecord):
            bucket["checkpoint_refs"].append(record.checkpoint_ref)
        elif isinstance(record, EvidenceRefRecord):
            bucket["evidence_refs"].append(record.evidence_ref)

    return {
        task_id: {
            "record_count": bucket["record_count"],
            "lifecycle_transitions": len(bucket["lifecycles"]),
            "lifecycles": bucket["lifecycles"],
            "checkpoint_ref_count": len(bucket["checkpoint_refs"]),
            "latest_checkpoint_ref": (
                bucket["checkpoint_refs"][-1] if bucket["checkpoint_refs"] else None
            ),
            "completed_step_count": len(bucket["completed_steps"]),
            "evidence_ref_count": len(bucket["evidence_refs"]),
        }
        for task_id, bucket in per_task.items()
    }


def render_ledger_summary(records: list[LedgerRecord]) -> str:
    """渲染紧凑、redacted 的 operator 摘要（每 task 一段；refs/counts/lifecycle only）。"""

    stats = ledger_summary_stats(records)
    lines = [f"Ledger summary: tasks={len(stats)} records={len(records)}"]
    if not stats:
        lines.append("  (empty — no ledger records)")
        return "\n".join(lines)
    for task_id, summary in stats.items():
        lifecycles = summary["lifecycles"]
        lifecycle_chain = " -> ".join(lifecycles) if lifecycles else "(none)"
        lines.append(f"  task={task_id}:")
        lines.append(f"    lifecycle: {lifecycle_chain}")
        lines.append(
            f"    checkpoint_refs: {summary['checkpoint_ref_count']} "
            f"(latest={summary['latest_checkpoint_ref']})"
        )
        lines.append(f"    completed_steps: {summary['completed_step_count']}")
        lines.append(f"    evidence_refs: {summary['evidence_ref_count']}")
    return "\n".join(lines)
