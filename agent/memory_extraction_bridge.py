"""Phase 5 — Extraction → Human Review Bridge.

将 extraction sandbox 的输出 (MemoryCandidateProposal) 桥接到
confirmation → operation intent → store 的治理链。

不修改 MemoryRuntime、不做自动 retain、不 bypass confirmation。
纯 library，不包含 print/input — 交互由调用方负责。
"""

from __future__ import annotations

import hashlib

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationRequest,
    MemoryConfirmationStatus,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_contracts import (
    MemoryCandidate,
    MemoryDecision,
    MemoryDecisionType,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)
from agent.memory_extraction import MemoryCandidateProposal, SuggestedAction
from agent.memory_operations import (
    build_memory_audit_summary,
    build_memory_operation_intent,
)
from agent.memory_store import (
    MemoryStoreApplyResult,
    MemoryStoreProtocol,
)


def _derive_candidate_id(content: str) -> str:
    """从 content 生成稳定的 candidate id。"""
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"extraction:{digest}"


def _scope_for_proposal(proposal: MemoryCandidateProposal) -> MemoryScope:
    """根据 proposal 的 memory_type 推断 scope。"""
    # procedural memories are often project-level rules
    if proposal.memory_type == "procedural":
        return MemoryScope.PROJECT
    return MemoryScope.USER


def _sensitivity_for_proposal(proposal: MemoryCandidateProposal) -> MemorySensitivity:
    """根据 proposal 的 memory_type 推断 sensitivity。"""
    if proposal.memory_type == "procedural":
        return MemorySensitivity.MEDIUM
    return MemorySensitivity.LOW


def proposal_to_candidate(
    proposal: MemoryCandidateProposal,
    *,
    scope: MemoryScope | None = None,
    sensitivity: MemorySensitivity | None = None,
) -> MemoryCandidate:
    """将 sandbox MemoryCandidateProposal 转换为 contract-layer MemoryCandidate。

    Args:
        proposal: extraction sandbox 输出的 proposal。
        scope: 覆盖默认 scope 推断。None 时根据 memory_type 推断。
        sensitivity: 覆盖默认 sensitivity 推断。None 时根据 memory_type 推断。
    """
    return MemoryCandidate(
        id=_derive_candidate_id(proposal.content),
        content=proposal.content,
        source=MemorySource.EXTERNAL_PROVIDER,
        source_event=proposal.evidence,
        proposed_type=proposal.memory_type,
        scope=scope or _scope_for_proposal(proposal),
        sensitivity=sensitivity or _sensitivity_for_proposal(proposal),
        stability="proposed",
        confidence=proposal.confidence,
        reason=proposal.rationale,
        metadata={
            "memory_type": proposal.memory_type,
            "source_type": "llm_extraction",
            "importance": proposal.importance,
            "suggested_action": proposal.suggested_action.value,
        },
    )


def proposal_to_decision(
    proposal: MemoryCandidateProposal,
    *,
    scope: MemoryScope | None = None,
    sensitivity: MemorySensitivity | None = None,
) -> MemoryDecision | None:
    """将 proposal 转换为 RETAIN MemoryDecision。

    IGNORE 类型的 proposal 返回 None。

    Bridge 规则：所有 proposal 的 requires_user_confirmation 强制为 True，
    不做自动 retain。
    """
    if proposal.suggested_action == SuggestedAction.IGNORE:
        return None

    candidate = proposal_to_candidate(
        proposal, scope=scope, sensitivity=sensitivity
    )
    return MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason=f"LLM extraction: {proposal.rationale[:200]}",
        provenance=f"extraction:{candidate.id}",
    )


def proposal_to_confirmation_request(
    proposal: MemoryCandidateProposal,
    *,
    scope: MemoryScope | None = None,
    sensitivity: MemorySensitivity | None = None,
) -> MemoryConfirmationRequest | None:
    """将 proposal 转换为可供用户确认的 MemoryConfirmationRequest。

    IGNORE 类型的 proposal 返回 None。
    """
    decision = proposal_to_decision(
        proposal, scope=scope, sensitivity=sensitivity
    )
    if decision is None:
        return None
    return build_memory_confirmation_request(decision)


def resolve_and_store(
    request: MemoryConfirmationRequest,
    choice: MemoryConfirmationChoice,
    store: MemoryStoreProtocol,
    *,
    free_text: str | None = None,
) -> MemoryStoreApplyResult | None:
    """解析用户确认选择，确认后写入 store。

    Args:
        request: 由 proposal_to_confirmation_request 生成的确认请求。
        choice: 用户选择。
        store: 目标 store（InMemoryMemoryStore 或 FilesystemMemoryStore）。
        free_text: EDIT_AND_ACCEPT 时的编辑文本。

    Returns:
        MemoryStoreApplyResult 当用户确认写入时；REJECT/SESSION_ONLY 返回 None。
    """
    result = resolve_memory_confirmation_choice(
        request, choice, free_text=free_text
    )

    if result.status != MemoryConfirmationStatus.APPROVED:
        return None

    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)
    return store.apply_operation_intent(intent, audit)


def batch_resolve_and_store(
    requests: list[MemoryConfirmationRequest | None],
    choices: dict[int, MemoryConfirmationChoice],
    store: MemoryStoreProtocol,
    *,
    free_texts: dict[int, str] | None = None,
) -> list[MemoryStoreApplyResult | None]:
    """批量处理多个 proposal 的确认和存储。

    Args:
        requests: proposal_to_confirmation_request 的返回值列表（含 None）。
        choices: {index: MemoryConfirmationChoice}。
        store: 目标 store。
        free_texts: {index: edited_text}，仅对 EDIT_AND_ACCEPT 有效。

    Returns:
        每个 proposal 的写入结果或 None。
    """
    free_texts = free_texts or {}
    results: list[MemoryStoreApplyResult | None] = []

    for i, req in enumerate(requests):
        if req is None:
            results.append(None)
            continue
        choice = choices.get(i)
        if choice is None:
            results.append(None)
            continue
        results.append(
            resolve_and_store(
                req, choice, store, free_text=free_texts.get(i)
            )
        )

    return results
