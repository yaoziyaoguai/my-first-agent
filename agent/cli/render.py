"""CLI 的唯一事件与结果渲染矩阵。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from agent.runtime.contracts import (
    ActiveRunStatus,
    ApprovalRequest,
    ConversationState,
    EgressClass,
    FactKind,
    GoalStatus,
    ProviderConsentGrantStatus,
    ProviderConsentGrantV1,
    ProviderDisclosureRequest,
    ProviderDisclosureRequestV2,
    RecoveryRequest,
    RunResult,
    RunStatus,
    RuntimeEvent,
    RuntimeEventKind,
)
from agent.runtime.evidence import INVALIDATED_BY_LATER_WORKSPACE_ACTIVITY
from agent.runtime.views import (
    SourceView,
    delivery_summary_message,
    pending_provider_disclosure_decision,
    project_goal_authorization_scopes,
    project_goal_target_reuse_unavailable,
    project_goal_view,
    project_obligation_rebind_disclosure,
    project_process_leases,
    project_visible_source_views,
    verification_scope_message,
)


class TerminalRenderer:
    """CLI 的唯一事件与结果渲染矩阵。

    S1-C（2026-10-09）：progress heartbeat 来自 provider-progress 线程，与
    delta/权威结果并发到达；对去重表、流式身份与一次输出使用窄锁，避免乱序
    覆盖。锁内不调用 Runtime/provider。
    """

    def __init__(
        self,
        write_fn: Callable[[str], None] = print,
        *,
        delta_write_fn: Callable[[str], None] | None = None,
        credential_env: str | None = None,
    ) -> None:
        self._write = write_fn
        self._delta_write = delta_write_fn
        self._credential_env = credential_env
        self._seen_event_ids: set[str] = set()
        # r19 小步 3:已流式呈现的回答文本;与最终权威 message 完全一致时
        # 不再重复打印(显示可由权威结果校正,而不是双份输出)。
        self._streamed_answer = ""
        self._stream_identity: tuple[str, str | None, int, str] | None = None
        self._terminal_hints: set[tuple[str, int, str]] = set()
        # r12：失效重跑提示只对每个 (goal, revision) 打一次。
        self._rerun_hint_keys: set[tuple[str, int]] = set()
        # S1-C：progress 线程与 REPL 主线程并发的窄锁。
        self._lock = threading.Lock()

    def emit(self, event: RuntimeEvent) -> None:
        with self._lock:
            if event.event_id in self._seen_event_ids:
                return
            self._seen_event_ids.add(event.event_id)
            if event.kind is RuntimeEventKind.MODEL_TEXT_DELTA:
                text = str(event.payload.get("text", ""))
                if not text:
                    return
                stream_identity = (
                    event.conversation_id,
                    event.run_id,
                    event.revision,
                    event.causation_id,
                )
                if stream_identity != self._stream_identity:
                    self._stream_identity = stream_identity
                    self._streamed_answer = ""
                self._streamed_answer += text
                display_text = terminal_text(text, allow_newlines=True)
                if self._delta_write is not None:
                    self._delta_write(display_text)
                else:
                    self._write(display_text)
                return
            message = self._event_message(event)
            if message is not None:
                self._write(message)

    def render_result(self, result: RunResult) -> None:
        with self._lock:
            self._render_result_locked(result)

    def _render_result_locked(self, result: RunResult) -> None:
        message = self._result_message(result)
        # Renderer 由整个 REPL 复用，但流式原文只属于刚结束的这次 run_turn。
        # 先完成本轮权威结果比较，再清空，避免下一轮回答与旧文本拼接。
        self._streamed_answer = ""
        self._stream_identity = None
        if message is not None:
            self._write(terminal_text(message, allow_newlines=True))
        goal_view = project_goal_view(result.state)
        rerun_note = self._invalidation_rerun_note(result.state)
        if goal_view.status == GoalStatus.VERIFIED_DONE.value:
            self._write(
                terminal_text(
                    delivery_summary_message(goal_view),
                    allow_newlines=True,
                )
            )
            if (
                rerun_note is not None
                and goal_view.goal_id is not None
                and goal_view.goal_revision is not None
                and (goal_view.goal_id, goal_view.goal_revision)
                not in self._rerun_hint_keys
            ):
                self._rerun_hint_keys.add(
                    (goal_view.goal_id, goal_view.goal_revision)
                )
                self._write(rerun_note)
        sources = goal_view.sources
        if sources:
            self._write(self._sources_message(sources))
        if goal_view.status == GoalStatus.VERIFIED_DONE.value and goal_view.verification_scope:
            self._write(
                terminal_text(
                    self._verification_scope_message(goal_view.verification_scope),
                    allow_newlines=True,
                )
            )
        if (
            goal_view.goal_id is not None
            and goal_view.goal_revision is not None
            and goal_view.status in {GoalStatus.VERIFIED_DONE.value, GoalStatus.CANCELLED.value}
        ):
            terminal_key = (
                goal_view.goal_id,
                goal_view.goal_revision,
                goal_view.status,
            )
            if terminal_key not in self._terminal_hints:
                self._terminal_hints.add(terminal_key)
                self._write("Task is closed. Use /new to start another task in this workspace.")
        for warning in result.delivery_warnings:
            self._write(f"Warning: {terminal_text(warning)}")

    def render_pending(self, state: ConversationState) -> None:
        """每次输入前从 authoritative state 只读投影 exact durable decision；
        不暴露内部 request identity。
        """

        # B（2026-10-18）：活跃 AWAITING_DISCLOSURE 与 /pause→/resume 恢复形状
        # （active=None、Goal=GOAL_READY）共用 views 的同一只读判定；已 receipt
        # 的形状不是 answerable pending，不渲染 [y/N]。Goal 仍 PAUSED 时不升
        # ——先 /resume。
        if pending_provider_disclosure_decision(state):
            request = state.provider_disclosure_request
            assert request is not None
            self._write(
                self._disclosure_message(
                    request=request,
                    grant=state.provider_consent_grant,
                )
            )
            return
        active = state.active_run
        if active is None:
            return
        if active.status is ActiveRunStatus.AWAITING_APPROVAL and isinstance(
            active.pending_request, ApprovalRequest
        ):
            request = active.pending_request
            requirement = request.artifact_confirmation_requirement
            self._write(
                self._approval_message(
                    tool_name=request.tool_name or "unknown",
                    risk=request.risk or "unknown",
                    side_effect=request.side_effect or "unknown",
                    preview=request.preview,
                    artifact_path=(requirement.artifact_path if requirement is not None else None),
                    authorization_scopes=project_goal_authorization_scopes(state),
                    goal_scope_unavailable=project_goal_target_reuse_unavailable(state),
                    obligation_rebind_disclosure=project_obligation_rebind_disclosure(state),
                )
            )
            return
        if active.status is ActiveRunStatus.AWAITING_RECOVERY and isinstance(
            active.pending_request, RecoveryRequest
        ):
            self._write(
                self._recovery_message(
                    active.pending_request.summary,
                    observation_unknown=(
                        active.executing_intent is not None
                        and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
                    ),
                )
            )
            return
        if active.status is ActiveRunStatus.PAUSED_LIMIT:
            # r14（2026-10-24 裁决 A′）：暂停原因随 checkpoint 持久化在
            # last_safe_result.error_code——重启后的 pending 提示必须沿用
            # 同会话的正确出路（预算耗尽的 /resume 是误导循环）。
            self._write(
                self._result_message_for_limit(
                    state.last_safe_result.error_code
                    if state.last_safe_result is not None
                    else None
                )
            )
        elif active.status is ActiveRunStatus.PAUSED_RETRYABLE:
            self._write(
                self._result_message_for_retryable(
                    state.last_safe_result.error_code
                    if state.last_safe_result is not None
                    else None
                )
            )

    def render_working(self) -> None:
        """在同步 Runtime 调用前确认输入已接收，不猜测内部阶段或进度。"""

        self._write("Working...")

    @staticmethod
    def _verification_scope_message(scopes: tuple[str, ...]) -> str:
        return verification_scope_message(scopes)

    def render_sources(self, state: ConversationState, *, advanced: bool = False) -> None:
        sources = project_visible_source_views(state, advanced=advanced)
        if not sources:
            self._write("No sources recorded for the current answer or task.")
            return
        self._write(self._sources_message(sources, advanced=advanced))

    def render_leases(self, state: ConversationState, *, advanced: bool = False) -> None:
        """F5/R11：active process authority lease 的 readable 摘要（默认隐藏 digest）。"""

        leases = project_process_leases(state, advanced=advanced)
        if not leases:
            self._write("No active process lease.")
            return
        lines = ["Active process leases:"]
        for index, lease in enumerate(leases):
            lines.append(
                f"[{index}] {lease.readable_command} · profile={lease.resource_profile} "
                f"· uses left={lease.remaining_uses} "
                f"· expires={lease.expires_at}"
                + (f" · id={lease.lease_id} · digest={lease.lease_digest}" if advanced else "")
            )
        lines.append("Revoke with /revoke <lease_id> or /revoke all (ids via --advanced).")
        self._write("\n".join(lines))

    @staticmethod
    def _invalidation_rerun_note(state: ConversationState) -> str | None:
        """r12（2026-10-24）：验证被后续 workspace 变更失效过、且最终验证通过
        （仅 VERIFIED_DONE 分支调用）时，向用户明示发生过失效重跑——否则
        「写→验证→再写→重验」在终端上完全不可见。事实源是 loop 落盘的
        completion_not_verified policy 结果；无该事实的普通完成不显示。
        """
        invalidated = any(
            fact.kind is FactKind.POLICY_RESULT
            and fact.content.get("code") == "completion_not_verified"
            and INVALIDATED_BY_LATER_WORKSPACE_ACTIVITY
            in str(fact.content.get("text", ""))
            for fact in state.facts
        )
        if not invalidated:
            return None
        return (
            "Note: a previous validation was invalidated by later workspace "
            "changes and re-run before this completion."
        )

    @staticmethod
    def _event_message(event: RuntimeEvent) -> str | None:
        # pending 类事件只是 advisory：可操作提示的唯一权威是每次输入前由
        # authoritative state snapshot 渲染的 render_pending，避免双权威与
        # event 丢失/延迟/重排影响正确提示。warning/informational 仍保留。
        payload = event.payload
        if event.kind in {
            RuntimeEventKind.APPROVAL_REQUESTED,
            RuntimeEventKind.RECOVERY_REQUESTED,
            RuntimeEventKind.DISCLOSURE_REQUESTED,
        }:
            return None
        if event.kind is RuntimeEventKind.LIMIT_REACHED:
            # RunResult 带 authoritative state，可投影准确 blocker/进展；事件本身不重复刷屏。
            return None
        if event.kind is RuntimeEventKind.WARNING:
            return f"Warning: {terminal_text(payload.get('message', 'runtime warning'))}"
        if (
            event.kind is RuntimeEventKind.MODEL_PROGRESS
            and payload.get("phase") == "provider_waiting"
        ):
            elapsed = payload.get("elapsed_seconds", 0)
            return f"Model is still working ({terminal_text(elapsed)}s elapsed)..."
        if event.kind in {
            RuntimeEventKind.MODEL_PROGRESS,
            RuntimeEventKind.TOOL_REQUESTED,
            RuntimeEventKind.TOOL_RESULT,
        }:
            return None
        return None

    def _result_message(self, result: RunResult) -> str | None:
        if result.status is RunStatus.COMPLETED:
            if result.message and result.message == self._streamed_answer:
                # 流式已逐字呈现同一文本;不重复打印(权威校正留给不一致时)。
                return None
            return result.message
        if result.status is RunStatus.AWAITING_APPROVAL:
            return None
        if result.status is RunStatus.AWAITING_RECOVERY:
            return None
        if result.status is RunStatus.AWAITING_DISCLOSURE:
            return None
        if result.status is RunStatus.CANCELLED:
            if result.error_code == "approval_declined" and result.message:
                return terminal_text(result.message, allow_newlines=True)
            return "Run cancelled."
        if result.status is RunStatus.LIMIT_REACHED:
            if result.error_code == "no_progress":
                view = project_goal_view(result.state)
                lines = ["Task paused because the same next step repeated with no new evidence."]
                if view.user_outcome:
                    lines.append(f"Goal remains incomplete: {terminal_text(view.user_outcome)}")
                if view.progress_summary:
                    lines.append(f"Last verified progress: {view.progress_summary}")
                lines.append(
                    "No authority was granted implicitly; any required operation still "
                    "needs its normal approval before it can run."
                )
                lines.append("Run /resume to try a new approach or /cancel.")
                return "\n".join(lines)
            return TerminalRenderer._result_message_for_limit(result.error_code)
        if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
            return "Conversation capacity reached. Start a new conversation."
        if result.status is RunStatus.FAILED_RETRYABLE:
            return TerminalRenderer._result_message_for_retryable(result.error_code)
        if result.status is RunStatus.FAILED_FATAL:
            if result.error_code == "provider_auth_error":
                if self._credential_env:
                    return (
                        "Provider authentication failed. Check the credential "
                        f"environment variable {terminal_text(self._credential_env)} "
                        "in this shell, then run first-agent again."
                    )
                return (
                    "Provider authentication failed. Check the configured credential "
                    "and run first-agent again."
                )
            if result.error_code in {"invalid_provider_response", "provider_protocol_error"}:
                return (
                    "The provider response was incompatible. Check the configured model "
                    "and endpoint, then run first-agent again."
                )
            base = f"Run failed: {result.error_code or 'fatal_error'}"
            if result.message:
                # 016 真实 E3(第 19/24 轮 J8):runtime_failure 的异常细节只在
                # RunResult.message 里;只打 error_code 会丢失定诊证据(REPL 以
                # 退出码 1 结束且无 traceback)。摘要压平空白并截断;凭据按设计
                # 从不进入异常消息,E3 的 secret-free 扫描仍是兜底。
                summary = " ".join(result.message.split())[:240]
                return f"{base} ({summary})"
            return base
        if result.status is RunStatus.CONFLICT:
            # 2026-10-24 P3：CONFLICT 不是同一种失败。恢复边界的状态拒绝与
            # 另一进程持锁有真实出路，照实指明；其余（CAS 失配、event 重入
            # 等）保持 fail-closed 的重启指引，由调用方以退出码 2 结束会话。
            if result.error_code == "unknown_effect_recovery_required":
                # LOW-2（2026-10-24 审计）：不同恢复子形接受的答复不同
                #（工具结果 success/failed/stop；公共观察 continue/stop），
                # 由下方重印的 pending 提示给出权威选项，这里只指路。
                return (
                    "That command is not available while an operation outcome is "
                    "unclassified.\n"
                    "Answer the pending recovery prompt below to resolve it first."
                )
            if result.error_code == "conversation_busy":
                return (
                    "Another process is using this conversation; it must finish or "
                    "exit before commands here can run."
                )
            return "State conflict: restart or reload this CLI before continuing."
        return None

    @staticmethod
    def _approval_message(
        *,
        tool_name: object,
        risk: object,
        side_effect: object,
        preview: object,
        artifact_path: str | None = None,
        authorization_scopes: tuple[str | None, str | None] = (None, None),
        goal_scope_unavailable: bool = False,
        obligation_rebind_disclosure: str | None = None,
    ) -> str:
        lines = [
            "Approval required",
            f"tool: {terminal_text(tool_name)}",
            f"risk/effect: {terminal_text(risk)}/{terminal_text(side_effect)}",
            f"preview: {terminal_text(preview, allow_newlines=True)}",
        ]
        if artifact_path is None:
            lines.append("Execute this operation? [y/N]")
        else:
            lines.append(
                f"This command may generate {terminal_text(artifact_path)}. "
                "Approve generation now? [y/N] The generated file is not confirmed yet; "
                "First Agent must show its current content for a separate confirmation."
            )
        # S2：f/d 就是既有 /approve-goal-target、/approve-goal-directory 的当前
        # 提示内快捷方式；只展示 Runtime 当前确实可铸的范围，不猜父目录。
        file_scope, directory_scope = authorization_scopes
        if artifact_path is None and (file_scope is not None or directory_scope is not None):
            # S2：保留原有 [y/N] 与“yes 只批准这一笔”的含义，再增加 f/d
            # 两个显式复用选项；不适用时不出现，也不猜父目录。问句行已由
            # 上面的 artifact 分支给出，这里只追加选项，不再重复问句。
            lines.append("Choose one:")
            lines.append("  y  This operation only")
            if file_scope is not None:
                lines.append(
                    f"  f  This file / this task / {terminal_text(tool_name)} — up to "
                    "16 uses, 60 minutes "
                    f"({terminal_text(file_scope)}; /approve-goal-target)"
                )
            if directory_scope is not None:
                lines.append(
                    f"  d  Declared task directory {terminal_text(directory_scope)} / "
                    f"{terminal_text(tool_name)} — up to 16 uses, 60 minutes "
                    "(/approve-goal-directory)"
                )
            lines.append("  n  Reject")
            lines.append("yes approves only this one operation.")
            lines.append(
                "Task changes or closure end the reusable permission. "
                "Revoke: /revoke-goal-target"
            )
        elif artifact_path is None and goal_scope_unavailable:
            # E1-A（2026-10-16）：spec 驱动 Goal 的 targets 是散文时，写入复用
            # 授权静默不适用（实测 0/17）；如实说明，避免"已授权"误读。
            lines.append(
                "No reusable Goal scope for this write: its path is not covered by "
                "the current task targets. Approving here covers only this one "
                "operation; later writes will each require approval again."
            )
        if obligation_rebind_disclosure is not None:
            # P2（对抗审查 2026-10-18）：批准=执行这一笔；若本次批准会同时把
            # 一条已失败的验证义务重绑定到这条命令，必须在批准前如实披露。
            lines.append(terminal_text(obligation_rebind_disclosure))
        return "\n".join(lines)

    @staticmethod
    def _recovery_message(
        summary: object,
        *,
        observation_unknown: bool = False,
    ) -> str:
        if observation_unknown:
            return (
                f"Unknown public observation: {terminal_text(summary)}\n"
                "Reply with 'continue' to record no evidence and proceed, or 'stop'. "
                "The request will not retry automatically."
            )
        return (
            f"Unknown tool outcome: {terminal_text(summary)}\n"
            "Reply with 'success', 'failed', or 'stop'."
        )

    @staticmethod
    def _disclosure_message(
        *,
        request: ProviderDisclosureRequest | ProviderDisclosureRequestV2,
        grant: ProviderConsentGrantV1 | None,
    ) -> str:
        data_summary = ", ".join(request.data_classes)
        if isinstance(request, ProviderDisclosureRequest):
            # Legacy request/receipt 语义保持原样，包括旧测试与旧 checkpoint。
            return (
                "Remote provider disclosure required\n"
                f"destination: {terminal_text(request.canonical_destination)}\n"
                f"model: {terminal_text(request.model)}\n"
                f"data: {terminal_text(data_summary)}\n"
                "Allow this information to be sent? [y/N]"
            )

        lines = [
            "Remote provider disclosure required",
            f"destination: {terminal_text(request.canonical_destination)}",
            f"model: {terminal_text(request.model)}",
            f"workspace: {terminal_text(request.workspace_identity_digest)}",
            f"data: {terminal_text(data_summary)}",
        ]
        if request.sources:
            lines.append("new or changed sources:")
            for source in request.sources:
                reuse = (
                    "same source can reuse the current consent"
                    if source.reusable
                    else "this pending content only"
                )
                lines.append(
                    f"- {terminal_text(source.label)} "
                    f"({terminal_text(source.data_class)}; {reuse})"
                )
        lines.append("  y  Approve the exact scope shown above")
        if request.grant_eligible:
            lines.append(
                "  s  Allow routine conversation data in this conversation — "
                "up to 32 model sends, expires in 60 minutes"
            )
        else:
            lines.append(
                "  s  unavailable — this request includes a new or unverified source"
            )
        lines.append("  n  Do not send")
        lines.append("Enter: do not send")
        if request.grant_eligible:
            lines.append(
                "Routine scope: your messages, conversation/task records, system "
                "policy, listed tool/control definitions, and summaries with verified "
                "covered sources. Tool outputs and other new sources are disclosed "
                "separately."
            )
        if isinstance(grant, ProviderConsentGrantV1):
            reason = TerminalRenderer._consent_unavailable_reason(grant)
            if reason is not None:
                lines.append(
                    f"Previous provider permission unavailable: {reason}. "
                    "Choose s to start a new permission."
                )
            else:
                # 决策队列 1（2026-10-24 裁决 C）：逐次披露保留，但活动许可
                # 在场时明示剩余额度与到期——读/验证类新源反复触发披露时，
                # 用户能看到常规许可还剩多少、这次为何仍要单独批准。
                quota = (
                    f"Active routine permission: "
                    f"{grant.max_uses - grant.uses_consumed} of "
                    f"{grant.max_uses} model sends left, "
                    f"expires {terminal_text(grant.expires_at)}."
                )
                if any(not source.reusable for source in request.sources):
                    quota += (
                        " Sources marked 'this pending content only' are "
                        "not covered by it."
                    )
                lines.append(quota)
        lines.append("Revoke: /revoke-provider-consent")
        return "\n".join(lines)

    @staticmethod
    def _consent_unavailable_reason(grant: ProviderConsentGrantV1) -> str | None:
        if grant.status is ProviderConsentGrantStatus.REVOKED:
            return "revoked"
        if grant.status is ProviderConsentGrantStatus.INVALIDATED:
            return "invalidated by a provider or workspace change"
        if grant.uses_consumed >= grant.max_uses:
            return "all 32 model sends used"
        try:
            expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return "expiry time is invalid"
        if datetime.now(UTC) >= expires:
            return f"expired at {grant.expires_at}"
        return None

    def render_provider_consent(self, state: ConversationState) -> None:
        """授予/撤销后的短确认；不重复整段审批，也不声称可撤回已发请求。"""

        grant = state.provider_consent_grant
        if grant is None:
            self._write("No provider consent is recorded for this conversation.")
            return
        if grant.status is ProviderConsentGrantStatus.REVOKED:
            self._write(
                "Provider consent revoked. New provider sends require a new decision."
            )
            return
        left = max(grant.max_uses - grant.uses_consumed, 0)
        self._write(
            f"Provider consent active: routine conversation data, {left} of "
            f"{grant.max_uses} model sends left, expires at {terminal_text(grant.expires_at)}. "
            "Revoke: /revoke-provider-consent"
        )

    @staticmethod
    def _result_message_for_limit(error_code: str | None = None) -> str:
        # E1-A 真实旅程（2026-10-16）：累计 model-attempt 预算耗尽后的 /resume
        # 会在派发前再次被拒，通用 "Run /resume to continue" 会形成误导循环。
        # 只有该原因需要指明真正的继续路径（同 ledger 提高 --max-model-attempts）。
        if error_code == "model_attempt_budget_exhausted":
            return (
                "Task paused: the model request budget on this ledger is exhausted. "
                "/resume cannot send new model requests under the current limit; "
                "restart with a higher --max-model-attempts on the same "
                "--transport-audit-ledger to continue this task, or /cancel."
            )
        return "Task paused at a safe execution limit. Run /resume to continue or /cancel."

    @staticmethod
    def _result_message_for_retryable(error_code: str | None = None) -> str:
        if error_code == "provider_timeout":
            return "The provider timed out. Run /resume to retry or /cancel."
        if error_code == "provider_transport":
            return "The provider could not be reached. Run /resume to retry or /cancel."
        if error_code == "provider_rate_limit":
            return "The provider rate limit was reached. Run /resume later or /cancel."
        if error_code == "provider_unavailable":
            return "The provider is temporarily unavailable. Run /resume later or /cancel."
        return "The provider failed transiently. Run /resume to retry or /cancel."

    @staticmethod
    def _sources_message(sources: tuple[SourceView, ...], *, advanced: bool = False) -> str:
        lines = ["Sources:"]
        for source in sources:
            detail = (
                f"{source.source_kind} · {source.title} · {source.locator} · "
                f"{source.observed_at} · {source.status}"
            )
            if source.failure_code is not None:
                detail = f"{detail} ({source.failure_code})"
            if advanced and source.source_ref is not None:
                detail = f"{detail} · {source.source_ref}"
            lines.append(f"- {terminal_text(detail)}")
        return "\n".join(lines)


def terminal_text(value: object, *, allow_newlines: bool = False) -> str:
    text = str(value)
    return "".join(
        character
        if character.isprintable() or (allow_newlines and character == "\n")
        else f"\\u{ord(character):04x}"
        for character in text
    )
