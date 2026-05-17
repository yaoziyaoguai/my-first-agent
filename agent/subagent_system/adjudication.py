"""Parent adjudication for L0 SubAgent results."""

from __future__ import annotations

from dataclasses import replace

from agent.subagent_system.result import ParentAdjudicationResult, SubAgentResult


def adjudicate_result(
    result: SubAgentResult,
    request: object,
    *,
    revision_count: int,
    confidence_threshold: float = 0.5,
) -> ParentAdjudicationResult:
    """Return one of the L0 parent adjudication actions.

    中文学习边界：adjudication 只做 parent decision，不执行工具、不写 Memory。
    后续 L1+ conversion actions 仍是 production target，不能提前变成默认负担。
    """

    if result.status == "needs_confirmation":
        return ParentAdjudicationResult.ask_user(
            "SubAgent requested confirmation",
            "SubAgent result needs human confirmation before continuing.",
        )
    if result.status == "needs_clarification":
        return ParentAdjudicationResult.ask_user(
            "SubAgent needs clarification",
            result.clarification_question or "Please clarify the SubAgent task.",
        )
    if result.status == "error":
        return ParentAdjudicationResult.reject("SubAgent returned error")
    if result.confidence < confidence_threshold and revision_count < getattr(request, "max_revisions", 0):
        revised = replace(
            request,
            task=f"{getattr(request, 'task')} (revision requested: improve confidence)",
        )
        return ParentAdjudicationResult.request_revision(
            "SubAgent confidence below threshold",
            revised,
        )
    if result.status in {"ok", "max_iterations_exceeded", "policy_blocked"}:
        return ParentAdjudicationResult.accept(
            "Parent accepted SubAgent result",
            merged_summary=result.summary,
        )
    return ParentAdjudicationResult.reject(f"Unhandled SubAgent status: {result.status}")

