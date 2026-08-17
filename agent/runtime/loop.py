"""唯一的 Agent Runtime effect-ordering loop。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from agent.runtime.context import ContextLimitError
from agent.runtime.contracts import (
    Action,
    ActionDisposition,
    ActiveRunStatus,
    ApprovalRequest,
    ApprovalRequired,
    BlockedClaim,
    CancelGoal,
    ClarificationRequest,
    CompletionClaim,
    ConfirmCriterion,
    ContextPack,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ConversationWorkspaceBindingV1,
    ExecutionAuthorityClass,
    ExecutionIntent,
    FactAdmissionBinding,
    FactAdmissionClass,
    FactKind,
    GoalDeltaProposal,
    GoalProgress,
    GoalProposal,
    GoalStatus,
    JSONValue,
    LoadedSnapshot,
    ModelTextBlock,
    ModelToolCall,
    PauseGoal,
    PendingRequest,
    PreferenceAdmissionBinding,
    ProviderDescriptor,
    ProviderDisclosureRequest,
    RecordedRunResult,
    RecoveryRequest,
    ResumeGoal,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
    SideEffectClass,
    SourceAuthorityBinding,
    SourceKind,
    SourceReceiptV1,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
    canonical_json_digest,
)
from agent.runtime.control import ControlBinding, ControlInbox, ControlRequestKind
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from agent.runtime.ports import (
    CheckpointCASConflictError,
    CheckpointStore,
    ContextManager,
    EventSink,
    InvalidProviderResponseError,
    ModelProvider,
    RetryableContextSourceError,
    RetryableProviderError,
    ToolRuntime,
)
from agent.runtime.state import (
    accept_action,
    accept_blocked_claim,
    accept_clarification_request,
    accept_goal_delta_proposal,
    accept_goal_proposal,
    admit_process_receipt_criterion,
    append_policy_result,
    apply_control_request,
    claim_run,
    complete_run,
    end_run,
    fail_run,
    finalize_action,
    mark_executing,
    pause_for_approval,
    pause_for_limit,
    pause_for_provider_disclosure,
    pause_for_recovery,
    pause_for_retryable,
    record_completion_claim,
    record_evidence,
    record_goal_progress,
    record_nonexecuted_tool_result,
    record_tool_result,
    start_tool_batch,
    verify_goal_completion,
)

_WORKSPACE_OBSERVATION_TOOLS = frozenset(
    {"read_file", "read_file_chunk", "list_files", "search_paths", "search_text"}
)
_WORKSPACE_MUTATION_TOOLS = frozenset({"write_file", "edit_file"})


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    max_model_calls: int | None = 16
    max_tool_calls: int | None = 32
    max_input_tokens: int | None = 100_000
    max_output_tokens: int | None = 20_000
    max_invalid_repairs: int = 1
    durable_effect_reserve_bytes: int = 65_536
    max_no_progress_replans: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("max_model_calls", self.max_model_calls),
            ("max_tool_calls", self.max_tool_calls),
            ("max_input_tokens", self.max_input_tokens),
            ("max_output_tokens", self.max_output_tokens),
        ):
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive or None")
        if self.durable_effect_reserve_bytes < 1:
            raise ValueError("durable_effect_reserve_bytes must be positive")
        if self.max_invalid_repairs < 0:
            raise ValueError("max_invalid_repairs must be non-negative")
        if self.max_no_progress_replans < 0:
            raise ValueError("max_no_progress_replans must be non-negative")


@dataclass(slots=True)
class _NoProgressTracker:
    """只让连续重复的同一种停滞消耗 repair allowance。"""

    signature: tuple[str, ...] | None = None
    repairs: int = 0
    observation_id: int | None = None

    def begin(self, signature: tuple[str, ...], *, observation_id: int) -> None:
        self.signature = signature
        self.repairs = 0
        self.observation_id = observation_id

    def same_replan_opportunity(self, observation_id: int) -> bool:
        return self.observation_id == observation_id

    def repair_exhausted(
        self,
        signature: tuple[str, ...],
        *,
        allowance: int,
        observation_id: int,
    ) -> bool:
        if self.same_replan_opportunity(observation_id):
            return False
        self.observation_id = observation_id
        if signature != self.signature:
            self.signature = signature
            self.repairs = 0
        if self.repairs >= allowance:
            return True
        self.repairs += 1
        return False

    def reset(self) -> None:
        self.signature = None
        self.repairs = 0
        self.observation_id = None


class AgentRuntime:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        context_manager: ContextManager,
        tool_runtime: ToolRuntime,
        checkpoint_store: CheckpointStore,
        event_sink: EventSink,
        limits: InvocationLimits,
        invocation_id_factory: Callable[[], str] | None = None,
        control_inbox: ControlInbox | None = None,
        provider_descriptor: ProviderDescriptor | None = None,
        evidence_registry: ClosedEvidenceRegistry | None = None,
        evidence_time_factory: Callable[[], str] | None = None,
        workspace_binding: ConversationWorkspaceBindingV1 | None = None,
    ) -> None:
        self._provider = provider
        self._context_manager = context_manager
        self._tool_runtime = tool_runtime
        self._checkpoint_store = checkpoint_store
        self._event_sink = event_sink
        self._limits = limits
        self._invocation_id_factory = invocation_id_factory or (lambda: str(uuid4()))
        self._control_inbox = control_inbox
        self._provider_descriptor = provider_descriptor
        self._evidence_registry = evidence_registry or ClosedEvidenceRegistry()
        self._evidence_time_factory = evidence_time_factory or (
            lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
        self._workspace_binding = workspace_binding
        self._event_buffer: ContextVar[list[RuntimeEvent] | None] = ContextVar(
            "agent_runtime_event_buffer",
            default=None,
        )
        self._delivering_events: ContextVar[bool] = ContextVar(
            "agent_runtime_delivering_events",
            default=False,
        )

    def run_turn(self, action: Action, snapshot: LoadedSnapshot) -> RunResult:
        if self._delivering_events.get():
            return RunResult(
                status=RunStatus.CONFLICT,
                state=snapshot.state,
                error_code="event_reentry_denied",
            )
        if action.conversation_id != snapshot.state.conversation_id:
            return RunResult(
                status=RunStatus.CONFLICT,
                state=snapshot.state,
                error_code="conversation_mismatch",
            )
        lease = self._checkpoint_store.try_acquire(action.conversation_id)
        if lease is None:
            return RunResult(
                status=RunStatus.CONFLICT,
                state=snapshot.state,
                error_code="conversation_busy",
            )

        events: list[RuntimeEvent] = []
        buffer_token = self._event_buffer.set(events)
        try:
            try:
                result = self._run_locked(action, snapshot)
            finally:
                if self._control_inbox is not None:
                    binding = self._control_inbox.current(action.conversation_id)
                    if binding is not None:
                        self._control_inbox.close(binding)
                lease.release()
            return self._deliver_events(result, events)
        finally:
            self._event_buffer.reset(buffer_token)

    def _run_locked(self, action: Action, snapshot: LoadedSnapshot) -> RunResult:
        warnings: list[str] = []
        current = snapshot
        try:
            binding_result = self._ensure_workspace_binding(current)
            if isinstance(binding_result, RunResult):
                return binding_result
            current = binding_result
            transition = accept_action(current.state, action)
            if transition.disposition is ActionDisposition.CONFLICT:
                return RunResult(
                    status=RunStatus.CONFLICT,
                    state=transition.state,
                    error_code=transition.reason,
                )
            if transition.disposition is ActionDisposition.REPLAYED:
                recorded = transition.recorded_result
                if recorded is None:
                    return RunResult(
                        status=RunStatus.CONFLICT,
                        state=transition.state,
                        error_code="action_in_progress",
                    )
                return RunResult(
                    status=recorded.status,
                    state=transition.state,
                    run_id=recorded.run_id,
                    message=recorded.message,
                    error_code=recorded.error_code,
                    replayed=True,
                )

            if isinstance(action, (PauseGoal, ResumeGoal, CancelGoal, ConfirmCriterion)):
                cancelled = isinstance(action, CancelGoal)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.CANCELLED if cancelled else RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=(
                        RuntimeEventKind.CANCELLED
                        if cancelled
                        else RuntimeEventKind.COMPLETED
                    ),
                    message=(
                        "goal cancelled at a safe boundary"
                        if cancelled
                        else (
                            "goal paused at a safe boundary"
                            if isinstance(action, PauseGoal)
                            else (
                                "goal resumed"
                                if isinstance(action, ResumeGoal)
                                else "criterion confirmation recorded"
                            )
                        )
                    ),
                    outcome_state=transition.state,
                )

            active = transition.state.active_run
            if active is None:
                return self._finish(
                    current,
                    action,
                    status=RunStatus.CANCELLED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.CANCELLED,
                    outcome_state=transition.state,
                )
            if active.status is ActiveRunStatus.AWAITING_APPROVAL:
                return self._finish_pending(
                    current,
                    action,
                    warnings,
                    outcome_state=transition.state,
                )
            if active.status is ActiveRunStatus.AWAITING_RECOVERY:
                return self._finish_pending(
                    current,
                    action,
                    warnings,
                    outcome_state=transition.state,
                )
            if (
                active.phase is ContinuationPhase.EXECUTING
                and active.executing_intent is not None
            ):
                executing = active.executing_intent
                request = RecoveryRequest(
                    request_id=f"recovery-{executing.intent_digest[:16]}",
                    run_id=active.run_id,
                    tool_call_id=executing.tool_call_id,
                    binding_digest=executing.intent_digest,
                    summary="Tool outcome is unknown; classify it before continuing.",
                )
                recovering = pause_for_recovery(transition.state, request)
                return self._finish_pending(
                    current,
                    action,
                    warnings,
                    outcome_state=recovering,
                )

            try:
                current = self._save(current, transition.state)
            except CheckpointCASConflictError as error:
                newest = error.current
                if newest is None:
                    raise
                return RunResult(
                    status=RunStatus.CONFLICT,
                    state=newest.state,
                    error_code="checkpoint_conflict",
                )
            invocation_id = self._invocation_id_factory()
            current = self._save(current, claim_run(current.state, invocation_id))
            self._open_control_binding(current.state)
            return self._drive(action, current, warnings)
        except CheckpointCASConflictError as error:
            newest = error.current
            if newest is None:
                raise
            return RunResult(
                status=RunStatus.CONFLICT,
                state=newest.state,
                error_code="checkpoint_conflict",
            )
        except Exception as error:
            state = current.state
            active = state.active_run
            executing = active.executing_intent if active is not None else None
            if (
                active is not None
                and executing is not None
                and active.phase is ContinuationPhase.EXECUTING
            ):
                request = RecoveryRequest(
                    request_id=f"recovery-{executing.intent_digest[:16]}",
                    run_id=active.run_id,
                    tool_call_id=executing.tool_call_id,
                    binding_digest=executing.intent_digest,
                    summary="Tool outcome is unknown; classify it before continuing.",
                )
                try:
                    recovering = pause_for_recovery(current.state, request)
                    return self._finish_pending(
                        current,
                        action,
                        warnings,
                        outcome_state=recovering,
                    )
                except Exception as recovery_error:
                    warnings.append(
                        "recovery persistence failed: "
                        f"{type(recovery_error).__name__}: {recovery_error}"
                    )
            if state.active_run is not None:
                try:
                    failed = fail_run(
                        state,
                        code="runtime_failure",
                        message=f"{type(error).__name__}: {error}",
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_FATAL,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="runtime_failure",
                        message=f"{type(error).__name__}: {error}",
                        outcome_state=failed,
                    )
                except Exception as persistence_error:
                    warnings.append(
                        "fatal persistence failed: "
                        f"{type(persistence_error).__name__}"
                    )
            return RunResult(
                status=RunStatus.FAILED_FATAL,
                state=current.state,
                run_id=(
                    current.state.active_run.run_id
                    if current.state.active_run is not None
                    else None
                ),
                error_code="runtime_failure",
                message=f"{type(error).__name__}: {error}",
                delivery_warnings=tuple(warnings),
            )

    def _ensure_workspace_binding(
        self,
        snapshot: LoadedSnapshot,
    ) -> LoadedSnapshot | RunResult:
        expected = self._workspace_binding
        if expected is None:
            return snapshot
        current = snapshot.state.workspace_binding
        if current is not None:
            if current != expected:
                return RunResult(
                    status=RunStatus.CONFLICT,
                    state=snapshot.state,
                    error_code="workspace_binding_mismatch",
                )
            return snapshot
        goal = snapshot.state.goal
        if goal is None:
            return RunResult(
                status=RunStatus.CONFLICT,
                state=snapshot.state,
                error_code="legacy_workspace_unbound",
            )
        if goal.workspace_identity_digest != expected.workspace_identity_digest:
            return RunResult(
                status=RunStatus.CONFLICT,
                state=snapshot.state,
                error_code="workspace_binding_mismatch",
            )
        # Schema migration 不改变产品 revision/action sequence；CAS token 仍会变化，
        # 因而 crash 前保持原 v2、成功后单向成为 v3，同一用户 action 可继续受理。
        return self._save(
            snapshot,
            replace(snapshot.state, workspace_binding=expected),
        )

    def _drive(
        self,
        action: Action,
        current: LoadedSnapshot,
        warnings: list[str],
    ) -> RunResult:
        model_calls = 0
        tool_calls = 0
        input_tokens = 0
        output_tokens = 0
        invalid_repairs = 0
        no_progress = _NoProgressTracker()
        no_progress_since_product_action = False
        (
            successful_product_requests,
            successful_workspace_observations,
        ) = self._successful_product_request_inventory(current.state)

        while True:
            active = current.state.active_run
            if active is None:
                raise RuntimeError("active run disappeared before terminal result")

            self._open_control_binding(current.state)
            controlled = self._poll_control(action, current, warnings)
            if controlled is not None:
                return controlled

            if active.phase is ContinuationPhase.TOOL:
                if active.batch_cursor >= len(active.tool_calls):
                    raise RuntimeError("tool cursor is outside the active batch")
                call = active.tool_calls[active.batch_cursor]
                # U3 契约:没有 durable Goal 时,effectful 任务工具必须在 prepare
                # 之前 fail closed;side_effect 只按名字取自 definitions 声明。
                if current.state.goal is None and self._is_effectful_tool(call.name):
                    failed = fail_run(
                        current.state,
                        code="effectful_tool_requires_goal",
                        message="Effectful task tools require a durable Goal first.",
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_FATAL,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="effectful_tool_requires_goal",
                        message="Effectful task tools require a durable Goal first.",
                        outcome_state=failed,
                    )
                if (
                    current.state.goal is not None
                    and current.state.goal.status is GoalStatus.PAUSED
                    and self._is_effectful_tool(call.name)
                ):
                    # F3:暂停的 Goal 在 prepare 之前 fail closed,连 approval
                    # prompt 都不允许出现;effect 必须先显式 ResumeGoal。
                    failed = fail_run(
                        current.state,
                        code="effectful_tool_requires_resumed_goal",
                        message=(
                            "The Goal is paused; resume it explicitly before any "
                            "effectful tool."
                        ),
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_FATAL,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="effectful_tool_requires_resumed_goal",
                        message=(
                            "The Goal is paused; resume it explicitly before any "
                            "effectful tool."
                        ),
                        outcome_state=failed,
                    )
                request_digest = self._product_request_digest(call.name, call.arguments)
                if (
                    request_digest in successful_product_requests
                    and not self._is_lease_governed_tool(call.name)
                ):
                    duplicate = ToolResult(
                        tool_call_id=call.tool_call_id,
                        content=(
                            "Duplicate request suppressed: the same product tool input "
                            "already succeeded in this run."
                        ),
                        is_error=True,
                        executed=False,
                    )
                    fact = self._tool_result_fact(current.state, duplicate)
                    current = self._save(
                        current,
                        record_nonexecuted_tool_result(current.state, fact),
                    )
                    warnings.extend(
                        self._emit(
                            current.state,
                            RuntimeEventKind.TOOL_RESULT,
                            causation_id=call.tool_call_id,
                            payload={"tool_call_id": call.tool_call_id, "is_error": True},
                        )
                    )
                    same_replan_opportunity = no_progress.same_replan_opportunity(
                        model_calls
                    )
                    if no_progress.repair_exhausted(
                        ("duplicate_product_request", request_digest),
                        allowance=self._limits.max_no_progress_replans,
                        observation_id=model_calls,
                    ):
                        return self._finish_no_progress(
                            current,
                            action,
                            warnings,
                            message=(
                                "Provider repeated a product tool request that had already "
                                "succeeded in the current run."
                            ),
                        )
                    no_progress_since_product_action = True
                    if same_replan_opportunity:
                        continue
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="no_progress_replan_required",
                            message=(
                                "That exact product tool request already succeeded in this "
                                "run and was not executed again. Do not repeat it. Choose a "
                                "materially different tool, input, or source; complete with "
                                "evidence; or send blocked_claim if no safe action can "
                                "advance the Goal."
                            ),
                        ),
                    )
                    continue
                prepared = self._tool_runtime.prepare(
                    call,
                    ToolPrepareContext(
                        conversation_id=current.state.conversation_id,
                        run_id=active.run_id,
                        state_revision=current.state.revision,
                        approval_basis_revision=(
                            active.approval_grant.approval_basis_revision
                            if active.approval_grant is not None
                            and active.approval_grant.approval_basis_revision is not None
                            else current.state.revision
                        ),
                        goal_id=(
                            current.state.goal.goal_id
                            if current.state.goal is not None
                            else None
                        ),
                        goal_revision=(
                            current.state.goal.revision
                            if current.state.goal is not None
                            else None
                        ),
                        workspace_identity_digest=(
                            current.state.goal.workspace_identity_digest
                            if current.state.goal is not None
                            else None
                        ),
                        goal_authorization=self._goal_authorization_for(
                            current.state,
                            call,
                        ),
                        fact_admission=self._fact_admission_for(
                            current.state,
                            call,
                        ),
                        preference_admission=self._preference_admission_for(
                            current.state,
                            call,
                        ),
                        source_authority=self._source_authority_for(
                            current.state,
                            call,
                        ),
                        process_leases=current.state.process_leases,
                        proposed_criteria=(
                            current.state.goal.proposed_criteria
                            if current.state.goal is not None
                            else ()
                        ),
                    ),
                    approval=active.approval_grant,
                )
                if isinstance(prepared, ApprovalRequired):
                    paused = pause_for_approval(current.state, prepared.request)
                    return self._finish_pending(
                        current,
                        action,
                        warnings,
                        outcome_state=paused,
                    )
                if isinstance(prepared, ToolResult):
                    no_progress_signature = (
                        "nonexecuted_tool",
                        request_digest,
                        canonical_json_digest(
                            {
                                "content": prepared.content,
                                "is_error": prepared.is_error,
                                "metadata": prepared.metadata,
                            }
                        ),
                    )
                    fact = self._tool_result_fact(current.state, prepared)
                    current = self._save(
                        current,
                        record_nonexecuted_tool_result(current.state, fact),
                    )
                    warnings.extend(
                        self._emit(
                            current.state,
                            RuntimeEventKind.TOOL_RESULT,
                            causation_id=call.tool_call_id,
                            payload={"tool_call_id": call.tool_call_id, "is_error": True},
                        )
                    )
                    if no_progress_since_product_action:
                        same_replan_opportunity = no_progress.same_replan_opportunity(
                            model_calls
                        )
                        if no_progress.repair_exhausted(
                            no_progress_signature,
                            allowance=self._limits.max_no_progress_replans,
                            observation_id=model_calls,
                        ):
                            return self._finish_no_progress(
                                current,
                                action,
                                warnings,
                                message=(
                                    "Provider repeated non-executed tool attempts without "
                                    "a successful product action."
                                ),
                            )
                        if same_replan_opportunity:
                            continue
                        current = self._save(
                            current,
                            append_policy_result(
                                current.state,
                                code="no_progress_replan_required",
                                message=(
                                    "The attempted tool was not executed and no product "
                                    "progress has occurred. Re-read the exact ToolResult, "
                                    "choose a materially different valid action, or send "
                                    "blocked_claim if no safe action can advance the Goal."
                                ),
                            ),
                        )
                    else:
                        no_progress.begin(
                            no_progress_signature,
                            observation_id=model_calls,
                        )
                        no_progress_since_product_action = True
                    continue
                if not isinstance(prepared, ExecutionIntent):
                    raise RuntimeError("Tool Runtime returned an unsupported preparation")
                if (
                    self._limits.max_tool_calls is not None
                    and tool_calls >= self._limits.max_tool_calls
                ):
                    paused = pause_for_limit(current.state)
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.LIMIT_REACHED,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.LIMIT_REACHED,
                        error_code="tool_call_limit",
                        outcome_state=paused,
                    )
                if not self._checkpoint_store.ensure_capacity(
                    current,
                    reserve_bytes=self._limits.durable_effect_reserve_bytes,
                ):
                    ended = end_run(
                        current.state,
                        status=RunStatus.CONVERSATION_LIMIT_REACHED,
                        code="conversation_capacity",
                        message="Conversation state has no safe capacity for another effect.",
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.CONVERSATION_LIMIT_REACHED,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.LIMIT_REACHED,
                        error_code="conversation_capacity",
                        outcome_state=ended,
                    )

                executing = mark_executing(
                    current.state,
                    tool_call_id=prepared.tool_call_id,
                    intent_digest=prepared.intent_digest,
                    idempotency_key=prepared.idempotency_key,
                    side_effect=prepared.side_effect,
                    egress=prepared.egress,
                    operation=prepared.operation or prepared.tool_name,
                    request_identity=(
                        prepared.request_identity or prepared.idempotency_key
                    ),
                    execution_authority=prepared.execution_authority,
                    process_lease_id=(
                        prepared.process_lease.lease_id
                        if prepared.process_lease is not None
                        else None
                    ),
                )
                current = self._save(current, executing)
                try:
                    tool_result = self._tool_runtime.invoke(prepared)
                except Exception:
                    request = RecoveryRequest(
                        request_id=f"recovery-{prepared.intent_digest[:16]}",
                        run_id=active.run_id,
                        tool_call_id=prepared.tool_call_id,
                        binding_digest=prepared.intent_digest,
                        summary="Tool outcome is unknown; classify it before continuing.",
                    )
                    recovering = pause_for_recovery(current.state, request)
                    return self._finish_pending(
                        current,
                        action,
                        warnings,
                        outcome_state=recovering,
                    )
                tool_calls += 1
                fact = self._tool_result_fact(current.state, tool_result)
                try:
                    post_result_state = record_tool_result(
                        current.state,
                        fact,
                        intent_digest=prepared.intent_digest,
                    )
                    # J1：成功 process receipt → 同一 transition 内铸造 TOOL_RECEIPT criterion。
                    _meta = (
                        tool_result.metadata
                        if isinstance(tool_result.metadata, dict)
                        else {}
                    )
                    if (
                        _meta.get("process_receipt_kind") == "process_v1"
                        and _meta.get("outcome") == "exited"
                        and _meta.get("exit_code") == 0
                        and _meta.get("receipt_digest")
                        and _meta.get("command_fingerprint")
                    ):
                        post_result_state = admit_process_receipt_criterion(
                            post_result_state,
                            tool_call_id=prepared.tool_call_id,
                            receipt_digest=_meta["receipt_digest"],
                            command_fingerprint=_meta["command_fingerprint"],
                            action_seq=action.action_seq,
                        )
                    current = self._save(current, post_result_state)
                except Exception:
                    request = RecoveryRequest(
                        request_id=f"recovery-{prepared.intent_digest[:16]}",
                        run_id=active.run_id,
                        tool_call_id=prepared.tool_call_id,
                        binding_digest=prepared.intent_digest,
                        summary="Tool outcome is unknown; classify it before continuing.",
                    )
                    recovering = pause_for_recovery(current.state, request)
                    return self._finish_pending(
                        current,
                        action,
                        warnings,
                        outcome_state=recovering,
                    )
                warnings.extend(
                    self._emit(
                        current.state,
                        RuntimeEventKind.TOOL_RESULT,
                        causation_id=prepared.tool_call_id,
                        payload={
                            "tool_call_id": prepared.tool_call_id,
                            "is_error": tool_result.is_error,
                        },
                    )
                )
                if tool_result.executed and not tool_result.is_error:
                    if call.name in _WORKSPACE_MUTATION_TOOLS:
                        # Workspace 发生真实 mutation 后，先前的本地观察已经过期；
                        # 允许同参数 read/search 重新执行并取得新 snapshot。外部 Web、
                        # history 与 effectful 请求仍保留 exact dedup。
                        successful_product_requests.difference_update(
                            successful_workspace_observations
                        )
                        successful_workspace_observations.clear()
                    successful_product_requests.add(request_digest)
                    if call.name in _WORKSPACE_OBSERVATION_TOOLS:
                        successful_workspace_observations.add(request_digest)
                no_progress.reset()
                no_progress_since_product_action = False
                continue

            if active.phase is not ContinuationPhase.MODEL:
                raise RuntimeError("EXECUTING continuation must enter recovery before resume")
            if (
                self._limits.max_model_calls is not None
                and model_calls >= self._limits.max_model_calls
            ):
                paused = pause_for_limit(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="model_call_limit",
                    outcome_state=paused,
                )

            try:
                context = self._context_manager.build(
                    current.state,
                    action,
                    self._tool_runtime.definitions(),
                )
            except RetryableContextSourceError as error:
                paused = pause_for_retryable(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_RETRYABLE,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="context_source_unavailable",
                    message=str(error),
                    outcome_state=paused,
                )
            except ContextLimitError as error:
                failed = fail_run(
                    current.state,
                    code=error.code,
                    message=str(error),
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.CONVERSATION_LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code=error.code,
                    outcome_state=failed,
                )
            disclosure = self._required_disclosure(context)
            if disclosure is not None and (
                current.state.provider_disclosure_receipt is None
                or current.state.provider_disclosure_receipt.request_digest
                != disclosure.request_digest
            ):
                paused = pause_for_provider_disclosure(current.state, disclosure)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.AWAITING_DISCLOSURE,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.DISCLOSURE_REQUESTED,
                    message="remote provider disclosure acknowledgement required",
                    outcome_state=paused,
                )
            if (
                self._limits.max_input_tokens is not None
                and input_tokens + context.budget.estimated_input_tokens
                > self._limits.max_input_tokens
            ):
                paused = pause_for_limit(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="input_token_limit",
                    outcome_state=paused,
                )
            if not self._checkpoint_store.ensure_capacity(
                current,
                reserve_bytes=self._limits.durable_effect_reserve_bytes,
            ):
                ended = end_run(
                    current.state,
                    status=RunStatus.CONVERSATION_LIMIT_REACHED,
                    code="conversation_capacity",
                    message="Conversation state has no safe capacity for another effect.",
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.CONVERSATION_LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="conversation_capacity",
                    outcome_state=ended,
                )

            model_calls += 1
            input_tokens += context.budget.estimated_input_tokens
            try:
                response = self._provider.generate(context)
            except InvalidProviderResponseError as error:
                # 归一化失败意味着本次响应的任何 tool/control 都未被接纳，
                # 所以可以在相同 trusted context 上做有界重试；绝不宽松解析。
                if invalid_repairs < self._limits.max_invalid_repairs:
                    invalid_repairs += 1
                    reason = str(error)
                    if reason not in {
                        "malformed_control",
                        "malformed_response",
                        "malformed_tool_call",
                        "response_too_large",
                        "unsupported_response_block",
                    }:
                        reason = "invalid_provider_response"
                    if reason == "malformed_control":
                        allowed_control_text = ", ".join(
                            sorted(self._advertised_control_kinds(context))
                        ) or "none"
                        if current.state.goal is not None:
                            repair_message = (
                                "Previous response was rejected (malformed_control). A "
                                "trusted_goal already exists, so goal_proposal is "
                                "unavailable. Allowed control kinds now: "
                                + allowed_control_text
                                + ". If trusted_goal already matches the user request, do "
                                "not send another goal_proposal or goal_delta_proposal: use "
                                "a currently advertised product tool. Use goal_delta_proposal "
                                "only for a real conflict with the user's requested Goal. "
                                "Otherwise use one of the other allowed controls only when "
                                "its terminal or clarification condition is true, include "
                                "every required field, and use valid JSON arguments."
                            )
                        else:
                            repair_message = (
                                "Previous response was rejected (malformed_control). Return "
                                "exactly one currently advertised reserved control call, "
                                "include every required field for its selected kind, and "
                                "use valid JSON arguments."
                            )
                    else:
                        repair_message = (
                            f"Previous response was rejected ({reason}). Return exactly "
                            "one response matching the supplied text, tool, or reserved "
                            "control schema, using valid JSON arguments."
                        )
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_provider_response",
                            message=repair_message,
                        ),
                    )
                    continue
                failed = fail_run(
                    current.state,
                    code="invalid_provider_response",
                    message="Provider repeated an invalid response after repair allowance.",
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_FATAL,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="invalid_provider_response",
                    outcome_state=failed,
                )
            except RetryableProviderError as error:
                paused = pause_for_retryable(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_RETRYABLE,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="provider_retryable",
                    message=str(error),
                    outcome_state=paused,
                )
            except Exception as error:
                failed = fail_run(
                    current.state,
                    code="provider_failure",
                    message=f"{type(error).__name__}: {error}",
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_FATAL,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="provider_failure",
                    message=str(error),
                    outcome_state=failed,
                )

            output_tokens += response.bounded_output_tokens
            if (
                self._limits.max_output_tokens is not None
                and output_tokens > self._limits.max_output_tokens
            ):
                paused = pause_for_limit(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="output_token_limit",
                    outcome_state=paused,
                )

            if response.stop_reason == "max_tokens":
                failed = fail_run(
                    current.state,
                    code="provider_output_truncated",
                    message="Provider stopped because its output limit was reached.",
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_FATAL,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="provider_output_truncated",
                    outcome_state=failed,
                )

            control = response.control
            if control is not None:
                control_kind = self._control_kind(control)
                advertised_control_kinds = self._advertised_control_kinds(context)
                if control_kind not in advertised_control_kinds:
                    # goal_progress 只有在当前 run 已产生真实产品结果时才会被
                    # advertised。模型继续发送它不是新的进度，而是 stalled
                    # narration：给一次可执行的 replan 反馈，持续重复再按
                    # no-progress fail closed，且绝不让隐藏 control 改写 Goal。
                    if isinstance(control, GoalProgress):
                        if no_progress.repair_exhausted(
                            ("unavailable_goal_progress",),
                            allowance=self._limits.max_no_progress_replans,
                            observation_id=model_calls,
                        ):
                            return self._finish_no_progress(
                                current,
                                action,
                                warnings,
                                message=(
                                    "Provider repeated GoalProgress without a newly "
                                    "successful product tool result."
                                ),
                            )
                        no_progress_since_product_action = True
                        current = self._save(
                            current,
                            append_policy_result(
                                current.state,
                                code="no_progress_replan_required",
                                message=(
                                    "goal_progress is not currently available because no "
                                    "new successful product tool result supports it. Do not "
                                    "narrate progress. Use an advertised product tool, "
                                    "complete with closed evidence, or send blocked_claim "
                                    "when no safe action can advance the Goal."
                                ),
                            ),
                        )
                        continue
                    if invalid_repairs >= self._limits.max_invalid_repairs:
                        failed = fail_run(
                            current.state,
                            code="invalid_model_control",
                            message=(
                                "Provider repeatedly used a control kind that was not "
                                "available in the current model context."
                            ),
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.FAILED_FATAL,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.FAILED,
                            error_code="invalid_model_control",
                            outcome_state=failed,
                        )
                    invalid_repairs += 1
                    allowed = ", ".join(sorted(advertised_control_kinds)) or "none"
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_model_control",
                            message=(
                                f"Control kind {control_kind} is not currently available "
                                f"and was not accepted. Allowed control kinds now: {allowed}. "
                                "Use an advertised product tool when concrete work remains."
                            ),
                        ),
                    )
                    continue
            if (
                control is not None
                and not isinstance(control, ClarificationRequest)
                and current.state.goal is not None
                and current.state.goal.status is GoalStatus.PAUSED
            ):
                # F3:暂停的 Goal 不接受任何 goal 控制(进度/修订/完成/阻塞),
                # 任务推进必须先显式 ResumeGoal;交互级澄清不受影响。
                if invalid_repairs >= self._limits.max_invalid_repairs:
                    failed = fail_run(
                        current.state,
                        code="invalid_model_control",
                        message=(
                            "Provider repeated goal controls while the Goal is paused."
                        ),
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_FATAL,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="invalid_model_control",
                        outcome_state=failed,
                    )
                invalid_repairs += 1
                current = self._save(
                    current,
                    append_policy_result(
                        current.state,
                        code="paused_goal_requires_resume",
                        message=(
                            "The Goal is paused. Answer the user directly; task "
                            "progression requires an explicit resume first."
                        ),
                    ),
                )
                continue
            if isinstance(control, ClarificationRequest):
                # 澄清边界:一次模型调用、零工具效果;先 CAS 持久化 CLARIFYING
                # receipt,再以边界问题本身作为该 run 唯一 assistant 回答收尾。
                run_id = active.run_id
                current = self._save(
                    current,
                    accept_clarification_request(current.state, control),
                )
                completed = complete_run(current.state, message=control.question)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=run_id,
                    message=control.question,
                    outcome_state=completed,
                )
            if isinstance(control, GoalProposal):
                # Goal 先经 CAS 落盘,再让同一个循环重建上下文,保证任何任务
                # 工具效果都发生在 durable Goal 之后(goal_cas < context_rebuild)。
                try:
                    transition_state = accept_goal_proposal(
                        current.state, control, context.goal_bootstrap
                    )
                except ValueError as error:
                    # 提案通过 normalize 但违反 reducer 校验（bootstrap binding /
                    # 预铸 admitted criteria / source fact 权威性等）：这是模型可
                    # 修复的控制参数错误，与 malformed_control 同类——不是
                    # provider/infra 故障。给既有 invalid_repairs 预算内的一次
                    # 修复机会；接受条件零放宽（被拒提案不创建 Goal）。
                    if invalid_repairs >= self._limits.max_invalid_repairs:
                        failed = fail_run(
                            current.state,
                            code="invalid_goal_proposal",
                            message=(
                                "Provider repeated an invalid GoalProposal after "
                                f"repair allowance: {error}"
                            ),
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.FAILED_FATAL,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.FAILED,
                            error_code="invalid_goal_proposal",
                            outcome_state=failed,
                        )
                    invalid_repairs += 1
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_goal_proposal",
                            message=(
                                "The goal_proposal was not accepted: "
                                f"{error}. Copy trusted_goal_bootstrap fields "
                                "exactly (created_from_fact_ids, "
                                "workspace_identity_digest, authority_snapshot), "
                                "leave admitted_criteria empty, and resend a "
                                "corrected goal_proposal."
                            ),
                        ),
                    )
                    continue
                current = self._save(current, transition_state)
                no_progress.reset()
                # Goal 建立的是控制边界，不是任务进展；下一步必须产生真实产品
                # 动作，不能先用 GoalProgress 把计划叙述成已完成的工作。
                no_progress_since_product_action = True
                continue
            if isinstance(control, GoalProgress):
                # 进度是活跃 Goal 的中间态:reducer 校验并落盘 EXECUTING 与
                # correlation receipt 后,同一循环重建上下文继续,不依赖用户
                # 再提交合成 "continue" 消息。
                if no_progress_since_product_action:
                    if no_progress.repair_exhausted(
                        ("goal_progress_without_product_action",),
                        allowance=self._limits.max_no_progress_replans,
                        observation_id=model_calls,
                    ):
                        return self._finish_no_progress(
                            current,
                            action,
                            warnings,
                            message=(
                                "Provider repeated GoalProgress without a product tool "
                                "action or new verification evidence."
                            ),
                        )
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="no_progress_replan_required",
                            message=(
                                "No product action or verification evidence was added "
                                "since the previous GoalProgress. Do not narrate more "
                                "progress. Call the concrete tools needed for trusted_goal."
                                "next_step, or send blocked_claim if no safe action can "
                                "advance it."
                            ),
                        ),
                    )
                    continue
                current = self._save(
                    current,
                    record_goal_progress(current.state, control),
                )
                no_progress_since_product_action = True
                continue
            if isinstance(control, GoalDeltaProposal):
                if self._goal_delta_is_noop(current.state, control):
                    if no_progress.repair_exhausted(
                        ("noop_goal_delta",),
                        allowance=self._limits.max_no_progress_replans,
                        observation_id=model_calls,
                    ):
                        return self._finish_no_progress(
                            current,
                            action,
                            warnings,
                            message=(
                                "Provider repeated GoalDeltaProposal without changing the "
                                "current Goal."
                            ),
                        )
                    no_progress_since_product_action = True
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="no_progress_replan_required",
                            message=(
                                "That goal_delta_proposal restates trusted_goal and was not "
                                "accepted. Do not narrate a no-op correction. Use an "
                                "advertised product tool now, or send blocked_claim only if "
                                "no safe action can advance the unchanged Goal."
                            ),
                        ),
                    )
                    continue
                current = self._save(
                    current,
                    accept_goal_delta_proposal(current.state, control),
                )
                no_progress.reset()
                no_progress_since_product_action = False
                if (
                    current.state.goal is not None
                    and current.state.goal.status is GoalStatus.NEEDS_AUTHORITY
                ):
                    run_id = active.run_id
                    completed = complete_run(
                        current.state,
                        message="Goal correction requires user authority before another effect.",
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.COMPLETED,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.COMPLETED,
                        run_id=run_id,
                        message="Goal correction requires user authority before another effect.",
                        outcome_state=completed,
                    )
                continue
            if isinstance(control, BlockedClaim):
                run_id = active.run_id
                blocked = accept_blocked_claim(current.state, control)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=run_id,
                    message=control.blocker,
                    outcome_state=blocked,
                )
            if isinstance(control, CompletionClaim):
                try:
                    records = self._evidence_registry.derive(
                        current.state,
                        control,
                        observed_at=self._evidence_time_factory(),
                    )
                    existing_ids = {
                        record.evidence_id for record in current.state.evidence_records
                    }
                    fresh = tuple(
                        record for record in records if record.evidence_id not in existing_ids
                    )
                    if fresh:
                        current = self._save(
                            current,
                            record_evidence(current.state, fresh),
                        )
                        no_progress.reset()
                    current = self._save(
                        current,
                        record_completion_claim(current.state, control),
                    )
                    current = self._save(
                        current,
                        verify_goal_completion(current.state),
                    )
                except EvidenceVerificationError as error:
                    if no_progress.repair_exhausted(
                        (
                            "unverified_completion",
                            str(error),
                            canonical_json_digest(
                                list(control.criterion_evidence_refs)
                            ),
                        ),
                        allowance=self._limits.max_no_progress_replans,
                        observation_id=model_calls,
                    ):
                        return self._finish_no_progress(
                            current,
                            action,
                            warnings,
                            message=(
                                "Provider repeated completion claims without adding "
                                "the required verification evidence."
                            ),
                        )
                    no_progress_since_product_action = True
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="completion_not_verified",
                            message=(
                                f"{error} "
                                + self._evidence_repair_instruction(str(error))
                            ),
                        ),
                    )
                    continue
                except ValueError as error:
                    # 已成功解码但不满足当前 trusted state 的 control（例如复用
                    # correlation_id）属于模型可修复输入，不应把用户任务升级为
                    # runtime_failure。修复次数仍受同一个 hard limit 约束。
                    if invalid_repairs >= self._limits.max_invalid_repairs:
                        failed = fail_run(
                            current.state,
                            code="invalid_model_control",
                            message="Provider repeated an invalid control after repair allowance.",
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.FAILED_FATAL,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.FAILED,
                            error_code="invalid_model_control",
                            outcome_state=failed,
                        )
                    invalid_repairs += 1
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_model_control",
                            message=(
                                "Control rejected by current trusted state: "
                                f"{error}. Use trusted_goal values and a new correlation_id."
                            ),
                        ),
                    )
                    continue
                run_id = active.run_id
                completed = complete_run(
                    current.state,
                    message="Goal completion verified by closed evidence oracles.",
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=run_id,
                    message="Goal completion verified by closed evidence oracles.",
                    outcome_state=completed,
                )

            texts = [block.text for block in response.blocks if isinstance(block, ModelTextBlock)]
            model_tools = [
                block for block in response.blocks if isinstance(block, ModelToolCall)
            ]
            if not texts and not model_tools:
                if invalid_repairs < self._limits.max_invalid_repairs:
                    invalid_repairs += 1
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_model_output",
                            message="Return final text or one or more supported tool calls.",
                        ),
                    )
                    continue
                failed = fail_run(
                    current.state,
                    code="invalid_model_output",
                    message="Provider returned invalid output after repair allowance.",
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_FATAL,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="invalid_model_output",
                    outcome_state=failed,
                )

            if model_tools:
                advertised_names = {tool.name for tool in context.tools}
                registered_names = {
                    tool.name for tool in self._tool_runtime.definitions()
                }
                unavailable_names = sorted(
                    {
                        block.name
                        for block in model_tools
                        if block.name in registered_names
                        and block.name not in advertised_names
                        and not self._is_effectful_tool(block.name)
                    }
                )
                if unavailable_names:
                    if no_progress.repair_exhausted(
                        ("unavailable_tool", *unavailable_names),
                        allowance=self._limits.max_no_progress_replans,
                        observation_id=model_calls,
                    ):
                        return self._finish_no_progress(
                            current,
                            action,
                            warnings,
                            message=(
                                "Provider repeatedly called a registered tool that was not "
                                "available in the current model context."
                            ),
                        )
                    no_progress_since_product_action = True
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="no_progress_replan_required",
                            message=(
                                "The requested tool is registered but not currently "
                                "available: "
                                + ", ".join(unavailable_names)
                                + ". It was not executed. Use only tools advertised in "
                                "the current context, complete with existing evidence, or "
                                "send blocked_claim if no safe action can advance the Goal."
                            ),
                        ),
                    )
                    continue
                calls = tuple(
                    ToolCall(block.tool_call_id, block.name, block.arguments)
                    for block in model_tools
                )
                current = self._save(
                    current,
                    start_tool_batch(
                        current.state,
                        calls,
                        preamble="\n".join(texts) or None,
                    ),
                )
                continue

            final_text = "\n".join(texts)
            goal = current.state.goal
            # PAUSED 与终态一样允许 prose 收尾:暂停下的普通问答只结束本次 run,
            # 不触碰仍然暂停的 Goal;推进必须先显式 ResumeGoal。
            if goal is not None and goal.status not in {
                GoalStatus.PAUSED,
                GoalStatus.BLOCKED,
                GoalStatus.VERIFIED_DONE,
                GoalStatus.CANCELLED,
            }:
                if invalid_repairs >= self._limits.max_invalid_repairs:
                    failed = fail_run(
                        current.state,
                        code="invalid_model_control",
                        message=(
                            "Provider repeated final prose while the durable Goal "
                            "still required a control decision."
                        ),
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_FATAL,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="invalid_model_control",
                        outcome_state=failed,
                    )
                invalid_repairs += 1
                current = self._save(
                    current,
                    append_policy_result(
                        current.state,
                        code="active_goal_requires_control",
                        message=(
                            "A nonterminal Goal cannot end with final prose. Continue with "
                            "goal progress, a tool call, a blocked claim, or a verifiable "
                            "completion control."
                        ),
                    ),
                )
                continue
            run_id = active.run_id
            completed = complete_run(current.state, message=final_text)
            return self._finish(
                current,
                action,
                status=RunStatus.COMPLETED,
                warnings=warnings,
                event_kind=RuntimeEventKind.COMPLETED,
                run_id=run_id,
                message=final_text,
                outcome_state=completed,
            )

    def _open_control_binding(self, state: ConversationState) -> None:
        if self._control_inbox is None or state.goal is None or state.active_run is None:
            return
        invocation_id = state.active_run.owner_invocation_id
        if invocation_id is None:
            return
        binding = ControlBinding(
            conversation_id=state.conversation_id,
            goal_id=state.goal.goal_id,
            goal_revision=state.goal.revision,
            invocation_id=invocation_id,
        )
        current = self._control_inbox.current(state.conversation_id)
        if current is None:
            self._control_inbox.open(binding)
        elif current != binding:
            self._control_inbox.close(current)
            self._control_inbox.open(binding)

    def _poll_control(
        self,
        action: Action,
        current: LoadedSnapshot,
        warnings: list[str],
    ) -> RunResult | None:
        if self._control_inbox is None:
            return None
        state = current.state
        goal = state.goal
        active = state.active_run
        if goal is None or active is None or active.owner_invocation_id is None:
            return None
        binding = ControlBinding(
            conversation_id=state.conversation_id,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            invocation_id=active.owner_invocation_id,
        )
        request = self._control_inbox.poll(binding)
        if request is None:
            return None
        controlled = apply_control_request(state, request)
        current = self._save(current, controlled)
        cancelled = request.kind is ControlRequestKind.CANCEL
        message = {
            ControlRequestKind.PAUSE: "goal paused at a safe boundary",
            ControlRequestKind.CORRECT: "goal correction recorded at a safe boundary",
            ControlRequestKind.CANCEL: "goal cancelled at a safe boundary",
        }[request.kind]
        return self._finish(
            current,
            action,
            status=RunStatus.CANCELLED if cancelled else RunStatus.COMPLETED,
            warnings=warnings,
            event_kind=(
                RuntimeEventKind.CANCELLED if cancelled else RuntimeEventKind.COMPLETED
            ),
            message=message,
            outcome_state=current.state,
        )

    def _finish_pending(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        *,
        outcome_state: ConversationState | None = None,
    ) -> RunResult:
        state = outcome_state if outcome_state is not None else current.state
        active = state.active_run
        if active is None or active.pending_request is None:
            raise RuntimeError("pending state has no request")
        if active.status is ActiveRunStatus.AWAITING_APPROVAL:
            status = RunStatus.AWAITING_APPROVAL
            event_kind = RuntimeEventKind.APPROVAL_REQUESTED
        elif active.status is ActiveRunStatus.AWAITING_RECOVERY:
            status = RunStatus.AWAITING_RECOVERY
            event_kind = RuntimeEventKind.RECOVERY_REQUESTED
        else:
            raise RuntimeError("unsupported pending state")
        return self._finish(
            current,
            action,
            status=status,
            warnings=warnings,
            event_kind=event_kind,
            run_id=active.run_id,
            request=active.pending_request,
            outcome_state=state,
        )

    def _finish_no_progress(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        *,
        message: str,
    ) -> RunResult:
        failed = fail_run(current.state, code="no_progress", message=message)
        return self._finish(
            current,
            action,
            status=RunStatus.FAILED_FATAL,
            warnings=warnings,
            event_kind=RuntimeEventKind.FAILED,
            error_code="no_progress",
            message=message,
            outcome_state=failed,
        )

    @staticmethod
    def _advertised_control_kinds(context: ContextPack) -> set[str]:
        schema = context.control_schema
        if not isinstance(schema, dict):
            return set()
        input_schema = schema.get("input_schema")
        properties = (
            input_schema.get("properties") if isinstance(input_schema, dict) else None
        )
        kind = properties.get("kind") if isinstance(properties, dict) else None
        values = kind.get("enum") if isinstance(kind, dict) else None
        if not isinstance(values, list):
            return set()
        return {value for value in values if isinstance(value, str)}

    @staticmethod
    def _control_kind(control: object) -> str:
        if isinstance(control, ClarificationRequest):
            return "clarification_request"
        if isinstance(control, GoalProposal):
            return "goal_proposal"
        if isinstance(control, GoalProgress):
            return "goal_progress"
        if isinstance(control, GoalDeltaProposal):
            return "goal_delta_proposal"
        if isinstance(control, CompletionClaim):
            return "completion_claim"
        if isinstance(control, BlockedClaim):
            return "blocked_claim"
        raise TypeError("unsupported model control")

    @staticmethod
    def _goal_delta_is_noop(
        state: ConversationState,
        proposal: GoalDeltaProposal,
    ) -> bool:
        goal = state.goal
        updates = proposal.delta.updates
        if goal is None or {"admitted_criteria", "authority_snapshot"} & updates.keys():
            return False
        for name, proposed in updates.items():
            current: object = getattr(goal, name)
            if name == "proposed_criteria":
                current = [
                    {
                        "criterion_id": item.criterion_id,
                        "description": item.description,
                        "oracle_kind": (
                            item.oracle_kind.value
                            if item.oracle_kind is not None
                            else None
                        ),
                        "artifact_path": item.artifact_path or "",
                    }
                    for item in goal.proposed_criteria
                ]
            if canonical_json_digest(current) != canonical_json_digest(proposed):
                return False
        return True

    @staticmethod
    def _evidence_repair_instruction(reason: str) -> str:
        if reason == "no exact read-back fact proves the research artifact":
            return (
                "Do not repeat completion. Call read_file for the artifact, pass that "
                "exact read-back text to build_citation_manifest with the existing source "
                "refs, rewrite the citation sidecar with its canonical JSON, then read "
                "both files back before a new completion claim."
            )
        if reason == "citation sidecar target requires admitted research provenance":
            return (
                "Do not repeat completion. Rebuild the citation manifest from current-Goal "
                "source refs, write its canonical JSON to the exact .citations.json target "
                "with approval, and read both artifact and sidecar back before retrying."
            )
        if "required source kind must contain extracted web content" in reason:
            return (
                "Do not repeat completion. Fetch an unattempted source_ref from the current "
                "Web Search, then rebuild and rewrite the citation sidecar using the "
                "extracted receipt before retrying."
            )
        if reason == "source receipt is not bound to the current Goal":
            return (
                "Do not repeat completion. Some cited retrieval happened before this Goal. "
                "Run materially different history, workspace, and Web source queries now "
                "under trusted_goal, rebuild the report and citation manifest only from "
                "those current-Goal source refs, rewrite both targets, and read both back."
            )
        if reason == "artifact contains an invented URL":
            return (
                "Do not repeat completion or fetch unrelated sources. Use edit_file on the "
                "artifact to remove every literal URL that is not exactly a cited current-Goal "
                "web_extracted_content origin_locator. Then read_file the changed artifact, "
                "rebuild and rewrite the citation sidecar from that exact text and existing "
                "source refs, read both targets back, and retry completion."
            )
        if reason in {
            "required source class is not cited",
            "required source kind is not cited",
        }:
            return (
                "Do not repeat completion. If the needed current-Goal source class already "
                "exists in FIRST_AGENT_RUNTIME_SOURCE_REFS, do not retrieve it again: remap "
                "each valid marker to a distinct source of the required source class. Only "
                "retrieve a new source when that "
                "class is genuinely absent; then retrieve a new history or workspace source "
                "and use its new source ref. Rebuild the report and citation manifest, rewrite "
                "both targets, and read both back before retrying."
            )
        return (
            "Do not repeat completion. Call the concrete tools needed to create the "
            "missing evidence, or send blocked_claim if no safe action can advance the Goal."
        )

    @staticmethod
    def _product_request_digest(
        tool_name: str,
        arguments: dict[str, JSONValue],
    ) -> str:
        return canonical_json_digest(
            {
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )

    @classmethod
    def _successful_product_request_inventory(
        cls,
        state: ConversationState,
    ) -> tuple[set[str], set[str]]:
        active = state.active_run
        if active is None:
            return set(), set()
        run_prefix = f"run:{active.run_id}:"
        request_by_call_id: dict[str, tuple[str, str]] = {}
        successful: set[str] = set()
        workspace_observations: set[str] = set()
        for fact in state.facts:
            if not fact.fact_id.startswith(run_prefix):
                continue
            if fact.kind is FactKind.TOOL_CALLS:
                raw_calls = fact.content.get("calls")
                if not isinstance(raw_calls, list):
                    continue
                for raw_call in raw_calls:
                    if not isinstance(raw_call, dict):
                        continue
                    call_id = raw_call.get("tool_call_id")
                    name = raw_call.get("name")
                    arguments = raw_call.get("arguments")
                    if (
                        isinstance(call_id, str)
                        and isinstance(name, str)
                        and isinstance(arguments, dict)
                    ):
                        request_by_call_id[call_id] = (
                            cls._product_request_digest(name, arguments),
                            name,
                        )
                continue
            if (
                fact.kind is FactKind.TOOL_RESULT
                and fact.content.get("executed") is True
                and fact.content.get("is_error") is False
            ):
                call_id = fact.content.get("tool_call_id")
                if isinstance(call_id, str) and call_id in request_by_call_id:
                    request_digest, tool_name = request_by_call_id[call_id]
                    if tool_name in _WORKSPACE_MUTATION_TOOLS:
                        successful.difference_update(workspace_observations)
                        workspace_observations.clear()
                    successful.add(request_digest)
                    if tool_name in _WORKSPACE_OBSERVATION_TOOLS:
                        workspace_observations.add(request_digest)
        return successful, workspace_observations

    def _finish(
        self,
        current: LoadedSnapshot,
        action: Action,
        *,
        status: RunStatus,
        warnings: list[str],
        event_kind: RuntimeEventKind,
        run_id: str | None = None,
        message: str | None = None,
        request: PendingRequest | None = None,
        error_code: str | None = None,
        outcome_state: ConversationState | None = None,
    ) -> RunResult:
        state = outcome_state if outcome_state is not None else current.state
        if run_id is None and state.active_run is not None:
            run_id = state.active_run.run_id
        if run_id is None and state.last_safe_result is not None:
            run_id = state.last_safe_result.run_id
        recorded = RecordedRunResult(
            status=status,
            run_id=run_id,
            message=message,
            request_id=request.request_id if request is not None else None,
            error_code=error_code,
        )
        finalized = finalize_action(
            state,
            action_seq=action.action_seq,
            result=recorded,
        )
        current = self._save(current, finalized)
        payload = {"status": status.value}
        causation_id = f"action:{action.action_seq}"
        if request is not None:
            payload["request_id"] = request.request_id
            payload["tool_call_id"] = request.tool_call_id
            if isinstance(request, ApprovalRequest):
                payload.update(
                    {
                        "tool_name": request.tool_name or "unknown",
                        "preview": request.preview,
                        "risk": request.risk or "unknown",
                        "side_effect": request.side_effect or "unknown",
                    }
                )
            if isinstance(request, RecoveryRequest):
                payload["summary"] = request.summary
                active = state.active_run
                if active is not None and active.executing_intent is not None:
                    payload["egress"] = active.executing_intent.egress.value
            causation_id = request.request_id
        if event_kind is RuntimeEventKind.DISCLOSURE_REQUESTED:
            disclosure = state.provider_disclosure_request
            if disclosure is not None:
                payload.update(
                    {
                        "request_digest": disclosure.request_digest,
                        "destination": disclosure.canonical_destination,
                        "model": disclosure.model,
                        "data_classes": list(disclosure.data_classes),
                    }
                )
        warnings.extend(
            self._emit(
                current.state,
                event_kind,
                causation_id=causation_id,
                payload=payload,
                run_id=run_id,
                stable_event_id=(
                    f"request:{request.request_id}" if request is not None else None
                ),
            )
        )
        return RunResult(
            status=status,
            state=current.state,
            run_id=run_id,
            message=message,
            request=request,
            error_code=error_code,
            delivery_warnings=tuple(warnings),
        )

    def _save(self, snapshot: LoadedSnapshot, state) -> LoadedSnapshot:
        return self._checkpoint_store.compare_and_swap(snapshot, state)

    def _is_effectful_tool(self, tool_name: str) -> bool:
        # 非 READ_ONLY 一律视为 effectful,未来新增的副作用类别默认 fail closed。
        return any(
            definition.name == tool_name
            and definition.side_effect is not SideEffectClass.READ_ONLY
            for definition in self._tool_runtime.definitions()
        )

    def _is_lease_governed_tool(self, tool_name: str) -> bool:
        # 015：LOCAL_SAME_UID_PROCESS 工具的 exact reuse 由 durable lease 治理（F2/R9，
        # 8 uses），不适用 read-only/source 的 product-request dedup——重复 exact command
        # 是合法的 lease reuse，不是 no-progress 重复。
        return any(
            definition.name == tool_name
            and definition.execution_authority
            is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
            for definition in self._tool_runtime.definitions()
        )

    def _required_disclosure(
        self,
        context,
    ) -> ProviderDisclosureRequest | None:
        descriptor = self._provider_descriptor
        if descriptor is None or not descriptor.remote:
            return None
        return ProviderDisclosureRequest.create(
            disclosure_id=f"provider:{descriptor.identity_digest[:16]}",
            provider_descriptor_digest=descriptor.identity_digest,
            canonical_destination=descriptor.canonical_destination,
            model=descriptor.model,
            data_classes=context.data_classes,
        )

    @staticmethod
    def _goal_authorization_for(state: ConversationState, call: ToolCall):
        goal = state.goal
        target = call.arguments.get("path")
        if goal is None or not isinstance(target, str):
            return None
        return next(
            (
                binding
                for binding in state.goal_authorizations
                if binding.authorizes(
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    workspace_identity_digest=goal.workspace_identity_digest,
                    operation=call.name,
                    normalized_target=target,
                )
            ),
            None,
        )

    @staticmethod
    def _fact_admission_for(
        state: ConversationState,
        call: ToolCall,
    ) -> FactAdmissionBinding | None:
        goal = state.goal
        content = call.arguments.get("content")
        if goal is None or call.name != "memory_remember" or not isinstance(content, str):
            return None
        source = next(
            (
                fact
                for fact in reversed(state.facts)
                if fact.kind is FactKind.USER_MESSAGE
                and fact.content.get("text") == content
            ),
            None,
        )
        if source is None:
            return None
        fact_digest = canonical_json_digest(
            {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
        )
        return FactAdmissionBinding.create(
            binding_id=f"fact-admission:{fact_digest[:16]}",
            fact_id=source.fact_id,
            fact_kind=source.kind,
            fact_digest=fact_digest,
            workspace_identity_digest=goal.workspace_identity_digest,
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            admission_class=FactAdmissionClass.WORKSPACE_FACT,
        )

    @staticmethod
    def _source_authority_for(
        state: ConversationState,
        call: ToolCall,
    ) -> SourceAuthorityBinding | None:
        if call.name != "web_fetch":
            return None
        source_ref = call.arguments.get("source_ref")
        prefix = "source-ref:v1:"
        if not isinstance(source_ref, str) or not source_ref.startswith(prefix):
            return None
        receipt_digest = source_ref[len(prefix) :]
        if (
            len(receipt_digest) != 64
            or any(character not in "0123456789abcdef" for character in receipt_digest)
        ):
            return None
        for fact in reversed(state.facts):
            if (
                fact.kind is not FactKind.TOOL_RESULT
                or fact.content.get("is_error") is not False
                or fact.content.get("executed") is not True
            ):
                continue
            metadata = fact.content.get("metadata")
            raw_receipts = (
                metadata.get("source_receipts") if isinstance(metadata, dict) else None
            )
            source_refs = metadata.get("source_refs") if isinstance(metadata, dict) else None
            if not isinstance(raw_receipts, list) or not isinstance(source_refs, list):
                continue
            if not any(
                isinstance(item, dict)
                and item.get("source_ref") == source_ref
                and item.get("receipt_digest") == receipt_digest
                for item in source_refs
            ):
                continue
            for raw_receipt in raw_receipts:
                try:
                    receipt = SourceReceiptV1.from_json(raw_receipt)
                except ValueError:
                    continue
                if (
                    receipt.receipt_digest != receipt_digest
                    or receipt.source_kind is not SourceKind.WEB_SEARCH_SNIPPET
                    or receipt.conversation_id != state.conversation_id
                    or receipt.request_identity is None
                ):
                    continue
                canonical_url = receipt.origin_locator
                if receipt.request_identity.startswith("tavily-search:v1:"):
                    resolved_url = AgentRuntime._url_from_tavily_search_result(
                        fact,
                        receipt,
                    )
                    if resolved_url is None:
                        continue
                    canonical_url = resolved_url
                return SourceAuthorityBinding.create(
                    source_fact_id=fact.fact_id,
                    receipt_digest=receipt.receipt_digest,
                    conversation_id=state.conversation_id,
                    request_identity=receipt.request_identity,
                    canonical_url=canonical_url,
                )
        return None

    @staticmethod
    def _url_from_tavily_search_result(
        fact: ConversationFact,
        receipt: SourceReceiptV1,
    ) -> str | None:
        """从 receipt digest 绑定的 durable result 恢复完整公开 URL。

        receipt locator 故意移除了 query；完整 URL 只作为 source result 数据保存，
        并同时受 content digest 与 origin request digest 约束。任何 mutation 都
        使 source_ref 失效，而不是让模型提供一个替代 URL。
        """
        raw_text = fact.content.get("text")
        if not isinstance(raw_text, str) or receipt.origin_request_digest is None:
            return None
        try:
            document = json.loads(raw_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(document, dict):
            return None
        results = document.get("results")
        if not isinstance(results, list) or len(results) > 16:
            return None
        for item in results:
            if not isinstance(item, dict):
                continue
            if canonical_json_digest(item) != receipt.content_digest:
                continue
            url = item.get("url")
            locator = item.get("locator")
            if (
                not isinstance(url, str)
                or not isinstance(locator, str)
                or locator != receipt.origin_locator
                or hashlib.sha256(url.encode("utf-8")).hexdigest()
                != receipt.origin_request_digest
            ):
                continue
            return url
        return None

    @staticmethod
    def _preference_admission_for(
        state: ConversationState,
        call: ToolCall,
    ) -> PreferenceAdmissionBinding | None:
        content = call.arguments.get("content")
        if (
            call.name not in {"owner_preference_confirm", "owner_preference_correct"}
            or not isinstance(content, str)
        ):
            return None
        source = next(
            (
                fact
                for fact in reversed(state.facts)
                if fact.kind is FactKind.USER_MESSAGE
                and fact.content.get("text") == content
            ),
            None,
        )
        if source is None:
            return None
        fact_digest = canonical_json_digest(
            {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
        )
        content_digest = canonical_json_digest(content)
        return PreferenceAdmissionBinding.create(
            binding_id=f"preference-admission:{fact_digest[:16]}",
            fact_id=source.fact_id,
            fact_digest=fact_digest,
            content_digest=content_digest,
        )

    def _emit(
        self,
        state,
        kind: RuntimeEventKind,
        *,
        causation_id: str,
        payload: dict,
        run_id: str | None = None,
        stable_event_id: str | None = None,
    ) -> list[str]:
        event = RuntimeEvent(
            event_id=stable_event_id or f"event:{state.revision}:{kind.value}",
            kind=kind,
            conversation_id=state.conversation_id,
            run_id=(
                run_id
                if run_id is not None
                else state.active_run.run_id
                if state.active_run is not None
                else None
            ),
            revision=state.revision,
            causation_id=causation_id,
            payload=payload,
        )
        event_buffer = self._event_buffer.get()
        if event_buffer is None:
            raise RuntimeError("runtime event emitted outside an invocation")
        event_buffer.append(event)
        return []

    def _deliver_events(
        self,
        result: RunResult,
        events: list[RuntimeEvent],
    ) -> RunResult:
        warnings = list(result.delivery_warnings)
        delivery_token = self._delivering_events.set(True)
        try:
            for event in events:
                try:
                    self._event_sink.emit(event)
                except Exception as error:
                    warnings.append(f"event delivery failed: {type(error).__name__}")
        finally:
            self._delivering_events.reset(delivery_token)
        return replace(result, delivery_warnings=tuple(warnings))

    @staticmethod
    def _tool_result_fact(state, result: ToolResult) -> ConversationFact:
        active = state.active_run
        if active is None:
            raise RuntimeError("tool result requires an active run")
        return ConversationFact(
            fact_id=f"run:{active.run_id}:tool-result:{result.tool_call_id}:{state.revision + 1}",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": result.tool_call_id,
                "text": result.content,
                "is_error": result.is_error,
                "executed": result.executed,
                "metadata": result.metadata,
            },
        )
