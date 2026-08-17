"""Kernel 的纯状态转换。

这里不调用模型、工具、持久化或事件 sink。所有外部效果由 loop 在状态转换之间排序。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

from agent.runtime.contracts import (
    AcknowledgeProviderDisclosure,
    Action,
    ActionDisposition,
    ActionTransition,
    ActiveRun,
    ActiveRunStatus,
    ApprovalGrant,
    ApprovalRequest,
    BlockedClaim,
    CancelGoal,
    CancelRun,
    CitationManifestV1,
    ClarificationRequest,
    CompletionClaim,
    ConfirmCriterion,
    ContinuationPhase,
    ControlInboxRequest,
    ControlReceipt,
    ControlRequestKind,
    ConversationFact,
    ConversationState,
    CriterionAdmissionBinding,
    EgressClass,
    EvidenceOracleKind,
    EvidenceRecord,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalBootstrap,
    GoalDelta,
    GoalDeltaProposal,
    GoalFrame,
    GoalProgress,
    GoalProposal,
    GoalStatus,
    InteractionState,
    PauseGoal,
    ProcessAuthorityLeaseV1,
    ProposedCriterion,
    ProviderDisclosureRequest,
    RecordedRunResult,
    RecoverUnknownObservation,
    RecoveryRequest,
    ReplayRecord,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    RevokeProcessAuthority,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
    canonical_action_digest,
    canonical_json_digest,
    source_result_since_latest_user,
)


class GoalRevisionConflictError(ValueError):
    pass


def _require_new_goal(state: ConversationState, goal: GoalFrame) -> None:
    if state.goal is not None:
        raise ValueError("conversation already has a goal")
    if goal.status is not GoalStatus.GOAL_READY:
        raise ValueError("new goal must start in GOAL_READY")
    fact_ids = {fact.fact_id for fact in state.facts}
    if not set(goal.created_from_fact_ids).issubset(fact_ids):
        raise ValueError("goal source fact is not authoritative conversation state")


def create_goal(state: ConversationState, goal: GoalFrame) -> ConversationState:
    _require_new_goal(state, goal)
    return replace(state, revision=state.revision + 1, goal=goal)


def _require_unused_correlation(state: ConversationState, correlation_id: str) -> None:
    if any(
        receipt.correlation_id == correlation_id
        for receipt in state.control_receipts
    ):
        raise ValueError("control correlation_id was already accepted")


def accept_clarification_request(
    state: ConversationState,
    request: ClarificationRequest,
) -> ConversationState:
    """接受一次澄清控制块:登记 correlation 绑定的 receipt 并进入 durable CLARIFYING。

    问题文本由 loop 作为该 run 唯一 assistant message 落盘,这里不触碰 active_run。
    """
    _require_unused_correlation(state, request.correlation_id)
    accepted_revision = state.revision + 1
    payload_digest = canonical_json_digest(
        {
            "question": request.question,
            "boundary_code": request.boundary_code,
            "missing_fields": request.missing_fields,
            "safe_assumptions": request.safe_assumptions,
        }
    )
    receipt = ControlReceipt.create(
        correlation_id=request.correlation_id,
        control_kind="clarification_request",
        goal_id=None,
        goal_revision=None,
        accepted_state_revision=accepted_revision,
        payload_digest=payload_digest,
    )
    return replace(
        state,
        revision=accepted_revision,
        interaction_state=InteractionState.CLARIFYING,
        control_receipts=(*state.control_receipts, receipt),
    )


def accept_goal_proposal(
    state: ConversationState,
    proposal: GoalProposal,
    bootstrap: GoalBootstrap | None,
) -> ConversationState:
    """接受一次 GoalProposal:在同一个 revision 里原子安装 Goal 与其 receipt。

    校验与 create_goal 同源(_require_new_goal),防止两条安装路径漂移;
    active_run 保持不变,由同一 loop 在 CAS 后重建上下文。
    """
    _require_unused_correlation(state, proposal.correlation_id)
    if source_result_since_latest_user(state):
        raise ValueError("GoalProposal requires a fresh user action after source retrieval")
    goal = proposal.goal_frame
    if bootstrap is None:
        raise ValueError("model GoalProposal requires Runtime goal bootstrap")
    if goal.created_from_fact_ids != (bootstrap.source_fact_id,):
        raise ValueError("model GoalProposal source binding does not match Runtime bootstrap")
    if goal.workspace_identity_digest != bootstrap.workspace_identity_digest:
        raise ValueError("model GoalProposal workspace binding does not match Runtime bootstrap")
    if goal.authority_snapshot != bootstrap.authority_snapshot:
        raise ValueError("model GoalProposal authority does not match Runtime bootstrap")
    if goal.admitted_criteria:
        raise ValueError("model GoalProposal cannot mint admitted criteria")
    _require_new_goal(state, goal)
    accepted_revision = state.revision + 1
    receipt = ControlReceipt.create(
        correlation_id=proposal.correlation_id,
        control_kind="goal_proposal",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=canonical_json_digest(asdict(goal)),
    )
    return replace(
        state,
        revision=accepted_revision,
        goal=goal,
        control_receipts=(*state.control_receipts, receipt),
    )


def record_goal_progress(
    state: ConversationState,
    progress: GoalProgress,
) -> ConversationState:
    goal = state.goal
    if goal is None or goal.goal_id != progress.goal_id:
        raise GoalRevisionConflictError("goal identity mismatch")
    if goal.revision != progress.goal_revision:
        raise GoalRevisionConflictError("goal revision mismatch")
    if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
        raise ValueError("terminal goal cannot accept progress")
    if goal.status is GoalStatus.PAUSED:
        # 进度会把 Goal 翻回 EXECUTING;暂停状态只能被显式 ResumeGoal 解除,
        # 不允许模型上报的 progress 静默恢复任务。
        raise ValueError("paused goal requires an explicit resume before progress")
    if any(
        receipt.correlation_id == progress.correlation_id
        for receipt in state.control_receipts
    ):
        raise ValueError("control correlation_id was already accepted")
    accepted_revision = state.revision + 1
    payload_digest = canonical_json_digest(
        {
            "goal_id": progress.goal_id,
            "goal_revision": progress.goal_revision,
            "summary": progress.summary,
            "next_step": progress.next_step,
        }
    )
    receipt = ControlReceipt.create(
        correlation_id=progress.correlation_id,
        control_kind="goal_progress",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=payload_digest,
    )
    return replace(
        state,
        revision=accepted_revision,
        goal=replace(
            goal,
            status=GoalStatus.EXECUTING,
            progress_summary=progress.summary,
            next_step=progress.next_step,
        ),
        control_receipts=(*state.control_receipts, receipt),
    )


def apply_goal_delta(state: ConversationState, delta: GoalDelta) -> ConversationState:
    goal = state.goal
    if goal is None or goal.goal_id != delta.goal_id:
        raise GoalRevisionConflictError("goal identity mismatch")
    if goal.revision != delta.expected_revision:
        raise GoalRevisionConflictError("goal revision mismatch")
    updates = dict(delta.updates)
    tuple_fields = {
        "targets",
        "scope",
        "non_goals",
        "assumptions",
        "proposed_criteria",
        "admitted_criteria",
    }
    for field_name in tuple_fields & updates.keys():
        updates[field_name] = tuple(updates[field_name])
    if "proposed_criteria" in updates:
        updates["proposed_criteria"] = tuple(
            _decode_delta_proposed_criterion(item) for item in updates["proposed_criteria"]
        )
    authority_fields = {
        "user_outcome",
        "beneficiary",
        "targets",
        "scope",
        "authority_snapshot",
    }
    updates.update(
        revision=goal.revision + 1,
        updated_at=delta.updated_at or goal.updated_at,
        progress_summary=None,
        next_step=None,
        status=(
            GoalStatus.NEEDS_AUTHORITY
            if authority_fields & delta.updates.keys()
            else GoalStatus.GOAL_READY
        ),
    )
    updated_goal = replace(goal, **updates)
    return replace(
        state,
        revision=state.revision + 1,
        goal=updated_goal,
        goal_authorizations=(),
        evidence_records=(),
        completion_claim=None,
        process_leases=(),
    )


def _decode_delta_proposed_criterion(value: object) -> ProposedCriterion:
    if not isinstance(value, Mapping) or set(value) != {
        "criterion_id",
        "description",
        "oracle_kind",
        "artifact_path",
    }:
        raise ValueError("goal delta proposed criterion has an invalid shape")
    criterion_id = value["criterion_id"]
    description = value["description"]
    oracle_kind = value["oracle_kind"]
    artifact_path = value["artifact_path"]
    if not isinstance(criterion_id, str) or not isinstance(description, str):
        raise ValueError("goal delta proposed criterion text fields must be strings")
    if not isinstance(oracle_kind, str):
        raise ValueError("goal delta proposed criterion oracle_kind must be a string")
    if not isinstance(artifact_path, str):
        raise ValueError("goal delta proposed criterion artifact_path must be a string")
    return ProposedCriterion(
        criterion_id=criterion_id,
        description=description,
        oracle_kind=EvidenceOracleKind(oracle_kind),
        artifact_path=artifact_path or None,
    )


def accept_goal_delta_proposal(
    state: ConversationState,
    proposal: GoalDeltaProposal,
) -> ConversationState:
    """受理 revision-bound delta；模型提议本身不产生任何新 authority。"""

    _require_unused_correlation(state, proposal.correlation_id)
    if {"admitted_criteria", "authority_snapshot"} & proposal.delta.updates.keys():
        raise ValueError("model GoalDeltaProposal cannot mint admission or authority")
    updated = apply_goal_delta(state, proposal.delta)
    goal = updated.goal
    if goal is None:
        raise ValueError("goal delta did not retain a goal")
    receipt = ControlReceipt.create(
        correlation_id=proposal.correlation_id,
        control_kind="goal_delta_proposal",
        goal_id=goal.goal_id,
        goal_revision=proposal.delta.expected_revision,
        accepted_state_revision=updated.revision,
        payload_digest=canonical_json_digest(asdict(proposal.delta)),
    )
    return replace(updated, control_receipts=(*updated.control_receipts, receipt))


def accept_blocked_claim(
    state: ConversationState,
    claim: BlockedClaim,
) -> ConversationState:
    """把准确 blocker 落为 durable fact 后安全结束当前 run。"""

    goal = _require_goal_revision(
        state,
        goal_id=claim.goal_id,
        expected_revision=claim.goal_revision,
    )
    _require_unused_correlation(state, claim.correlation_id)
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over blocked claim")
    if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
        raise ValueError("terminal goal cannot become blocked")
    active = state.active_run
    if active is None or active.phase is not ContinuationPhase.MODEL:
        raise ValueError("blocked claim requires an active model phase")
    accepted_revision = state.revision + 1
    fact = ConversationFact(
        fact_id=f"control:{claim.correlation_id}:blocked",
        kind=FactKind.POLICY_RESULT,
        content={
            "code": "blocked_claim",
            "blocker": claim.blocker,
            "safe_attempts": list(claim.safe_attempts),
            "resume_condition": claim.resume_condition,
        },
    )
    receipt = ControlReceipt.create(
        correlation_id=claim.correlation_id,
        control_kind="blocked_claim",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=canonical_json_digest(
            {
                "goal_id": claim.goal_id,
                "goal_revision": claim.goal_revision,
                "blocker": claim.blocker,
                "safe_attempts": claim.safe_attempts,
                "resume_condition": claim.resume_condition,
            }
        ),
    )
    return replace(
        state,
        revision=accepted_revision,
        facts=(*state.facts, fact),
        goal=replace(
            goal,
            status=GoalStatus.BLOCKED,
            next_step=claim.resume_condition,
        ),
        active_run=None,
        last_safe_result=RecordedRunResult(
            status=RunStatus.COMPLETED,
            run_id=active.run_id,
            message=claim.blocker,
        ),
        control_receipts=(*state.control_receipts, receipt),
    )


def _require_goal_revision(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> GoalFrame:
    goal = state.goal
    if goal is None or goal.goal_id != goal_id:
        raise GoalRevisionConflictError("goal identity mismatch")
    if goal.revision != expected_revision:
        raise GoalRevisionConflictError("goal revision mismatch")
    return goal


def _has_unknown_effect(state: ConversationState) -> bool:
    active = state.active_run
    return active is not None and (
        active.phase is ContinuationPhase.EXECUTING
        or active.status is ActiveRunStatus.AWAITING_RECOVERY
    )


def _stop_safe_active_run(
    state: ConversationState,
    *,
    status: RunStatus,
    message: str,
) -> tuple[None, RecordedRunResult | None]:
    active = state.active_run
    if active is None:
        return None, state.last_safe_result
    return None, RecordedRunResult(status=status, run_id=active.run_id, message=message)


def pause_goal(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=goal_id,
        expected_revision=expected_revision,
    )
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal pause")
    if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
        raise ValueError("terminal goal cannot be paused")
    if goal.status is GoalStatus.PAUSED:
        raise ValueError("goal is already paused")
    active_run, result = _stop_safe_active_run(
        state,
        status=RunStatus.COMPLETED,
        message="goal paused at a safe boundary",
    )
    return replace(
        state,
        revision=state.revision + 1,
        goal=replace(goal, status=GoalStatus.PAUSED),
        active_run=active_run,
        last_safe_result=result,
        process_leases=(),
    )


def resume_goal(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=goal_id,
        expected_revision=expected_revision,
    )
    if goal.status not in {GoalStatus.PAUSED, GoalStatus.BLOCKED}:
        raise ValueError("only a paused or blocked goal can resume")
    if state.active_run is not None:
        raise ValueError("paused goal cannot resume over an active run")
    return replace(
        state,
        revision=state.revision + 1,
        goal=replace(goal, status=GoalStatus.GOAL_READY),
    )


def cancel_goal(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=goal_id,
        expected_revision=expected_revision,
    )
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal cancellation")
    if goal.status is GoalStatus.VERIFIED_DONE:
        raise ValueError("verified goal cannot be cancelled")
    if goal.status is GoalStatus.CANCELLED:
        raise ValueError("goal is already cancelled")
    active_run, result = _stop_safe_active_run(
        state,
        status=RunStatus.CANCELLED,
        message="goal cancelled at a safe boundary",
    )
    return replace(
        state,
        revision=state.revision + 1,
        goal=replace(goal, status=GoalStatus.CANCELLED, next_step=None),
        completion_claim=None,
        active_run=active_run,
        last_safe_result=result,
        process_leases=(),
    )


def apply_control_request(
    state: ConversationState,
    request: ControlInboxRequest,
) -> ConversationState:
    """在 Runtime 的安全轮询点把 process-local 请求变成 durable state。"""

    goal = _require_goal_revision(
        state,
        goal_id=request.goal_id,
        expected_revision=request.goal_revision,
    )
    active = state.active_run
    if (
        request.conversation_id != state.conversation_id
        or active is None
        or active.owner_invocation_id != request.invocation_id
    ):
        raise ValueError("control request does not bind the active invocation")
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal control")
    if any(receipt.correlation_id == request.request_id for receipt in state.control_receipts):
        raise ValueError("control request was already accepted")

    if request.kind is ControlRequestKind.PAUSE:
        updated = pause_goal(
            state,
            goal_id=request.goal_id,
            expected_revision=request.goal_revision,
        )
    elif request.kind is ControlRequestKind.CANCEL:
        updated = cancel_goal(
            state,
            goal_id=request.goal_id,
            expected_revision=request.goal_revision,
        )
    else:
        if request.message is None:
            raise ValueError("goal correction message is required")
        correction = ConversationFact(
            fact_id=f"control:{request.request_id}:user",
            kind=FactKind.USER_MESSAGE,
            content={"text": request.message, "control": "goal_correction"},
        )
        updated = replace(
            state,
            revision=state.revision + 1,
            facts=(*state.facts, correction),
            goal=replace(
                goal,
                revision=goal.revision + 1,
                status=GoalStatus.NEEDS_AUTHORITY,
                progress_summary=None,
                next_step="Review and admit the user's correction before another effect.",
            ),
            goal_authorizations=(),
            evidence_records=(),
            completion_claim=None,
            interaction_state=InteractionState.CLARIFYING,
            active_run=None,
            last_safe_result=RecordedRunResult(
                status=RunStatus.COMPLETED,
                run_id=active.run_id,
                message="goal correction recorded at a safe boundary",
            ),
        )

    receipt = ControlReceipt.create(
        correlation_id=request.request_id,
        control_kind=f"goal_{request.kind.value}",
        goal_id=request.goal_id,
        goal_revision=request.goal_revision,
        accepted_state_revision=updated.revision,
        payload_digest=request.payload_digest,
    )
    return replace(updated, control_receipts=(*updated.control_receipts, receipt))


def pause_for_provider_disclosure(
    state: ConversationState,
    request: ProviderDisclosureRequest,
) -> ConversationState:
    active = state.active_run
    if active is None or active.phase is not ContinuationPhase.MODEL:
        raise ValueError("provider disclosure must pause before a model send")
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over disclosure")
    goal = state.goal
    if goal is not None and goal.status not in {
        GoalStatus.CANCELLED,
        GoalStatus.VERIFIED_DONE,
    }:
        goal = replace(goal, status=GoalStatus.NEEDS_AUTHORITY)
    return replace(
        state,
        revision=state.revision + 1,
        goal=goal,
        provider_disclosure_request=request,
        provider_disclosure_receipt=None,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_DISCLOSURE,
            owner_invocation_id=None,
        ),
    )


def acknowledge_provider_disclosure(
    state: ConversationState,
    action: AcknowledgeProviderDisclosure,
) -> ConversationState:
    request = state.provider_disclosure_request
    active = state.active_run
    if (
        request is None
        or request.request_digest != action.request_digest
        or active is None
        or active.status is not ActiveRunStatus.AWAITING_DISCLOSURE
    ):
        raise ValueError("provider disclosure acknowledgement does not match")
    goal = state.goal
    if goal is not None and goal.status is GoalStatus.NEEDS_AUTHORITY:
        goal = replace(goal, status=GoalStatus.GOAL_READY)
    return replace(
        state,
        goal=goal,
        provider_disclosure_receipt=request.acknowledge(
            receipt_id=f"disclosure-receipt:{action.action_seq}",
            acknowledged_action_seq=action.action_seq,
            acknowledged_at=action.acknowledged_at,
        ),
        active_run=replace(active, status=ActiveRunStatus.RUNNABLE),
    )


def record_completion_claim(
    state: ConversationState,
    claim: CompletionClaim,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=claim.goal_id,
        expected_revision=claim.goal_revision,
    )
    if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
        raise ValueError("completion claim requires an executable goal")
    if any(
        receipt.correlation_id == claim.correlation_id
        for receipt in state.control_receipts
    ):
        raise ValueError("control correlation_id was already accepted")
    evidence_ids = {record.evidence_id for record in state.evidence_records}
    if not set(claim.criterion_evidence_refs).issubset(evidence_ids):
        raise ValueError("completion claim references unknown evidence")
    accepted_revision = state.revision + 1
    payload_digest = canonical_json_digest(
        {
            "goal_id": claim.goal_id,
            "goal_revision": claim.goal_revision,
            "criterion_evidence_refs": claim.criterion_evidence_refs,
        }
    )
    receipt = ControlReceipt.create(
        correlation_id=claim.correlation_id,
        control_kind="completion_claim",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=payload_digest,
    )
    return replace(
        state,
        revision=accepted_revision,
        completion_claim=claim,
        control_receipts=(*state.control_receipts, receipt),
    )


def record_evidence(
    state: ConversationState,
    records: tuple[EvidenceRecord, ...],
) -> ConversationState:
    goal = state.goal
    if goal is None or not records:
        raise ValueError("evidence requires a current goal and at least one record")
    known = {record.evidence_id for record in state.evidence_records}
    criteria = {criterion.criterion_id: criterion for criterion in goal.admitted_criteria}
    for record in records:
        criterion = criteria.get(record.criterion_id)
        if (
            record.evidence_id in known
            or record.goal_id != goal.goal_id
            or record.goal_revision != goal.revision
            or criterion is None
            or record.oracle_kind is not criterion.oracle_kind
            or record.predicate_digest != canonical_json_digest(criterion.predicate)
        ):
            raise ValueError("evidence does not bind the current admitted criterion")
        known.add(record.evidence_id)
    return replace(
        state,
        revision=state.revision + 1,
        evidence_records=(*state.evidence_records, *records),
    )


def verify_goal_completion(state: ConversationState) -> ConversationState:
    goal = state.goal
    claim = state.completion_claim
    if goal is None or claim is None:
        raise ValueError("completion verification requires a current claim")
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal verification")
    if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
        raise ValueError("goal status is not eligible for completion verification")
    if claim.goal_id != goal.goal_id or claim.goal_revision != goal.revision:
        raise GoalRevisionConflictError("completion claim is stale")
    referenced = {
        record.evidence_id: record
        for record in state.evidence_records
        if record.evidence_id in claim.criterion_evidence_refs
    }
    mandatory = tuple(
        criterion for criterion in goal.admitted_criteria if criterion.mandatory
    )
    if not mandatory:
        raise ValueError("goal has no mandatory criterion")
    if any(criterion.oracle_kind is None for criterion in goal.proposed_criteria):
        raise ValueError(
            "every proposed completion criterion requires a typed evidence oracle"
        )
    artifact_requirements = tuple(
        criterion
        for criterion in goal.proposed_criteria
        if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
    )
    for requirement in artifact_requirements:
        if not any(
            criterion.criterion_id == requirement.criterion_id
            and criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and criterion.predicate.get("path") == requirement.artifact_path
            for criterion in mandatory
        ):
            raise ValueError(
                "artifact criterion must be admitted before completion verification"
            )
    evidence_by_criterion = {
        record.criterion_id: record for record in referenced.values()
    }
    if any(
        criterion.criterion_id not in evidence_by_criterion
        or not evidence_by_criterion[criterion.criterion_id].passed
        or evidence_by_criterion[criterion.criterion_id].goal_id != goal.goal_id
        or evidence_by_criterion[criterion.criterion_id].goal_revision != goal.revision
        or evidence_by_criterion[criterion.criterion_id].oracle_kind
        is not criterion.oracle_kind
        or evidence_by_criterion[criterion.criterion_id].predicate_digest
        != canonical_json_digest(criterion.predicate)
        for criterion in mandatory
    ):
        raise ValueError("current evidence does not prove every mandatory criterion")
    return replace(
        state,
        revision=state.revision + 1,
        goal=replace(goal, status=GoalStatus.VERIFIED_DONE, next_step=None),
        process_leases=(),
    )


def _conflict(state: ConversationState, reason: str) -> ActionTransition:
    return ActionTransition(ActionDisposition.CONFLICT, state, reason=reason)


def _find_replay(state: ConversationState, action_seq: int):
    return next(
        (record for record in state.replay_records if record.action_seq == action_seq),
        None,
    )


def _append_replay_record(
    state: ConversationState,
    *,
    action_seq: int,
    action_digest: str,
    max_replay_records: int,
) -> ConversationState | None:
    if max_replay_records < 1:
        raise ValueError("max_replay_records must be positive")

    records = list(state.replay_records)
    replay_floor = state.replay_floor
    while len(records) >= max_replay_records:
        # replay_floor 表示连续窗口；不能越过更早的 unfinished action 去删后项。
        if not records or records[0].result is None:
            return None
        evicted = records.pop(0)
        replay_floor = max(replay_floor, evicted.action_seq + 1)
    records.append(ReplayRecord(action_seq=action_seq, action_digest=action_digest))
    # replay record 与 next_action_seq 是同一个接受动作的原子不变量，不能构造半状态。
    return replace(
        state,
        next_action_seq=state.next_action_seq + 1,
        replay_floor=replay_floor,
        replay_records=tuple(records),
    )


def _action_is_legal(state: ConversationState, action: Action) -> tuple[bool, str | None]:
    active = state.active_run
    if isinstance(action, AcknowledgeProviderDisclosure):
        request = state.provider_disclosure_request
        if (
            request is None
            or request.request_digest != action.request_digest
            or active is None
            or active.status is not ActiveRunStatus.AWAITING_DISCLOSURE
        ):
            return False, "provider_disclosure_mismatch"
        return True, None
    if isinstance(action, ConfirmCriterion):
        goal = state.goal
        if (
            goal is None
            or goal.goal_id != action.goal_id
            or goal.revision != action.goal_revision
            or active is not None
        ):
            return False, "goal_revision_mismatch"
        criterion = next(
            (
                item
                for item in goal.admitted_criteria
                if item.criterion_id == action.criterion_id
            ),
            None,
        )
        if (
            criterion is None
            or criterion.oracle_kind is not EvidenceOracleKind.USER_CONFIRMATION
            or criterion.admission_digest != action.admission_binding_digest
        ):
            return False, "criterion_confirmation_mismatch"
        return True, None
    if isinstance(action, SubmitMessage):
        if active is not None:
            return False, "illegal_action_for_state"
        if not action.message.strip() or not action.run_id:
            return False, "invalid_submit_message"
        return True, None

    if isinstance(action, (PauseGoal, ResumeGoal, CancelGoal)):
        goal = state.goal
        if goal is None or goal.goal_id != action.goal_id:
            return False, "goal_identity_mismatch"
        if goal.revision != action.goal_revision:
            return False, "goal_revision_mismatch"
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        if isinstance(action, PauseGoal):
            if goal.status in {
                GoalStatus.PAUSED,
                GoalStatus.VERIFIED_DONE,
                GoalStatus.CANCELLED,
            }:
                return False, "illegal_action_for_state"
            return True, None
        if isinstance(action, ResumeGoal):
            if goal.status not in {GoalStatus.PAUSED, GoalStatus.BLOCKED} or active is not None:
                return False, "illegal_action_for_state"
            return True, None
        if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
            return False, "illegal_action_for_state"
        return True, None

    if isinstance(action, RevokeProcessAuthority):
        # revoke 是独立 authority action；expected_revision CAS 由 accept_action 通用处理。
        # unknown-effect recovery 优先，revoke 不假装取消已可能的 in-flight effect。
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        return True, None

    if active is None:
        return False, "illegal_action_for_state"

    if isinstance(action, ResolveApproval):
        pending = active.pending_request
        if active.status is not ActiveRunStatus.AWAITING_APPROVAL or not isinstance(
            pending, ApprovalRequest
        ):
            return False, "illegal_action_for_state"
        if (
            action.request_id != pending.request_id
            or action.binding_digest != pending.binding_digest
        ):
            return False, "pending_request_mismatch"
        return True, None

    if isinstance(action, ResolveUnknownToolOutcome):
        pending = active.pending_request
        if active.status is not ActiveRunStatus.AWAITING_RECOVERY or not isinstance(
            pending, RecoveryRequest
        ):
            return False, "illegal_action_for_state"
        if (
            action.request_id != pending.request_id
            or action.binding_digest != pending.binding_digest
        ):
            return False, "pending_request_mismatch"
        if (
            active.executing_intent is not None
            and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
        ):
            return False, "typed_observation_recovery_required"
        return True, None

    if isinstance(action, RecoverUnknownObservation):
        intent = active.executing_intent
        if (
            intent is None
            or active.phase is not ContinuationPhase.EXECUTING
            or intent.egress is not EgressClass.PUBLIC_NETWORK
            or action.tool_call_id != intent.tool_call_id
            or action.intent_digest != intent.intent_digest
        ):
            return False, "observation_recovery_mismatch"
        return True, None

    if isinstance(action, Resume):
        if active.status in {
            ActiveRunStatus.RUNNABLE,
            ActiveRunStatus.AWAITING_APPROVAL,
            ActiveRunStatus.PAUSED_LIMIT,
            ActiveRunStatus.PAUSED_RETRYABLE,
        }:
            return True, None
        return False, "illegal_action_for_state"

    if isinstance(action, CancelRun):
        if active.status is ActiveRunStatus.AWAITING_RECOVERY:
            # 未知 effect 必须由人类 exact 分类，不能被取消绕过。
            return False, "illegal_action_for_state"
        if (
            active.status is ActiveRunStatus.RUNNABLE
            and active.phase is ContinuationPhase.EXECUTING
        ):
            # EXECUTING 的 effect 可能已发生；只能 Resume 进入 unknown-outcome recovery。
            return False, "illegal_action_for_state"
        if active.status in {
            ActiveRunStatus.RUNNABLE,
            ActiveRunStatus.AWAITING_APPROVAL,
            ActiveRunStatus.PAUSED_LIMIT,
            ActiveRunStatus.PAUSED_RETRYABLE,
        }:
            return True, None
        return False, "illegal_action_for_state"
    return False, "illegal_action_for_state"


def _add_minutes_rfc3339(timestamp: str, minutes: int) -> str:
    """对 RFC 3339（含 ``Z``）时间戳加分钟，返回同为 ``Z`` 后缀的 RFC 3339。"""

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _require_zoned_rfc3339(timestamp: str) -> str:
    """F6（review finding）：批准时刻必须是带时区 RFC3339——naive/malformed fail closed。"""

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("approved_at must be a zoned RFC3339 timestamp")
    return timestamp


def _mint_process_authority_lease(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    approved_at: str | None = None,
) -> ConversationState:
    """ResolveApproval(approved=True) 对 process candidate 铸造 durable lease（KTD3/KTD4）。

    lease 时效锚定**批准**时刻。process approval 必须携带带时区的 RFC3339
    ``approved_at``；缺失、malformed 或 naive 时间一律 fail closed，不能退回 candidate
    创建时刻并静默缩短租期。非 process approval（无 candidate）不铸造。lease use 在
    durable EXECUTING checkpoint 时单调消费（U6/U7）。
    """

    candidate = pending.process_authority_candidate
    if candidate is None:
        return state
    if approved_at is None:
        raise ValueError("approved_at is required for process approval")
    lease_issued_at = _require_zoned_rfc3339(approved_at)
    lease = ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity=pending.request_id,
        issued_at=lease_issued_at,
        expires_at=_add_minutes_rfc3339(lease_issued_at, candidate.expiry_minutes),
        max_uses=candidate.max_uses,
        uses_consumed=0,
    )
    return replace(state, process_leases=(*state.process_leases, lease))


def _apply_action(state: ConversationState, action: Action) -> ConversationState:
    if isinstance(action, AcknowledgeProviderDisclosure):
        return acknowledge_provider_disclosure(state, action)
    if isinstance(action, ConfirmCriterion):
        goal = state.goal
        if goal is None:
            raise ValueError("criterion confirmation requires a goal")
        fact = ConversationFact(
            fact_id=f"action:{action.action_seq}:criterion-confirmation",
            kind=FactKind.USER_MESSAGE,
            content={
                "criterion_id": action.criterion_id,
                "confirmed": action.confirmed,
            },
        )
        evidence = state.evidence_records
        if action.confirmed:
            criterion = next(
                item
                for item in goal.admitted_criteria
                if item.criterion_id == action.criterion_id
            )
            evidence = (
                *evidence,
                EvidenceRecord(
                    evidence_id=(
                        f"evidence:{goal.goal_id}:{goal.revision}:{criterion.criterion_id}"
                    ),
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    criterion_id=criterion.criterion_id,
                    oracle_kind=criterion.oracle_kind,
                    predicate_digest=canonical_json_digest(criterion.predicate),
                    source_fact_ids=(fact.fact_id,),
                    source_digest=canonical_json_digest(
                        [
                            {
                                "fact_id": fact.fact_id,
                                "kind": fact.kind,
                                "content": fact.content,
                            }
                        ]
                    ),
                    oracle_identity="user-confirmation:v1",
                    passed=True,
                    observed_at="operator-confirmed",
                ),
            )
        return replace(state, facts=(*state.facts, fact), evidence_records=evidence)
    if isinstance(action, SubmitMessage):
        fact = ConversationFact(
            fact_id=f"action:{action.action_seq}:user",
            kind=FactKind.USER_MESSAGE,
            content={"text": action.message},
        )
        return replace(
            state,
            facts=(*state.facts, fact),
            active_run=ActiveRun(run_id=action.run_id),
        )

    if isinstance(action, PauseGoal):
        return pause_goal(
            state,
            goal_id=action.goal_id,
            expected_revision=action.goal_revision,
        )
    if isinstance(action, ResumeGoal):
        return resume_goal(
            state,
            goal_id=action.goal_id,
            expected_revision=action.goal_revision,
        )
    if isinstance(action, CancelGoal):
        return cancel_goal(
            state,
            goal_id=action.goal_id,
            expected_revision=action.goal_revision,
        )

    if isinstance(action, RevokeProcessAuthority):
        if action.lease_id is None:
            retained: tuple[ProcessAuthorityLeaseV1, ...] = ()
        else:
            retained = tuple(
                lease
                for lease in state.process_leases
                if lease.lease_id != action.lease_id
            )
        return replace(state, process_leases=retained)

    active = state.active_run
    if active is None:
        raise ValueError("active run required")

    if isinstance(action, ResolveApproval):
        pending = active.pending_request
        if not isinstance(pending, ApprovalRequest):
            raise ValueError("approval request required")
        if action.approved:
            updated = replace(
                active,
                status=ActiveRunStatus.RUNNABLE,
                phase=ContinuationPhase.TOOL,
                pending_request=None,
                approval_grant=ApprovalGrant(
                    request_id=pending.request_id,
                    binding_digest=pending.binding_digest,
                    approval_basis_revision=pending.approval_basis_revision,
                ),
                approved_request_ids=(*active.approved_request_ids, pending.request_id),
            )
            updated_state = replace(state, active_run=updated)
            updated_state = _mint_process_authority_lease(
                updated_state, pending, approved_at=action.approved_at
            )
            updated_state = _admit_process_artifact_criterion(
                updated_state, pending, action=action,
            )
            updated_state = _admit_approved_process_receipt_criterion(
                updated_state,
                pending,
                action=action,
            )
            updated_state = _admit_approved_file_criterion(
                updated_state,
                action=action,
                active=active,
            )
            return _admit_approved_research_criterion(
                updated_state,
                action=action,
                active=active,
            )
        rejection = ConversationFact(
            fact_id=f"action:{action.action_seq}:rejection",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": pending.tool_call_id,
                "text": "User rejected the requested tool action.",
                "is_error": True,
                "rejected": True,
            },
        )
        updated = replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            phase=(
                ContinuationPhase.TOOL
                if active.batch_cursor + 1 < len(active.tool_calls)
                else ContinuationPhase.MODEL
            ),
            pending_request=None,
            approval_grant=None,
            rejected_request_ids=(*active.rejected_request_ids, pending.request_id),
            batch_cursor=active.batch_cursor + 1,
            tool_calls=(
                active.tool_calls
                if active.batch_cursor + 1 < len(active.tool_calls)
                else ()
            ),
        )
        return replace(state, active_run=updated, facts=(*state.facts, rejection))

    if isinstance(action, ResolveUnknownToolOutcome):
        pending = active.pending_request
        if not isinstance(pending, RecoveryRequest):
            raise ValueError("recovery request required")
        succeeded = action.resolution.value == "mark_succeeded"
        synthetic = ConversationFact(
            fact_id=f"action:{action.action_seq}:recovery",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": pending.tool_call_id,
                "text": (
                    "Operator classified the previous tool effect as succeeded."
                    if succeeded
                    else "Operator classified the previous tool effect as failed."
                ),
                "is_error": not succeeded,
                "synthetic": True,
            },
        )
        updated = replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            phase=(
                ContinuationPhase.TOOL
                if active.batch_cursor + 1 < len(active.tool_calls)
                else ContinuationPhase.MODEL
            ),
            pending_request=None,
            executing_intent=None,
            batch_cursor=active.batch_cursor + 1,
            tool_calls=(
                active.tool_calls
                if active.batch_cursor + 1 < len(active.tool_calls)
                else ()
            ),
        )
        return replace(state, active_run=updated, facts=(*state.facts, synthetic))

    if isinstance(action, RecoverUnknownObservation):
        intent = active.executing_intent
        if intent is None or intent.egress is not EgressClass.PUBLIC_NETWORK:
            raise ValueError("PUBLIC_NETWORK executing intent required")
        observation = ConversationFact(
            fact_id=f"action:{action.action_seq}:observation-unknown",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": intent.tool_call_id,
                "text": (
                    "The public-network observation outcome is unknown; the previous "
                    "request will not be retried automatically."
                ),
                "is_error": True,
                "executed": True,
                "metadata": {
                    "code": "observation_unknown",
                    "observation_outcome": "observation_unknown",
                    "source_receipts": [],
                },
            },
        )
        next_cursor = active.batch_cursor + 1
        has_more = next_cursor < len(active.tool_calls)
        updated = replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            phase=ContinuationPhase.TOOL if has_more else ContinuationPhase.MODEL,
            pending_request=None,
            executing_intent=None,
            batch_cursor=next_cursor,
            tool_calls=active.tool_calls if has_more else (),
            approval_grant=None,
            owner_invocation_id=None,
        )
        return replace(state, active_run=updated, facts=(*state.facts, observation))

    if isinstance(action, Resume):
        if active.status in {ActiveRunStatus.AWAITING_APPROVAL, ActiveRunStatus.AWAITING_RECOVERY}:
            return state
        return replace(
            state,
            active_run=replace(
                active,
                status=ActiveRunStatus.RUNNABLE,
                owner_invocation_id=None,
            ),
        )

    if isinstance(action, CancelRun):
        return replace(
            state,
            active_run=None,
            last_safe_result=RecordedRunResult(
                status=RunStatus.CANCELLED,
                run_id=active.run_id,
            ),
        )
    raise TypeError(f"unsupported action: {type(action).__name__}")


def _admit_approved_file_criterion(
    state: ConversationState,
    *,
    action: ResolveApproval,
    active: ActiveRun,
) -> ConversationState:
    """审批 exact 文件写入时由 Runtime 铸造 deterministic read-back criterion。"""

    goal = state.goal
    if goal is None or active.batch_cursor >= len(active.tool_calls):
        return state
    call = active.tool_calls[active.batch_cursor]
    pending = active.pending_request
    path = call.arguments.get("path")
    if (
        call.name not in {"write_file", "edit_file"}
        or not isinstance(path, str)
        or not isinstance(pending, ApprovalRequest)
        or pending.new_content_digest is None
    ):
        return state
    criterion_id = (
        goal.proposed_criteria[0].criterion_id
        if len(goal.proposed_criteria) == 1
        else f"criterion:approved-write:{call.tool_call_id}"
    )
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids
            and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("approved write criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "path": path,
        "sha256": pending.new_content_digest,
    }
    if any(
        item.criterion_id == criterion_id
        and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and item.predicate == predicate
        for item in goal.admitted_criteria
    ):
        return state
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:approval:{action.action_seq}:{call.tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate=predicate,
        required_evidence_class="workspace_file",
    )
    description = next(
        (
            item.description
            for item in goal.proposed_criteria
            if item.criterion_id == criterion_id
        ),
        f"approved file {path} has the exact requested content",
    )
    admitted = binding.admit(description)
    superseded_ids = {
        item.criterion_id
        for item in goal.admitted_criteria
        if item.criterion_id == criterion_id
        or (
            item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and item.predicate.get("path") == path
        )
        or (
            item.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
            and path
            in {
                item.predicate.get("artifact_path"),
                item.predicate.get("manifest_path"),
            }
        )
    }
    retained_criteria = tuple(
        item
        for item in goal.admitted_criteria
        if item.criterion_id not in superseded_ids
    )
    retained_evidence = tuple(
        item
        for item in state.evidence_records
        if item.criterion_id not in superseded_ids
    )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*retained_criteria, admitted),
        ),
        evidence_records=retained_evidence,
        completion_claim=None,
    )


def _admit_approved_research_criterion(
    state: ConversationState,
    *,
    action: ResolveApproval,
    active: ActiveRun,
) -> ConversationState:
    """审批 citation sidecar 时铸造额外的 Runtime-owned provenance criterion。"""

    goal = state.goal
    if goal is None or active.batch_cursor >= len(active.tool_calls):
        return state
    call = active.tool_calls[active.batch_cursor]
    pending = active.pending_request
    path = call.arguments.get("path")
    content = call.arguments.get("content")
    if (
        call.name not in {"write_file", "edit_file"}
        or not isinstance(path, str)
        or not path.endswith(".citations.json")
        or not isinstance(content, str)
        or not isinstance(pending, ApprovalRequest)
        or pending.new_content_digest is None
    ):
        return state
    try:
        manifest = CitationManifestV1.from_json(content)
    except ValueError:
        return state
    if (
        manifest.goal_id != goal.goal_id
        or manifest.goal_revision != goal.revision
        or path != f"{manifest.artifact_path}.citations.json"
        or path not in goal.targets
        or manifest.artifact_path not in goal.targets
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids
            and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("research criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    criterion_id = "criterion:research-provenance:" + canonical_json_digest(
        {"goal_id": goal.goal_id, "artifact_path": manifest.artifact_path}
    )[:16]
    predicate = {
        "artifact_path": manifest.artifact_path,
        "artifact_sha256": manifest.artifact_sha256,
        "manifest_path": path,
        "manifest_sha256": pending.new_content_digest,
        "manifest_digest": manifest.manifest_digest,
        "minimum_distinct_sources": 3,
        "required_source_kinds": [
            "history_excerpt",
            "workspace_excerpt",
            "web_extracted_content",
        ],
        "required_source_classes": ["history", "workspace"],
        "required_receipt_digests": [],
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:research:{action.action_seq}:{call.tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.RESEARCH_PROVENANCE,
        predicate=predicate,
        required_evidence_class="research_provenance",
    )
    admitted = binding.admit(
        "artifact and citation sidecar are bound to current-Goal source receipts"
    )
    retained_criteria = tuple(
        item for item in goal.admitted_criteria if item.criterion_id != criterion_id
    )
    retained_evidence = tuple(
        item for item in state.evidence_records if item.criterion_id != criterion_id
    )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*retained_criteria, admitted),
        ),
        evidence_records=retained_evidence,
        completion_claim=None,
    )


def _admit_approved_process_receipt_criterion(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    action: ResolveApproval,
) -> ConversationState:
    """批准 process 时即固化成功 receipt 义务，恢复路径不得绕过。"""

    goal = state.goal
    candidate = pending.process_authority_candidate
    if goal is None or candidate is None:
        return state
    if (
        candidate.goal_id != goal.goal_id
        or candidate.goal_revision != goal.revision
        or candidate.workspace_identity_digest != goal.workspace_identity_digest
    ):
        raise ValueError("process candidate does not bind the current Goal")
    criterion_id = (
        f"criterion:process-receipt:{goal.goal_id}:{goal.revision}:"
        f"{pending.tool_call_id}"
    )
    if any(
        item.criterion_id == criterion_id
        and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.admitted_criteria
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids
            and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("process receipt criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "receipt_kind": "process_v1",
        "command_fingerprint": candidate.command_fingerprint,
        "outcome": "exited",
        "exit_code": 0,
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=(
            f"criterion-admission:process-receipt:{action.action_seq}:"
            f"{pending.tool_call_id}"
        ),
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="process_receipt",
    )
    admitted = binding.admit(
        "approved local_process must produce the exact successful Kernel receipt"
    )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def _admit_process_artifact_criterion(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    action: ResolveApproval,
) -> ConversationState:
    """ResolveApproval 时铸造 FILESYSTEM_DIGEST criterion（F4：用户确认 digest）。

    authority 是 **ResolveApproval action 自带的 confirmed_artifact**（用户在批准
    command 的同一 typed action 里确认 path+sha256）——模型无法自供（schema 回
    closed 4 字段）。candidate 的 ea 字段是 runtime 内部残留（prepare 路径恒
    None，保持 checkpoint 兼容），不再作为 authority 来源。malformed fail closed。
    """

    goal = state.goal
    if goal is None:
        return state
    ea_path = action.confirmed_artifact_path
    ea_sha = action.confirmed_artifact_sha256
    requirement = pending.artifact_confirmation_requirement
    if requirement is not None and not any(
        item.criterion_id == requirement.criterion_id
        and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and item.artifact_path == requirement.artifact_path
        for item in goal.proposed_criteria
    ):
        raise ValueError(
            "artifact confirmation requirement does not match a current Goal criterion"
        )
    if requirement is not None and (
        ea_path is None
        or ea_sha is None
        or ea_path != requirement.artifact_path
    ):
        raise ValueError(
            "artifact confirmation must match the pending path and include sha256"
        )
    if ea_path is None and ea_sha is None:
        return state
    import re as _re

    if (
        not isinstance(ea_path, str)
        or not ea_path
        or "\x00" in ea_path
        or ea_path.startswith("/")
        or ".." in ea_path.split("/")
        or not isinstance(ea_sha, str)
        or not _re.match(r"^[a-f0-9]{64}$", ea_sha)
    ):
        raise ValueError("confirmed_artifact must be workspace-relative path + 64-hex sha256")
    criterion_id = (
        requirement.criterion_id
        if requirement is not None
        else f"criterion:process-artifact:{goal.goal_id}:{goal.revision}:{ea_path}"
    )
    if any(
        item.criterion_id == criterion_id
        and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        for item in goal.admitted_criteria
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids
            and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("process artifact criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {"path": ea_path, "sha256": ea_sha}
    binding = CriterionAdmissionBinding.create(
        binding_id=(
            f"criterion-admission:process-artifact:{action.action_seq}:{pending.tool_call_id}"
        ),
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate=predicate,
        required_evidence_class="workspace_file",
    )
    admitted = binding.admit(
        f"process artifact {ea_path} reads back with exact approved sha256"
    )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def admit_process_receipt_criterion(
    state: ConversationState,
    *,
    tool_call_id: str,
    receipt_digest: str,
    command_fingerprint: str,
    action_seq: int,
) -> ConversationState:
    """兼容路径：成功 process receipt 后补铸 mandatory TOOL_RECEIPT criterion。

    正常路径已在批准时铸造不含未知 digest 的义务，因同 criterion_id
    本函数会保持原义务。它仅为旧的非标准路径保留；不信任 model prose。
    """

    goal = state.goal
    if goal is None:
        return state
    criterion_id = f"criterion:process-receipt:{goal.goal_id}:{goal.revision}:{tool_call_id}"
    if any(
        item.criterion_id == criterion_id
        and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.admitted_criteria
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids
            and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        return state
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "receipt_kind": "process_v1",
        "receipt_digest": receipt_digest,
        "command_fingerprint": command_fingerprint,
        "outcome": "exited",
        "exit_code": 0,
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:process-receipt:{action_seq}:{tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="process_receipt",
    )
    admitted = binding.admit("local_process command contract satisfied by Kernel receipt")
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def accept_action(
    state: ConversationState | None,
    action: Action,
    *,
    max_replay_records: int = 64,
) -> ActionTransition:
    if state is None:
        state = ConversationState.new(action.conversation_id)
    if action.conversation_id != state.conversation_id:
        return _conflict(state, "conversation_mismatch")
    if action.action_seq < 1:
        return _conflict(state, "invalid_action_sequence")

    digest = canonical_action_digest(action)
    replay = _find_replay(state, action.action_seq)
    if replay is not None:
        if replay.action_digest != digest:
            return _conflict(state, "action_digest_mismatch")
        if replay.result is None:
            return _conflict(state, "action_in_progress")
        return ActionTransition(
            ActionDisposition.REPLAYED,
            state,
            recorded_result=replay.result,
        )
    if action.action_seq < state.replay_floor:
        return _conflict(state, "action_sequence_expired")
    if action.action_seq < state.next_action_seq:
        return _conflict(state, "action_result_unavailable")
    if action.action_seq > state.next_action_seq:
        return _conflict(state, "action_sequence_gap")
    if action.expected_revision != state.revision:
        return _conflict(state, "revision_mismatch")

    legal, reason = _action_is_legal(state, action)
    if not legal:
        return _conflict(state, reason or "illegal_action_for_state")

    with_replay = _append_replay_record(
        state,
        action_seq=action.action_seq,
        action_digest=digest,
        max_replay_records=max_replay_records,
    )
    if with_replay is None:
        return _conflict(state, "replay_capacity_exhausted")
    applied = _apply_action(with_replay, action)
    applied = replace(
        applied,
        revision=state.revision + 1,
    )
    return ActionTransition(ActionDisposition.ACCEPTED, applied)


def finalize_action(
    state: ConversationState,
    *,
    action_seq: int,
    result: RecordedRunResult,
    max_replay_records: int = 64,
) -> ConversationState:
    if max_replay_records < 1:
        raise ValueError("max_replay_records must be positive")
    records = list(state.replay_records)
    index = next((i for i, record in enumerate(records) if record.action_seq == action_seq), None)
    if index is None:
        raise ValueError("action replay record not found")
    if records[index].result is not None:
        if records[index].result == result:
            return state
        raise ValueError("action already finalized with a different result")
    records[index] = replace(records[index], result=result)
    replay_floor = state.replay_floor
    while len(records) > max_replay_records:
        evicted = records.pop(0)
        if evicted.result is None:
            raise ValueError("cannot evict an unfinished replay record")
        replay_floor = max(replay_floor, evicted.action_seq + 1)
    return replace(
        state,
        revision=state.revision + 1,
        replay_floor=replay_floor,
        replay_records=tuple(records),
        last_safe_result=result,
    )


def complete_run(state: ConversationState, *, message: str | None = None) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("active run required")
    facts = state.facts
    if message is not None:
        facts = (
            *facts,
            ConversationFact(
                fact_id=f"run:{active.run_id}:assistant:{state.revision + 1}",
                kind=FactKind.ASSISTANT_MESSAGE,
                content={"text": message},
            ),
        )
    return replace(
        state,
        revision=state.revision + 1,
        facts=facts,
        active_run=None,
        last_safe_result=RecordedRunResult(
            status=RunStatus.COMPLETED,
            run_id=active.run_id,
            message=message,
        ),
    )


def claim_run(state: ConversationState, invocation_id: str) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    if active.owner_invocation_id is not None:
        raise ValueError("run is already owned")
    if not invocation_id:
        raise ValueError("invocation_id must not be empty")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(active, owner_invocation_id=invocation_id),
    )


def start_tool_batch(
    state: ConversationState,
    calls: tuple[ToolCall, ...],
    *,
    preamble: str | None = None,
) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    if active.phase is not ContinuationPhase.MODEL:
        raise ValueError("tool batch can only start from MODEL phase")
    if not calls:
        raise ValueError("tool batch must not be empty")
    call_ids = tuple(call.tool_call_id for call in calls)
    if len(set(call_ids)) != len(call_ids):
        raise ValueError("tool_call_id must be unique within a batch")
    serialized_calls = [
        {
            "tool_call_id": call.tool_call_id,
            "name": call.name,
            "arguments": call.arguments,
        }
        for call in calls
    ]
    content = {"calls": serialized_calls}
    if preamble:
        content["preamble"] = preamble
    fact = ConversationFact(
        fact_id=f"run:{active.run_id}:tool-batch:{state.revision + 1}",
        kind=FactKind.TOOL_CALLS,
        content=content,
    )
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, fact),
        active_run=replace(
            active,
            phase=ContinuationPhase.TOOL,
            batch_cursor=0,
            tool_calls=calls,
            approval_grant=None,
        ),
    )


def append_policy_result(state: ConversationState, *, code: str, message: str) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("active run required")
    fact = ConversationFact(
        fact_id=f"run:{active.run_id}:policy:{state.revision + 1}",
        kind=FactKind.POLICY_RESULT,
        content={"code": code, "text": message},
    )
    return replace(state, revision=state.revision + 1, facts=(*state.facts, fact))


def pause_for_limit(state: ConversationState) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.PAUSED_LIMIT,
            owner_invocation_id=None,
        ),
    )


def pause_for_retryable(state: ConversationState) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.PAUSED_RETRYABLE,
            owner_invocation_id=None,
        ),
    )


def fail_run(state: ConversationState, *, code: str, message: str) -> ConversationState:
    return end_run(
        state,
        status=RunStatus.FAILED_FATAL,
        code=code,
        message=message,
    )


def end_run(
    state: ConversationState,
    *,
    status: RunStatus,
    code: str,
    message: str,
) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("active run required")
    result = RecordedRunResult(
        status=status,
        run_id=active.run_id,
        message=message,
        error_code=code,
    )
    return replace(
        state,
        revision=state.revision + 1,
        active_run=None,
        last_safe_result=result,
    )


def record_nonexecuted_tool_result(
    state: ConversationState,
    result: ConversationFact,
) -> ConversationState:
    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.TOOL
        or result.kind is not FactKind.TOOL_RESULT
    ):
        raise ValueError("TOOL phase and Tool Result required")
    expected = active.tool_calls[active.batch_cursor] if active.tool_calls else None
    if expected is None or result.content.get("tool_call_id") != expected.tool_call_id:
        raise ValueError("tool result does not match the current batch cursor")
    next_cursor = active.batch_cursor + 1
    has_more = next_cursor < len(active.tool_calls)
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, result),
        active_run=replace(
            active,
            phase=ContinuationPhase.TOOL if has_more else ContinuationPhase.MODEL,
            batch_cursor=next_cursor,
            tool_calls=active.tool_calls if has_more else (),
            approval_grant=None,
        ),
    )
def pause_for_approval(
    state: ConversationState,
    request: ApprovalRequest,
) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    if request.run_id != active.run_id or active.pending_request is not None:
        raise ValueError("approval request does not match active run")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            owner_invocation_id=None,
        ),
    )


def mark_executing(
    state: ConversationState,
    *,
    tool_call_id: str,
    intent_digest: str,
    idempotency_key: str,
    side_effect: SideEffectClass = SideEffectClass.WRITE,
    egress: EgressClass = EgressClass.NONE,
    operation: str = "legacy_effect",
    request_identity: str | None = None,
    execution_authority: ExecutionAuthorityClass = ExecutionAuthorityClass.IN_PROCESS,
    process_lease_id: str | None = None,
) -> ConversationState:
    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.TOOL
        or active.executing_intent is not None
        or active.pending_request is not None
    ):
        raise ValueError("clean RUNNABLE active run required")
    current_call = active.tool_calls[active.batch_cursor]
    if current_call.tool_call_id != tool_call_id:
        raise ValueError("executing intent must bind the current tool call")
    record = ExecutingIntentRecord(
        tool_call_id=tool_call_id,
        intent_digest=intent_digest,
        idempotency_key=idempotency_key,
        side_effect=side_effect,
        egress=egress,
        execution_authority=execution_authority,
        operation=operation,
        request_identity=request_identity or idempotency_key,
    )
    if (
        execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
        and process_lease_id is None
    ):
        # F1（P1 review finding 2026-08-16）：LOCAL_SAME_UID_PROCESS 的 EXECUTING
        # checkpoint 必须绑定 exact durable lease（lease use 单调消费的载体）；
        # 无 lease 不得进入 EXECUTING（裸 ApprovalGrant 不能绕过 lease 合同）。
        raise ValueError(
            "process executing intent must consume an exact durable lease"
        )
    process_leases = state.process_leases
    if process_lease_id is not None:
        # lease use 在 durable EXECUTING checkpoint 时单调消费；超过 max_uses 由
        # ProcessAuthorityLeaseV1.__post_init__ fail closed（R9 use exhaustion）。
        incremented: list[ProcessAuthorityLeaseV1] = []
        consumed = False
        for lease in process_leases:
            if lease.lease_id == process_lease_id and not consumed:
                incremented.append(
                    replace(lease, uses_consumed=lease.uses_consumed + 1)
                )
                consumed = True
            else:
                incremented.append(lease)
        if not consumed:
            raise ValueError("process lease use could not bind the executing intent")
        process_leases = tuple(incremented)
    return replace(
        state,
        revision=state.revision + 1,
        process_leases=process_leases,
        active_run=replace(
            active,
            phase=ContinuationPhase.EXECUTING,
            executing_intent=record,
            approval_grant=None,
        ),
    )


def record_tool_result(
    state: ConversationState,
    result: ConversationFact,
    *,
    intent_digest: str,
) -> ConversationState:
    active = state.active_run
    intent = active.executing_intent if active else None
    tool_call_id = result.content.get("tool_call_id")
    if (
        active is None
        or active.phase is not ContinuationPhase.EXECUTING
        or intent is None
        or intent.intent_digest != intent_digest
        or intent.tool_call_id != tool_call_id
        or result.kind is not FactKind.TOOL_RESULT
    ):
        raise ValueError("matching EXECUTING intent and Tool Result required")
    next_cursor = active.batch_cursor + 1
    has_more = next_cursor < len(active.tool_calls)
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, result),
        active_run=replace(
            active,
            phase=ContinuationPhase.TOOL if has_more else ContinuationPhase.MODEL,
            executing_intent=None,
            batch_cursor=next_cursor,
            tool_calls=active.tool_calls if has_more else (),
        ),
    )


def pause_for_recovery(
    state: ConversationState,
    request: RecoveryRequest,
) -> ConversationState:
    active = state.active_run
    intent = active.executing_intent if active else None
    if (
        active is None
        or intent is None
        or active.phase is not ContinuationPhase.EXECUTING
        or request.run_id != active.run_id
        or request.tool_call_id != intent.tool_call_id
        or request.binding_digest != intent.intent_digest
    ):
        raise ValueError("recovery request must bind the EXECUTING intent")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_RECOVERY,
            pending_request=request,
            owner_invocation_id=None,
        ),
    )
