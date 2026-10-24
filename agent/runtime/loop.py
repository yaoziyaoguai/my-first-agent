"""唯一的 Agent Runtime effect-ordering loop。"""

from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from agent.continuity.compaction import (
    CompactionArchiveError,
    CompactionResponseError,
    archive_compaction_source,
    parse_compaction_response,
)
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
    ActiveRun,
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
    CompactionPlanV1,
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
    InvocationOrigin,
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
    ResolveApproval,
    ResumeGoal,
    RevokeGoalTargetAuthority,
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
from agent.runtime.evidence import (
    WORKSPACE_WRITE_TOOLS,
    WRITABLE_PROCESS_TOOLS,
    ClosedEvidenceRegistry,
    EvidenceVerificationError,
    trusted_readonly_native_sandbox_success,
)
from agent.runtime.ports import (
    CheckpointCASConflictError,
    CheckpointStore,
    ContextManager,
    ConversationArchive,
    EventSink,
    InvalidProviderResponseError,
    ModelAttemptBudgetExhaustedError,
    ModelProvider,
    RetryableContextSourceError,
    RetryableProviderError,
    ToolRuntime,
)
from agent.runtime.provider_consent import (
    ProviderDispatchGateV1,
    charge_provider_dispatch,
    evaluate_provider_dispatch,
    final_dispatch_expiry_check,
    invalidate_provider_consent,
    workspace_read_dispatch_notice,
)
from agent.runtime.resource_lifecycle import managed_process_receipts
from agent.runtime.state import (
    accept_action,
    accept_begin_answer,
    accept_blocked_claim,
    accept_clarification_request,
    accept_goal_delta_proposal,
    accept_goal_draft_proposal,
    acknowledge_noop_goal_delta,
    admit_governed_tool_receipt_criterion,
    admit_process_receipt_criterion,
    admit_sandbox_receipt_criterion,
    admit_web_source_criterion,
    append_policy_result,
    apply_compaction_summary,
    apply_control_request,
    authoritative_deliverable_file_paths,
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
    record_foreground_model_attempt,
    record_goal_progress,
    record_nonexecuted_tool_result,
    record_provider_response,
    record_tool_result,
    release_operator_tool,
    start_tool_batch,
    verify_goal_completion,
)

