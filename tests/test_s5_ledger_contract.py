"""S5-G01 契约测试：durable governed task ledger 的记录契约。

本文件锁定 S5 ledger 的「窄契约」(S5_GOAL.md §5/§6, AC-2/AC-7)：

- 四种记录类型 (task_lifecycle / step_progress / checkpoint_ref / evidence_ref)；
- 每种类型只承载 safe-summary / 引用字段，绝不承载 raw payload / raw secret；
- per-task_id 的 seq 严格递增（append-only 排序不变量）；
- 一个确定性的 reference recovery task，覆盖全部四种 kind 并定义 interruption/resume 边界。

这些测试在 ``agent/task_ledger.py`` 实现前必须失败（RED），实现后通过（GREEN）。
真正的 runtime 恢复 E2E 在 S5-G05；本文件只锁定契约与 reference 数据。
"""

from __future__ import annotations

import dataclasses

import pytest

from agent.task_ledger import (
    REFERENCE_RESUME_AFTER_SEQ,
    CheckpointRefRecord,
    EvidenceRefRecord,
    LedgerRecordKind,
    LedgerValidationError,
    StepProgressRecord,
    TaskLifecycleRecord,
    assert_monotonic_order,
    build_reference_recovery_records,
    validate_ledger_record,
)


def test_ledger_record_kinds_defined():
    # 四种记录 kind 的稳定字符串值，供 JSONL 持久化 (S5-G03) 与 redaction (S5-G02) 复用。
    assert LedgerRecordKind.TASK_LIFECYCLE.value == "task_lifecycle"
    assert LedgerRecordKind.STEP_PROGRESS.value == "step_progress"
    assert LedgerRecordKind.CHECKPOINT_REF.value == "checkpoint_ref"
    assert LedgerRecordKind.EVIDENCE_REF.value == "evidence_ref"


def test_task_lifecycle_record_carries_safe_contract_fields():
    record = TaskLifecycleRecord(
        task_id="t1",
        seq=1,
        recorded_at="2026-06-20T00:00:00Z",
        lifecycle="running",
        raw_status="running",
        user_goal="summarize the report",
        plan_goal="plan-a",
    )
    assert record.task_id == "t1"
    assert record.lifecycle == "running"
    # safe-summary 契约：只持有 goal 文本与状态，不持有任何 raw payload。
    assert record.user_goal == "summarize the report"


def test_step_progress_record_carries_safe_contract_fields():
    record = StepProgressRecord(
        task_id="t1",
        seq=2,
        recorded_at="2026-06-20T00:00:01Z",
        step_index=0,
        step_id="s0",
        step_status="completed",
        completion_summary="step 0 done",
    )
    assert record.step_index == 0
    assert record.step_status == "completed"
    assert record.completion_summary == "step 0 done"


def test_checkpoint_ref_record_carries_safe_contract_fields():
    # checkpoint_ref 是 checkpoint 文件路径字符串（引用，不是状态本体）——
    # checkpoint 仍是唯一的状态恢复源（AC-4）。
    record = CheckpointRefRecord(
        task_id="t1",
        seq=3,
        recorded_at="2026-06-20T00:00:02Z",
        checkpoint_ref="/tmp/s5/t1.json",
        checkpoint_source="step_boundary",
        task_status_at_save="running",
    )
    assert record.checkpoint_ref == "/tmp/s5/t1.json"
    assert record.checkpoint_source == "step_boundary"


def test_evidence_ref_record_carries_safe_contract_fields():
    # evidence_ref 是 ref_id（引用），safe_summary 是脱敏摘要——绝不存 raw 工具输出。
    record = EvidenceRefRecord(
        task_id="t1",
        seq=4,
        recorded_at="2026-06-20T00:00:03Z",
        evidence_ref="ev-step0-mark",
        evidence_kind="tool",
        safe_summary="step 0 mark_step_complete",
    )
    assert record.evidence_ref == "ev-step0-mark"
    assert record.evidence_kind == "tool"


