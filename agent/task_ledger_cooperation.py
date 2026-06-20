"""S5-G04 checkpoint-ledger 协作层。

把 durable ledger 接到 governed task 的 checkpoint 边界，并提供恢复时的一致性检查：

- ``record_checkpoint_boundary``：在 checkpoint 保存边界，从 ``GovernedTaskState`` 派生
  lifecycle / step / checkpoint_ref 记录并经 ``TaskLedger.append`` 落盘（append 内部
  会 redact + 校验 + 强制 seq）。**不**读写 checkpoint 文件本身——checkpoint 仍是
  唯一的状态恢复源（AC-4）。
- ``check_recovery_consistency``：恢复后比对 ledger 记录与恢复出的状态，检测
  missing checkpoint ref / stale ledger / 状态不匹配；``report.ok`` 驱动 recovery
  拒绝（AC-5：已完成步骤不得静默重复）。

边界：本层不执行工具、不跑 loop、不绕过 policy/approval/evidence seam（AC-6）。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.task_ledger import (
    CheckpointRefRecord,
    LedgerRecord,
    StepProgressRecord,
    TaskLifecycleRecord,
)
from agent.task_ledger_store import TaskLedger
from agent.task_state_model import GovernedTaskState


def latest_checkpoint_ref(records: list[LedgerRecord]) -> CheckpointRefRecord | None:
    """返回 ledger 中最后一条 checkpoint_ref 记录（按 seq 顺序）。"""

    latest = None
    for record in records:
        if isinstance(record, CheckpointRefRecord):
            latest = record
    return latest


def latest_ledger_lifecycle(records: list[LedgerRecord]) -> str | None:
    """返回 ledger 中最后一条 task_lifecycle 记录的 lifecycle 值。"""

    latest = None
    for record in records:
        if isinstance(record, TaskLifecycleRecord):
            latest = record.lifecycle
    return latest


def ledger_completed_step_count(records: list[LedgerRecord]) -> int:
    """返回 ledger 中被记为 completed 的不同 step_index 数量。"""

    completed_indices: set[int] = set()
    for record in records:
        if isinstance(record, StepProgressRecord) and record.step_status == "completed":
            completed_indices.add(record.step_index)
    return len(completed_indices)


def _next_seq_for_task(records: list[LedgerRecord], task_id: str) -> int:
    return max((r.seq for r in records if r.task_id == task_id), default=0) + 1


@dataclass(frozen=True, slots=True)
class LedgerConsistencyIssue:
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class LedgerConsistencyReport:
    issues: tuple[LedgerConsistencyIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def check_recovery_consistency(
    records: list[LedgerRecord],
    *,
    checkpoint_ref_exists: bool,
    governed_state: GovernedTaskState,
) -> LedgerConsistencyReport:
    """比对 ledger 记录与恢复出的 governed 状态，返回一致性问题报告。

    - missing_checkpoint_ref：ledger 指向的 checkpoint 不存在，无法恢复状态；
    - stale_ledger_entry：checkpoint 恢复的进度领先于 ledger（ledger 没跟上）；
    - task_state_mismatch：ledger 记录的进度领先于 checkpoint 可恢复进度
      （已完成工作会被重复），或 lifecycle 与恢复状态不一致。
    """

    issues: list[LedgerConsistencyIssue] = []

    latest_cp = latest_checkpoint_ref(records)
    if latest_cp is not None and not checkpoint_ref_exists:
        issues.append(
            LedgerConsistencyIssue(
                "missing_checkpoint_ref",
                f"ledger references checkpoint {latest_cp.checkpoint_ref!r} but it does not exist",
            )
        )

    ledger_completed = ledger_completed_step_count(records)
    restored_completed = governed_state.progress.completed_steps
    if restored_completed > ledger_completed:
        issues.append(
            LedgerConsistencyIssue(
                "stale_ledger_entry",
                f"restored {restored_completed} completed; ledger only has {ledger_completed}",
            )
        )
    elif ledger_completed > restored_completed:
        issues.append(
            LedgerConsistencyIssue(
                "task_state_mismatch",
                f"ledger {ledger_completed} > checkpoint {restored_completed} (would repeat)",
            )
        )

    last_lifecycle = latest_ledger_lifecycle(records)
    restored_lifecycle = governed_state.lifecycle.value
    if last_lifecycle is not None and last_lifecycle != restored_lifecycle:
        issues.append(
            LedgerConsistencyIssue(
                "task_state_mismatch",
                f"ledger lifecycle {last_lifecycle!r} != restored {restored_lifecycle!r}",
            )
        )

    return LedgerConsistencyReport(tuple(issues))


def record_checkpoint_boundary(
    ledger: TaskLedger,
    governed_state: GovernedTaskState,
    *,
    task_id: str,
    checkpoint_ref: str,
    checkpoint_source: str | None,
    recorded_at: str,
) -> list[LedgerRecord]:
    """在 checkpoint 保存边界向 ledger 追加 lifecycle/step/checkpoint_ref 记录。

    只从 ``governed_state`` 派生 safe-summary 记录并经 ``ledger.append`` 落盘。不读写
    checkpoint 文件本身——checkpoint 仍是唯一状态恢复源（AC-4）。返回本次追加的记录。
    """

    existing = ledger.read_all()
    seq = _next_seq_for_task(existing, task_id)
    appended: list[LedgerRecord] = []

    if latest_ledger_lifecycle(existing) != governed_state.lifecycle.value:
        appended.append(
            ledger.append(
                TaskLifecycleRecord(
                    task_id,
                    seq,
                    recorded_at,
                    governed_state.lifecycle.value,
                    governed_state.raw_status,
                    governed_state.user_goal,
                    governed_state.plan_goal,
                )
            )
        )
        seq += 1

    current_step = governed_state.current_step
    if current_step is not None:
        appended.append(
            ledger.append(
                StepProgressRecord(
                    task_id,
                    seq,
                    recorded_at,
                    current_step.index,
                    current_step.step_id,
                    current_step.status.value,
                    current_step.completion_summary,
                )
            )
        )
        seq += 1

    appended.append(
        ledger.append(
            CheckpointRefRecord(
                task_id,
                seq,
                recorded_at,
                checkpoint_ref,
                checkpoint_source,
                governed_state.raw_status,
            )
        )
    )
    return appended
