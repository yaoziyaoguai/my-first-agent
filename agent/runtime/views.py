"""从 authoritative state 生成所有 surface 共用的只读 Goal 投影。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent.runtime.contracts import (
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalRequest,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    EgressClass,
    EvidenceOracleKind,
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
    targets: tuple[str, ...]
    progress_summary: str | None
    next_step: str | None
    blocker: str | None
    safe_attempts: tuple[str, ...]
    resume_condition: str | None
    criteria_total: int
    criteria_verified: int
    verification_scope: tuple[str, ...]
    durable_authorities_closed: bool
    legal_actions: tuple[str, ...]
    sources: tuple[SourceView, ...]


@dataclass(frozen=True, slots=True)
class BackgroundRecoveryView:
    automation_id: str
    automation_revision: int
    occurrence_id: str
    checkpoint_identity_digest: str
    goal: GoalView


def verification_scope_message(scopes: tuple[str, ...]) -> str:
    """把可信 evidence scope 转成所有交互面一致的有界声明。"""

    return (
        "Evidence scope: "
        + "; ".join(scopes)
        + ". This proves only the listed checks; it does not independently establish "
        "numerical or semantic correctness beyond them."
    )


def delivery_summary_message(view: GoalView) -> str:
    """从终态生成不依赖模型自述的最小交付摘要。"""

    if view.status != GoalStatus.VERIFIED_DONE.value or view.user_outcome is None:
        raise ValueError("delivery summary requires a verified Goal")
    targets = ", ".join(view.targets) if view.targets else "no declared file target"
    authority_status = "closed" if view.durable_authorities_closed else "still open"
    return (
        f"Verified delivery: {view.user_outcome}\n"
        f"Targets: {targets}\n"
        f"Required evidence: {view.criteria_verified}/{view.criteria_total} passed\n"
        f"Durable task permissions: {authority_status}.\n"
        "User acceptance: not established by these evidence checks."
    )


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


def pending_provider_disclosure_decision(state: ConversationState) -> bool:
    """B（2026-10-18）：pending provider 外发确认的唯一只读判定。

    活跃 AWAITING_DISCLOSURE 与 /pause→/resume 后的孤儿形状
    （active=None、Goal=GOAL_READY）在 request 非空且 receipt=None 时
    是同一个 answerable pending 决策；render_pending 与 CLI 的
    y/n/空回车路由共用本判定，Runtime 仍独立校验 action 合法性。
    只读，不推进状态。
    """

    if state.provider_disclosure_request is None:
        return False
    if state.provider_disclosure_receipt is not None:
        return False
    active = state.active_run
    if active is not None:
        return active.status is ActiveRunStatus.AWAITING_DISCLOSURE
    goal = state.goal
    return goal is not None and goal.status is GoalStatus.GOAL_READY


def project_goal_authorization_scopes(
    state: ConversationState,
) -> tuple[str | None, str | None]:
    """R4：当前 pending 文件审批的 (精确文件 scope, 目录 scope) 纯投影。

    与 Runtime 铸授权共用 agent.runtime.state 的同一 scope 判定，None 表示
    对应无参数短命令不适用；不得触发 Runtime、Provider、Tool 或持久化。
    """

    from agent.runtime.state import _goal_target_authorization_scope

    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.AWAITING_APPROVAL
        or not isinstance(active.pending_request, ApprovalRequest)
        or not active.tool_calls
        or active.batch_cursor >= len(active.tool_calls)
    ):
        return (None, None)
    pending = active.pending_request
    return (
        _goal_target_authorization_scope(state, pending, active, directory=False),
        _goal_target_authorization_scope(state, pending, active, directory=True),
    )


def project_goal_target_reuse_unavailable(state: ConversationState) -> bool:
    """目标写入审批的复用透明度纯投影（与 R4 共用同一 scope 判定）。

    spec 驱动 Goal 的 targets 常为散文，write_file/edit_file 不在其中时
    复用授权静默不适用（E1-A 实测 0/17）；True 表示"Goal 存在、本次是
    目标写入、但没有任何可复用 scope"，审批提示据此如实说明，不改语义。
    """

    if state.goal is None:
        return False
    file_scope, directory_scope = project_goal_authorization_scopes(state)
    if file_scope is not None or directory_scope is not None:
        return False
    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.AWAITING_APPROVAL
        or not isinstance(active.pending_request, ApprovalRequest)
    ):
        return False
    return active.pending_request.tool_name in {"write_file", "edit_file"}


def project_obligation_rebind_disclosure(state: ConversationState) -> str | None:
    """发现 3 的审批透明度纯投影：本次批准是否会重绑定一条失败的验证义务。

    批准语义是「执行这一笔操作」；重绑定会改写 admitted 义务的 pinned 命令。
    对抗审查 2026-10-18 指出该改写此前对用户不可见。返回 None 表示不会重绑定。
    与 Runtime 共用同一资格判定，不触发 Runtime/Provider/Tool/持久化。
    """

    from agent.runtime.state import _rebindable_failed_process_obligation

    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.AWAITING_APPROVAL
        or not isinstance(active.pending_request, ApprovalRequest)
        or active.pending_request.tool_name != "local_process"
        or not active.tool_calls
        or active.batch_cursor >= len(active.tool_calls)
    ):
        return None
    call = active.tool_calls[active.batch_cursor]
    arguments = call.arguments if isinstance(call.arguments, dict) else {}
    candidate = active.pending_request.process_authority_candidate
    criterion = _rebindable_failed_process_obligation(
        state, arguments, candidate=candidate
    )
    if criterion is None:
        return None
    new_text = (
        candidate.readable_command
        if candidate is not None and candidate.readable_command
        else _literal_command_text(arguments)
    )
    old_text = _pinned_command_text(state, criterion)
    return (
        f"Note: the earlier validation command `{old_text}` did not run "
        "successfully in this environment. Approving now also re-binds that "
        f"pending verification obligation to `{new_text}`; the required evidence "
        "becomes this command's successful run."
    )


def _literal_command_text(arguments: Mapping[str, object]) -> str:
    executable = arguments.get("executable")
    argv = arguments.get("argv")
    parts = [executable] if isinstance(executable, str) else []
    if isinstance(argv, (list, tuple)):
        parts.extend(item for item in argv if isinstance(item, str))
    return " ".join(parts) if parts else "this command"


def _pinned_command_text(state: ConversationState, criterion: AdmittedCriterion) -> str:
    """还原义务当前 pinned 命令的字面形式（展示用；等价判定另走 canonical form）。"""

    fingerprint = criterion.predicate.get("command_fingerprint")
    if not isinstance(fingerprint, str):
        return "an earlier command"
    calls: dict[str, object] = {}
    for fact in state.facts:
        if fact.kind is not FactKind.TOOL_CALLS:
            continue
        for raw in fact.content.get("calls", ()):
            if isinstance(raw, dict) and isinstance(raw.get("tool_call_id"), str):
                calls[raw["tool_call_id"]] = raw.get("arguments")
    for fact in state.facts:
        if fact.kind is not FactKind.TOOL_RESULT:
            continue
        metadata = fact.content.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("command_fingerprint") != fingerprint:
            continue
        call_arguments = calls.get(fact.content.get("tool_call_id"))
        if isinstance(call_arguments, dict):
            return _literal_command_text(call_arguments)
    return "an earlier command"


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
            targets=(),
            progress_summary=None,
            next_step=None,
            blocker=None,
            safe_attempts=(),
            resume_condition=None,
            criteria_total=0,
            criteria_verified=0,
            verification_scope=(),
            durable_authorities_closed=True,
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
        targets=goal.targets,
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
        verification_scope=(
            _verification_scope(goal.admitted_criteria, passed_criteria)
            if goal.status is GoalStatus.VERIFIED_DONE
            else ()
        ),
        durable_authorities_closed=not bool(
            state.goal_authorizations
            or state.process_leases
            or state.sandbox_leases
            or state.browser_leases
            or state.browser_takeover_pending
        ),
        legal_actions=_goal_actions(state),
        sources=visible_sources[-32:],
    )


def _verification_scope(
    criteria: tuple[AdmittedCriterion, ...],
    passed_criteria: set[str],
) -> tuple[str, ...]:
    """只投影 closed oracle 实际证明的范围，不复述模型提供的 criterion prose。"""

    scopes: list[str] = []
    for criterion in criteria:
        if criterion.criterion_id not in passed_criteria:
            continue
        predicate = criterion.predicate
        if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST:
            path = predicate.get("path")
            scope = (
                f"exact current bytes of {path}"
                if isinstance(path, str) and path
                else "exact bound workspace file bytes"
            )
        elif criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT:
            receipt_kind = predicate.get("receipt_kind")
            if receipt_kind == "process_v1":
                scope = "approved local process exited with code 0"
            elif receipt_kind == "native_sandbox_v1":
                scope = "approved sandbox command produced its bound success receipt"
            else:
                scope = "bound governed tool receipt"
        elif criterion.oracle_kind is EvidenceOracleKind.USER_CONFIRMATION:
            scope = "explicit owner confirmation"
        elif criterion.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE:
            scope = "artifact bytes linked to recorded research source receipts"
        elif criterion.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT:
            scope = "recorded public Web source receipt"
        elif criterion.oracle_kind is EvidenceOracleKind.BROWSER_READBACK:
            scope = "approved browser action plus bound same-session readback"
        else:  # pragma: no cover - enum expansion must add an explicit projection
            scope = "bound closed-oracle evidence"
        if scope not in scopes:
            scopes.append(scope)
    return tuple(scopes)


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
        raw_receipts = metadata.get("source_receipts") if isinstance(metadata, dict) else None
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
                if goal_revision is not None and receipt.goal_revision != goal_revision:
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
    if goal is None:
        return ()
    if goal.status in {GoalStatus.CANCELLED, GoalStatus.VERIFIED_DONE}:
        # Goal 生命周期已经结束，但 conversation 仍可接受普通追问；这只复用既有
        # SubmitMessage，不恢复/替换 Goal，也不能越过待处理的 browser takeover。
        if state.active_run is None and state.browser_takeover_pending is None:
            return ("submit",)
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
