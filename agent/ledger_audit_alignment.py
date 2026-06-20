"""S5-G06 ledger-aware audit/replay 对齐层。

把 S4 ``ReplayChain`` 的 ref_ids 与 S5 ledger 的 evidence/step/checkpoint refs 对齐，
证明恢复后的 task 拥有连贯的 task/evidence/ledger 视图（AC-8）。本层只读取 replay chain
与 ledger 记录，**不**修改 S4 的 ``build_replay_chain`` / ``render_replay_summary`` 契约，
也不持久化任何 raw payload——``LedgerAuditAlignment`` 只持有 refs / counts / checkpoint_ref。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.task_ledger import (
    CheckpointRefRecord,
    EvidenceRefRecord,
    LedgerRecord,
    StepProgressRecord,
)
from agent.task_replay_chain import ReplayChain


@dataclass(frozen=True, slots=True)
class LedgerAuditAlignment:
    """replay chain 与 ledger refs 的对齐结果（结构化、无 content）。"""

    task_scope_id: str
    replay_event_count: int
    ledger_record_count: int
    ledger_checkpoint_ref: str | None
    unaligned_evidence_refs: tuple[str, ...]
    unaligned_step_refs: tuple[str, ...]

    @property
    def coherent(self) -> bool:
        return not self.unaligned_evidence_refs and not self.unaligned_step_refs


def align_ledger_with_replay(
    replay_chain: ReplayChain,
    ledger_records: list[LedgerRecord],
) -> LedgerAuditAlignment:
    """检查 ledger 的 evidence/step refs 是否都在 replay chain 的 ref_ids 中。

    checkpoint ref 不参与对齐判定（它是指向 checkpoint 文件的引用，不是 replay 事件），
    只在结果中报告。evidence/step refs 必须能在 replay chain 中找到对应事件，否则视为
    task/evidence/ledger 不连贯（AC-8）。
    """

    replay_ref_ids = {event.ref_id for event in replay_chain.events}
    evidence_refs = [
        record.evidence_ref
        for record in ledger_records
        if isinstance(record, EvidenceRefRecord)
    ]
    step_refs = [
        record.step_id
        for record in ledger_records
        if isinstance(record, StepProgressRecord) and record.step_id
    ]
    latest_checkpoint = None
    for record in ledger_records:
        if isinstance(record, CheckpointRefRecord):
            latest_checkpoint = record

    return LedgerAuditAlignment(
        task_scope_id=replay_chain.task_scope_id,
        replay_event_count=len(replay_chain.events),
        ledger_record_count=len(ledger_records),
        ledger_checkpoint_ref=(
            latest_checkpoint.checkpoint_ref if latest_checkpoint is not None else None
        ),
        unaligned_evidence_refs=tuple(
            ref for ref in evidence_refs if ref not in replay_ref_ids
        ),
        unaligned_step_refs=tuple(
            ref for ref in step_refs if ref not in replay_ref_ids
        ),
    )
