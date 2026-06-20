"""S5-G04 checkpoint-ledger 协作测试。

锁定 AC-4：checkpoint 仍是唯一的状态恢复源；ledger 提供 durable 审计/进度连续性，
两者不得静默分歧。``record_checkpoint_boundary`` 在 checkpoint 保存边界派生记录；
``check_recovery_consistency`` 检测 missing checkpoint ref / stale ledger / 状态不匹配，
``report.ok`` 驱动 recovery 拒绝（AC-5：已完成步骤不得静默重复）。

这些测试在 cooperation 模块实现前必须失败（RED），实现后通过（GREEN）。
"""

from __future__ import annotations

from agent.task_ledger import (
    CheckpointRefRecord,
    StepProgressRecord,
    TaskLifecycleRecord,
)
from agent.task_ledger_cooperation import (
    check_recovery_consistency,
    latest_checkpoint_ref,
    record_checkpoint_boundary,
)
from agent.task_ledger_store import TaskLedger
from agent.task_state_model import (
    GovernedStepState,
    GovernedStepStatus,
    GovernedTaskLifecycle,
    GovernedTaskProgress,
    GovernedTaskState,
)


def _governed(
    lifecycle: GovernedTaskLifecycle = GovernedTaskLifecycle.RUNNING,
    completed_steps: int = 0,
    current_step: GovernedStepState | None = None,
) -> GovernedTaskState:
    return GovernedTaskState(
        lifecycle=lifecycle,
        raw_status=lifecycle.value,
        user_goal="demo goal",
        plan_goal="demo-plan",
        progress=GovernedTaskProgress(
            completed_steps=completed_steps,
            total_steps=max(completed_steps, 2),
            current_step_index=completed_steps,
        ),
        steps=(),
        current_step=current_step,
        blocking_reason=None,
        failure_reason=None,
        resumable=True,
    )


def _step(index: int, status: GovernedStepStatus) -> GovernedStepState:
    return GovernedStepState(
        index=index,
        step_id=f"s{index}",
        title=f"step {index + 1}",
        step_type=None,
        status=status,
    )


def _ledger_with(records, tmp_path):
    """直接落盘若干记录（绕过 record_checkpoint_boundary），用于喂养一致性检查器。"""
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    for record in records:
        ledger.append(record)
    return ledger


def test_consistency_ok_when_checkpoint_and_ledger_match(tmp_path):
    ledger = _ledger_with(
        [
            TaskLifecycleRecord("t1", 1, "r1", "running", "running", "g", "p"),
            StepProgressRecord("t1", 2, "r2", 0, "s0", "completed", "done"),
            CheckpointRefRecord("t1", 3, "r3", "/tmp/c.json", "step_boundary", "running"),
        ],
        tmp_path,
    )
    report = check_recovery_consistency(
        ledger.read_all(),
        checkpoint_ref_exists=True,
        governed_state=_governed(GovernedTaskLifecycle.RUNNING, completed_steps=1),
    )
    assert report.ok
    assert report.issues == ()


def test_consistency_flags_missing_checkpoint_ref(tmp_path):
    ledger = _ledger_with(
        [
            CheckpointRefRecord("t1", 1, "r1", "/tmp/gone.json", "step_boundary", "running"),
        ],
        tmp_path,
    )
    report = check_recovery_consistency(
        ledger.read_all(),
        checkpoint_ref_exists=False,
        governed_state=_governed(GovernedTaskLifecycle.RUNNING, completed_steps=0),
    )
    assert not report.ok
    assert any(i.kind == "missing_checkpoint_ref" for i in report.issues)


def test_consistency_flags_stale_ledger_when_checkpoint_ahead(tmp_path):
    # checkpoint 恢复出 2 个已完成步骤，ledger 只记录了 1 个 —— ledger stale。
    ledger = _ledger_with(
        [
            StepProgressRecord("t1", 1, "r1", 0, "s0", "completed", "done 0"),
            CheckpointRefRecord("t1", 2, "r2", "/tmp/c.json", "step_boundary", "running"),
        ],
        tmp_path,
    )
    report = check_recovery_consistency(
        ledger.read_all(),
        checkpoint_ref_exists=True,
        governed_state=_governed(GovernedTaskLifecycle.RUNNING, completed_steps=2),
    )
    assert not report.ok
    assert any(i.kind == "stale_ledger_entry" for i in report.issues)


