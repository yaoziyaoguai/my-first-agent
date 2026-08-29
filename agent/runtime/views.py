"""从 authoritative state 生成所有 surface 共用的只读 Goal 投影。"""

from __future__ import annotations

from dataclasses import dataclass

from agent.runtime.contracts import (
    ActiveRunStatus,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EgressClass,
    FactKind,
    GoalStatus,
    SourceKind,
    SourceReceiptV1,
)


@dataclass(frozen=True, slots=True)
class SourceView:
    source_kind: str
    locator: str
    title: str
    observed_at: str
    status: str
    truncated: bool
    failure_code: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class GoalView:
    conversation_id: str
    goal_id: str | None
    goal_revision: int | None
    status: str
    interaction_state: str
    user_outcome: str | None
    progress_summary: str | None
    next_step: str | None
    blocker: str | None
    safe_attempts: tuple[str, ...]
    resume_condition: str | None
    criteria_total: int
    criteria_verified: int
    legal_actions: tuple[str, ...]
    sources: tuple[SourceView, ...]


@dataclass(frozen=True, slots=True)
class BackgroundRecoveryView:
    automation_id: str
    automation_revision: int
    occurrence_id: str
    checkpoint_identity_digest: str
    goal: GoalView


def project_background_recovery(
    state: ConversationState,
    *,
    automation_id: str,
    automation_revision: int,
    occurrence_id: str,
    checkpoint_identity_digest: str,
    definition_digest: str,
) -> BackgroundRecoveryView:
    """校验 automation handoff 后，只从精确 Runtime checkpoint 投影恢复状态。"""

    binding = state.background_occurrence_binding
    if binding is None:
        raise ValueError("Runtime checkpoint has no background occurrence binding")
    expected = (
        automation_id,
        automation_revision,
        occurrence_id,
        checkpoint_identity_digest,
        definition_digest,
    )
    actual = (
        binding.automation_id,
        binding.automation_revision,
        binding.occurrence_id,
        binding.checkpoint_identity_digest,
        binding.definition_digest,
    )
    if actual != expected:
        raise ValueError("Runtime checkpoint does not match the automation handoff")
    return BackgroundRecoveryView(
        automation_id=automation_id,
        automation_revision=automation_revision,
        occurrence_id=occurrence_id,
        checkpoint_identity_digest=checkpoint_identity_digest,
        goal=project_goal_view(state),
    )


@dataclass(frozen=True, slots=True)
class ProcessLeaseView:
    """active process authority lease 的 readable 投影（design §12.2）。

    默认 surface 只显示 readable command/cwd/剩余 uses/expires；digest/ID 仅在 advanced
    视图暴露（不泄露内部 digest 噪音）。
    """

    readable_command: str
    cwd_digest: str
    resource_profile: str
    remaining_uses: int
    expires_at: str
    lease_digest: str | None = None
    # F5/R11：advanced 视图额外暴露 lease_id（用户撤销单条所需的精确标识）。
    lease_id: str | None = None


def project_process_leases(
    state: ConversationState,
    *,
    advanced: bool = False,
) -> tuple[ProcessLeaseView, ...]:
    """纯投影 active process leases；不触发 Runtime/Tool/persistence。"""

    views: list[ProcessLeaseView] = []
    for lease in state.process_leases:
        views.append(
            ProcessLeaseView(
                readable_command=_lease_readable(lease),
                cwd_digest=lease.cwd_digest,
                resource_profile=lease.resource_profile,
                remaining_uses=lease.remaining_uses,
                expires_at=lease.expires_at,
                lease_digest=lease.lease_digest if advanced else None,
                lease_id=lease.lease_id if advanced else None,
            )
        )
    return tuple(views)


def _lease_readable(lease) -> str:  # noqa: ANN001
    return lease.readable_command


def project_goal_view(state: ConversationState) -> GoalView:
    """纯投影；不得触发 Runtime、Provider、Tool 或持久化。"""

    goal = state.goal
    if goal is None:
        return GoalView(
            conversation_id=state.conversation_id,
            goal_id=None,
            goal_revision=None,
            status=state.interaction_state.value,
            interaction_state=state.interaction_state.value,
            user_outcome=None,
            progress_summary=None,
            next_step=None,
            blocker=None,
            safe_attempts=(),
            resume_condition=None,
            criteria_total=0,
            criteria_verified=0,
            legal_actions=("submit",) if state.active_run is None else _run_actions(state),
            sources=project_source_views(
                state,
                run_id=_visible_run_id(state),
            ),
        )

    passed_criteria = {
        record.criterion_id
        for record in state.evidence_records
        if record.goal_id == goal.goal_id
        and record.goal_revision == goal.revision
        and record.passed
    }
    blocker, safe_attempts, resume_condition = _blocked_details(state)
    visible_sources = project_visible_source_views(state)
    return GoalView(
        conversation_id=state.conversation_id,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        status=goal.status.value,
        interaction_state=state.interaction_state.value,
        user_outcome=goal.user_outcome,
        progress_summary=goal.progress_summary,
        next_step=goal.next_step,
        blocker=blocker,
        safe_attempts=safe_attempts,
        resume_condition=resume_condition,
        criteria_total=len(goal.admitted_criteria),
        criteria_verified=len(
            {
                criterion.criterion_id
                for criterion in goal.admitted_criteria
                if criterion.criterion_id in passed_criteria
            }
        ),
        legal_actions=_goal_actions(state),
        sources=visible_sources[-32:],
    )


