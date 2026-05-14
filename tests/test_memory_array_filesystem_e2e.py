"""Phase 7 Memory Array filesystem E2E dogfood。

这些测试使用固定的临时根目录 /tmp/dogfood_memory_array_filesystem_e2e，
只写 synthetic / non-sensitive data，不读取真实 sessions/runs、agent_log.jsonl
或 .env 内容。

覆盖 RFC Phase 6/7 的 filesystem 路径：
- episodic T2 auto-retain 写入真实 frontmatter/index
- semantic consolidation: loader → detector → pipeline → T1 pending → review
- procedural emergence: active_records gate → pending_review → inline_confirmation seam
- recall/snapshot 基础只读验证

测试目标是 dogfood filesystem store 的真实落盘行为，不改变 memory governance 语义。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from agent.memory_consolidation_pipeline import run_consolidation_pipeline
from agent.memory_consolidation_review import (
    dispatch_consolidation_candidates_to_pending_review,
)
from agent.memory_contracts import MemoryScope
from agent.memory_emergence import (
    CorrectionEvidence,
    DeterministicEmergenceDetector,
    InlineConfirmationResponse,
    _validate_confirmation_form,
    apply_inline_confirmation_response,
    dispatch_procedural_candidates_to_pending_review,
    prepare_procedural_inline_confirmation_request,
)
from agent.memory_fs_store import FilesystemMemoryStore, parse_memory_file
from agent.memory_operations import (
    MemoryConfirmationChoice,
    MemoryConfirmationStatus,
    MemoryDecisionType,
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_review import (
    accept_pending_proposal,
    edit_and_accept_pending_proposal,
    list_pending_proposals,
    reject_pending_proposal,
)
from agent.memory_snapshot_generator import (
    MemorySnapshotBuildOptions,
    build_memory_snapshot_from_store,
)


DOGFOOD_ROOT = Path("/tmp/dogfood_memory_array_filesystem_e2e")


def _reset_dogfood_root() -> Path:
    """只清理固定 /tmp dogfood 目录，避免误删真实 memory root。"""
    expected = Path("/tmp/dogfood_memory_array_filesystem_e2e").resolve()
    actual = DOGFOOD_ROOT.resolve()
    if actual != expected:
        raise RuntimeError(f"unexpected dogfood root: {actual}")
    if DOGFOOD_ROOT.exists():
        shutil.rmtree(DOGFOOD_ROOT)
    DOGFOOD_ROOT.mkdir(parents=True, exist_ok=True)
    return DOGFOOD_ROOT


def _intent(
    *,
    content: str,
    source_summary: str,
    memory_type: str,
    source_type: str,
    scope: MemoryScope = MemoryScope.USER,
    confirmation: MemoryConfirmationStatus = MemoryConfirmationStatus.APPROVED,
    user_choice: MemoryConfirmationChoice = MemoryConfirmationChoice.ACCEPT,
    confidence: float | None = None,
) -> MemoryOperationIntent:
    """构造已经过 governance routing 的 synthetic intent，不触发 LLM/runtime。"""
    return MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=confirmation,
        user_choice=user_choice,
        content_summary=content,
        source_summary=source_summary,
        scope=scope,
        safety_summary="synthetic non-sensitive dogfood evidence",
        sensitive_redacted=False,
        user_visible_summary=f"[synthetic] {content[:80]}",
        memory_type=memory_type,
        source_type=source_type,
        confidence=confidence,
    )


def _apply_intent(store: FilesystemMemoryStore, intent: MemoryOperationIntent):
    """统一走 MemoryOperationIntent → audit → store.apply_operation_intent 路径。"""
    return store.apply_operation_intent(intent, build_memory_audit_summary(intent))


def _write_episodic(
    store: FilesystemMemoryStore,
    index: int,
    content: str,
    *,
    confidence: float = 0.65,
):
    intent = _intent(
        content=content,
        source_summary=f"synthetic episodic dogfood source {index}",
        memory_type="episodic",
        source_type="agent_suggested",
        confirmation=MemoryConfirmationStatus.AUTO_RETAINED,
        confidence=confidence,
    )
    return _apply_intent(store, intent)


def _active_correction_evidence() -> list[CorrectionEvidence]:
    """构造 3 条同一 correction pattern 的 procedural emergence 证据。"""
    return [
        CorrectionEvidence(
            record_id="proc-ev-001",
            content="以后请先检查 git status 再提交",
            correction_type="process_order",
            scope="git_operations",
            confidence=0.72,
            source_memory_type="episodic",
        ),
        CorrectionEvidence(
            record_id="proc-ev-002",
            content="下次先检查 git status，再决定是否 commit",
            correction_type="process_order",
            scope="git_operations",
            confidence=0.74,
            source_memory_type="episodic",
        ),
        CorrectionEvidence(
            record_id="proc-ev-003",
            content="记得先检查 git status，然后再进入提交流程",
            correction_type="process_order",
            scope="git_operations",
            confidence=0.76,
            source_memory_type="episodic",
        ),
    ]


def _record_ids(store: FilesystemMemoryStore, memory_type: str) -> list[str]:
    return sorted(r.id for r in store.list_records() if r.memory_type == memory_type)


def _archive_count(root: Path, status: str) -> int:
    return len(sorted((root / "_pending" / "archived" / status).glob("t1_*.json")))


def test_memory_array_filesystem_e2e_dogfood_report() -> None:
    """Filesystem E2E dogfood 验证真实 _pending/ 和正式 memory records。

    这些测试验证 RFC §10.5 / §15.5 中 procedural explicit confirmation 边界：
    pending_review 与 inline_confirmation 都必须先获得 human confirmation；
    reject/other 不写正式 store，procedural 不支持 silent retain 或 auto approve。
    """
    root = _reset_dogfood_root()
    store = FilesystemMemoryStore(root_dir=root)

    # A. episodic T2 auto-retain：只允许 episodic 自动保留，confidence 必须保真。
    episodic_result = _write_episodic(
        store,
        1,
        "synthetic episodic: pytest fixture cleanup improved smoke verification stability",
        confidence=0.67,
    )
    assert episodic_result.status.value == "applied"
    assert episodic_result.record is not None
    assert episodic_result.record.memory_type == "episodic"
    assert episodic_result.record.approval_status == "auto_retained"
    assert episodic_result.record.metadata["confidence"] == 0.67
    _validate_confirmation_form("pending_review")
    _validate_confirmation_form("inline_confirmation")
    with pytest.raises(ValueError, match="不被允许"):
        _validate_confirmation_form("auto_retained")

    # 为 semantic consolidation 追加至少 3 条同主题 synthetic episodic records。
    for idx, text in enumerate((
        "synthetic episodic: pytest fixture cleanup removed stale temp home for smoke verification",
        "synthetic episodic: pytest fixture cleanup prevents smoke verification timeout",
        "synthetic episodic: pytest fixture cleanup keeps smoke verification deterministic",
    ), start=2):
        result = _write_episodic(store, idx, text, confidence=0.69)
        assert result.status.value == "applied"

    index_path = root / "_meta" / "index.json"
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_data["total"] >= 4
    episodic_file = next((root / "episodic").glob("*.md"))
    parsed_episodic = parse_memory_file(episodic_file)
    assert any(meta.get("confidence") == 0.67 for meta in parsed_episodic)

    # B. semantic consolidation：loader → detector → pipeline → pending → review。
    pipeline = run_consolidation_pipeline(store)
    assert pipeline.evidence_count >= 4
    assert pipeline.candidate_count >= 1
    semantic_candidate = pipeline.candidates[0]
    assert semantic_candidate.memory_type == "semantic"
    assert semantic_candidate.governance_route == "T1"
    assert len(semantic_candidate.source_evidence) >= 3

    semantic_accept = semantic_candidate
    semantic_reject = replace(
        semantic_candidate,
        content=f"{semantic_candidate.content} [reject synthetic branch]",
        evidence_summary=f"{semantic_candidate.evidence_summary} reject branch",
    )
    semantic_edit = replace(
        semantic_candidate,
        content=f"{semantic_candidate.content} [edit synthetic branch]",
        evidence_summary=f"{semantic_candidate.evidence_summary} edit branch",
    )

    dispatch = dispatch_consolidation_candidates_to_pending_review(
        [semantic_accept],
        memory_root=root,
        source="filesystem_e2e_semantic_accept",
    )
    assert dispatch.dispatched == 1
    proposal = list_pending_proposals(memory_root=str(root))[0]
    accepted_semantic = accept_pending_proposal(proposal, store)
    assert accepted_semantic.status.value == "applied"
    assert accepted_semantic.record is not None
    assert accepted_semantic.record.memory_type == "semantic"

    before_reject_semantic_count = len(_record_ids(store, "semantic"))
    dispatch_consolidation_candidates_to_pending_review(
        [semantic_reject],
        memory_root=root,
        source="filesystem_e2e_semantic_reject",
    )
    reject_pending_proposal(list_pending_proposals(memory_root=str(root))[0])
    assert len(_record_ids(store, "semantic")) == before_reject_semantic_count

    dispatch_consolidation_candidates_to_pending_review(
        [semantic_edit],
        memory_root=root,
        source="filesystem_e2e_semantic_edit",
    )
    edited_semantic_content = "用户稳定偏好 pytest fixture cleanup 的 synthetic semantic memory"
    edited_semantic = edit_and_accept_pending_proposal(
        list_pending_proposals(memory_root=str(root))[0],
        edited_semantic_content,
        store,
    )
    assert edited_semantic.status.value == "applied"
    assert edited_semantic.record is not None
    assert edited_semantic.record.content == edited_semantic_content
    assert "source_evidence=" in edited_semantic.record.source_summary
    assert "[consolidation:" in edited_semantic.record.source_summary
    assert "evidence_summary=" in edited_semantic.record.source_summary
    assert edited_semantic.record.metadata["confidence"] == semantic_edit.confidence

    # C. procedural emergence：gate fail-closed + T1 pending/inline confirmation。
    detector = DeterministicEmergenceDetector()
    fail_closed = detector.detect(_active_correction_evidence(), active_records_count=49)
    assert fail_closed.gate_passed is False
    assert fail_closed.candidates == ()

    emergence = detector.detect(_active_correction_evidence(), active_records_count=50)
    assert emergence.gate_passed is True
    assert len(emergence.candidates) >= 1
    procedural_candidate = emergence.candidates[0]
    assert procedural_candidate.memory_type == "procedural"
    assert procedural_candidate.governance_route == "T1"

    procedural_accept = procedural_candidate
    procedural_reject = replace(
        procedural_candidate,
        content=f"{procedural_candidate.content} [reject synthetic branch]",
    )
    procedural_edit = replace(
        procedural_candidate,
        content=f"{procedural_candidate.content} [edit synthetic branch]",
    )
    dispatch_procedural_candidates_to_pending_review(
        [procedural_accept],
        memory_root=root,
        source="filesystem_e2e_procedural_accept",
    )
    accepted_procedural = accept_pending_proposal(
        list_pending_proposals(memory_root=str(root))[0],
        store,
    )
    assert accepted_procedural.status.value == "applied"
    assert accepted_procedural.record is not None
    assert accepted_procedural.record.memory_type == "procedural"
    assert "correction_pattern=" in accepted_procedural.record.source_summary

    before_reject_procedural_count = len(_record_ids(store, "procedural"))
    dispatch_procedural_candidates_to_pending_review(
        [procedural_reject],
        memory_root=root,
        source="filesystem_e2e_procedural_reject",
    )
    reject_pending_proposal(list_pending_proposals(memory_root=str(root))[0])
    assert len(_record_ids(store, "procedural")) == before_reject_procedural_count

    dispatch_procedural_candidates_to_pending_review(
        [procedural_edit],
        memory_root=root,
        source="filesystem_e2e_procedural_edit",
    )
    edited_procedural_content = "先检查 git status，再执行 synthetic commit 流程"
    edited_procedural = edit_and_accept_pending_proposal(
        list_pending_proposals(memory_root=str(root))[0],
        edited_procedural_content,
        store,
    )
    assert edited_procedural.status.value == "applied"
    assert edited_procedural.record is not None
    assert edited_procedural.record.content == edited_procedural_content

    inline_accept_candidate = replace(
        procedural_candidate,
        content="inline accept: 先检查 git status",
        source_evidence=("inline-accept-1", "inline-accept-2", "inline-accept-3"),
    )
    inline_edit_candidate = replace(
        procedural_candidate,
        content="inline edit: 先检查 git status",
        source_evidence=("inline-edit-1", "inline-edit-2", "inline-edit-3"),
    )
    inline_reject_candidate = replace(
        procedural_candidate,
        content="inline reject: 先检查 git status",
        source_evidence=("inline-reject-1", "inline-reject-2", "inline-reject-3"),
    )
    inline_other_candidate = replace(
        procedural_candidate,
        content="inline other: 先检查 git status",
        source_evidence=("inline-other-1", "inline-other-2", "inline-other-3"),
    )

    inline_accept = prepare_procedural_inline_confirmation_request(inline_accept_candidate)
    assert inline_accept.allowed_actions == ("accept", "reject", "edit", "other")
    inline_accept_result = apply_inline_confirmation_response(
        inline_accept,
        InlineConfirmationResponse(action="accept"),
        store,
    )
    assert inline_accept_result.status == "applied"
    assert inline_accept_result.store_result is not None
    assert inline_accept_result.store_result.record is not None
    assert inline_accept_result.store_result.record.memory_type == "procedural"

    inline_edit = prepare_procedural_inline_confirmation_request(inline_edit_candidate)
    inline_edit_result = apply_inline_confirmation_response(
        inline_edit,
        InlineConfirmationResponse(
            action="edit_accept",
            edited_content="inline edit accepted synthetic procedural content",
        ),
        store,
    )
    assert inline_edit_result.status == "applied"
    assert inline_edit_result.store_result is not None
    assert inline_edit_result.store_result.record is not None
    assert inline_edit_result.store_result.record.content == (
        "inline edit accepted synthetic procedural content"
    )

    before_no_write_count = len(_record_ids(store, "procedural"))
    inline_reject = prepare_procedural_inline_confirmation_request(inline_reject_candidate)
    inline_reject_result = apply_inline_confirmation_response(
        inline_reject,
        InlineConfirmationResponse(action="reject"),
        store,
    )
    assert inline_reject_result.status == "no_write"
    inline_other = prepare_procedural_inline_confirmation_request(inline_other_candidate)
    inline_other_result = apply_inline_confirmation_response(
        inline_other,
        InlineConfirmationResponse(action="other", free_text="synthetic follow-up"),
        store,
    )
    assert inline_other_result.status == "needs_followup"
    assert len(_record_ids(store, "procedural")) == before_no_write_count

    # D. recall/snapshot 基础验证：只读，不临时实现新的 snapshot 能力。
    episodic_records = store.recall(memory_type="episodic", max_items=20)
    semantic_records = store.recall(memory_type="semantic", max_items=20)
    procedural_records = store.recall(memory_type="procedural", max_items=20)
    assert len(episodic_records) >= 4
    assert len(semantic_records) >= 2
    assert len(procedural_records) >= 4

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(
            selection_reason="filesystem e2e dogfood recall smoke",
            max_items=5,
        ),
    )
    assert snapshot.items

    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    report = {
        "memory_root": str(root),
        "_pending": {
            "pending_count": len(list_pending_proposals(memory_root=str(root))),
            "archived_accepted": _archive_count(root, "accepted"),
            "archived_rejected": _archive_count(root, "rejected"),
        },
        "index": {
            "path": str(index_path),
            "exists": index_path.exists(),
            "total": index_data["total"],
        },
        "episodic_records": _record_ids(store, "episodic"),
        "semantic_records": _record_ids(store, "semantic"),
        "procedural_records": _record_ids(store, "procedural"),
        "metadata_preserved": {
            "episodic_confidence": episodic_result.record.metadata["confidence"],
            "semantic_source_evidence": "source_evidence="
            in edited_semantic.record.source_summary,
            "semantic_consolidation_type": "[consolidation:"
            in edited_semantic.record.source_summary,
            "procedural_correction_pattern": "correction_pattern="
            in accepted_procedural.record.source_summary,
            "inline_confirmation_form": "confirmation_form=inline_confirmation"
            in inline_accept_result.store_result.record.source_summary,
        },
        "snapshot": {
            "item_count": len(snapshot.items),
            "limitation": "snapshot smoke only; no new snapshot capability implemented",
        },
        "secret_leakage_check": "no",
        "read_real_sessions_runs": "no",
        "read_agent_log": "no",
    }
    report_path = root / "dogfood_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    assert report["_pending"]["pending_count"] == 0
    assert report["_pending"]["archived_accepted"] >= 4
    assert report["_pending"]["archived_rejected"] >= 2
    assert report["metadata_preserved"]["semantic_source_evidence"] is True
    assert report["metadata_preserved"]["procedural_correction_pattern"] is True
    assert report["secret_leakage_check"] == "no"
    assert report["read_real_sessions_runs"] == "no"
    assert report["read_agent_log"] == "no"
