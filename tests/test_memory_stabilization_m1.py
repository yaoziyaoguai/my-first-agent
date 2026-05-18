"""v0.9.x Stabilization Phase 4 的 Memory M1 行为刻画测试。

这些测试不引入新的 Memory 语义，只把当前治理边界固定下来：
候选必须经过确认，pending_review 不能冒充批准，Skill/SubAgent 只能提出候选，
不能绕过 Memory governance 直接写入。
"""

from __future__ import annotations

import json

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_emergence import (
    InlineConfirmationResponse,
    ProceduralCandidate,
    apply_inline_confirmation_response,
    dispatch_procedural_candidates_to_pending_review,
    prepare_procedural_inline_confirmation_request,
)
from agent.memory_operations import (
    MemoryOperationType,
    build_memory_audit_summary,
    build_memory_operation_intent,
)
from agent.memory_policy import DeterministicMemoryPolicy
from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus
from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.memory_boundary import (
    MemoryProposal as SkillMemoryProposal,
    SkillMemoryBoundary,
)
from agent.subagent_system.memory_boundary import (
    MemoryProposal as SubAgentMemoryProposal,
    SubAgentMemoryBoundary,
)


def _retain_request():
    decision = DeterministicMemoryPolicy().decide(
        "remember that I prefer concise answers",
    )
    return build_memory_confirmation_request(decision)


def _procedural_candidate() -> ProceduralCandidate:
    return ProceduralCandidate(
        content="先写行为刻画测试，再做 Memory 边界重构。",
        memory_type="procedural",
        source_evidence=("evidence-1", "evidence-2", "evidence-3"),
        correction_pattern="先写测试再改代码",
        correction_type="process_order",
        scope="user",
        confidence=0.8,
        governance_route="T1",
        evidence_summary="用户多次纠正实现顺序，要求先锁定现状。",
        created_at="2026-05-18T00:00:00Z",
    )


def test_m1_reject_and_session_only_do_not_become_approved_retain() -> None:
    """拒绝和仅本次会话都不能被 store 当作已批准的长期 retain。"""

    store = InMemoryMemoryStore()

    rejected = resolve_memory_confirmation_choice(
        _retain_request(),
        MemoryConfirmationChoice.REJECT,
    )
    reject_intent = build_memory_operation_intent(rejected)
    reject_result = store.apply_operation_intent(
        reject_intent,
        build_memory_audit_summary(reject_intent),
    )

    assert reject_intent.operation_type is MemoryOperationType.REJECT
    assert reject_result.status is MemoryStoreApplyStatus.SKIPPED
    assert store.list_records() == ()

    session_only = resolve_memory_confirmation_choice(
        _retain_request(),
        MemoryConfirmationChoice.SESSION_ONLY,
    )
    session_intent = build_memory_operation_intent(session_only)
    session_result = store.apply_operation_intent(
        session_intent,
        build_memory_audit_summary(session_intent),
    )

    # 现有 fake store 会保留 session_only 视图用于测试，但它必须显式标记
    # approval_status=session_only，不能伪装成 approved 长期记忆。
    assert session_intent.operation_type is MemoryOperationType.USE_ONCE
    assert session_result.status is MemoryStoreApplyStatus.APPLIED
    assert session_result.record is not None
    assert session_result.record.approval_status == "session_only"
    assert session_result.record.created_by_operation is MemoryOperationType.USE_ONCE


def test_m1_accept_is_required_before_approved_store_record() -> None:
    """只有 explicit accept 才会生成 approved fake store record。"""

    accepted = resolve_memory_confirmation_choice(
        _retain_request(),
        MemoryConfirmationChoice.ACCEPT,
    )
    intent = build_memory_operation_intent(accepted)
    store = InMemoryMemoryStore()
    result = store.apply_operation_intent(intent, build_memory_audit_summary(intent))

    assert result.status is MemoryStoreApplyStatus.APPLIED
    assert result.record is not None
    assert result.record.approval_status == "approved"
    assert result.record.content == "I prefer concise answers"


def test_m1_pending_review_dispatch_stays_pending_not_approved(tmp_path) -> None:
    """Procedural emergence 只能写 pending_review proposal，不写 approved record。"""

    result = dispatch_procedural_candidates_to_pending_review(
        [_procedural_candidate()],
        memory_root=tmp_path,
    )

    assert result.dispatched == 1
    proposal_path = result.proposal_filepaths[0]
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

    assert proposal["confirmation_form"] == "pending_review"
    assert proposal["approval_status"] == "pending"
    assert proposal["memory_type"] == "procedural"
    assert proposal["governance_route"] == "T1"


def test_m1_inline_confirmation_reject_or_other_is_no_write() -> None:
    """inline confirmation 只有 accept/edit_accept 可以进入 store 写入路径。"""

    request = prepare_procedural_inline_confirmation_request(_procedural_candidate())
    store = InMemoryMemoryStore()

    rejected = apply_inline_confirmation_response(
        request,
        InlineConfirmationResponse(action="reject"),
        store=store,
    )
    needs_followup = apply_inline_confirmation_response(
        request,
        InlineConfirmationResponse(action="other", free_text="稍后再决定"),
        store=store,
    )

    assert rejected.status == "no_write"
    assert rejected.store_result is None
    assert needs_followup.status == "needs_followup"
    assert needs_followup.store_result is None
    assert store.list_records() == ()


def test_m1_skill_and_subagent_memory_proposals_are_not_store_writes() -> None:
    """Skill/SubAgent 的 Memory 输出只能是 proposal，不能持有 store 写入权。"""

    descriptor = SkillDescriptor(
        name="memory-safe-skill",
        description="proposes memory without direct write",
        version="0.1.0",
        status="active",
        risk_level="low",
        memory_scope="propose_memory",
    )
    skill_boundary = SkillMemoryBoundary(descriptor)
    skill_proposal = SkillMemoryProposal(
        content="prefer concise stabilization reports",
        category="user_preference",
        confidence=0.8,
    )

    assert skill_boundary.can_propose_memory() is True
    assert not hasattr(skill_boundary, "memory_store")
    assert not hasattr(skill_proposal, "write")
    assert not hasattr(skill_proposal, "persist")
    assert not hasattr(skill_proposal, "save")

    subagent_boundary = SubAgentMemoryBoundary(approved_context="approved summary")
    routed = subagent_boundary.route_proposal(
        SubAgentMemoryProposal(
            content="prefer concise stabilization reports",
            category="user_preference",
            confidence=0.7,
        ),
        subagent_name="local-worker",
    )

    assert routed.auto_approved is False
    assert routed.source == "subagent"
    assert not hasattr(subagent_boundary, "memory_store")