def project_visible_source_views(
    state: ConversationState,
    *,
    advanced: bool = False,
) -> tuple[SourceView, ...]:
    goal = state.goal
    if goal is None:
        return project_source_views(
            state,
            run_id=_visible_run_id(state),
            advanced=advanced,
        )
    goal_sources = project_source_views(
        state,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        advanced=advanced,
    )
    current_sources = project_source_views(
        state,
        run_id=_visible_run_id(state),
        advanced=advanced,
    )
    return (
        *goal_sources,
        *(
            item
            for item in current_sources
            if item.observed_at == "not_observed" and item not in goal_sources
        ),
    )[-32:]


def project_source_views(
    state: ConversationState,
    *,
    run_id: str | None = None,
    goal_id: str | None = None,
    goal_revision: int | None = None,
    advanced: bool = False,
    limit: int = 32,
) -> tuple[SourceView, ...]:
    """从 durable ToolResult receipts 投影用户可读来源；不推进任何状态。"""

    if limit < 1:
        raise ValueError("source view limit must be positive")
    if goal_revision is not None and goal_id is None:
        raise ValueError("goal revision requires a goal id")
    calls = _tool_calls(state.facts)
    views: list[SourceView] = []
    for fact in state.facts:
        if fact.kind is not FactKind.TOOL_RESULT:
            continue
        call_id = fact.content.get("tool_call_id")
        call = calls.get(call_id) if isinstance(call_id, str) else None
        metadata = fact.content.get("metadata")
        raw_receipts = (
            metadata.get("source_receipts") if isinstance(metadata, dict) else None
        )
        receipts: list[SourceReceiptV1] = []
        if isinstance(raw_receipts, (list, tuple)):
            for raw_receipt in raw_receipts:
                try:
                    receipt = SourceReceiptV1.from_json(raw_receipt)
                except ValueError:
                    continue
                if run_id is not None and receipt.run_id != run_id:
                    continue
                if goal_id is not None and receipt.goal_id != goal_id:
                    continue
                if (
                    goal_revision is not None
                    and receipt.goal_revision != goal_revision
                ):
                    continue
                receipts.append(receipt)
        refs = _source_refs(metadata) if advanced else {}
        for receipt in receipts:
            views.append(
                SourceView(
                    source_kind=receipt.source_kind.value,
                    locator=receipt.origin_locator,
                    title=receipt.title or receipt.origin_locator,
                    observed_at=receipt.observed_at,
                    status=_receipt_status(receipt),
                    truncated=receipt.truncated,
                    source_ref=refs.get(receipt.receipt_digest),
                )
            )
        if receipts or call is None or not _source_tool(call["name"]):
            continue
        if run_id is not None and _fact_run_id(fact) != run_id:
            continue
        if goal_id is not None:
            continue
        status, failure_code = _empty_source_status(fact, metadata)
        if status is None:
            continue
        views.append(
            SourceView(
                source_kind=_empty_source_kind(call["name"]),
                locator=_empty_source_locator(call["name"]),
                title=_empty_source_title(call["name"], status),
                observed_at="not_observed",
                status=status,
                truncated=status == "partial",
                failure_code=failure_code,
            )
        )
    return tuple(views[-limit:])


def _visible_run_id(state: ConversationState) -> str | None:
    if state.active_run is not None:
        return state.active_run.run_id
    if state.last_safe_result is not None:
        return state.last_safe_result.run_id
    return None


def _tool_calls(facts: tuple[ConversationFact, ...]) -> dict[str, dict]:
    calls: dict[str, dict] = {}
    for fact in facts:
        if fact.kind is not FactKind.TOOL_CALLS:
            continue
        raw_calls = fact.content.get("calls")
        if not isinstance(raw_calls, (list, tuple)):
            continue
        for raw in raw_calls:
            if (
                isinstance(raw, dict)
                and isinstance(raw.get("tool_call_id"), str)
                and isinstance(raw.get("name"), str)
            ):
                calls[raw["tool_call_id"]] = raw
    return calls


def _source_refs(metadata: object) -> dict[str, str]:
    if not isinstance(metadata, dict):
        return {}
    raw_refs = metadata.get("source_refs")
    if not isinstance(raw_refs, (list, tuple)):
        return {}
    refs: dict[str, str] = {}
    for item in raw_refs:
        if (
            isinstance(item, dict)
            and isinstance(item.get("receipt_digest"), str)
            and isinstance(item.get("source_ref"), str)
        ):
            refs[item["receipt_digest"]] = item["source_ref"]
    return refs


