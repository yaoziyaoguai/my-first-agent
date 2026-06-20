"""S5 durable governed task ledger —— 契约层 (S5-G01)。

本模块定义 durable governed task recovery 的「窄、safe-summary」ledger 契约
(S5_GOAL.md §5/§6, AC-2/AC-7):

- 四种记录类型：task lifecycle / step progress / checkpoint ref / evidence ref；
- 每种类型只承载 safe-summary 或引用字段，**绝不**承载 raw tool 输出或 raw secret；
- per-task_id 的 seq 严格递增（append-only 排序不变量）；
- 一个确定性的 reference recovery task，覆盖四种 kind 并定义 interruption/resume 边界。

边界（与 frozen S5 goal 一致）：

- ledger 只是 checkpoint 的**审计/进度连续性**补充，**不是**状态恢复源（AC-4）；
- 不执行工具、不跑 loop、不绕过 policy/approval/evidence seam（AC-6）；
- 真正的 JSONL 持久化在 S5-G03；redaction 强制在 S5-G02；runtime 接入在 S5-G04；
- 这里只锁定数据契约与确定性 reference 数据，不引入真实时间源。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from agent.evidence_redaction import redact_text


class LedgerRecordKind(str, Enum):
    """Ledger 记录类型标签，供持久化 (S5-G03) 与 redaction (S5-G02) 复用。"""

    TASK_LIFECYCLE = "task_lifecycle"
    STEP_PROGRESS = "step_progress"
    CHECKPOINT_REF = "checkpoint_ref"
    EVIDENCE_REF = "evidence_ref"


class LedgerValidationError(Exception):
    """Ledger 记录违反必填字段或 append-only 排序契约时抛出。"""


# 四种记录类型共享的身份字段：task_id / seq / recorded_at。
# seq 是 per-task_id 严格递增的 append 序号；recorded_at 由调用方/存储层 (S5-G03)
# 供给，保证 reference 数据可确定性复现（本模块不读真实时钟）。


@dataclass(frozen=True, slots=True)
class TaskLifecycleRecord:
    """任务级生命周期记录（派生自 GovernedTaskLifecycle）。"""

    task_id: str
    seq: int
    recorded_at: str
    lifecycle: str
    raw_status: str
    user_goal: str | None
    plan_goal: str | None


@dataclass(frozen=True, slots=True)
class StepProgressRecord:
    """步骤级进度记录（safe-summary，不含 raw 工具输出）。"""

    task_id: str
    seq: int
    recorded_at: str
    step_index: int
    step_id: str | None
    step_status: str
    completion_summary: str | None


@dataclass(frozen=True, slots=True)
class CheckpointRefRecord:
    """Checkpoint 引用记录：checkpoint_ref 是路径字符串（引用，不是状态本体）。"""

    task_id: str
    seq: int
    recorded_at: str
    checkpoint_ref: str
    checkpoint_source: str | None
    task_status_at_save: str | None


@dataclass(frozen=True, slots=True)
class EvidenceRefRecord:
    """Evidence 引用记录：evidence_ref 是 ref_id，safe_summary 是脱敏摘要。"""

    task_id: str
    seq: int
    recorded_at: str
    evidence_ref: str
    evidence_kind: str
    safe_summary: str | None


LedgerRecord = (
    TaskLifecycleRecord | StepProgressRecord | CheckpointRefRecord | EvidenceRefRecord
)


def validate_ledger_record(record: LedgerRecord) -> None:
    """校验单条记录的必填身份字段：task_id 非空、seq >= 1、recorded_at 非空。"""

    if not record.task_id:
        raise LedgerValidationError("ledger record missing task_id")
    if record.seq < 1:
        raise LedgerValidationError(f"ledger record seq must be >= 1, got {record.seq}")
    if not record.recorded_at:
        raise LedgerValidationError("ledger record missing recorded_at")


def assert_monotonic_order(records: list[LedgerRecord]) -> None:
    """断言 records 在每个 task_id 内 seq 严格递增（append-only 排序不变量）。

    多 task 共享同一 ledger 文件时，各自 seq 空间独立判断。
    """

    last_seq: dict[str, int] = {}
    for record in records:
        previous = last_seq.get(record.task_id)
        if previous is not None and record.seq <= previous:
            raise LedgerValidationError(
                f"ledger seq not strictly increasing for task_id={record.task_id}: "
                f"{previous} -> {record.seq}"
            )
        last_seq[record.task_id] = record.seq


# reference recovery task：确定性的 fake/local 数据（固定时间戳，无真实时钟）。
_REFERENCE_TASK_ID = "s5-reference-task"
_REFERENCE_STAMPS = tuple(
    f"2026-06-20T00:00:{minute:02d}Z" for minute in range(1, 11)
)

# 恢复边界：step 0 完成并写完 checkpoint 之后（seq 6），step 1 尚未开始。
# resume 时读取 seq <= 该值的持久前缀即可从 checkpoint+ledger 恢复，继续 step 1。
REFERENCE_RESUME_AFTER_SEQ = 6


def build_reference_recovery_records() -> list[LedgerRecord]:
    """构造确定性的 reference recovery task 记录序列。

    覆盖全部四种 kind，并在 seq 6（step 0 的 checkpoint 边界）之后留有未完成工作
    （step 1），用于定义 interruption/resume 点。两次调用逐字段相等。
    """

    task_id = _REFERENCE_TASK_ID
    return [
        TaskLifecycleRecord(
            task_id, 1, _REFERENCE_STAMPS[0],
            "planning", "awaiting_plan_confirmation",
            "reference: durable recovery demo", "reference-plan",
        ),
        StepProgressRecord(
            task_id, 2, _REFERENCE_STAMPS[1],
            0, "s0", "active", None,
        ),
        TaskLifecycleRecord(
            task_id, 3, _REFERENCE_STAMPS[2],
            "running", "running",
            "reference: durable recovery demo", "reference-plan",
        ),
        EvidenceRefRecord(
            task_id, 4, _REFERENCE_STAMPS[3],
            "ev-step0-mark", "tool", "step 0 mark_step_complete",
        ),
        StepProgressRecord(
            task_id, 5, _REFERENCE_STAMPS[4],
            0, "s0", "completed", "step 0 done",
        ),
        CheckpointRefRecord(
            task_id, 6, _REFERENCE_STAMPS[5],
            "/tmp/s5/s5-reference-task.json", "step_boundary", "running",
        ),
        StepProgressRecord(
            task_id, 7, _REFERENCE_STAMPS[6],
            1, "s1", "active", None,
        ),
        EvidenceRefRecord(
            task_id, 8, _REFERENCE_STAMPS[7],
            "ev-step1-mark", "tool", "step 1 mark_step_complete",
        ),
        StepProgressRecord(
            task_id, 9, _REFERENCE_STAMPS[8],
            1, "s1", "completed", "step 1 done",
        ),
        TaskLifecycleRecord(
            task_id, 10, _REFERENCE_STAMPS[9],
            "done", "done",
            "reference: durable recovery demo", "reference-plan",
        ),
    ]


# S5-G02 redaction 边界：每种记录类型的 free-text 字段（必须 redact）。
# 其余字段为结构化 id / path / 受控词表，按构造契约不携带 secret，故不 redact
# ——redact 它们会破坏 recovery 所需的精确 checkpoint_ref / step_id / ref 匹配。
_FREE_TEXT_FIELDS: dict[type, tuple[str, ...]] = {
    TaskLifecycleRecord: ("user_goal", "plan_goal"),
    StepProgressRecord: ("completion_summary",),
    EvidenceRefRecord: ("safe_summary",),
    CheckpointRefRecord: (),
}


def _redact_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_text(value)


def redact_ledger_record(record: LedgerRecord) -> LedgerRecord:
    """返回一条新的 ledger 记录，其 free-text 字段经 ``redact_text`` 脱敏。

    这是 ledger 持久化 (S5-G03) 与 summary 投影 (S5-G11) 之前的脱敏硬边界
    (AC-7)。即便调用方误把合成 key 放进 user_goal / completion_summary /
    safe_summary / plan_goal，本层也会先剥离。结构化字段（id / path / seq /
    受控词表）原样保留——它们由构造契约保证安全，且 recovery/ref 匹配需要精确值。

    不可变：返回新记录，原记录不变。
    """

    redact_fields = _FREE_TEXT_FIELDS.get(type(record), ())
    if not redact_fields:
        return record
    changes = {name: _redact_optional(getattr(record, name)) for name in redact_fields}
    return replace(record, **changes)
