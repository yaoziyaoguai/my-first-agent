"""唯一的 Agent Runtime effect-ordering loop。"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
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
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ExecutionIntent,
    FactAdmissionBinding,
    FactAdmissionClass,
    FactKind,
    GoalDeltaProposal,
    GoalProgress,
    GoalProposal,
    GoalStatus,
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


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    max_model_calls: int = 16
    max_tool_calls: int = 32
    max_input_tokens: int = 100_000
    max_output_tokens: int = 20_000
    max_invalid_repairs: int = 1
    durable_effect_reserve_bytes: int = 65_536

    def __post_init__(self) -> None:
        for name, value in (
            ("max_model_calls", self.max_model_calls),
            ("max_tool_calls", self.max_tool_calls),
            ("max_input_tokens", self.max_input_tokens),
            ("max_output_tokens", self.max_output_tokens),
            ("durable_effect_reserve_bytes", self.durable_effect_reserve_bytes),
        ):
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_invalid_repairs < 0:
            raise ValueError("max_invalid_repairs must be non-negative")


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
            transition = accept_action(snapshot.state, action)
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
                prepared = self._tool_runtime.prepare(
                    call,
                    ToolPrepareContext(
                        conversation_id=current.state.conversation_id,
                        run_id=active.run_id,
                        state_revision=current.state.revision,
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
                    continue
                if not isinstance(prepared, ExecutionIntent):
                    raise RuntimeError("Tool Runtime returned an unsupported preparation")
                if tool_calls >= self._limits.max_tool_calls:
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
                    current = self._save(
                        current,
                        record_tool_result(
                            current.state,
                            fact,
                            intent_digest=prepared.intent_digest,
                        ),
                    )
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
                continue

            if active.phase is not ContinuationPhase.MODEL:
                raise RuntimeError("EXECUTING continuation must enter recovery before resume")
            if model_calls >= self._limits.max_model_calls:
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
            if input_tokens + context.budget.estimated_input_tokens > self._limits.max_input_tokens:
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
            if output_tokens > self._limits.max_output_tokens:
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
                current = self._save(
                    current,
                    accept_goal_proposal(current.state, control, context.goal_bootstrap),
                )
                continue
            if isinstance(control, GoalProgress):
                # 进度是活跃 Goal 的中间态:reducer 校验并落盘 EXECUTING 与
                # correlation receipt 后,同一循环重建上下文继续,不依赖用户
                # 再提交合成 "continue" 消息。
                current = self._save(
                    current,
                    record_goal_progress(current.state, control),
                )
                continue
            if isinstance(control, GoalDeltaProposal):
                current = self._save(
                    current,
                    accept_goal_delta_proposal(current.state, control),
                )
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
                        observed_at="runtime-verified",
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
                    current = self._save(
                        current,
                        record_completion_claim(current.state, control),
                    )
                    current = self._save(
                        current,
                        verify_goal_completion(current.state),
                    )
                except EvidenceVerificationError as error:
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="completion_not_verified",
                            message=str(error),
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
                if fact.kind in {FactKind.USER_MESSAGE, FactKind.TOOL_RESULT}
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