_WORKSPACE_OBSERVATION_TOOLS = frozenset(
    {
        "read_file",
        "confirm_file",
        "read_file_chunk",
        "list_files",
        "search_paths",
        "search_text",
    }
)
# 可变观察：结果依赖外部世界当前状态（workspace 文件、live browser session），
# 在任何实际执行的 effect 之后都可能过期，因此允许同参数重新观察。
_MUTABLE_OBSERVATION_TOOLS = _WORKSPACE_OBSERVATION_TOOLS | {"browser_observe"}


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    max_model_calls: int | None = 16
    # 单次 run 跨 /resume 的 durable 上限；与上面的 invocation-local 分片分开。
    # caller 可显式提高后继续，但恢复本身不会重置已经消费的模型调用。
    max_run_model_calls: int | None = None
    # 当前 durable run 的墙钟上限；首次接管时起算，Resume/重启不清零。
    max_run_wall_seconds: int | None = None
    max_tool_calls: int | None = 32
    max_input_tokens: int | None = 100_000
    max_output_tokens: int | None = 20_000
    max_invalid_repairs: int = 1
    # 只在前台、且 provider 已明确归类为 timeout/transport/unavailable 时
    # 允许有限自动重试；429/认证/额度与 background unknown outcome 不走这里。
    max_retryable_provider_retries: int = 0
    durable_effect_reserve_bytes: int = 65_536
    # 这是“第 N 次连续同指纹停滞即熔断”的阈值。默认 2 保留一次纠偏机会；
    # Everyday 显式设为 16，在第 16 次命中后暂停而不是再多发送一次。
    max_no_progress_replans: int = 2

    def __post_init__(self) -> None:
        for name, value in (
            ("max_model_calls", self.max_model_calls),
            ("max_run_model_calls", self.max_run_model_calls),
            ("max_run_wall_seconds", self.max_run_wall_seconds),
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
        if self.max_retryable_provider_retries < 0:
            raise ValueError("max_retryable_provider_retries must be non-negative")
        if self.max_no_progress_replans < 0:
            raise ValueError("max_no_progress_replans must be non-negative")


# invalid_repairs 计数器覆盖的全部修复型 policy code（闭合集合）。consent
# 披露暂停会中断 run_turn 并在恢复时重建 _drive 局部计数器；若不从 durable
# 的 run 级 POLICY_RESULT facts 重建额度，"空响应修复 × 外发确认暂停"交替
# 会让修复上限永远重置（2026-10-23 E3 harness 实测 1000+ 次无界循环）。
_INVALID_REPAIR_POLICY_CODES = frozenset(
    (
        "invalid_provider_response",
        "invalid_model_output",
        "invalid_model_control",
        "invalid_goal_proposal",
        "invalid_goal_delta",
        "unadvertised_tool",
        "paused_goal_requires_resume",
        "explicit_non_prose_outcome_requires_goal",
        "active_goal_requires_control",
    )
)


# oracle r3 F2：这些停滞 facts 不是有效模型输出，不得打断"连续无效响应"
# 链（invalid → transient → invalid 在运行中语义下是连续 2 次）。
_STALL_TRANSPARENT_POLICY_CODES = frozenset(
    {"provider_transient_retry", "no_progress_replan_required"}
)


def _run_invalid_repairs(state) -> int:
    """从本 run 已落盘的修复型 policy facts 重建连续无效响应额度。

    从尾部回扫：修复型 facts 计数；透明停滞 facts（瞬态重试/no-progress
    修复）跳过；任何其他 fact（有效输出、用户/工具动作）打断链条。透明
    跳过只影响链完整性，不会把被打断的历史修复计回来（欠计修复为安全
    方向的反面——此处修复的是欠计）。
    """

    active = state.active_run
    if active is None:
        return 0
    prefix = f"run:{active.run_id}:policy:"
    count = 0
    for fact in reversed(state.facts):
        if not (fact.fact_id.startswith(prefix) and fact.kind is FactKind.POLICY_RESULT):
            break
        code = fact.content.get("code")
        if code in _INVALID_REPAIR_POLICY_CODES:
            count += 1
        elif code in _STALL_TRANSPARENT_POLICY_CODES:
            continue
        else:
            break
    return count


def _run_transient_retries(state) -> int:
    """从本 run 的 `provider_transient_retry` facts 累计重建瞬态重试额度。"""

    active = state.active_run
    if active is None:
        return 0
    prefix = f"run:{active.run_id}:policy:"
    return sum(
        1
        for fact in state.facts
        if fact.fact_id.startswith(prefix)
        and fact.kind is FactKind.POLICY_RESULT
        and fact.content.get("code") == "provider_transient_retry"
    )


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


@dataclass(slots=True)
class _ToolBatchConvergence:
    """当前已接纳模型工具批次的 invocation-local 收敛摘要。"""

    failure_signatures: list[tuple[str, ...]]
    has_success: bool = False
    feedback: str | None = None
    eligible: bool = True


class _CheckpointWriteError(RuntimeError):
    """保留失败写入前的显式 CAS cursor，不从 store 隐式重载状态。"""

    def __init__(self, cause: Exception, current: LoadedSnapshot) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.current = current


@dataclass(frozen=True, slots=True)
class _CompactionCallResult:
    """一次成功 compaction 调用的内部结果（020）。

    input 计数来自 compaction 专用 ContextPack 的真实预算估算；output 是
    provider 自报的 ``ModelResponse.output_tokens``（当前合同没有 usage
    嵌套对象，未上报记 0）。
    """

    snapshot: LoadedSnapshot
    input_tokens: int
    output_tokens: int
    context: ContextPack


@dataclass(slots=True)
class _ProviderProgressReporter:
    stop: threading.Event
    thread: threading.Thread
    started_at: float
    next_sequence: Callable[[], int]


class AgentRuntime:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        context_manager: ContextManager,
        tool_runtime: ToolRuntime,
        checkpoint_store: CheckpointStore,
        event_sink: EventSink,
        progress_event_sink: EventSink | None = None,
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
        conversation_archive: ConversationArchive | None = None,
        provider_progress_interval_seconds: float = 15.0,
        run_time_factory: Callable[[], str] | None = None,
    ) -> None:
        if provider_progress_interval_seconds <= 0:
            raise ValueError("provider progress interval must be positive")
        self._provider = provider
        self._context_manager = context_manager
        self._tool_runtime = tool_runtime
        self._checkpoint_store = checkpoint_store
        self._event_sink = event_sink
        # 运行中 advisory 与锁后交付的权威 Runtime events 使用不同端口。
        # 只有能接受并发、不可重放提示的 caller 才显式注入此 sink。
        self._progress_event_sink = progress_event_sink
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
        # 020 自动 compaction：archive 在缩减 CAS 前无损原样存档完整 state；
        # None 时无 compaction 能力，普通 run 路径完全不变。
        self._conversation_archive = conversation_archive
        self._provider_progress_interval_seconds = provider_progress_interval_seconds
        self._run_time_factory = run_time_factory or (
            lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
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
            transition = accept_action(
                current.state,
                action,
                now=self._run_time_factory(),
            )
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

            if isinstance(action, RevokeGoalTargetAuthority):
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    message="Current task file permissions revoked.",
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
            if isinstance(action, ResolveApproval) and not action.approved:
                return self._finish(
                    current,
                    action,
                    status=RunStatus.CANCELLED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.CANCELLED,
                    message=(
                        "The requested action was declined. It was not executed; the "
                        "current goal remains available for a new instruction or /cancel."
                    ),
                    error_code="approval_declined",
                    outcome_state=transition.state,
                )
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

            transition_state = self._ensure_run_started(transition.state)
            try:
                current = self._save(current, transition_state)
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
        except _CheckpointWriteError as failure:
            return self._handle_unexpected_error(
                action,
                failure.current,
                warnings,
                failure.cause,
            )
        except Exception as error:
            return self._handle_unexpected_error(action, current, warnings, error)

    def _ensure_run_started(self, state: ConversationState) -> ConversationState:
        active = state.active_run
        if active is None or active.run_started_at is not None:
            return state
        started_at = self._run_time_factory()
        try:
            datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as error:
            raise ValueError("run_time_factory must return zoned RFC3339") from error
        return replace(
            state,
            active_run=replace(active, run_started_at=started_at),
        )

    def _handle_unexpected_error(
        self,
        action: Action,
        current: LoadedSnapshot,
        warnings: list[str],
        error: Exception,
    ) -> RunResult:
        """只基于显式传入的最新 CAS cursor 收尾；不得向 store hidden reload。"""

        state = current.state
        active = state.active_run
        executing = active.executing_intent if active is not None else None
        if (
            active is not None
            and executing is not None
            and active.phase is ContinuationPhase.EXECUTING
        ):
            # R1：durable snapshot 处于 EXECUTING（效果可能已发生）或已落盘
            # AWAITING_RECOVERY（同相同 intent 不变量）时，UNKNOWN 不能被
            # fail_run 清成确定终态。先按既有路径尝试落 recovery；保存不了
            # 则返回明确失败并保留 durable 未知态，存储恢复后由 Resume/
            # Resolve 继续，零工具重放。
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
                return self._finish_unknown_effect_persistence_failure(
                    action,
                    current,
                    warnings,
                    error,
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
                    f"fatal persistence failed: {type(persistence_error).__name__}"
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

    def _finish_unknown_effect_persistence_failure(
        self,
        action: Action,
        current: LoadedSnapshot,
        warnings: list[str],
        error: Exception,
    ) -> RunResult:
        """UNKNOWN 的 recovery 落盘失败：如实失败，保留 durable 未知态。

        不能报告任何尚未落盘的安全终态，也不能清空 run；action 本身仍按
        replay 合同收尾（能保存时），使同一 action 的重复提交得到确定性结果。
        """

        message = (
            "The tool effect outcome is unknown and its recovery checkpoint could "
            "not be saved. The durable state still records the unclassified "
            "execution; resume the run to classify it before continuing. "
            f"{type(error).__name__}: {error}"
        )
        try:
            return self._finish(
                current,
                action,
                status=RunStatus.FAILED_FATAL,
                warnings=warnings,
                event_kind=RuntimeEventKind.FAILED,
                error_code="recovery_persistence_failed",
                message=message,
                outcome_state=current.state,
            )
        except Exception as finalize_error:
            warnings.append(
                f"fatal persistence failed: {type(finalize_error).__name__}"
            )
            active = current.state.active_run
            return RunResult(
                status=RunStatus.FAILED_FATAL,
                state=current.state,
                run_id=active.run_id if active is not None else None,
                error_code="recovery_persistence_failed",
                message=message,
                delivery_warnings=tuple(warnings),
                model_calls_used=(
                    active.model_calls_used if active is not None else 0
                ),
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
        compaction_batches = 0
        # consent 披露暂停会拆分 run_turn；修复额度从 durable 的 run 级
        # policy facts 重建，避免"空响应修复 × 确认暂停"交替无界循环。
        invalid_repairs = _run_invalid_repairs(current.state)
        # oracle r2 §F-4：瞬态重试额度同样跨 resume 重建。该计数在 run 内
        # 是累计语义（有效响应不复位），因此用全量计数而非尾部连续。
        retryable_provider_retries = _run_transient_retries(current.state)
        no_progress = _NoProgressTracker()
        no_progress_since_product_action = False
        (
            successful_product_requests,
            successful_workspace_observations,
            native_validation_successes,
        ) = self._successful_product_request_inventory(current.state)
        tool_batch = self._resumed_tool_batch_convergence(current.state)

        while True:
            active = current.state.active_run
            if active is None:
                raise RuntimeError("active run disappeared before terminal result")

            if (
                active.invocation_origin is InvocationOrigin.OPERATOR
                and active.status is ActiveRunStatus.RUNNABLE
                and active.phase is ContinuationPhase.MODEL
            ):
                released = release_operator_tool(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=active.run_id,
                    message="operator tool action completed",
                    outcome_state=released,
                )

            self._open_control_binding(current.state)
            controlled = self._poll_control(action, current, warnings)
            if controlled is not None:
                return controlled

            if (
                active.status is ActiveRunStatus.RUNNABLE
                and self._run_wall_budget_expired(active.run_started_at)
            ):
                paused = pause_for_limit(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="run_wall_time_limit",
                    outcome_state=paused,
                )

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
                    active.invocation_origin is InvocationOrigin.MODEL
                    and request_digest
                    in successful_product_requests | native_validation_successes
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
                        metadata={"code": "duplicate_product_request"},
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
                    tool_batch.failure_signatures.append(
                        ("duplicate_product_request", request_digest)
                    )
                    tool_batch.feedback = duplicate_guidance
                    if not self._tool_batch_is_complete(active):
                        continue
                    current, no_progress_since_product_action, finished = (
                        self._finalize_tool_batch_convergence(
                            current,
                            action,
                            warnings,
                            batch=tool_batch,
                            no_progress=no_progress,
                            no_progress_since_product_action=(
                                no_progress_since_product_action
                            ),
                            observation_id=model_calls,
                        )
                    )
                    if finished is not None:
                        return finished
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
                        invocation_origin=active.invocation_origin,
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
                    no_progress_signature = self._tool_failure_signature(
                        request_digest,
                        prepared,
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
                    if active.invocation_origin is InvocationOrigin.MODEL:
                        tool_batch.failure_signatures.append(no_progress_signature)
                        if not self._tool_batch_is_complete(active):
                            continue
                        current, no_progress_since_product_action, finished = (
                            self._finalize_tool_batch_convergence(
                                current,
                                action,
                                warnings,
                                batch=tool_batch,
                                no_progress=no_progress,
                                no_progress_since_product_action=(
                                    no_progress_since_product_action
                                ),
                                observation_id=model_calls,
                            )
                        )
                        if finished is not None:
                            return finished
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
                    goal_authorization_id=(
                        prepared.goal_authorization.binding_id
                        if prepared.goal_authorization is not None
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
                    # R1：成功 read-only sandbox receipt 的结果时准入（镜像 process）。
                    if (
                        _meta.get("sandbox_receipt_kind") == "native_sandbox_v1"
                        and _meta.get("outcome") == "exited"
                        and _meta.get("exit_code") == 0
                        and _meta.get("mode") == "read-only"
                        and _meta.get("receipt_digest")
                        and _meta.get("command_fingerprint")
                        and isinstance(_meta.get("policy_digest"), str)
                        and isinstance(_meta.get("network"), str)
                    ):
                        post_result_state = admit_sandbox_receipt_criterion(
                            post_result_state,
                            tool_call_id=prepared.tool_call_id,
                            receipt_digest=_meta["receipt_digest"],
                            command_fingerprint=_meta["command_fingerprint"],
                            policy_digest=_meta["policy_digest"],
                            mode=_meta["mode"],
                            network=_meta["network"],
                            action_seq=action.action_seq,
                        )
                    if (
                        tool_result.executed
                        and not tool_result.is_error
                        and _meta.get("governed_tool_receipt_kind")
                        == "governed_tool_v1"
                        and isinstance(_meta.get("receipt_digest"), str)
                    ):
                        post_result_state = admit_governed_tool_receipt_criterion(
                            post_result_state,
                            tool_call_id=prepared.tool_call_id,
                            tool_name=prepared.tool_name,
                            receipt_digest=_meta["receipt_digest"],
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
                if tool_result.executed:
                    # S1-A（2026-10-09）：三个集合由 durable fact fold 在每次已执行
                    # result checkpoint 保存成功后统一重建（operator 结果同样参与
                    # 失效判断）；不再维护 live 增量副本。checkpoint 保存失败走
                    # 上方 recovery，不会提前更新成功缓存。
                    (
                        successful_product_requests,
                        successful_workspace_observations,
                        native_validation_successes,
                    ) = self._successful_product_request_inventory(current.state)
                if active.invocation_origin is InvocationOrigin.MODEL:
                    if tool_result.executed and not tool_result.is_error:
                        tool_batch.has_success = True
                    else:
                        tool_batch.failure_signatures.append(
                            self._tool_failure_signature(
                                request_digest,
                                tool_result,
                            )
                        )
                    if not self._tool_batch_is_complete(active):
                        continue
                    current, no_progress_since_product_action, finished = (
                        self._finalize_tool_batch_convergence(
                            current,
                            action,
                            warnings,
                            batch=tool_batch,
                            no_progress=no_progress,
                            no_progress_since_product_action=(
                                no_progress_since_product_action
                            ),
                            observation_id=model_calls,
                        )
                    )
                    if finished is not None:
                        return finished
                    continue

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
            if (
                not recovering_persisted_response
                and background_binding is None
                and self._limits.max_run_model_calls is not None
                and active.model_calls_used >= self._limits.max_run_model_calls
            ):
                paused = pause_for_limit(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="run_model_call_limit",
                    outcome_state=paused,
                )

            # 020 前台 compaction 接线：archive 已注入、非 background
            # occurrence、非 persisted-response 恢复时先做只读规划；actionable
            # 才执行一个压缩批次并回到循环头，否则落回普通 build 路径。
            # 压缩批次与普通 provider 调用共享同一套 invocation 门禁：
            # 4 个批次上限、disclosure exact-receipt、input/output token
            # 限额；model-call 限额已在循环头统一检查，此处不重复。
            if (
                self._conversation_archive is not None
                and background_binding is None
                and not recovering_persisted_response
            ):
                usage = self._checkpoint_store.usage(current)
                try:
                    plan = self._context_manager.plan_compaction(
                        current.state,
                        action,
                        self._tool_runtime.definitions(),
                        active_checkpoint_bytes=usage.active_bytes,
                        soft_threshold_bytes=usage.soft_threshold_bytes,
                    )
                except ContextLimitError as error:
                    # F4：compaction preflight 的 ContextLimitError 与普通
                    # build 同型终态，不升级为 runtime_failure。
                    return self._finish_context_limit(
                        current, action, warnings, error
                    )
                if plan.actionable:
                    if compaction_batches >= 4:
                        paused = pause_for_limit(current.state)
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.LIMIT_REACHED,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.LIMIT_REACHED,
                            error_code="compaction_batch_limit",
                            outcome_state=paused,
                        )
                    try:
                        context = self._context_manager.build_compaction(
                            current.state, plan, current.token
                        )
                    except ContextLimitError as error:
                        # 同上：pack 构建超限与普通 build 同型，零副作用。
                        return self._finish_context_limit(
                            current, action, warnings, error
                        )
                    # 与普通 provider 分支共用同一许可判断；常规许可/最后一份
                    # 精确例外之外仍必须重新决定。
                    gate_now = self._run_time_factory()
                    gate_run_id = (
                        current.state.active_run.run_id
                        if current.state.active_run is not None
                        else f"compaction:{action.action_seq}"
                    )
                    current, disclosure_gate = self._provider_gate(
                        current,
                        context,
                        purpose="compaction",
                        now=gate_now,
                        run_id=gate_run_id,
                    )
                    if not disclosure_gate.admitted:
                        if disclosure_gate.request is None:
                            return self._finish(
                                current,
                                action,
                                status=RunStatus.FAILED_FATAL,
                                warnings=warnings,
                                event_kind=RuntimeEventKind.FAILED,
                                error_code="consent_scope_missing",
                                outcome_state=current.state,
                            )
                        paused = pause_for_provider_disclosure(
                            current.state, disclosure_gate.request
                        )
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
                    # compaction 也是一次真实模型尝试：必须与普通调用一样在
                    # 发送前持久化扣账。失败不退款，Resume 也不会重置。
                    compaction_source = current
                    try:
                        attempted = charge_provider_dispatch(
                            current.state,
                            disclosure_gate,
                            descriptor=self._provider_descriptor,
                            scope=context.consent_scope,
                            purpose="compaction",
                            run_id=gate_run_id,
                            now=self._run_time_factory(),
                        )
                    except ValueError:
                        # P4（2026-10-24）：扣次重算发现 gate 已陈旧；state
                        # 未被扣改，重新要求披露决策而非致命失败。
                        return self._pause_for_disclosure_recheck(
                            current,
                            action,
                            warnings,
                            context,
                            purpose="compaction",
                            run_id=gate_run_id,
                        )
                    current = self._save(
                        current,
                        record_foreground_model_attempt(
                            attempted,
                            input_tokens=context.budget.estimated_input_tokens,
                        ),
                    )
                    if (
                        disclosure_gate is not None
                        and disclosure_gate.reason == "grant_workspace_read"
                    ):
                        grant_now = attempted.provider_consent_grant
                        if grant_now is not None:
                            warnings.append(
                                workspace_read_dispatch_notice(
                                    grant_now,
                                    context.consent_scope,
                                )
                            )
                    # S6：校验后跨过到期点，transport 前最后重验；过期即重新
                    # 要求决策，不因已扣次继续发送。
                    expired = final_dispatch_expiry_check(
                        current.state,
                        disclosure_gate,
                        now=self._run_time_factory(),
                    )
                    if expired is not None:
                        return self._pause_for_disclosure_recheck(
                            current,
                            action,
                            warnings,
                            context,
                            purpose="compaction",
                            run_id=gate_run_id,
                        )
                    model_calls += 1
                    input_tokens += context.budget.estimated_input_tokens
                    try:
                        result = self._perform_compaction(
                            current,
                            plan,
                            context,
                            source_snapshot=compaction_source,
                        )
                    except ModelAttemptBudgetExhaustedError:
                        paused = pause_for_limit(current.state)
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.LIMIT_REACHED,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.LIMIT_REACHED,
                            error_code="model_attempt_budget_exhausted",
                            outcome_state=paused,
                        )
                    except RetryableProviderError as error:
                        # 压缩批次的 provider 失败与普通模型调用同语义：
                        # pause_for_retryable + FAILED_RETRYABLE，等待显式
                        # Resume；不隐式重试压缩提交，也不升级为 fatal。
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
                    except (CompactionResponseError, CompactionArchiveError) as error:
                        # summary 拒绝与 archive 不可用都发生在本批缩减 CAS 前。
                        # 保留最新 current（可能已含前一批缩减），释放 invocation
                        # owner，等待显式 Resume；不在这里隐式重试 Provider/archive。
                        paused = pause_for_retryable(current.state)
                        error_code = (
                            "compaction_response_invalid"
                            if isinstance(error, CompactionResponseError)
                            else "compaction_archive_unavailable"
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.FAILED_RETRYABLE,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.FAILED,
                            error_code=error_code,
                            message=str(error),
                            outcome_state=paused,
                        )
                    current = result.snapshot
                    output_tokens += result.output_tokens
                    compaction_batches += 1
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
                    continue

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
                return self._finish_context_limit(current, action, warnings, error)
            disclosure: ProviderDisclosureRequest | None = None
            disclosure_gate: ProviderDispatchGateV1 | None = None
            if not recovering_persisted_response:
                if background_binding is not None:
                    # 后台 occurrence 有独立的授权权威，不得借用交互会话 grant。
                    disclosure = self._required_disclosure(context)
                    if disclosure is not None and (
                        current.state.provider_disclosure_receipt is None
                        or current.state.provider_disclosure_receipt.request_digest
                        != disclosure.request_digest
                    ):
                        paused = pause_for_provider_disclosure(
                            current.state, disclosure
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.AWAITING_DISCLOSURE,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.DISCLOSURE_REQUESTED,
                            message="remote provider disclosure acknowledgement required",
                            outcome_state=paused,
                        )
                else:
                    current, disclosure_gate = self._provider_gate(
                        current,
                        context,
                        purpose="runtime_progress",
                        now=self._run_time_factory(),
                        run_id=active.run_id,
                    )
                    if not disclosure_gate.admitted:
                        if disclosure_gate.request is None:
                            return self._finish(
                                current,
                                action,
                                status=RunStatus.FAILED_FATAL,
                                warnings=warnings,
                                event_kind=RuntimeEventKind.FAILED,
                                error_code="consent_scope_missing",
                                outcome_state=current.state,
                            )
                        paused = pause_for_provider_disclosure(
                            current.state, disclosure_gate.request
                        )
                        return self._finish(
                            current,
                            action,
                            status=RunStatus.AWAITING_DISCLOSURE,
                            warnings=warnings,
                            event_kind=RuntimeEventKind.DISCLOSURE_REQUESTED,
                            message="remote provider disclosure acknowledgement required",
                            outcome_state=paused,
                        )
                    disclosure = (
                        disclosure_gate.request
                        if isinstance(
                            disclosure_gate.request, ProviderDisclosureRequest
                        )
                        else None
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
                else:
                    attempted = current.state
                    if disclosure_gate is not None:
                        # 许可扣次与 attempt record 必须在同一 durable
                        # transition 落盘；失败不退款，恢复也不再扣。
                        try:
                            attempted = charge_provider_dispatch(
                                attempted,
                                disclosure_gate,
                                descriptor=self._provider_descriptor,
                                scope=context.consent_scope,
                                purpose="runtime_progress",
                                run_id=active.run_id,
                                now=self._run_time_factory(),
                            )
                        except ValueError:
                            # P4（2026-10-24）：扣次重算发现 gate 已陈旧
                            #（跨过到期点等）。state 未被扣改，与 transport
                            # 前最后重验同路：重新要求披露决策，不致命。
                            return self._pause_for_disclosure_recheck(
                                current,
                                action,
                                warnings,
                                context,
                                purpose="runtime_progress",
                                run_id=active.run_id,
                            )
                    current = self._save(
                        current,
                        record_foreground_model_attempt(
                            attempted,
                            input_tokens=context.budget.estimated_input_tokens,
                        ),
                    )
                    if (
                        disclosure_gate is not None
                        and disclosure_gate.reason == "grant_workspace_read"
                    ):
                        # item 1：r 许可放行的派发逐次附带非阻断审计通知。
                        grant_now = attempted.provider_consent_grant
                        if grant_now is not None:
                            warnings.append(
                                workspace_read_dispatch_notice(
                                    grant_now,
                                    context.consent_scope,
                                )
                            )
                    if disclosure_gate is not None:
                        # S6：校验后跨过到期点，transport 前最后重验。
                        expired = final_dispatch_expiry_check(
                            current.state,
                            disclosure_gate,
                            now=self._run_time_factory(),
                        )
                        if expired is not None:
                            return self._pause_for_disclosure_recheck(
                                current,
                                action,
                                warnings,
                                context,
                                purpose="runtime_progress",
                                run_id=active.run_id,
                            )
            progress_reporter = None
            try:
                if not recovering_persisted_response:
                    progress_reporter = self._start_provider_progress(current)
                    response = self._provider.generate(
                        context,
                        delta_observer=self._delta_observer_for(current),
                    )
            except ModelAttemptBudgetExhaustedError:
                paused = pause_for_limit(current.state)
                return self._finish(
                    current,
                    action,
                    status=RunStatus.LIMIT_REACHED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.LIMIT_REACHED,
                    error_code="model_attempt_budget_exhausted",
                    outcome_state=paused,
                )
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
                if provider_code == "provider_stream_cancelled":
                    controlled = self._poll_control(action, current, warnings)
                    if controlled is not None:
                        return controlled
                    failed = fail_run(
                        current.state,
                        code="provider_stream_cancelled_without_control",
                        message="Provider stream stopped without a bound control request.",
                    )
                    return self._finish(
                        current,
                        action,
                        status=RunStatus.FAILED_FATAL,
                        warnings=warnings,
                        event_kind=RuntimeEventKind.FAILED,
                        error_code="provider_stream_cancelled_without_control",
                        outcome_state=failed,
                    )
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
                    "provider_stream_interrupted",
                    "provider_rate_limit",
                    "provider_unavailable",
                }:
                    provider_code = "provider_retryable"
                safely_retryable = provider_code in {
                    "provider_timeout",
                    "provider_transport",
                    "provider_unavailable",
                }
                if (
                    safely_retryable
                    and retryable_provider_retries
                    < self._limits.max_retryable_provider_retries
                ):
                    retryable_provider_retries += 1
                    current = self._save(
                        current,
                        append_policy_result(
                            current.state,
                            code="provider_transient_retry",
                            message=(
                                "A transient provider failure occurred before a usable "
                                "response. Runtime is retrying within the caller's bounded "
                                "attempt budget."
                            ),
                        ),
                    )
                    continue
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
            finally:
                if progress_reporter is not None:
                    self._stop_provider_progress(progress_reporter, current)

            retryable_provider_retries = 0
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
                completed = complete_run(
                    current.state,
                    message=control.question,
                    provider_continuation=response.provider_continuation,
                )
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
                completed = complete_run(
                    current.state,
                    message=control.text,
                    provider_continuation=response.provider_continuation,
                )
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
                        provider_continuation=response.provider_continuation,
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
                        # W1.5：与完成门复用同一交付缺口判断。admitted 证据全部
                        # 可推导不等于权威原文的明确交付对象已覆盖；缺口未闭合
                        # 时不得断言"证据已完整"并指示重发 completion_claim——
                        # 那会让服从指引的 claim 立即被完成门以同一缺口拒绝。
                        deliverable_gap = sorted(
                            authoritative_deliverable_file_paths(current.state)
                            - {
                                criterion.predicate.get("path")
                                for criterion in goal_frame.admitted_criteria
                                if criterion.mandatory
                                and criterion.oracle_kind
                                is EvidenceOracleKind.FILESYSTEM_DIGEST
                                and isinstance(
                                    criterion.predicate.get("path"), str
                                )
                            }
                        )
                        if deliverable_gap:
                            if no_progress.repair_exhausted(
                                (
                                    "blocked_claim_with_deliverable_gap",
                                    *deliverable_gap,
                                ),
                                allowance=self._limits.max_no_progress_replans,
                                observation_id=model_calls,
                            ):
                                return self._finish_no_progress(
                                    current,
                                    action,
                                    warnings,
                                    message=(
                                        "Provider repeated blocked claims while "
                                        "explicit deliverable files were still "
                                        "missing from admitted criteria."
                                    ),
                                )
                            no_progress_since_product_action = True
                            current = self._save(
                                current,
                                append_policy_result(
                                    current.state,
                                    code="blocked_claim_not_verified",
                                    message=(
                                        "The blocked_claim was not accepted: explicit "
                                        "user deliverable files are still outside the "
                                        "current admitted criteria: "
                                        + ", ".join(deliverable_gap)
                                        + ". Advance them through the normal approval "
                                        "and final read-back path, or produce a "
                                        "durable blocker for them, before reporting "
                                        "this Goal as blocked."
                                    ),
                                ),
                            )
                            continue
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
                                    "after reviewing the current authoritative user "
                                    "input and consumed corrections item by item: "
                                    "each requirement_coverage entry must state its "
                                    "requirement, cite its source facts, and bind "
                                    "the current admitted mandatory criteria, and "
                                    "criterion_evidence_refs must be copied "
                                    "exactly, element for element and in order, "
                                    "from the CURRENT trusted_goal block's "
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
                    stored = {
                        record.evidence_id: record
                        for record in current.state.evidence_records
                    }
                    # 新证据入库，被后续写入失效后重新导出的旧证据按 id 原位
                    # 刷新（R2-C：claim 被拒后继续写入并重新读回是可修复路径，
                    # 不能因陈旧缓存硬失败）。
                    pending_records = tuple(
                        record
                        for record in records
                        if stored.get(record.evidence_id) != record
                    )
                    if pending_records:
                        current = self._save(
                            current,
                            record_evidence(current.state, pending_records),
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
                completion_text = "\n".join(
                    block.text
                    for block in response.blocks
                    if isinstance(block, ModelTextBlock)
                ).strip()
                completion_message = (
                    completion_text
                    or "Goal completion verified by closed evidence oracles."
                )
                completed = complete_run(
                    current.state,
                    message=completion_message,
                    provider_continuation=response.provider_continuation,
                )
                return self._finish(
                    current,
                    action,
                    status=RunStatus.COMPLETED,
                    warnings=warnings,
                    event_kind=RuntimeEventKind.COMPLETED,
                    run_id=run_id,
                    message=completion_message,
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
                        provider_continuation=response.provider_continuation,
                    ),
                )
                tool_batch = _ToolBatchConvergence(failure_signatures=[])
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
            completed = complete_run(
                current.state,
                message=final_text,
                provider_continuation=response.provider_continuation,
            )
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
        # RC-03（2026-10-11）：apply_control_request 会清空 active_run；在 reducer
        # 前捕获本次 run 的实际用量，随终态记录与返回值保全。
        pre_control_active = state.active_run
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
            usage_active=pre_control_active,
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
            and not AgentRuntime._is_operator_fact(fact)
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
            if AgentRuntime._is_operator_fact(fact):
                continue
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
            if AgentRuntime._is_operator_fact(fact):
                continue
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
            if AgentRuntime._is_operator_fact(fact):
                continue
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
            and not AgentRuntime._is_operator_fact(fact)
            and fact.fact_id.startswith(prefix)
            and fact.content.get("code") == code
            for fact in state.facts
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
    def _tool_failure_signature(
        request_digest: str,
        result: ToolResult,
    ) -> tuple[str, ...]:
        return AgentRuntime._tool_failure_values_signature(
            request_digest,
            content=result.content,
            executed=result.executed,
            is_error=result.is_error,
            metadata=result.metadata,
        )

    @staticmethod
    def _tool_failure_values_signature(
        request_digest: str,
        *,
        content: object,
        executed: object,
        is_error: object,
        metadata: object,
    ) -> tuple[str, ...]:
        stable_metadata = metadata if isinstance(metadata, dict) else {}
        return (
            "known_tool_failure",
            request_digest,
            canonical_json_digest(
                {
                    "content": content,
                    "executed": executed,
                    "is_error": is_error,
                    "code": stable_metadata.get("code"),
                    "outcome": stable_metadata.get("outcome"),
                    "exit_code": stable_metadata.get("exit_code"),
                }
            ),
        )

    @staticmethod
    def _tool_batch_is_complete(active) -> bool:
        return active.batch_cursor + 1 == len(active.tool_calls)

    def _finalize_tool_batch_convergence(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        *,
        batch: _ToolBatchConvergence,
        no_progress: _NoProgressTracker,
        no_progress_since_product_action: bool,
        observation_id: int,
    ) -> tuple[LoadedSnapshot, bool, RunResult | None]:
        # Tool result 的 checkpoint/event 仍逐项完成；这里只在 final result 后
        # 对整个已接纳批次做一次收敛判断。
        if not batch.eligible or batch.has_success:
            no_progress.reset()
            return current, False, None
        if not batch.failure_signatures:
            raise RuntimeError("completed model tool batch has no classified result")

        signature = (
            batch.failure_signatures[0]
            if len(batch.failure_signatures) == 1
            else (
                "known_tool_failure_batch",
                canonical_json_digest(batch.failure_signatures),
            )
        )
        same_replan_opportunity = no_progress.same_replan_opportunity(observation_id)
        if no_progress.repair_exhausted(
            signature,
            allowance=self._limits.max_no_progress_replans,
            observation_id=observation_id,
        ):
            return (
                current,
                True,
                self._finish_no_progress(
                    current,
                    action,
                    warnings,
                    message=(
                        "The same tool batch kept returning known failures. The task is "
                        "paused with its recorded results preserved; adjust the request or "
                        "environment, then explicitly continue."
                    ),
                ),
            )

        should_feedback = batch.feedback is not None or (
            no_progress_since_product_action and not same_replan_opportunity
        )
        if should_feedback:
            current = self._save(
                current,
                append_policy_result(
                    current.state,
                    code="no_progress_replan_required",
                    message=(
                        batch.feedback
                        or "The completed tool batch returned known failures and no product "
                        "progress occurred. Re-read every ToolResult, choose a materially "
                        "different valid action, or send blocked_claim if no safe action can "
                        "advance the Goal."
                    ),
                ),
            )
        return current, True, None

    def _resumed_tool_batch_convergence(
        self,
        state: ConversationState,
    ) -> _ToolBatchConvergence:
        batch = _ToolBatchConvergence(failure_signatures=[])
        active = state.active_run
        if (
            active is None
            or active.invocation_origin is not InvocationOrigin.MODEL
            or active.phase is not ContinuationPhase.TOOL
            or active.batch_cursor == 0
        ):
            return batch

        expected_calls = tuple(
            (
                call.tool_call_id,
                call.name,
                canonical_json_digest(call.arguments),
            )
            for call in active.tool_calls
        )
        run_prefix = f"run:{active.run_id}:"
        batch_index: int | None = None
        for index in range(len(state.facts) - 1, -1, -1):
            fact = state.facts[index]
            if (
                fact.kind is not FactKind.TOOL_CALLS
                or not fact.fact_id.startswith(f"{run_prefix}tool-batch:")
            ):
                continue
            raw_calls = fact.content.get("calls")
            if not isinstance(raw_calls, list) or len(raw_calls) != len(expected_calls):
                continue
            actual_calls: list[tuple[str, str, str]] = []
            for raw_call in raw_calls:
                if not isinstance(raw_call, dict):
                    break
                call_id = raw_call.get("tool_call_id")
                name = raw_call.get("name")
                arguments = raw_call.get("arguments")
                if (
                    not isinstance(call_id, str)
                    or not isinstance(name, str)
                    or not isinstance(arguments, dict)
                ):
                    break
                actual_calls.append(
                    (call_id, name, canonical_json_digest(arguments))
                )
            if tuple(actual_calls) == expected_calls:
                batch_index = index
                break

        if batch_index is None:
            batch.eligible = False
            return batch

        prefix_results: list[ConversationFact] = []
        for fact in state.facts[batch_index + 1 :]:
            if fact.kind is FactKind.TOOL_RESULT:
                prefix_results.append(fact)
                if len(prefix_results) == active.batch_cursor:
                    break
        if len(prefix_results) != active.batch_cursor:
            batch.eligible = False
            return batch

        for call, fact in zip(
            active.tool_calls[: active.batch_cursor],
            prefix_results,
            strict=True,
        ):
            if fact.content.get("tool_call_id") != call.tool_call_id:
                batch.eligible = False
                return batch
            if not (
                fact.fact_id.startswith(f"{run_prefix}tool-result:")
                or fact.fact_id.startswith("action:")
            ):
                batch.eligible = False
                return batch
            if (
                fact.fact_id.startswith("action:")
                or fact.content.get("rejected") is True
                or fact.content.get("synthetic") is True
            ):
                batch.eligible = False
                continue
            if (
                fact.content.get("executed") is True
                and fact.content.get("is_error") is False
            ):
                batch.has_success = True
                continue
            request_digest = self._product_request_digest(call.name, call.arguments)
            text = fact.content.get("text")
            metadata = fact.content.get("metadata")
            if (
                fact.content.get("executed") is False
                and isinstance(metadata, dict)
                and metadata.get("code") == "duplicate_product_request"
            ):
                batch.failure_signatures.append(
                    ("duplicate_product_request", request_digest)
                )
                batch.feedback = (
                    text
                    if isinstance(text, str)
                    else self._duplicate_product_request_guidance(state, call)
                )
                continue
            batch.failure_signatures.append(
                self._tool_failure_values_signature(
                    request_digest,
                    content=text,
                    executed=fact.content.get("executed"),
                    is_error=fact.content.get("is_error"),
                    metadata=metadata,
                )
            )
        return batch

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

    def _successful_product_request_inventory(
        self,
        state: ConversationState,
    ) -> tuple[set[str], set[str], set[str]]:
        # S1-A（2026-10-09）：三个集合由同一 durable fact fold 重建——
        # ordinary（普通成功请求）、mutable_observation（ordinary 子集，沿用
        # 原文件/browser 可变观察失效语义）、native_validation（可信只读
        # native sandbox 验证成功；与 ordinary 不重叠，不先放 ordinary 再删）。
        # 参数级抑制查询 ordinary ∪ native_validation。已执行的
        # write/edit/mkdir、same-UID process，以及不能被严格分类证明只读的
        # 已执行 sandbox（含失败/超时/非零退出），使 native_validation 清空，
        # 这就是“检查→修改→同命令复测”的释放路径；A/B 两个可信验证可共存。
        # operator 请求不进入成功集合（不读取被隐去的参数），但其已执行
        # mutation 结果同样参与失效判断。每次调用都从 retained facts 全量折叠，
        # 不维护另一份 live 增量副本；summary 不作为执行凭据。
        state_changing_tools = frozenset(
            definition.name
            for definition in self._tool_runtime.definitions()
            if definition.side_effect is not SideEffectClass.READ_ONLY
        )
        active = state.active_run
        if active is None:
            return set(), set(), set()
        goal = state.goal
        workspace_digest = (
            goal.workspace_identity_digest if goal is not None else None
        )
        run_prefix = f"run:{active.run_id}:"
        request_by_call_id: dict[str, tuple[str | None, str]] = {}
        ordinary: set[str] = set()
        mutable_observation: set[str] = set()
        native_validation: set[str] = set()
        # W1（2026-10-12）：managed writer 在场集合，与 active_task_resources
        # 共用同一 receipt 形状解释（managed_process_receipts）；验证取得时
        # 在场即失格。跨 run 的 managed receipt 也参与追踪（与资源门一致）。
        active_writers: set[str] = set()
        for fact in state.facts:
            if fact.kind is FactKind.CONTEXT_SUMMARY:
                # RC-01/020（2026-10-11）：与证据判定共用同一保守边界——
                # summary 代表被裁剪掉的任意历史跨度，Runtime 无法再证明其中
                # 没有写入；早于它的成功请求不再抑制同参重试，否则压缩后
                # 「不能完成也不能显式重验」。晚于 summary 的新结果正常累积。
                #
                # P2-1（2026-10-13）：writer 在场状态不随 summary 清空——它是
                # durable resource ownership 事实（存活 writer 的 start
                # receipt 受压缩保护、保留在 facts 中），前向折叠在 summary
                # 处的值恰是 retained 前缀的折叠结果，与 evidence 侧
                # managed_writer_active_at 同一语义；清空会让 summary 之后取得
                # 的验证被错误计入 native_validation，而 evidence 侧拒绝它，
                # 同参重验又被该错误抑制挡住，两侧分叉。
                ordinary.clear()
                mutable_observation.clear()
                native_validation.clear()
                continue
            # W1（2026-10-12）：writer 在场追踪跨 run 生效（资源门看全序列），
            # 因此置于 run 前缀过滤之前；只解释 managed receipt 形状。
            for event, resource_ref in managed_process_receipts((fact,)):
                if event == "started":
                    active_writers.add(resource_ref)
                else:
                    active_writers.discard(resource_ref)
            if not fact.fact_id.startswith(run_prefix) and not (
                fact.fact_id.startswith("action:")
                and fact.kind is FactKind.TOOL_RESULT
                and fact.content.get("unknown_outcome") is True
            ):
                # RC-01（2026-10-11）：UNKNOWN 恢复事实不带 run 前缀
                # （action:N:recovery），不能被 run-prefix 过滤漏掉其失效含义；
                # 通过 tool_call_id 关联本 run 的调用清单参与折叠。
                continue
            if fact.kind is FactKind.TOOL_CALLS:
                raw_calls = fact.content.get("calls")
                if not isinstance(raw_calls, list):
                    continue
                operator_origin = (
                    fact.content.get("invocation_origin")
                    == InvocationOrigin.OPERATOR.value
                )
                for raw_call in raw_calls:
                    if not isinstance(raw_call, dict):
                        continue
                    call_id = raw_call.get("tool_call_id")
                    name = raw_call.get("name")
                    if not (isinstance(call_id, str) and isinstance(name, str)):
                        continue
                    if operator_origin:
                        # operator 参数被隐去：只留工具身份供失效判断，不记 digest。
                        request_by_call_id[call_id] = (None, name)
                        continue
                    arguments = raw_call.get("arguments")
                    if isinstance(arguments, dict):
                        request_by_call_id[call_id] = (
                            self._product_request_digest(name, arguments),
                            name,
                        )
                continue
            if fact.kind is not FactKind.TOOL_RESULT:
                continue
            call_id = fact.content.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in request_by_call_id:
                continue
            request_digest, tool_name = request_by_call_id[call_id]
            if fact.content.get("unknown_outcome") is True:
                # RC-01/RC-02（2026-10-11）：结果未知 → 保守失效，不授予新豁免。
                # 与证据判定共用同一谓词（统一证据与去重判断）；mark_failed 不豁免。
                if ClosedEvidenceRegistry._may_invalidate_workspace_validation(fact):
                    native_validation.clear()
                if tool_name in state_changing_tools:
                    ordinary.difference_update(mutable_observation)
                    mutable_observation.clear()
                continue
            if fact.content.get("executed") is not True:
                # executed=false 的拒绝不产生新豁免，也不构成失效。
                continue
            metadata = fact.content.get("metadata")
            metadata_dict = metadata if isinstance(metadata, dict) else None
            if tool_name in WORKSPACE_WRITE_TOOLS or tool_name in WRITABLE_PROCESS_TOOLS or (
                metadata_dict is not None and "process_receipt" in metadata_dict
            ):
                # 写入、可写 same-UID 进程启动与 same-UID process 的已执行结果
                # （成功/失败/超时）都可能已改写验证输入；先失效再记录本次成功。
                native_validation.clear()
            trusted_sandbox = False
            if metadata_dict is not None and (
                "sandbox_receipt" in metadata_dict
                or metadata_dict.get("sandbox_receipt_kind") == "native_sandbox_v1"
            ):
                trusted_sandbox = (
                    workspace_digest is not None
                    and trusted_readonly_native_sandbox_success(
                        fact,
                        workspace_identity_digest=workspace_digest,
                    )
                )
                if not trusted_sandbox:
                    native_validation.clear()
            if tool_name in state_changing_tools:
                ordinary.difference_update(mutable_observation)
                mutable_observation.clear()
            if (
                request_digest is not None
                and fact.content.get("is_error") is False
            ):
                if trusted_sandbox and active_writers:
                    # W1（2026-10-12）：验证取得时存在未确认关闭的 managed
                    # writer → 取得即失格：既不进 native_validation，也不
                    # 回落 ordinary（同参重验不被抑制，普通工具抑制不变）。
                    pass
                elif trusted_sandbox:
                    native_validation.add(request_digest)
                else:
                    ordinary.add(request_digest)
                    if tool_name in _MUTABLE_OBSERVATION_TOOLS:
                        mutable_observation.add(request_digest)
        return ordinary, mutable_observation, native_validation

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
        usage_active: ActiveRun | None = None,
    ) -> RunResult:
        state = outcome_state if outcome_state is not None else current.state
        # terminal reducer 会清空 active_run；用 reducer 前的 current 保留本次 run 用量。
        # RC-03（2026-10-11）：apply_control_request 先清空 active_run，两边都
        # None → 控制终态用量丢失；调用方在 reducer 前捕获并显式传入。
        usage_active = usage_active or current.state.active_run or state.active_run
        model_calls_used = (
            usage_active.model_calls_used if usage_active is not None else 0
        )
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
            # 2026-10-10：终态记录保留本次 run 的模型 usage（费用可观测性）。
            model_calls_used=(
                usage_active.model_calls_used if usage_active is not None else None
            ),
            input_tokens_used=(
                usage_active.input_tokens_used if usage_active is not None else None
            ),
            output_tokens_used=(
                usage_active.output_tokens_used if usage_active is not None else None
            ),
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
            model_calls_used=model_calls_used,
        )

    def _save(self, snapshot: LoadedSnapshot, state) -> LoadedSnapshot:
        try:
            return self._checkpoint_store.compare_and_swap(snapshot, state)
        except CheckpointCASConflictError:
            raise
        except Exception as error:
            # 调用者提供的 snapshot 就是本次失败写入前的显式最新 cursor。
            # 将它随错误上送，避免 run_turn 为恢复而偷偷再次 load store。
            raise _CheckpointWriteError(error, snapshot) from error

    def _finish_context_limit(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        error: ContextLimitError,
    ) -> RunResult:
        """ContextLimitError 的统一终态：普通 build 与 compaction preflight 共用。"""

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

    def _perform_compaction(
        self,
        current: LoadedSnapshot,
        plan: CompactionPlanV1,
        context: ContextPack,
        *,
        source_snapshot: LoadedSnapshot | None = None,
    ) -> _CompactionCallResult:
        """执行一次长会话压缩（020 内部成功路径）。

        调用方必须已持有 run_turn 取得的 conversation mutation lease，并
        传入 ``build_compaction`` 已构建好的专用 ContextPack。顺序固定：
        单次 provider 调用 → 严格解析 → reducer 换 summary →
        archive-before-CAS：先把完整原样 source 幂等写入 archive，成功后
        才由 ``self._save`` 执行本批缩减的 CAS。任何失败原样向上传播，
        本方法不捕获、不重试、不回滚。
        """
        if self._conversation_archive is None:
            raise RuntimeError("compaction requires a conversation archive")
        if not plan.actionable:
            raise RuntimeError("compaction requires an actionable plan")
        source = source_snapshot or current
        response = self._provider.generate(context)
        summary = parse_compaction_response(
            response,
            source_checkpoint_digest=source.token.removeprefix("sha256:"),
            source_fact_ids_digest=canonical_json_digest(list(plan.removable_fact_ids)),
        )
        reduced = apply_compaction_summary(
            current.state,
            summary,
            plan.removable_fact_ids,
            source_scope=context.consent_scope,
        )
        archive_compaction_source(
            self._conversation_archive,
            source,
            reduced,
            model_attempt_recorded=source_snapshot is not None,
        )
        saved = self._save(current, reduced)
        return _CompactionCallResult(
            snapshot=saved,
            input_tokens=context.budget.estimated_input_tokens,
            output_tokens=response.bounded_output_tokens,
            context=context,
        )

    def _is_effectful_tool(self, tool_name: str) -> bool:
        # 非 READ_ONLY 一律视为 effectful,未来新增的副作用类别默认 fail closed。
        return any(
            definition.name == tool_name and definition.side_effect is not SideEffectClass.READ_ONLY
            for definition in self._tool_runtime.definitions()
        )

    def _run_wall_budget_expired(self, started_at: str | None) -> bool:
        limit = self._limits.max_run_wall_seconds
        if limit is None:
            return False
        if started_at is None:
            raise RuntimeError("bounded run is missing its durable start time")
        now = datetime.fromisoformat(self._run_time_factory().replace("Z", "+00:00"))
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if now.tzinfo is None or started.tzinfo is None:
            raise RuntimeError("run wall budget requires zoned timestamps")
        elapsed = (now - started).total_seconds()
        # 系统时钟回拨时无法证明还有预算，按到界处理而不是获得额外执行时间。
        return elapsed < 0 or elapsed >= limit

    def _is_lease_governed_tool(self, tool_name: str) -> bool:
        # 015：LOCAL_SAME_UID_PROCESS 工具的 exact reuse 由 durable lease 治理（F2/R9，
        # 8 uses），不适用 read-only/source 的 product-request dedup——重复 exact command
        # 是合法的 lease reuse，不是 no-progress 重复。
        return any(
            definition.name == tool_name
            and definition.execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
            for definition in self._tool_runtime.definitions()
        )

    def _pause_for_disclosure_recheck(
        self,
        current: LoadedSnapshot,
        action: Action,
        warnings: list[str],
        context: ContextPack,
        *,
        purpose: str,
        run_id: str,
    ) -> RunResult:
        """S6 失效重验的统一出口：重算 gate，有新请求→暂停重问，无→致命。

        扣次被拒（gate 在扣次重算时已陈旧，2026-10-24 P4）与 transport 前
        最后重验过期同属一个窗口：合同出路都是零 provider 调用地重新要求
        披露决策；只有重算后连候选请求都不存在才按 consent_scope_missing
        致命收场。
        """
        refreshed = evaluate_provider_dispatch(
            state=current.state,
            descriptor=self._provider_descriptor,
            scope=context.consent_scope,
            purpose=purpose,
            run_id=run_id,
            now=self._run_time_factory(),
        )
        if refreshed.request is None:
            return self._finish(
                current,
                action,
                status=RunStatus.FAILED_FATAL,
                warnings=warnings,
                event_kind=RuntimeEventKind.FAILED,
                error_code="consent_scope_missing",
                outcome_state=current.state,
            )
        paused = pause_for_provider_disclosure(current.state, refreshed.request)
        return self._finish(
            current,
            action,
            status=RunStatus.AWAITING_DISCLOSURE,
            warnings=warnings,
            event_kind=RuntimeEventKind.DISCLOSURE_REQUESTED,
            message="remote provider disclosure acknowledgement required",
            outcome_state=paused,
        )

    def _provider_gate(
        self,
        current: LoadedSnapshot,
        context: ContextPack,
        *,
        purpose: str,
        now: str,
        run_id: str,
    ) -> tuple[LoadedSnapshot, ProviderDispatchGateV1]:
        """统一的只读许可判断；身份漂移先落 durable fence 再重新请求。"""

        gate = evaluate_provider_dispatch(
            state=current.state,
            descriptor=self._provider_descriptor,
            scope=context.consent_scope,
            now=now,
            purpose=purpose,
            run_id=run_id,
        )
        if gate.grant_invalidated:
            invalidated = invalidate_provider_consent(current.state)
            if invalidated != current.state:
                current = self._save(current, invalidated)
            # 旧 grant 已不适用于当前身份；重新生成不带旧 grant 的候选，
            # 避免把不可用许可继续显示成 s 或沿用旧额度。
            gate = evaluate_provider_dispatch(
                state=current.state,
                descriptor=self._provider_descriptor,
                scope=context.consent_scope,
                now=now,
                purpose=purpose,
                run_id=run_id,
            )
        return current, gate

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
        _, projections = project_tool_result_sources(
            AgentRuntime._non_operator_facts(state.facts),
            state,
        )
        return public_web_requirement_pending(state, projections)

    @staticmethod
    def _citable_source_refs_for(state: ConversationState) -> tuple[str, ...]:
        if state.goal is None:
            return ()
        _, projections = project_tool_result_sources(
            AgentRuntime._non_operator_facts(state.facts),
            state,
        )
        return citable_source_refs(projections)

    @staticmethod
    def _citable_citation_sources_for(
        state: ConversationState,
    ) -> tuple[tuple[str, str], ...]:
        if state.goal is None:
            return ()
        _, projections = project_tool_result_sources(
            AgentRuntime._non_operator_facts(state.facts),
            state,
        )
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
            if AgentRuntime._is_operator_fact(fact):
                continue
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
            if AgentRuntime._is_operator_fact(fact):
                continue
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

    def _delta_observer_for(self, current):  # noqa: ANN001
        """r19 小步 3:流式文本增量的窄观察实现(advisory)。

        直写 event_sink 绕过 invocation 事件缓冲,保证增量在生成期间到达
        界面;事件不携带权威状态语义——丢失、重复或乱序不改变 checkpoint、
        审批与执行顺序,最终显示可由权威结果校正。
        """
        state = current.state
        conversation_id = state.conversation_id
        run_id = state.active_run.run_id if state.active_run is not None else None
        revision = state.revision
        causation_id = f"model-delta:{run_id or conversation_id}:{revision}"
        sink = self._event_sink
        counter = itertools.count(start=1)

        class _TextDeltaObserver:
            def on_text_delta(self, text: str) -> None:
                event = RuntimeEvent(
                    event_id=(
                        f"event:model-delta:{conversation_id}:{revision}"
                        f":{next(counter)}"
                    ),
                    kind=RuntimeEventKind.MODEL_TEXT_DELTA,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    revision=revision,
                    causation_id=causation_id,
                    payload={"text": text},
                    advisory=True,
                )
                sink.emit(event)

            def cancellation_requested(self) -> bool:
                if (
                    self_control_inbox is None
                    or state.goal is None
                    or state.active_run is None
                    or state.active_run.owner_invocation_id is None
                ):
                    return False
                binding = ControlBinding(
                    conversation_id=state.conversation_id,
                    goal_id=state.goal.goal_id,
                    goal_revision=state.goal.revision,
                    invocation_id=state.active_run.owner_invocation_id,
                )
                return self_control_inbox.pending(binding)

        self_control_inbox = self._control_inbox
        return _TextDeltaObserver()

    def _start_provider_progress(
        self,
        current: LoadedSnapshot,
    ) -> _ProviderProgressReporter | None:
        """在非流式 provider 阻塞期间只发送 advisory 活性事件。"""

        if self._progress_event_sink is None:
            return None

        stop = threading.Event()
        started_at = time.monotonic()
        counter = itertools.count(start=1)
        next_sequence = counter.__next__
        self._emit_provider_progress_advisory(
            current,
            phase="provider_started",
            elapsed_seconds=0.0,
            sequence=next_sequence(),
        )

        def report_waiting() -> None:
            while not stop.wait(self._provider_progress_interval_seconds):
                self._emit_provider_progress_advisory(
                    current,
                    phase="provider_waiting",
                    elapsed_seconds=time.monotonic() - started_at,
                    sequence=next_sequence(),
                )

        thread = threading.Thread(
            target=report_waiting,
            name="first-agent-provider-progress",
            daemon=True,
        )
        thread.start()
        return _ProviderProgressReporter(stop, thread, started_at, next_sequence)

    def _stop_provider_progress(
        self,
        reporter: _ProviderProgressReporter,
        current: LoadedSnapshot,
    ) -> None:
        reporter.stop.set()
        reporter.thread.join(timeout=1.0)
        self._emit_provider_progress_advisory(
            current,
            phase="provider_finished",
            elapsed_seconds=time.monotonic() - reporter.started_at,
            sequence=reporter.next_sequence(),
        )

    def _emit_provider_progress_advisory(
        self,
        current: LoadedSnapshot,
        *,
        phase: str,
        elapsed_seconds: float,
        sequence: int,
    ) -> None:
        state = current.state
        active = state.active_run
        run_id = active.run_id if active is not None else None
        event = RuntimeEvent(
            event_id=(
                f"event:model-progress:{state.conversation_id}:{run_id}:"
                f"{state.revision}:{sequence}"
            ),
            kind=RuntimeEventKind.MODEL_PROGRESS,
            conversation_id=state.conversation_id,
            run_id=run_id,
            revision=state.revision,
            causation_id=f"provider:{run_id or state.conversation_id}",
            payload={
                "phase": phase,
                "elapsed_seconds": round(max(0.0, elapsed_seconds), 1),
            },
            advisory=True,
        )
        try:
            sink = self._progress_event_sink
            if sink is not None:
                sink.emit(event)
        except Exception:
            # advisory 失败不能改变 provider 调用或权威结果。
            return

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
    def _is_operator_fact(fact: ConversationFact) -> bool:
        return fact.content.get("invocation_origin") == InvocationOrigin.OPERATOR.value

    @staticmethod
    def _non_operator_facts(
        facts: tuple[ConversationFact, ...],
    ) -> tuple[ConversationFact, ...]:
        return tuple(fact for fact in facts if not AgentRuntime._is_operator_fact(fact))

    @staticmethod
    def _tool_result_fact(state, result: ToolResult) -> ConversationFact:
        active = state.active_run
        if active is None:
            raise RuntimeError("tool result requires an active run")
        content = {
            "tool_call_id": result.tool_call_id,
            "text": result.content,
            "is_error": result.is_error,
            "executed": result.executed,
            "metadata": result.metadata,
        }
        if result.result_source_proof is not None:
            # 该键只由 KernelToolRuntime 在成功执行后填充；record_tool_result
            # 会重新校验并转存为 state-owned proof，同时从 fact 中移除。
            content["runtime_source_proof"] = (
                result.result_source_proof.to_dict()
            )
        if active.invocation_origin is InvocationOrigin.OPERATOR:
            content["invocation_origin"] = InvocationOrigin.OPERATOR.value
        return ConversationFact(
            fact_id=f"run:{active.run_id}:tool-result:{result.tool_call_id}:{state.revision + 1}",
            kind=FactKind.TOOL_RESULT,
            content=content,
        )