def _receipt_status(receipt: SourceReceiptV1) -> str:
    if receipt.truncated:
        return "truncated"
    if receipt.source_kind is SourceKind.WEB_SEARCH_SNIPPET:
        return "search_only"
    if receipt.source_kind is SourceKind.WEB_EXTRACTED_CONTENT:
        return "extracted"
    return "complete"


def _fact_run_id(fact: ConversationFact) -> str | None:
    parts = fact.fact_id.split(":", 3)
    return parts[1] if len(parts) == 4 and parts[0] == "run" else None


def _source_tool(name: str) -> bool:
    return name in {
        "history_search",
        "history_get",
        "list_files",
        "read_file",
        "search_paths",
        "search_text",
        "read_file_chunk",
        "web_search",
        "web_fetch",
    }


def _empty_source_status(
    fact: ConversationFact,
    metadata: object,
) -> tuple[str | None, str | None]:
    if fact.content.get("is_error") is True:
        code = metadata.get("code") if isinstance(metadata, dict) else None
        return "failed", code if isinstance(code, str) else "source_error"
    if isinstance(metadata, dict):
        if metadata.get("status") == "no_match" or metadata.get("result_count") == 0:
            return "no_match", None
        if metadata.get("incomplete") is True or metadata.get("truncated") is True:
            return "partial", None
    return None, None


def _empty_source_kind(tool_name: str) -> str:
    if tool_name.startswith("history_"):
        return "history_search"
    if tool_name.startswith("web_"):
        return "web_search" if tool_name == "web_search" else "web_extracted_content"
    return "workspace_search"


def _empty_source_locator(tool_name: str) -> str:
    if tool_name.startswith("history_"):
        return "current workspace history"
    if tool_name.startswith("web_"):
        return "Tavily public Web"
    return "current workspace"


def _empty_source_title(tool_name: str, status: str) -> str:
    category = _empty_source_locator(tool_name)
    return f"{category}: {status.replace('_', ' ')}"


def _run_actions(state: ConversationState) -> tuple[str, ...]:
    active = state.active_run
    if active is None:
        return ("submit",)
    if active.status is ActiveRunStatus.AWAITING_APPROVAL:
        return ("approve", "reject")
    if active.status is ActiveRunStatus.AWAITING_DISCLOSURE:
        return ("ack_provider",)
    if (
        active.status is ActiveRunStatus.AWAITING_RECOVERY
        and active.executing_intent is not None
        and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
    ):
        return ("record_observation_unknown",)
    if (
        active.status is ActiveRunStatus.AWAITING_RECOVERY
        or active.phase is ContinuationPhase.EXECUTING
    ):
        return ("mark_succeeded", "mark_failed")
    return ("resume", "cancel")


def _goal_actions(state: ConversationState) -> tuple[str, ...]:
    goal = state.goal
    if goal is None or goal.status in {GoalStatus.CANCELLED, GoalStatus.VERIFIED_DONE}:
        return ()
    active = state.active_run
    if (
        active is not None
        and active.status is ActiveRunStatus.AWAITING_RECOVERY
        and active.executing_intent is not None
        and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
    ):
        return ("record_observation_unknown",)
    if active is not None and (
        active.status is ActiveRunStatus.AWAITING_RECOVERY
        or active.phase is ContinuationPhase.EXECUTING
    ):
        return ("mark_succeeded", "mark_failed")
    if goal.status in {GoalStatus.PAUSED, GoalStatus.BLOCKED}:
        return ("resume_goal", "correct_goal", "cancel_goal")
    return ("pause_goal", "correct_goal", "cancel_goal")


def _blocked_details(
    state: ConversationState,
) -> tuple[str | None, tuple[str, ...], str | None]:
    for fact in reversed(state.facts):
        if fact.content.get("code") != "blocked_claim":
            continue
        blocker = fact.content.get("blocker")
        attempts = fact.content.get("safe_attempts")
        resume = fact.content.get("resume_condition")
        return (
            blocker if isinstance(blocker, str) else None,
            tuple(item for item in attempts if isinstance(item, str))
            if isinstance(attempts, list)
            else (),
            resume if isinstance(resume, str) else None,
        )
    return None, (), None


_TAKEOVER_SESSION_UNSET = object()


def project_browser_takeover_status(
    state: ConversationState,
    *,
    current_session_ref: object = _TAKEOVER_SESSION_UNSET,
) -> str | None:
    """restart/空闲投影：pending takeover 的准确状态与控件（spec §7）。

    session 丢失或漂移 → needs-human；正常 pending → 等待用户完成浏览器
    接管（/browser-done、/cancel），绝不投影成 "resuming"。
    """
    pending = state.browser_takeover_pending
    if pending is None:
        return None
    if current_session_ref is _TAKEOVER_SESSION_UNSET or (
        current_session_ref is None or current_session_ref != pending.session_ref
    ):
        return (
            "Browser takeover session is missing or drifted; "
            "needs human decision before any browser action resumes."
        )
    return (
        "Browser takeover waiting: complete the sign-in in the dedicated browser "
        "window, then run /browser-done or /cancel to return control."
    )