def test_consistency_flags_mismatch_when_ledger_ahead_of_checkpoint(tmp_path):
    # ledger 记录了 2 个已完成步骤，checkpoint 只能恢复 1 个 —— 已完成工作会被重复。
    ledger = _ledger_with(
        [
            StepProgressRecord("t1", 1, "r1", 0, "s0", "completed", "done 0"),
            StepProgressRecord("t1", 2, "r2", 1, "s1", "completed", "done 1"),
            CheckpointRefRecord("t1", 3, "r3", "/tmp/c.json", "step_boundary", "running"),
        ],
        tmp_path,
    )
    report = check_recovery_consistency(
        ledger.read_all(),
        checkpoint_ref_exists=True,
        governed_state=_governed(GovernedTaskLifecycle.RUNNING, completed_steps=1),
    )
    assert not report.ok
    assert any(i.kind == "task_state_mismatch" for i in report.issues)


def test_consistency_flags_lifecycle_mismatch(tmp_path):
    ledger = _ledger_with(
        [
            TaskLifecycleRecord("t1", 1, "r1", "done", "done", "g", "p"),
            CheckpointRefRecord("t1", 2, "r2", "/tmp/c.json", "step_boundary", "done"),
        ],
        tmp_path,
    )
    report = check_recovery_consistency(
        ledger.read_all(),
        checkpoint_ref_exists=True,
        governed_state=_governed(GovernedTaskLifecycle.RUNNING, completed_steps=0),
    )
    assert not report.ok
    assert any(i.kind == "task_state_mismatch" for i in report.issues)


def test_record_checkpoint_boundary_appends_lifecycle_step_checkpoint(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    governed = _governed(
        GovernedTaskLifecycle.RUNNING,
        completed_steps=0,
        current_step=_step(0, GovernedStepStatus.ACTIVE),
    )
    appended = record_checkpoint_boundary(
        ledger,
        governed,
        task_id="t1",
        checkpoint_ref="/tmp/c.json",
        checkpoint_source="step_boundary",
        recorded_at="r1",
    )
    kinds = [type(r) for r in appended]
    assert kinds == [TaskLifecycleRecord, StepProgressRecord, CheckpointRefRecord]
    # 落盘后读回应包含这三条，seq 严格递增。
    records = ledger.read_all()
    assert [r.seq for r in records] == [1, 2, 3]
    assert latest_checkpoint_ref(records).checkpoint_ref == "/tmp/c.json"


def test_record_checkpoint_boundary_skips_unchanged_lifecycle(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    governed = _governed(GovernedTaskLifecycle.PLANNING, completed_steps=0)
    first = record_checkpoint_boundary(
        ledger, governed, task_id="t1", checkpoint_ref="/tmp/c1.json",
        checkpoint_source="plan", recorded_at="r1",
    )
    # 首次：lifecycle(None→planning) + checkpoint_ref。
    assert [type(r) for r in first] == [TaskLifecycleRecord, CheckpointRefRecord]
    second = record_checkpoint_boundary(
        ledger, governed, task_id="t1", checkpoint_ref="/tmp/c2.json",
        checkpoint_source="plan", recorded_at="r2",
    )
    # 同 lifecycle：跳过 lifecycle，只追加 checkpoint_ref。
    assert [type(r) for r in second] == [CheckpointRefRecord]


def test_record_boundary_then_consistency_ok(tmp_path):
    ledger = TaskLedger(tmp_path / "ledger.jsonl")
    governed = _governed(
        GovernedTaskLifecycle.RUNNING,
        completed_steps=1,
        current_step=_step(1, GovernedStepStatus.ACTIVE),
    )
    # 先补一条已完成的 step 记录，模拟 step 0 已完成。
    ledger.append(StepProgressRecord("t1", 1, "r0", 0, "s0", "completed", "done 0"))
    record_checkpoint_boundary(
        ledger, governed, task_id="t1", checkpoint_ref="/tmp/c.json",
        checkpoint_source="step_boundary", recorded_at="r1",
    )
    report = check_recovery_consistency(
        ledger.read_all(),
        checkpoint_ref_exists=True,
        governed_state=governed,
    )
    assert report.ok
