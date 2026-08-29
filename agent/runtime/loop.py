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
from agent.runtime.context_control import goal_correction_pending, web_fetch_source_refs
from agent.runtime.context_source import (
    citable_citation_sources,
    citable_source_refs,
    project_tool_result_sources,
    public_web_requirement_pending,
)
from agent.runtime.contracts import (
    AbandonUnknownModelOutcome,
    Action,
    ActionDisposition,
    ActiveRunStatus,
    ApprovalRequest,
    ApprovalRequired,
    BackgroundExecutionAuthorityV1,
    BeginAnswer,
    BlockedClaim,
    BrowserTakeoverRequestV1,
    CancelBrowserTakeover,
    CancelGoal,
    CitationManifestV1,
    ClarificationRequest,
    CompleteBrowserTakeover,
    CompletionClaim,
    ConfirmCriterion,
    ContextPack,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ConversationWorkspaceBindingV1,
    DirectResponse,
    EvidenceOracleKind,
    ExecutionAuthorityClass,
    ExecutionIntent,
    FactAdmissionBinding,
    FactAdmissionClass,
    FactKind,
    GoalDeltaProposal,
    GoalDraftProposal,
    GoalProgress,
    GoalStatus,
    JSONValue,
    LoadedSnapshot,
    ModelTextBlock,
    ModelToolCall,
    PauseGoal,
    PendingRequest,
    PersistedModelResponseV1,
    PreferenceAdmissionBinding,
    ProviderCallIntentV1,
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
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
    canonical_action_digest,
    canonical_json_digest,
    context_pack_digest,
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
    accept_begin_answer,
    accept_blocked_claim,
    accept_clarification_request,
    accept_goal_delta_proposal,
    accept_goal_draft_proposal,
    acknowledge_noop_goal_delta,
    admit_process_receipt_criterion,
    admit_web_source_criterion,
    append_policy_result,
    apply_control_request,
    authoritative_process_entrypoints,
    begin_browser_takeover,
    begin_provider_call,
    claim_run,
    complete_run,
    consume_provider_response,
    end_run,
    fail_run,
    finalize_action,
    goal_correction_adds_runtime_obligation,
    mark_executing,
    mark_model_outcome_unknown,
    normalize_process_entrypoint,
    pause_for_approval,
    pause_for_limit,
    pause_for_provider_disclosure,
    pause_for_recovery,
    pause_for_retryable,
    reclaim_background_run,
    record_completion_claim,
    record_evidence,
    record_goal_progress,
    record_nonexecuted_tool_result,
    record_provider_response,
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
    # 这是“第 N 次连续同指纹停滞即熔断”的阈值。默认 2 保留一次纠偏机会；
    # Everyday 显式设为 16，在第 16 次命中后暂停而不是再多发送一次。
    max_no_progress_replans: int = 2

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
    """累计相同停滞指纹；真实进展或策略变化会重置。"""

    signature: tuple[str, ...] | None = None
    repairs: int = 0
    observation_id: int | None = None

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
        self.repairs += 1
        return allowance == 0 or self.repairs >= allowance

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
        browser_takeover_complete: Callable[[BrowserTakeoverRequestV1], int]
        | None = None,
        background_execution_authority: BackgroundExecutionAuthorityV1 | None = None,
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
        self._browser_takeover_complete = browser_takeover_complete
        self._background_execution_authority = background_execution_authority
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
            if self._background_execution_authority is not None:
                occurrence_binding = current.state.background_occurrence_binding
                if (
                    occurrence_binding is None
                    or occurrence_binding.binding_digest
                    != self._background_execution_authority.occurrence_binding.binding_digest
                ):
                    return RunResult(
                        status=RunStatus.CONFLICT,
                        state=current.state,
                        error_code="background_occurrence_binding_mismatch",
                    )
            resumed = self._resume_background_replay(action, current, warnings)
            if resumed is not None:
                return resumed
            if (
                current.state.browser_takeover_pending is not None
                and not isinstance(
                    action, (CompleteBrowserTakeover, CancelBrowserTakeover)
                )
            ):
                # pending takeover 期间 provider/tool/observe/recording 为零：
                # 只接受 typed complete/cancel controls。
                return RunResult(
                    status=RunStatus.CONFLICT,
                    state=current.state,
                    error_code="browser_takeover_pending",
                )
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

            if isinstance(action, CompleteBrowserTakeover):
                pending = current.state.browser_takeover_pending
                if pending is None or self._browser_takeover_complete is None:
                    return RunResult(
                        status=RunStatus.CONFLICT,
                        state=current.state,
                        error_code="browser_takeover_completion_unavailable",
                    )
                try:
                    completed_revision = self._browser_takeover_complete(pending)
                except (OSError, ValueError):
                    return RunResult(
                        status=RunStatus.CONFLICT,
                        state=current.state,
                        error_code="browser_takeover_completion_failed",
                    )
                if completed_revision != pending.profile_revision + 1:
                    return RunResult(
                        status=RunStatus.CONFLICT,
                        state=current.state,
                        error_code="browser_takeover_revision_invalid",
                    )

            if (
                isinstance(action, (CompleteBrowserTakeover, CancelBrowserTakeover))
                and transition.state.active_run is None
            ):
                # 兼容只含 durable pending 的恢复投影。真实 product flow 会
                # 保留原 active run，并在下方重新 claim 后继续唯一 _drive。
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    message=(
                        "browser takeover completed; profile revision advanced, "
                        "fresh browser_observe required"
                        if isinstance(action, CompleteBrowserTakeover)
                        else "browser takeover cancelled"
                    ),
                    outcome_state=transition.state,
                )

            if isinstance(action, (PauseGoal, ResumeGoal, CancelGoal, ConfirmCriterion)):
                cancelled = isinstance(action, CancelGoal)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.CANCELLED if cancelled else RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=(
                        RuntimeEventKind.CANCELLED if cancelled else RuntimeEventKind.COMPLETED
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

            if isinstance(action, AbandonUnknownModelOutcome):
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_FATAL,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code="model_outcome_abandoned",
                    message="Unknown provider outcome was abandoned for this occurrence.",
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
            if active.phase is ContinuationPhase.EXECUTING and active.executing_intent is not None:
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
                    warnings.append(f"fatal persistence failed: {type(persistence_error).__name__}")
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

    def _resume_background_replay(
        self,
        action: Action,
        current: LoadedSnapshot,
        warnings: list[str],
    ) -> RunResult | None:
        """恢复同一 unfinished occurrence action，不创建 scheduler/model 第二循环。"""

        state = current.state
        active = state.active_run
        if (
            state.background_occurrence_binding is None
            or not isinstance(action, SubmitMessage)
            or active is None
            or active.run_id != action.run_id
        ):
            return None
        replay = next(
            (
                item
                for item in state.replay_records
                if item.action_seq == action.action_seq
            ),
            None,
        )
        if (
            replay is None
            or replay.result is not None
            or replay.action_digest != canonical_action_digest(action)
        ):
            return None
        if active.status is ActiveRunStatus.MODEL_OUTCOME_UNKNOWN:
            return self._finish(
                current,
                action,
                status=RunStatus.FAILED_RETRYABLE,
                warnings=warnings,
                event_kind=RuntimeEventKind.FAILED,
                error_code="model_outcome_unknown",
                message="Provider outcome is unknown; abandon this occurrence explicitly.",
                outcome_state=state,
            )
        if (
            active.status is ActiveRunStatus.MODEL_EXECUTING
            and active.persisted_model_response is None
        ):
            unknown = mark_model_outcome_unknown(state)
            return self._finish(
                current,
                action,
                status=RunStatus.FAILED_RETRYABLE,
                warnings=warnings,
                event_kind=RuntimeEventKind.FAILED,
                error_code="model_outcome_unknown",
                message="Provider outcome is unknown; abandon this occurrence explicitly.",
                outcome_state=unknown,
            )
        if (
            active.status is ActiveRunStatus.RUNNABLE
            and active.phase is ContinuationPhase.EXECUTING
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
            recovering = pause_for_recovery(state, request)
            return self._finish_pending(
                current,
                action,
                warnings,
                outcome_state=recovering,
            )
        safely_reclaimable = (
            active.status is ActiveRunStatus.MODEL_EXECUTING
            and active.persisted_model_response is not None
        ) or (
            active.status is ActiveRunStatus.RUNNABLE
            and active.phase is not ContinuationPhase.EXECUTING
        )
        if not safely_reclaimable:
            return None
        invocation_id = self._invocation_id_factory()
        current = self._save(
            current,
            reclaim_background_run(state, invocation_id),
        )
        self._open_control_binding(current.state)
        return self._drive(action, current, warnings)

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
                            "The Goal is paused; resume it explicitly before any effectful tool."
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
                            "The Goal is paused; resume it explicitly before any effectful tool."
                        ),
                        outcome_state=failed,
                    )
                request_digest = self._product_request_digest(call.name, call.arguments)
                if (
                    request_digest in successful_product_requests
                    and not self._is_lease_governed_tool(call.name)
                ):
                    duplicate_guidance = self._duplicate_product_request_guidance(
                        current.state,
                        call,
                    )
                    duplicate = ToolResult(
                        tool_call_id=call.tool_call_id,
                        content=duplicate_guidance,
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
                    same_replan_opportunity = no_progress.same_replan_opportunity(model_calls)
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
                            message=duplicate_guidance,
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
                            current.state.goal.goal_id if current.state.goal is not None else None
                        ),
                        goal_revision=(
                            current.state.goal.revision if current.state.goal is not None else None
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
                        sandbox_leases=current.state.sandbox_leases,
                        browser_leases=current.state.browser_leases,
                        browser_takeover_pending=(
                            current.state.browser_takeover_pending
                        ),
                        proposed_criteria=(
                            current.state.goal.proposed_criteria
                            if current.state.goal is not None
                            else ()
                        ),
                        admitted_criterion_ids=(
                            frozenset(
                                criterion.criterion_id
                                for criterion in current.state.goal.admitted_criteria
                            )
                            if current.state.goal is not None
                            else frozenset()
                        ),
                        citable_source_refs=self._citable_source_refs_for(
                            current.state,
                        ),
                        citable_citation_sources=(
                            self._citable_citation_sources_for(current.state)
                        ),
                        web_fetch_source_refs=web_fetch_source_refs(current.state),
                        citation_manifest_allowed=bool(
                            current.state.goal is not None
                            and any(
                                target.endswith(".citations.json")
                                for target in current.state.goal.targets
                            )
                        ),
                        citation_sidecar_paths=(
                            tuple(
                                target
                                for target in current.state.goal.targets
                                if target.endswith(".citations.json")
                            )
                            if current.state.goal is not None
                            else ()
                        ),
                        citation_artifact_paths=(
                            tuple(
                                target
                                for target in current.state.goal.targets
                                if not target.endswith(".citations.json")
                            )
                            if current.state.goal is not None
                            and any(
                                target.endswith(".citations.json")
                                for target in current.state.goal.targets
                            )
                            else ()
                        ),
                        citation_manifest_content_digests=(
                            self._citation_manifest_content_digests_for(current.state)
                        ),
                        public_web_requirement_pending=self._public_web_requirement_pending(
                            current.state,
                        ),
                        goal_correction_pending=goal_correction_pending(current.state),
                        background_execution_authority=(
                            self._background_execution_authority
                        ),
                        background_tool_calls_used=active.tool_calls_used,
                        background_sandbox_commands_used=(
                            active.sandbox_commands_used
                        ),
                        background_browser_actions_used=active.browser_actions_used,
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
                        same_replan_opportunity = no_progress.same_replan_opportunity(model_calls)
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

                if prepared.browser_takeover_request is not None:
                    # headed browser 是用户可见副作用。先把 exact takeover
                    # request durable-save，再允许 ToolRuntime 调 adapter 切换窗口。
                    pending_takeover = begin_browser_takeover(
                        current.state,
                        prepared.browser_takeover_request,
                    )
                    current = self._save(current, pending_takeover)

                executing = mark_executing(
                    current.state,
                    tool_call_id=prepared.tool_call_id,
                    intent_digest=prepared.intent_digest,
                    idempotency_key=prepared.idempotency_key,
                    side_effect=prepared.side_effect,
                    egress=prepared.egress,
                    operation=prepared.operation or prepared.tool_name,
                    request_identity=(prepared.request_identity or prepared.idempotency_key),
                    execution_authority=prepared.execution_authority,
                    process_lease_id=(
                        prepared.process_lease.lease_id
                        if prepared.process_lease is not None
                        else None
                    ),
                    sandbox_lease_id=(
                        prepared.sandbox_lease.lease_id
                        if prepared.sandbox_lease is not None
                        else None
                    ),
                    browser_lease_id=(
                        prepared.browser_lease.lease_id
                        if prepared.browser_lease is not None
                        else None
                    ),
                    background_action_authority=(
                        prepared.background_action_authority
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
                    _meta = tool_result.metadata if isinstance(tool_result.metadata, dict) else {}
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
                    if _meta.get("source_receipts"):
                        post_result_state = admit_web_source_criterion(
                            post_result_state,
                            tool_call_id=prepared.tool_call_id,
                            action_seq=action.action_seq,
                        )
                    if (
                        tool_result.browser_takeover_request is not None
                        and post_result_state.browser_takeover_pending
                        != tool_result.browser_takeover_request
                    ):
                        raise ValueError("browser takeover result changed durable binding")
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
                if tool_result.browser_takeover_request is not None:
                    # pending 已经在上一 CAS 中持久化且 invocation ownership
                    # 已释放。必须立即返回，不能再调用 provider 或下一个 tool。
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.COMPLETED,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.COMPLETED,
                        run_id=active.run_id,
                        message="browser takeover waiting for user",
                        outcome_state=current.state,
                    )
                if tool_result.executed and not tool_result.is_error:
                    verified = self._finish_if_durable_evidence_is_complete(
                        current,
                        action,
                        warnings,
                        tool_name=call.name,
                    )
                    if verified is not None:
                        return verified
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
            background_binding = current.state.background_occurrence_binding
            recovering_persisted_response = (
                active.status is ActiveRunStatus.MODEL_EXECUTING
                and active.persisted_model_response is not None
            )
            if (
                background_binding is not None
                and not recovering_persisted_response
                and active.model_calls_used >= background_binding.model_call_limit
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
            if (
                not recovering_persisted_response
                and
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
                not recovering_persisted_response
                and background_binding is not None
                and active.input_tokens_used + context.budget.estimated_input_tokens
                > background_binding.max_input_tokens
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
            if (
                not recovering_persisted_response
                and
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

            if recovering_persisted_response:
                intent = active.provider_call_intent
                persisted = active.persisted_model_response
                if (
                    intent is None
                    or persisted is None
                    or background_binding is None
                    or intent.action_seq != action.action_seq
                    or intent.context_digest != context_pack_digest(context)
                    or intent.occurrence_binding_digest
                    != background_binding.binding_digest
                ):
                    unknown = mark_model_outcome_unknown(
                        replace(
                            current.state,
                            active_run=replace(
                                active,
                                persisted_model_response=None,
                            ),
                        )
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_RETRYABLE,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="model_response_binding_mismatch",
                        outcome_state=unknown,
                    )
                response = persisted.response
                current = LoadedSnapshot(
                    state=consume_provider_response(current.state),
                    token=current.token,
                )
            else:
                model_calls += 1
                input_tokens += context.budget.estimated_input_tokens
                if background_binding is not None:
                    intent = ProviderCallIntentV1.create(
                        action_seq=action.action_seq,
                        provider_call_index=active.model_calls_used + 1,
                        context_digest=context_pack_digest(context),
                        disclosure_digest=(
                            disclosure.request_digest if disclosure is not None else None
                        ),
                        occurrence_binding_digest=background_binding.binding_digest,
                    )
                    current = self._save(
                        current,
                        begin_provider_call(
                            current.state,
                            intent,
                            input_tokens=context.budget.estimated_input_tokens,
                        ),
                    )
            try:
                if not recovering_persisted_response:
                    response = self._provider.generate(context)
            except InvalidProviderResponseError as error:
                if background_binding is not None:
                    return self._finish_background_model_unknown(
                        current,
                        action,
                        warnings,
                    )
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
                        allowed_control_text = (
                            ", ".join(sorted(self._advertised_control_kinds(context))) or "none"
                        )
                        # 有界 shape detail(键名/期望形状)来自归一化层;真实模型
                        # 只拿到 "malformed_control" 时无从自纠(016 J11 实测)。
                        shape_detail = getattr(error, "detail", None)
                        detail_suffix = (
                            f" Rejected payload shape: {shape_detail}."
                            if shape_detail
                            else ""
                        )
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
                                + detail_suffix
                            )
                        else:
                            repair_message = (
                                "Previous response was rejected (malformed_control). Return "
                                "exactly one currently advertised reserved control call, "
                                "include every required field for its selected kind, and "
                                "use valid JSON arguments."
                                + detail_suffix
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
                if background_binding is not None:
                    return self._finish_background_model_unknown(
                        current,
                        action,
                        warnings,
                    )
                paused = pause_for_retryable(current.state)
                provider_code = getattr(error, "code", "provider_retryable")
                if provider_code == "provider_http_retryable":
                    provider_code = (
                        "provider_rate_limit"
                        if getattr(error, "status_code", None) == 429
                        else "provider_unavailable"
                    )
                if provider_code not in {
                    "provider_retryable",
                    "provider_timeout",
                    "provider_transport",
                    "provider_rate_limit",
                    "provider_unavailable",
                }:
                    provider_code = "provider_retryable"
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_RETRYABLE,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code=provider_code,
                    message=str(error),
                    outcome_state=paused,
                )
            except Exception as error:
                if background_binding is not None:
                    return self._finish_background_model_unknown(
                        current,
                        action,
                        warnings,
                    )
                provider_code = getattr(error, "code", "provider_failure")
                if provider_code not in {
                    "provider_auth_error",
                    "provider_configuration_error",
                    "provider_http_error",
                    "provider_failure",
                }:
                    provider_code = "provider_failure"
                failed = fail_run(
                    current.state,
                    code=provider_code,
                    message=str(error),
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.FAILED_FATAL,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.FAILED,
                    error_code=provider_code,
                    message=str(error),
                    outcome_state=failed,
                )

            if background_binding is not None and not recovering_persisted_response:
                active_after_send = current.state.active_run
                if active_after_send is None or active_after_send.provider_call_intent is None:
                    raise RuntimeError("background provider intent disappeared")
                persisted = PersistedModelResponseV1.create(
                    request_digest=active_after_send.provider_call_intent.request_digest,
                    response=response,
                )
                current = self._save(
                    current,
                    record_provider_response(current.state, persisted),
                )
                current = LoadedSnapshot(
                    state=consume_provider_response(current.state),
                    token=current.token,
                )

            output_tokens += response.bounded_output_tokens
            current_active = current.state.active_run
            if (
                background_binding is not None
                and current_active is not None
                and current_active.output_tokens_used
                > background_binding.max_output_tokens
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
                    # 016 真实 E3(第 53/93 轮 J8)观测:双文件已写、证据就绪的收尾
                    # 阶段,模型反复提交当前语境不可用的 control(具体 kind 未记
                    # 录于 bounded FAIL_DETAIL)并在额度内未收敛。只列 allowed kinds
                    # 不教收尾动作;repair 需补上 evidence 已存在时的正确收尾——
                    # 复制当前投影 refs 的 completion_claim。该指引对任何不可用
                    # kind 都安全成立,不预设实际 wire kind。
                    if (
                        current.state.goal is None
                        and "goal_proposal" in advertised_control_kinds
                        and "direct_response" not in advertised_control_kinds
                    ):
                        repair_message = (
                            f"Control kind {control_kind} is not currently available and "
                            f"was not accepted. Allowed control kinds now: {allowed}. "
                            "This trusted user action has an explicit non-prose outcome: "
                            "answer text cannot write, edit, research into an artifact, "
                            "run, test, or validate the requested result. Submit "
                            "goal_proposal now using the advertised semantic draft fields; "
                            "use clarification_request only if a real intent or authority "
                            "boundary prevents that proposal."
                        )
                    else:
                        repair_message = (
                            f"Control kind {control_kind} is not currently available "
                            f"and was not accepted. Allowed control kinds now: {allowed}. "
                            "Use an advertised product tool when concrete work remains; "
                            "when the required evidence already exists, finish instead "
                            "with completion_claim, copying criterion_evidence_refs "
                            "exactly, element for element and in order, from the "
                            "CURRENT trusted_goal block's "
                            "expected_completion_evidence_refs."
                        )
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_model_control",
                            message=repair_message,
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
                        message=("Provider repeated goal controls while the Goal is paused."),
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
                begin_answer_available = "begin_answer" in self._advertised_control_kinds(
                    context
                )
                discovery_tools = tuple(
                    sorted(
                        tool.name
                        for tool in context.tools
                        if tool.name
                        in {
                            "list_files",
                            "read_file",
                            "read_file_chunk",
                            "search_paths",
                            "search_text",
                        }
                    )
                )
                if (
                    current.state.goal is None
                    and control.boundary_code != "direction_boundary"
                    and (begin_answer_available or discovery_tools)
                    and not self._run_has_product_tool_attempt(current.state)
                    and not self._run_has_policy_result(
                        current.state,
                        "clarification_requires_discovery",
                    )
                ):
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="clarification_requires_discovery",
                            message=(
                                "Do not ask the user for locally discoverable workspace "
                                "facts. If this is a question, submit begin_answer now; "
                                "Runtime will then expose only read-only grounding "
                                "capabilities. If it is an explicit verifiable task, "
                                "submit goal_proposal first, derived only from the user's "
                                "request; unknown target files can be discovered after "
                                "the Goal exists or represented by the deferred filesystem "
                                "criterion. Ask one clarification only if a user-intent "
                                "boundary still remains."
                                + (
                                    " Available read-only tools after begin_answer: "
                                    f"{', '.join(discovery_tools)}."
                                    if discovery_tools
                                    else ""
                                )
                            ),
                        ),
                    )
                    no_progress_since_product_action = True
                    continue
                # 澄清边界:一次模型调用、零工具效果;先 CAS 持久化 CLARIFYING
                # receipt,再以边界问题本身作为该 run 唯一 assistant 回答收尾。
                run_id = active.run_id
                try:
                    clarified = accept_clarification_request(current.state, control)
                except ValueError as error:
                    # 第 87 轮定诊的姊妹缺口:correlation 复用等可修复输入同样
                    # 不得升级为 runtime_failure;有界修复与 CompletionClaim 同型。
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
                current = self._save(current, clarified)
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
            if isinstance(control, BeginAnswer):
                try:
                    answering = accept_begin_answer(current.state, control)
                except ValueError as error:
                    if invalid_repairs >= self._limits.max_invalid_repairs:
                        failed = fail_run(
                            current.state,
                            code="invalid_model_control",
                            message="Provider repeated an invalid begin_answer control.",
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
                                "begin_answer was not accepted: "
                                f"{error}. Use one of the currently advertised controls."
                            ),
                        ),
                    )
                    continue
                current = self._save(current, answering)
                invalid_repairs = 0
                no_progress.reset()
                no_progress_since_product_action = False
                continue
            if isinstance(control, DirectResponse):
                run_id = active.run_id
                completed = complete_run(current.state, message=control.text)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=run_id,
                    message=control.text,
                    outcome_state=completed,
                )
            if isinstance(control, GoalDraftProposal):
                # Goal 先经 CAS 落盘,再让同一个循环重建上下文,保证任何任务
                # 工具效果都发生在 durable Goal 之后(goal_cas < context_rebuild)。
                try:
                    transition_state = accept_goal_draft_proposal(
                        current.state,
                        control,
                        context.goal_bootstrap,
                        admitted_at=self._evidence_time_factory(),
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
                                f"{error}. "
                                + (
                                    "Resend only the advertised semantic draft fields; "
                                    "use non-empty targets, scope, and criteria; next_step "
                                    "is an optional planning hint; "
                                    "and give every filesystem_digest criterion its exact "
                                    "workspace-relative artifact_path. Runtime owns Goal "
                                    "identity, authority, status, timestamps, and admission."
                                )
                            ),
                        ),
                    )
                    continue
                current = self._save(current, transition_state)
                # 受理的 Goal draft 是确定性控制进展,同样重置 invalid 修复额度
                # (与 delta 受理一致),避免跨成功累计误判 fatal。
                invalid_repairs = 0
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
                try:
                    progressed_state = record_goal_progress(current.state, control)
                except ValueError as error:
                    # 已解码且当前 schema 可见的 progress 仍可能复用既有
                    # correlation_id；这是模型可修复输入，不能升级成 runtime_failure。
                    if invalid_repairs >= self._limits.max_invalid_repairs:
                        failed = fail_run(
                            current.state,
                            code="invalid_model_control",
                            message=(
                                "Provider repeated an invalid GoalProgress after "
                                f"repair allowance: {error}"
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
                            code="invalid_model_control",
                            message=(
                                f"GoalProgress was not accepted: {error}. Use trusted_goal "
                                "identity, a new correlation_id, and report progress only "
                                "after a newly successful product tool result."
                            ),
                        ),
                    )
                    continue
                current = self._save(current, progressed_state)
                # repair allowance 只约束连续无效响应；已受理的 control 是新的
                # trusted observation，不能让早先错误跨真实进展累计到 fatal。
                invalid_repairs = 0
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
                    try:
                        current = self._save(
                            current,
                            acknowledge_noop_goal_delta(current.state, control),
                        )
                    except ValueError as error:
                        # 016 真实 E3 第 36 轮 J11:首个 delta 已消费 correction 时,
                        # noop 路径的"correction 已消费"ValueError 会作为未捕获异常
                        # 变成 runtime_failure fatal(并伴随 fatal 持久化冲突)。它与
                        # 其余 delta 错误同类,必须是额度内可修复的 policy_result。
                        if invalid_repairs >= self._limits.max_invalid_repairs:
                            failed = fail_run(
                                current.state,
                                code="invalid_goal_delta",
                                message=(
                                    "Provider repeated an invalid GoalDeltaProposal "
                                    f"after repair allowance: {error}"
                                ),
                            )
                            return self._finish(
                                current,
                                action,
                                status=RunStatus.FAILED_FATAL,
                                warnings=warnings,
                                event_kind=RuntimeEventKind.FAILED,
                                error_code="invalid_goal_delta",
                                outcome_state=failed,
                            )
                        invalid_repairs += 1
                        current = self._save(
                            current,
                            append_policy_result(
                                current.state,
                                code="invalid_goal_delta",
                                message=(
                                    f"The goal_delta_proposal was not accepted: {error}. "
                                    "Do not resend the delta; use an advertised product "
                                    "tool on the corrected Goal now."
                                ),
                            ),
                        )
                        continue
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
                try:
                    corrected_state = accept_goal_delta_proposal(current.state, control)
                except ValueError as error:
                    if invalid_repairs >= self._limits.max_invalid_repairs:
                        failed = fail_run(
                            current.state,
                            code="invalid_goal_delta",
                            message=(
                                "Provider repeated an invalid GoalDeltaProposal after "
                                f"repair allowance: {error}"
                            ),
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.FAILED_FATAL,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.FAILED,
                            error_code="invalid_goal_delta",
                            outcome_state=failed,
                        )
                    invalid_repairs += 1
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="invalid_goal_delta",
                            message=(
                                f"The goal_delta_proposal was not accepted: {error}. "
                                "Resend one atomic delta from the current trusted_goal. If "
                                "targets change, update every corresponding filesystem "
                                "criterion and path-dependent Goal field in that same delta."
                            ),
                        ),
                    )
                    continue
                current = self._save(current, corrected_state)
                # 真实受理的 control 是确定性进展:invalid 修复额度随之重置,
                # 否则跨成功的累计会把健康对话误判成 fatal(016 J11 实测)。
                invalid_repairs = 0
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
                available_tools = tuple(sorted(tool.name for tool in context.tools))
                pending_obligation_tools = (
                    self._evidence_registry.pending_obligation_tools(
                        current.state,
                        available_tools=available_tools,
                    )
                )
                if pending_obligation_tools or (
                    available_tools
                    and not self._run_has_product_tool_attempt(current.state)
                ):
                    required_tools = pending_obligation_tools or available_tools
                    if no_progress.repair_exhausted(
                        ("unverified_blocked_claim", *required_tools),
                        allowance=self._limits.max_no_progress_replans,
                        observation_id=model_calls,
                    ):
                        return self._finish_no_progress(
                            current,
                            action,
                            warnings,
                            message=(
                                "Provider repeated a blocked claim without attempting an "
                                "available product tool."
                            ),
                        )
                    no_progress_since_product_action = True
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="blocked_claim_not_verified",
                            message=(
                                "The blocked_claim was not accepted because no relevant "
                                "product tool attempt supports a still-pending Runtime-owned "
                                "Goal obligation. Required next tool: "
                                f"{', '.join(required_tools)}. Unrelated workspace reads do "
                                "not establish this blocker. Call the tool that can advance "
                                "trusted_goal now; claim blocked only after a concrete safe "
                                "attempt produces a durable blocker."
                                if pending_obligation_tools
                                else "The blocked_claim was not accepted because no product "
                                "tool attempt supports it. Available product tools: "
                                f"{', '.join(available_tools)}. Call the tool that can "
                                "advance trusted_goal now; claim blocked only after a "
                                "concrete safe attempt produces a durable blocker."
                            ),
                        ),
                    )
                    continue
                goal_frame = current.state.goal
                mandatory_refs = tuple(
                    ClosedEvidenceRegistry.evidence_id(
                        goal_frame.goal_id,
                        goal_frame.revision,
                        criterion.criterion_id,
                    )
                    for criterion in goal_frame.admitted_criteria
                    if criterion.mandatory
                )
                # 用户拒绝当前 Goal 仍需要的 authority 时，blocked 是合法终态；
                # 但 correction 后拒绝旧 target，或已持有 closed Web receipt 后
                # 拒绝重复检索，只是在维护现有 authority，不得据此把已经可证明
                # 的 Goal 终化为 blocked（016 J11 真实三连实测）。
                if mandatory_refs and not self._rejection_still_blocks_current_goal(
                    current.state
                ):
                    probe = CompletionClaim(
                        correlation_id=control.correlation_id,
                        goal_id=goal_frame.goal_id,
                        goal_revision=goal_frame.revision,
                        criterion_evidence_refs=mandatory_refs,
                    )
                    try:
                        self._evidence_registry.derive(
                            current.state,
                            probe,
                            observed_at=self._evidence_time_factory(),
                        )
                    except EvidenceVerificationError as error:
                        evidence_gap = str(error)
                        gap_repair = self._evidence_registry.assess_gap(
                            evidence_gap,
                            available_tools=available_tools,
                        )
                        if gap_repair.repairable_tools:
                            if no_progress.repair_exhausted(
                                (
                                    "blocked_claim_with_repairable_evidence",
                                    *gap_repair.repairable_tools,
                                ),
                                allowance=self._limits.max_no_progress_replans,
                                observation_id=model_calls,
                            ):
                                return self._finish_no_progress(
                                    current,
                                    action,
                                    warnings,
                                    message=(
                                        "Provider repeated blocked claims while an "
                                        "available tool could close the evidence gap."
                                    ),
                                )
                            no_progress_since_product_action = True
                            current = self._save(
                                current,
                                append_policy_result(
                                    current.state,
                                    code="blocked_claim_not_verified",
                                    message=(
                                        "The blocked_claim was not accepted because the "
                                        "current evidence gap is repairable with an "
                                        "advertised product tool. Required next tool: "
                                        f"{', '.join(gap_repair.repairable_tools)}. "
                                        + gap_repair.repair_instruction
                                    ),
                                ),
                            )
                            continue
                    else:
                        # 016 第 96 轮 a2 J7:edit+process 均成功(exit 0、durable
                        # receipts)后模型以 blocked 收尾。守卫合同要求 attempt
                        # "produces a durable blocker";完成证据已可推导时
                        # "无安全动作可推进"不成立,受理会把可完成 Goal 终化为
                        # blocked(false-completion 的对偶)。拒绝并给 completion
                        # 修复指引;证据不可推导时 blocked 语义照旧成立。
                        if no_progress.repair_exhausted(
                            ("blocked_claim_with_derivable_evidence",),
                            allowance=self._limits.max_no_progress_replans,
                            observation_id=model_calls,
                        ):
                            return self._finish_no_progress(
                                current,
                                action,
                                warnings,
                                message=(
                                    "Provider repeated blocked claims while complete "
                                    "evidence was derivable."
                                ),
                            )
                        no_progress_since_product_action = True
                        current = self._save(
                            current,
                            append_policy_result(
                                current.state,
                                code="completion_evidence_available",
                                message=(
                                    "The blocked_claim was not accepted: every "
                                    "mandatory criterion already has derivable "
                                    "evidence from durable facts, so a safe action "
                                    "can advance this Goal. Resend completion_claim "
                                    "with criterion_evidence_refs copied exactly, "
                                    "element for element and in order, from the "
                                    "CURRENT trusted_goal block's "
                                    "expected_completion_evidence_refs; do not "
                                    "report this Goal as blocked."
                                ),
                            ),
                        )
                        continue
                run_id = active.run_id
                accepted_control = self._ground_rejected_process_blocker(
                    current.state,
                    control,
                )
                try:
                    blocked = accept_blocked_claim(current.state, accepted_control)
                except ValueError as error:
                    # 016 真实 E3 第 87 轮 J10:correlation 复用等可修复控制输入
                    # 不得升级为 runtime_failure;与 CompletionClaim 同型的有界修复
                    # (§18 先例),额度与 fatal 语义不变。
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
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=run_id,
                    message=accepted_control.blocker,
                    outcome_state=blocked,
                )
            if isinstance(control, CompletionClaim):
                try:
                    records = self._evidence_registry.derive(
                        current.state,
                        control,
                        observed_at=self._evidence_time_factory(),
                    )
                    existing_ids = {record.evidence_id for record in current.state.evidence_records}
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
                            canonical_json_digest(list(control.criterion_evidence_refs)),
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
                                + self._evidence_registry.assess_gap(
                                    str(error)
                                ).repair_instruction
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
            model_tools = [block for block in response.blocks if isinstance(block, ModelToolCall)]
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
                registered_names = {tool.name for tool in self._tool_runtime.definitions()}
                unadvertised_names = sorted(
                    {
                        block.name
                        for block in model_tools
                        if block.name not in advertised_names
                        and (
                            current.state.goal is None
                            or block.name in registered_names
                        )
                    }
                )
                if unadvertised_names:
                    if no_progress.repair_exhausted(
                        ("unadvertised_tool", *unadvertised_names),
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
                            code="unadvertised_tool",
                            message=(
                                "The requested tool is registered but not currently "
                                "available: "
                                + ", ".join(unadvertised_names)
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
                # 一个已广告、已持久化的 tool batch 是合法 Provider response。
                # 后续若再出现 malformed/control 错误，应获得新的连续修复预算；
                # tool 自身的失败/停滞仍由 result、policy 与 no-progress 边界处理。
                invalid_repairs = 0
                continue

            final_text = "\n".join(texts)
            goal = current.state.goal
            if (
                goal is None
                and "direct_response" not in self._advertised_control_kinds(context)
            ):
                # non-strict Provider 仍可能绕过 tool schema 返回裸 prose。若 trusted
                # action 已证明文字不可能完成 outcome，裸 prose 与隐藏的
                # direct_response 等价，必须走同一有界修复，不能静默宣称完成。
                if invalid_repairs >= self._limits.max_invalid_repairs:
                    failed = fail_run(
                        current.state,
                        code="invalid_model_control",
                        message=(
                            "Provider repeated final prose for an explicit non-prose "
                            "outcome after repair allowance."
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
                        code="explicit_non_prose_outcome_requires_goal",
                        message=(
                            "Final prose cannot complete the explicit requested action. "
                            "Submit the advertised goal_proposal, or ask one clarification "
                            "only if a real intent or authority boundary remains."
                        ),
                    ),
                )
                continue
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
                                "A nonterminal Goal cannot end with final prose. When the "
                                "required evidence already exists, send completion_claim and "
                                "copy criterion_evidence_refs exactly, element for element and "
                                "in order, from CURRENT trusted_goal."
                                "expected_completion_evidence_refs. If concrete work remains, "
                                "call an advertised product tool; use blocked_claim only when "
                                "no safe action can advance the Goal."
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
            event_kind=(RuntimeEventKind.CANCELLED if cancelled else RuntimeEventKind.COMPLETED),
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

    def _finish_background_model_unknown(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
    ) -> RunResult:
        unknown = mark_model_outcome_unknown(current.state)
        return self._finish(
            current,
            action,
            status=RunStatus.FAILED_RETRYABLE,
            warnings=warnings,
            event_kind=RuntimeEventKind.FAILED,
            error_code="model_outcome_unknown",
            message="Provider outcome is unknown; abandon this occurrence explicitly.",
            outcome_state=unknown,
        )

    def _finish_no_progress(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        *,
        message: str,
    ) -> RunResult:
        paused = pause_for_limit(current.state)
        return self._finish(
            current,
            action,
            status=RunStatus.LIMIT_REACHED,
            warnings=warnings,
            event_kind=RuntimeEventKind.LIMIT_REACHED,
            error_code="no_progress",
            message=message,
            outcome_state=paused,
        )

    @staticmethod
    def _advertised_control_kinds(context: ContextPack) -> set[str]:
        schema = context.control_schema
        if not isinstance(schema, dict):
            return set()
        input_schema = schema.get("input_schema")
        properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
        kind = properties.get("kind") if isinstance(properties, dict) else None
        values = kind.get("enum") if isinstance(kind, dict) else None
        if not isinstance(values, list):
            return set()
        return {value for value in values if isinstance(value, str)}

    @staticmethod
    def _control_kind(control: object) -> str:
        if isinstance(control, DirectResponse):
            return "direct_response"
        if isinstance(control, BeginAnswer):
            return "begin_answer"
        if isinstance(control, ClarificationRequest):
            return "clarification_request"
        if isinstance(control, GoalDraftProposal):
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
        if (
            goal is None
            or proposal.delta.goal_id != goal.goal_id
            or proposal.delta.expected_revision != goal.revision
            or {"admitted_criteria", "authority_snapshot"} & updates.keys()
        ):
            return False
        if goal_correction_adds_runtime_obligation(state):
            return False
        for name, proposed in updates.items():
            current: object = getattr(goal, name)
            if name == "proposed_criteria":
                current = [
                    {
                        "criterion_id": item.criterion_id,
                        "description": item.description,
                        "oracle_kind": (
                            item.oracle_kind.value if item.oracle_kind is not None else None
                        ),
                        "artifact_path": item.artifact_path or "",
                    }
                    for item in goal.proposed_criteria
                ]
            if canonical_json_digest(current) != canonical_json_digest(proposed):
                return False
        return True

    @staticmethod
    def _run_has_product_tool_attempt(state: ConversationState) -> bool:
        active = state.active_run
        if active is None:
            return False
        prefix = f"run:{active.run_id}:"
        return any(
            fact.kind is FactKind.TOOL_CALLS
            and fact.fact_id.startswith(prefix)
            and isinstance(fact.content.get("calls"), list)
            and bool(fact.content["calls"])
            for fact in state.facts
        )

    @staticmethod
    def _rejection_still_blocks_current_goal(state: ConversationState) -> bool:
        """只把仍属于当前 Goal 的拒绝视为真实 blocker。

        ``rejected_request_ids`` 本身没有 tool 语义；必须回到当前 run 的 durable
        TOOL_CALLS/TOOL_RESULT facts 判断。无法精确配对时 fail closed，继续尊重
        用户拒绝。旧 target 与已满足 Web 义务的重复请求不再拥有当前 Goal 的
        authority，因此不能绕过 false-blocked 守卫。
        """

        active = state.active_run
        goal = state.goal
        if active is None or not active.rejected_request_ids:
            return False
        if goal is None:
            return True

        run_prefix = f"run:{active.run_id}:"
        calls: dict[str, tuple[str, object]] = {}
        for fact in state.facts:
            if fact.kind is not FactKind.TOOL_CALLS or not fact.fact_id.startswith(
                run_prefix
            ):
                continue
            raw_calls = fact.content.get("calls")
            if not isinstance(raw_calls, list):
                continue
            for raw in raw_calls:
                if not isinstance(raw, dict):
                    continue
                call_id = raw.get("tool_call_id")
                name = raw.get("name")
                if isinstance(call_id, str) and isinstance(name, str):
                    calls[call_id] = (name, raw.get("arguments"))

        rejected_calls: list[tuple[str, object]] = []
        for fact in state.facts:
            if fact.kind is not FactKind.TOOL_RESULT or fact.content.get("rejected") is not True:
                continue
            call_id = fact.content.get("tool_call_id")
            if isinstance(call_id, str) and call_id in calls:
                rejected_calls.append(calls[call_id])
        if len(rejected_calls) != len(active.rejected_request_ids):
            return True

        web_requirement_ids = {
            item.criterion_id
            for item in goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        }
        admitted_web_ids = {
            item.criterion_id
            for item in goal.admitted_criteria
            if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
            and item.mandatory
        }
        web_requirement_satisfied = bool(web_requirement_ids) and (
            web_requirement_ids <= admitted_web_ids
        )
        for name, arguments in rejected_calls:
            if name in {"web_search", "web_fetch"} and web_requirement_satisfied:
                continue
            if name in {"write_file", "edit_file"} and isinstance(arguments, dict):
                path = arguments.get("path")
                if isinstance(path, str) and path not in goal.targets:
                    continue
            return True
        return False

    @staticmethod
    def _ground_rejected_process_blocker(
        state: ConversationState,
        claim: BlockedClaim,
    ) -> BlockedClaim:
        """用户拒绝必需进程且零执行时，以 durable facts 固定准确结果。"""

        active = state.active_run
        goal = state.goal
        if active is None or goal is None:
            return claim
        has_process_obligation = any(
            criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and criterion.criterion_id.startswith("criterion:required-local-process:")
            for criterion in goal.proposed_criteria
        )
        if not has_process_obligation:
            return claim

        run_prefix = f"run:{active.run_id}:"
        requested_entrypoints = authoritative_process_entrypoints(state)
        current_process_calls: dict[str, bool] = {}
        latest_relevant_rejected = False
        executed = False
        for fact in state.facts:
            if fact.kind is FactKind.TOOL_CALLS and fact.fact_id.startswith(run_prefix):
                raw_calls = fact.content.get("calls")
                if not isinstance(raw_calls, list):
                    continue
                for raw in raw_calls:
                    if not isinstance(raw, dict):
                        continue
                    call_id = raw.get("tool_call_id")
                    if not isinstance(call_id, str):
                        continue
                    current_process_calls.pop(call_id, None)
                    name = raw.get("name")
                    arguments = raw.get("arguments")
                    if (
                        name != "local_process"
                        or not isinstance(arguments, dict)
                    ):
                        continue
                    executable = arguments.get("executable")
                    if not isinstance(executable, str):
                        continue
                    normalized = normalize_process_entrypoint(executable)
                    relevant = (
                        normalized in requested_entrypoints
                        if requested_entrypoints
                        else executable.strip().strip("'\"").startswith("./")
                    )
                    current_process_calls[call_id] = relevant
                    if relevant:
                        latest_relevant_rejected = False
                continue
            if fact.kind is not FactKind.TOOL_RESULT:
                continue
            call_id = fact.content.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in current_process_calls:
                continue
            if current_process_calls[call_id]:
                latest_relevant_rejected = fact.content.get("rejected") is True
            executed = executed or fact.content.get("executed") is True
        if not latest_relevant_rejected or executed:
            return claim

        return replace(
            claim,
            blocker=(
                "The requested local process was not run because you declined approval. "
                "No process was started, so the task remains blocked."
            ),
            safe_attempts=(
                "requested the exact local process and recorded the denial without "
                "starting it",
            ),
            resume_condition="approve the exact requested local process",
        )

    @staticmethod
    def _run_has_policy_result(state: ConversationState, code: str) -> bool:
        active = state.active_run
        if active is None:
            return False
        prefix = f"run:{active.run_id}:"
        return any(
            fact.kind is FactKind.POLICY_RESULT
            and fact.fact_id.startswith(prefix)
            and fact.content.get("code") == code
            for fact in state.facts
        )

    def _finish_if_durable_evidence_is_complete(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        *,
        tool_name: str,
    ) -> RunResult | None:
        """最终 read-back 已闭合全部 oracle 时，由 Runtime 确定性收尾。

        ``completion_claim`` 的模型字段只是逐字复制 Runtime 已发布的 evidence refs，
        不携带新的用户意图或 authority。继续要求模型抄写会在研究任务的双文件
        read-back 后造成无意义 churn。这里仍先用同一个 ``ClosedEvidenceRegistry``
        完整重算，再按原有 evidence → claim → VERIFIED_DONE checkpoint 顺序持久化；
        任一 criterion 尚不可证明时不写入任何状态，继续唯一 model/tool loop。
        只读 ``read_file`` 是窄触发 seam；process/Web/effect result 仍需经过后续
        模型控制，从而不截断复用、变更重批或拒绝零执行等既有安全路径。
        """

        if tool_name != "read_file":
            return None
        goal = current.state.goal
        active = current.state.active_run
        if (
            goal is None
            or active is None
            or goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}
        ):
            return None
        mandatory_refs = tuple(
            ClosedEvidenceRegistry.evidence_id(
                goal.goal_id,
                goal.revision,
                criterion.criterion_id,
            )
            for criterion in goal.admitted_criteria
            if criterion.mandatory
        )
        if not mandatory_refs:
            return None
        claim = CompletionClaim(
            correlation_id=(
                "runtime-completion:"
                + canonical_json_digest(
                    {
                        "run_id": active.run_id,
                        "goal_id": goal.goal_id,
                        "goal_revision": goal.revision,
                        "evidence_refs": mandatory_refs,
                    }
                )[:24]
            ),
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            criterion_evidence_refs=mandatory_refs,
        )
        try:
            records = self._evidence_registry.derive(
                current.state,
                claim,
                observed_at=self._evidence_time_factory(),
            )
            existing_ids = {
                record.evidence_id for record in current.state.evidence_records
            }
            fresh = tuple(
                record for record in records if record.evidence_id not in existing_ids
            )
            candidate = current.state
            if fresh:
                candidate = record_evidence(candidate, fresh)
            candidate = record_completion_claim(candidate, claim)
            verify_goal_completion(candidate)
        except (EvidenceVerificationError, ValueError):
            return None

        if fresh:
            current = self._save(current, record_evidence(current.state, fresh))
        current = self._save(current, record_completion_claim(current.state, claim))
        current = self._save(current, verify_goal_completion(current.state))
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

    @staticmethod
    def _duplicate_product_request_guidance(
        state: ConversationState,
        call: ToolCall,
    ) -> str:
        base = (
            "Duplicate request suppressed: the same product tool input already succeeded "
            "in this run. Do not repeat it."
        )
        if call.name != "web_fetch":
            return (
                base
                + " Choose a materially different tool, input, or source; complete with "
                "evidence; or send blocked_claim if no safe action can advance the Goal."
            )
        refs = web_fetch_source_refs(state)
        if refs:
            return (
                base
                + " For web_fetch, use one of these currently unattempted exact "
                "FIRST_AGENT_RUNTIME_WEB_FETCH_REFS: "
                + ", ".join(refs)
                + "."
            )
        return (
            base
            + " No unattempted Web fetch ref remains. Use the successful source results "
            "already in context and proceed to the requested artifact, or issue a "
            "materially different web_search only if another source is genuinely required."
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
                stable_event_id=(f"request:{request.request_id}" if request is not None else None),
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
            definition.name == tool_name and definition.side_effect is not SideEffectClass.READ_ONLY
            for definition in self._tool_runtime.definitions()
        )

    def _is_lease_governed_tool(self, tool_name: str) -> bool:
        # 015：LOCAL_SAME_UID_PROCESS 工具的 exact reuse 由 durable lease 治理（F2/R9，
        # 8 uses），不适用 read-only/source 的 product-request dedup——重复 exact command
        # 是合法的 lease reuse，不是 no-progress 重复。
        return any(
            definition.name == tool_name
            and definition.execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
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
                if fact.kind is FactKind.USER_MESSAGE and fact.content.get("text") == content
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
    def _public_web_requirement_pending(state: ConversationState) -> bool:
        if state.goal is None:
            return False
        _, projections = project_tool_result_sources(state.facts, state)
        return public_web_requirement_pending(state, projections)

    @staticmethod
    def _citable_source_refs_for(state: ConversationState) -> tuple[str, ...]:
        if state.goal is None:
            return ()
        _, projections = project_tool_result_sources(state.facts, state)
        return citable_source_refs(projections)

    @staticmethod
    def _citable_citation_sources_for(
        state: ConversationState,
    ) -> tuple[tuple[str, str], ...]:
        if state.goal is None:
            return ()
        _, projections = project_tool_result_sources(state.facts, state)
        return citable_citation_sources(projections)

    @staticmethod
    def _citation_manifest_content_digests_for(
        state: ConversationState,
    ) -> tuple[str, ...]:
        active = state.active_run
        goal = state.goal
        if active is None or goal is None:
            return ()
        run_prefix = f"run:{active.run_id}:"
        builder_call_ids: set[str] = set()
        accepted: list[str] = []
        artifact_paths = {
            target for target in goal.targets if not target.endswith(".citations.json")
        }
        for fact in state.facts:
            if not fact.fact_id.startswith(run_prefix):
                continue
            if fact.kind is FactKind.TOOL_CALLS:
                raw_calls = fact.content.get("calls")
                if not isinstance(raw_calls, list):
                    continue
                for raw_call in raw_calls:
                    if (
                        isinstance(raw_call, dict)
                        and raw_call.get("name") == "build_citation_manifest"
                        and isinstance(raw_call.get("tool_call_id"), str)
                    ):
                        builder_call_ids.add(raw_call["tool_call_id"])
                continue
            if (
                fact.kind is not FactKind.TOOL_RESULT
                or fact.content.get("tool_call_id") not in builder_call_ids
                or fact.content.get("executed") is not True
                or fact.content.get("is_error") is not False
            ):
                continue
            content = fact.content.get("text")
            if not isinstance(content, str):
                continue
            try:
                manifest = CitationManifestV1.from_json(content)
            except ValueError:
                continue
            if (
                manifest.goal_id != goal.goal_id
                or manifest.goal_revision != goal.revision
                or manifest.artifact_path not in artifact_paths
            ):
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest not in accepted:
                accepted.append(digest)
        return tuple(accepted)

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
        if len(receipt_digest) != 64 or any(
            character not in "0123456789abcdef" for character in receipt_digest
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
            raw_receipts = metadata.get("source_receipts") if isinstance(metadata, dict) else None
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
                or hashlib.sha256(url.encode("utf-8")).hexdigest() != receipt.origin_request_digest
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
        if call.name not in {
            "owner_preference_confirm",
            "owner_preference_correct",
        } or not isinstance(content, str):
            return None
        source = next(
            (
                fact
                for fact in reversed(state.facts)
                if fact.kind is FactKind.USER_MESSAGE and fact.content.get("text") == content
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