@pytest.mark.parametrize(
    "task_id,seq,recorded_at",
    [
        ("", 1, "2026-06-20T00:00:00Z"),  # 空 task_id
        ("t1", -1, "2026-06-20T00:00:00Z"),  # 负 seq
        ("t1", 1, ""),  # 空 recorded_at
    ],
)
def test_validate_ledger_record_rejects_missing_identity(task_id, seq, recorded_at):
    record = TaskLifecycleRecord(
        task_id=task_id,
        seq=seq,
        recorded_at=recorded_at,
        lifecycle="running",
        raw_status="running",
        user_goal=None,
        plan_goal=None,
    )
    with pytest.raises(LedgerValidationError):
        validate_ledger_record(record)


def test_assert_monotonic_order_accepts_increasing_seq_per_task():
    records = [
        TaskLifecycleRecord("t1", 1, "t1", "planning", "awaiting_plan_confirmation", None, None),
        StepProgressRecord("t1", 2, "t2", 0, "s0", "active", None),
        CheckpointRefRecord("t1", 3, "t3", "/tmp/c.json", "step_boundary", "running"),
    ]
    # 不抛异常即通过：同一 task_id 内 seq 严格递增。
    assert_monotonic_order(records)


def test_assert_monotonic_order_allows_interleaved_tasks():
    # 多 task 共享一个 ledger 文件时，各自 seq 空间独立严格递增即可。
    records = [
        TaskLifecycleRecord("t1", 1, "t1", "planning", "awaiting_plan_confirmation", None, None),
        TaskLifecycleRecord("t2", 1, "t2", "planning", "awaiting_plan_confirmation", None, None),
        StepProgressRecord("t1", 2, "t3", 0, "s0", "active", None),
    ]
    assert_monotonic_order(records)


def test_assert_monotonic_order_rejects_non_increasing_seq():
    records = [
        TaskLifecycleRecord("t1", 1, "t1", "planning", "awaiting_plan_confirmation", None, None),
        # 同 task_id 出现重复 seq（非严格递增）——违反 append-only 排序不变量。
        StepProgressRecord("t1", 1, "t2", 0, "s0", "active", None),
    ]
    with pytest.raises(LedgerValidationError):
        assert_monotonic_order(records)


def test_reference_recovery_task_covers_all_record_kinds():
    records = build_reference_recovery_records()
    kinds = {type(r) for r in records}
    assert TaskLifecycleRecord in kinds
    assert StepProgressRecord in kinds
    assert CheckpointRefRecord in kinds
    assert EvidenceRefRecord in kinds


def test_reference_recovery_task_is_monotonically_ordered():
    records = build_reference_recovery_records()
    # reference task 自身必须满足排序契约。
    assert_monotonic_order(records)


def test_reference_recovery_task_defines_resume_boundary_with_remaining_work():
    records = build_reference_recovery_records()
    final_seq = records[-1].seq
    # 恢复点定义在某个已完成 checkpoint 边界之后、最终记录之前 —— 即中断后仍有未完成工作。
    assert final_seq > REFERENCE_RESUME_AFTER_SEQ
    # 恢复点之前的持久前缀必须自足：覆盖全部四种 kind，足以从 checkpoint+ledger 恢复。
    prefix = [r for r in records if r.seq <= REFERENCE_RESUME_AFTER_SEQ]
    prefix_kinds = {type(r) for r in prefix}
    assert {
        TaskLifecycleRecord,
        StepProgressRecord,
        CheckpointRefRecord,
        EvidenceRefRecord,
    } <= prefix_kinds


def test_reference_recovery_task_is_deterministic():
    # 两次构造必须逐字段相等 —— reference task 是确定性的 fake/local 数据（无真实时间源）。
    first = build_reference_recovery_records()
    second = build_reference_recovery_records()
    assert first == second


def test_ledger_contract_excludes_raw_secret_payload_fields():
    # AC-2/AC-7 硬边界：ledger 记录类型绝不暴露 raw payload / raw secret 字段。
    record_types = (
        TaskLifecycleRecord,
        StepProgressRecord,
        CheckpointRefRecord,
        EvidenceRefRecord,
    )
    all_fields: set[str] = set()
    for record_type in record_types:
        all_fields.update(f.name for f in dataclasses.fields(record_type))

    forbidden = {
        "payload",
        "raw_input",
        "raw_output",
        "tool_input",
        "tool_output",
        "secret",
        "secrets",
        "token",
        "api_key",
        "apikey",
        "credential",
        "credentials",
    }
    leaked = all_fields & forbidden
    assert not leaked, (
        f"ledger contract must not expose raw payload/secret fields, found: {leaked}"
    )
