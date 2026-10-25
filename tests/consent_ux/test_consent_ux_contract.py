"""2026-10-21 确认疲劳修复包（consent-ux）验收测试。

对应 docs/handoffs/2026-10-21-consent-ux-repair/ 的 SPEC 与 VALIDATION：

- U1/U7：常规会话许可与旧精确路径的分离（新 s 不影响旧 y 语义）。
- S3/S5/S6：grant 生命周期——32 次/60 分钟、身份漂移持久化失效且 A→B→A
  不复活、撤销 fence、单次 y 票据只消费一次、扣账竞态守卫。
- S7/N12/N13：schema11 严格编解码、无 active run 也不丢字段、v10 兼容、
  篡改 digest 拒绝。
- W1/N19：内置文件结果可信来源证明只由 Kernel 校验转存，伪造/失配拒绝。
- W3/S2/N1-N3：CLI s/f/d 与 /revoke-provider-consent 的解析合同，以及
  v2 披露提示的选项渲染；不适用时明确拒绝且不降级为单笔批准。

U2/U3/U4/U5/U6/U8/U9 的完整交互旅程（真实文件效果、pause→resume、压缩、
固定 4 次确认预算）属于 VALIDATION 的 journey 级验收，其执行状态统一记录
在 docs/handoffs/2026-10-11-product-reliability-closure/RESULTS.md；本文件
只固化可在生产路径自动复现的合同行为。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from functools import reduce

import pytest

from agent.cli.app import _parse_action
from agent.cli.render import TerminalRenderer
from agent.runtime.checkpoint import (
    CheckpointInvariantError,
    CheckpointVersionError,
    LocalCheckpointStore,
    _encode_state,
)
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    CONSENT_MAX_USES,
    CONSENT_PROFILE_ROUTINE,
    CONSENT_PROFILE_WORKSPACE_READ,
    CONSENT_TTL_SECONDS,
    NO_WORKSPACE_IDENTITY,
    ROUTINE_DATA_CLASSES,
    WORKSPACE_READ_DATA_CLASSES,
    AcknowledgeProviderDisclosure,
    ActionDisposition,
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ArtifactConfirmationRequirementV1,
    BackgroundOccurrenceBindingV1,
    BlockedClaim,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ConversationWorkspaceBindingV1,
    EgressClass,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    GrantProviderConsent,
    GrantProviderWorkspaceReadConsent,
    ModelResponse,
    ModelTextBlock,
    ProcessAuthorityCandidateV1,
    ProposedCriterion,
    ProviderConsentGrantStatus,
    ProviderConsentGrantV1,
    ProviderConsentScopeV1,
    ProviderConsentToolBindingV1,
    ProviderDescriptor,
    ProviderDisclosureReceiptV2,
    ProviderDisclosureRequest,
    ProviderDisclosureRequestV2,
    ProviderDisclosureSourceV1,
    ProviderFileSourceProofV1,
    ProviderSummarySourceBoundaryV1,
    Resume,
    RevokeProviderConsent,
    RunStatus,
    SideEffectClass,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.provider_consent import (
    CONTROL_SCHEMA_STRUCTURE_DIGEST,
    build_disclosure_request_v2,
    charge_provider_dispatch,
    evaluate_provider_dispatch,
    grant_availability,
    grant_identity_matches,
    mint_provider_consent_grant,
    workspace_read_dispatch_notice,
)
from agent.runtime.state import (
    accept_action,
    mark_executing,
    record_tool_result,
    start_tool_batch,
)
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

_T0 = "2026-10-21T10:00:00Z"
_DONE = ModelResponse((ModelTextBlock("done"),))
_INTENT_DIGEST = "1" * 64


def _descriptor(*, model: str = "remote-model") -> ProviderDescriptor:
    return ProviderDescriptor(
        family="openai_compatible",
        model=model,
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _runtime(
    state: ConversationState,
    descriptor: ProviderDescriptor | None,
    responses: tuple[ModelResponse, ...] | None = None,
    *,
    run_time_factory=None,
):
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(*(responses if responses is not None else (_DONE,)))
    runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=descriptor,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-consent-ux",
        run_time_factory=run_time_factory,
    )
    return runtime, store, provider


def _submit(state: ConversationState, *, run_id: str = "run-1") -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message="hello",
    )


def _ack(state: ConversationState, *, digest: str, at: str = _T0):
    return AcknowledgeProviderDisclosure(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=digest,
        acknowledged_at=at,
    )


def _grant_action(state: ConversationState) -> GrantProviderConsent:
    request = state.provider_disclosure_request
    assert isinstance(request, ProviderDisclosureRequestV2)
    return GrantProviderConsent(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        request_digest=request.request_digest,
        scope_digest=request.scope_digest,
    )


def _scope(
    *,
    data_classes: tuple[str, ...] = ("system_policy", "user_messages"),
    sources: tuple[ProviderDisclosureSourceV1, ...] = (),
    routine: bool = True,
    goal_id: str | None = None,
    goal_revision: int | None = None,
    workspace: str = NO_WORKSPACE_IDENTITY,
) -> ProviderConsentScopeV1:
    return ProviderConsentScopeV1(
        workspace_identity_digest=workspace,
        goal_id=goal_id,
        goal_revision=goal_revision,
        tool_bindings=(),
        control_schema_digest=CONTROL_SCHEMA_STRUCTURE_DIGEST,
        data_classes=data_classes,
        sources=sources,
        routine_compatible=routine,
    )


def _source(label: str, *, reusable: bool = True) -> ProviderDisclosureSourceV1:
    return ProviderDisclosureSourceV1(
        data_class="workspace_excerpt",
        boundary_digest=hashlib.sha256(label.encode("utf-8")).hexdigest(),
        label=label,
        reusable=reusable,
    )


def _v2_request(
    *,
    scope: ProviderConsentScopeV1 | None = None,
    grant=None,
    run_id: str = "run-1",
    purpose: str = "runtime_progress",
) -> ProviderDisclosureRequestV2:
    return build_disclosure_request_v2(
        descriptor=_descriptor(),
        scope=scope or _scope(),
        grant=grant,
        purpose=purpose,
        run_id=run_id,
    )


# ── U1：常规会话许可 ─────────────────────────────────────────────────────


def test_consent_ux_u1_three_turns_need_one_decision_and_three_sends() -> None:
    runtime, store, provider = _runtime(
        ConversationState.new("conversation-1"),
        _descriptor(),
        (_DONE, _DONE, _DONE),
    )

    first = runtime.run_turn(_submit(store.state), store.load())
    assert first.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    request = store.state.provider_disclosure_request
    assert isinstance(request, ProviderDisclosureRequestV2)
    assert request.grant_eligible is True

    granted = runtime.run_turn(_grant_action(store.state), store.load())
    assert granted.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    grant = store.state.provider_consent_grant
    assert grant is not None and grant.uses_consumed == 1

    # 第 2/3 轮：conversation_history 加入后仍是常规范围——零新外发决定。
    for expected_uses in (2, 3):
        turn = runtime.run_turn(
            _submit(store.state, run_id=f"run-{expected_uses}"), store.load()
        )
        assert turn.status is RunStatus.COMPLETED
        assert store.state.provider_disclosure_request is None
        assert store.state.provider_consent_grant.uses_consumed == expected_uses

    assert len(provider.calls) == 3


def test_consent_ux_u1_without_grant_single_yes_covers_exactly_one_send() -> None:
    """S5：新模式单次 y 只绑定当前待发内容，消费一次后需要重新决定。"""

    runtime, store, provider = _runtime(
        ConversationState.new("conversation-1"), _descriptor(), (_DONE, _DONE)
    )

    runtime.run_turn(_submit(store.state), store.load())
    request = store.state.provider_disclosure_request
    assert isinstance(request, ProviderDisclosureRequestV2)

    first = runtime.run_turn(
        _ack(store.state, digest=request.request_digest), store.load()
    )
    assert first.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    assert store.state.provider_consent_grant is None
    receipt = store.state.provider_disclosure_receipt
    assert isinstance(receipt, ProviderDisclosureReceiptV2)
    assert receipt.consumed_at is not None

    second = runtime.run_turn(_submit(store.state, run_id="run-2"), store.load())
    assert second.status is RunStatus.AWAITING_DISCLOSURE
    assert len(provider.calls) == 1


# ── S6：次数与 TTL ───────────────────────────────────────────────────────


def test_consent_ux_s6_thirty_second_send_allowed_thirty_third_requires_decision() -> None:
    assert CONSENT_MAX_USES == 32
    assert CONSENT_TTL_SECONDS == 3_600

    state = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=_T0
    )
    grant = reduce(lambda g, _: g.with_use(), range(31), grant)
    assert grant.uses_consumed == 31
    assert grant_availability(grant, now=_T0) is None

    scope = _scope()
    state = replace(state, provider_consent_grant=grant)
    gate = evaluate_provider_dispatch(
        state=state,
        descriptor=_descriptor(),
        scope=scope,
        now=_T0,
        purpose="runtime_progress",
        run_id="run-32",
    )
    assert gate.admitted and gate.grant_use
    charged = charge_provider_dispatch(
        state,
        gate,
        descriptor=_descriptor(),
        scope=scope,
        purpose="runtime_progress",
        run_id="run-32",
        now=_T0,
    )
    assert charged.provider_consent_grant.uses_consumed == 32

    gate_33 = evaluate_provider_dispatch(
        state=charged,
        descriptor=_descriptor(),
        scope=scope,
        now=_T0,
        purpose="runtime_progress",
        run_id="run-33",
    )
    assert not gate_33.admitted
    # 既有 grant 不再可用时统一报 grant_unavailable；耗尽原因由 availability 给出。
    assert gate_33.reason == "grant_unavailable"
    assert grant_availability(charged.provider_consent_grant, now=_T0) == "exhausted"


def test_consent_ux_s3_expired_grant_requires_new_decision_and_new_s_renews() -> None:
    clock = {"now": _T0}

    def time_factory() -> str:
        return clock["now"]

    runtime, store, provider = _runtime(
        ConversationState.new("conversation-1"),
        _descriptor(),
        (_DONE, _DONE),
        run_time_factory=time_factory,
    )
    runtime.run_turn(_submit(store.state), store.load())
    runtime.run_turn(_grant_action(store.state), store.load())
    first_grant = store.state.provider_consent_grant
    assert first_grant.issued_at == _T0

    clock["now"] = (
        datetime.fromisoformat(first_grant.expires_at.replace("Z", "+00:00"))
        + timedelta(minutes=1)
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")

    later = runtime.run_turn(_submit(store.state, run_id="run-2"), store.load())
    assert later.status is RunStatus.AWAITING_DISCLOSURE
    assert len(provider.calls) == 1
    # 到期是计算属性：旧 grant 保留为 fence 记录，不静默删除。
    assert store.state.provider_consent_grant.expires_at == first_grant.expires_at

    # 明确重新选 s 才能建立新 grant、新期限。
    renewed = runtime.run_turn(_grant_action(store.state), store.load())
    assert renewed.status is RunStatus.COMPLETED
    assert store.state.provider_consent_grant.issued_at == clock["now"]
    assert store.state.provider_consent_grant.grant_id != first_grant.grant_id
    assert len(provider.calls) == 2


def test_consent_ux_s6_charge_rejects_grant_that_expired_after_gate() -> None:
    state = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=_T0
    )
    state = replace(state, provider_consent_grant=grant)
    gate = evaluate_provider_dispatch(
        state=state,
        descriptor=_descriptor(),
        scope=_scope(),
        now=_T0,
        purpose="runtime_progress",
        run_id="run-1",
    )
    assert gate.admitted and gate.grant_use

    later = (
        datetime.fromisoformat(_T0.replace("Z", "+00:00")) + timedelta(seconds=3_601)
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="no longer usable|stale"):
        charge_provider_dispatch(
            state,
            gate,
            descriptor=_descriptor(),
            scope=_scope(),
            purpose="runtime_progress",
            run_id="run-1",
            now=later,
        )


# ── S3/N6：身份漂移与撤销 ────────────────────────────────────────────────


def test_consent_ux_n6_descriptor_change_invalidates_grant_without_revival() -> None:
    runtime_a, store, provider_a = _runtime(
        ConversationState.new("conversation-1"), _descriptor(model="model-a"), (_DONE,)
    )
    runtime_a.run_turn(_submit(store.state), store.load())
    runtime_a.run_turn(_grant_action(store.state), store.load())
    assert store.state.provider_consent_grant is not None

    # 换模型：旧 grant 持久化 INVALIDATED，先落 fence 再要求新决定。
    runtime_b, store_b, provider_b = _runtime(
        store.state, _descriptor(model="model-b"), (_DONE, _DONE)
    )
    store = store_b
    switched = runtime_b.run_turn(_submit(store.state, run_id="run-2"), store.load())
    assert switched.status is RunStatus.AWAITING_DISCLOSURE
    assert (
        store.state.provider_consent_grant.status
        is ProviderConsentGrantStatus.INVALIDATED
    )
    # 对 B 的新披露用 y 单次批准并完成发送，清掉 pending。
    pending_b = store.state.provider_disclosure_request
    assert isinstance(pending_b, ProviderDisclosureRequestV2)
    answered = runtime_b.run_turn(
        _ack(store.state, digest=pending_b.request_digest), store.load()
    )
    assert answered.status is RunStatus.COMPLETED
    assert len(provider_b.calls) == 1

    # A→B→A 不复活：切回原身份，被失效的 grant 仍不可用，需要重新决定。
    runtime_a2, store_a2, _ = _runtime(
        store.state, _descriptor(model="model-a"), (_DONE,)
    )
    store = store_a2
    back = runtime_a2.run_turn(_submit(store.state, run_id="run-3"), store.load())
    assert back.status is RunStatus.AWAITING_DISCLOSURE
    assert (
        store.state.provider_consent_grant.status
        is ProviderConsentGrantStatus.INVALIDATED
    )
    assert len(provider_a.calls) == 1


def test_consent_ux_n6_workspace_identity_change_breaks_grant_match() -> None:
    state = ConversationState.new("conversation-1")
    scope = _scope(workspace="workspace-1")
    request = _v2_request(scope=scope)
    grant = mint_provider_consent_grant(
        state=state, request=request, action_seq=1, now=_T0
    )

    assert grant_identity_matches(
        grant, descriptor=_descriptor(), workspace_identity_digest="workspace-1"
    )
    assert not grant_identity_matches(
        grant, descriptor=_descriptor(), workspace_identity_digest="workspace-2"
    )
    # 空/未知 workspace 不是通配符。
    assert not grant_identity_matches(
        grant, descriptor=_descriptor(), workspace_identity_digest=NO_WORKSPACE_IDENTITY
    )


def test_consent_ux_n9_revoke_is_durable_and_stops_routine_reuse() -> None:
    runtime, store, provider = _runtime(
        ConversationState.new("conversation-1"), _descriptor(), (_DONE,)
    )
    runtime.run_turn(_submit(store.state), store.load())
    runtime.run_turn(_grant_action(store.state), store.load())
    grant_id = store.state.provider_consent_grant.grant_id

    revoke = RevokeProviderConsent(
        conversation_id=store.state.conversation_id,
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
    )
    revoked = runtime.run_turn(revoke, store.load())
    # idle 状态动作统一返回 CANCELLED；关键契约是 durable 状态已应用。
    assert revoked.status is RunStatus.CANCELLED
    # 撤销动作本身不触发 provider。
    assert len(provider.calls) == 1
    assert store.state.provider_consent_grant.status is ProviderConsentGrantStatus.REVOKED
    assert store.state.provider_consent_grant.grant_id == grant_id

    after = runtime.run_turn(_submit(store.state, run_id="run-2"), store.load())
    assert after.status is RunStatus.AWAITING_DISCLOSURE
    assert len(provider.calls) == 1


# ── U7：legacy 精确路径不生成 grant ─────────────────────────────────────


def test_consent_ux_u7_legacy_ack_and_reuse_never_mint_grant() -> None:
    descriptor = _descriptor()
    legacy_request = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-legacy",
        provider_descriptor_digest=descriptor.identity_digest,
        canonical_destination=descriptor.canonical_destination,
        model=descriptor.model,
        data_classes=("system_policy", "user_messages"),
    )
    # 用真实 SubmitMessage 生成 user fact，保证 ContextPack 类别与旧 request 一致。
    seeded = accept_action(
        None,
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="hello",
        ),
    ).state
    state = replace(
        seeded,
        active_run=replace(
            seeded.active_run, status=ActiveRunStatus.AWAITING_DISCLOSURE
        ),
        provider_disclosure_request=legacy_request,
    )
    runtime, store, provider = _runtime(state, descriptor, (_DONE, _DONE))

    first = runtime.run_turn(
        _ack(store.state, digest=legacy_request.request_digest), store.load()
    )
    assert first.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    assert store.state.provider_consent_grant is None

    # 旧精确语义保留其固有疲劳：首次交换后 conversation_history 加入，类别
    # 变化触发新的外发决定（这正是本轮 s 要修的问题），但 y 依旧只是精确
    # 回执——任何时候都不铸造范围 grant。
    second = runtime.run_turn(_submit(store.state, run_id="run-3"), store.load())
    assert second.status is RunStatus.AWAITING_DISCLOSURE
    assert store.state.provider_consent_grant is None

    follow_up = store.state.provider_disclosure_request
    assert follow_up is not None
    answered = runtime.run_turn(
        _ack(store.state, digest=follow_up.request_digest), store.load()
    )
    assert answered.status is RunStatus.COMPLETED
    assert len(provider.calls) == 2
    assert store.state.provider_consent_grant is None


# ── N7/U9：来源边界与最后一条精确例外 ──────────────────────────────────


def test_consent_ux_u9_exception_reuses_last_exact_scope_and_blocks_new_source() -> None:
    descriptor = _descriptor()
    routine_scope = _scope()
    file_scope = _scope(
        data_classes=("system_policy", "user_messages", "workspace_excerpt"),
        sources=(_source("write_file notes/a.txt"),),
        routine=False,
        goal_id="goal-1",
        goal_revision=1,
    )
    state = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=_T0
    )
    state = replace(state, provider_consent_grant=grant)

    def gate(scope, *, run_id="run-1"):
        return evaluate_provider_dispatch(
            state=state,
            descriptor=descriptor,
            scope=scope,
            now=_T0,
            purpose="runtime_progress",
            run_id=run_id,
        )

    # A（常规）由 grant 直接过；B（文件来源）首次必须决定。
    assert gate(routine_scope).admitted
    b_first = gate(file_scope)
    assert not b_first.admitted and b_first.reason == "decision_required"

    # 用户对 B 的首次披露回答 y：保存 v2 request + 未消费 receipt。
    b_request = _v2_request(scope=file_scope, grant=grant, run_id="run-1")
    b_receipt = ProviderDisclosureReceiptV2(
        receipt_id="receipt-b",
        request_digest=b_request.request_digest,
        acknowledged_action_seq=2,
        acknowledged_at=_T0,
        consumed_at=None,
    )
    state = replace(
        state, provider_disclosure_request=b_request, provider_disclosure_receipt=b_receipt
    )
    b_second = gate(file_scope)
    # 首次 y 之后，同来源复用走 grant 例外（S5 路径2），扣 grant 不再耗单次票据。
    assert b_second.admitted and b_second.grant_use
    assert b_second.reason == "grant_exception"

    # A→B→A→B：中间的常规发送不抹掉 B 例外。
    assert gate(routine_scope, run_id="run-2").admitted
    b_again = gate(file_scope, run_id="run-3")
    assert b_again.admitted and b_again.reason == "grant_exception"

    # 新来源 C 即使同类别也不被放行。
    c_scope = _scope(
        data_classes=file_scope.data_classes,
        sources=(_source("write_file notes/other.txt"),),
        routine=False,
        goal_id="goal-1",
        goal_revision=1,
    )
    c_gate = gate(c_scope, run_id="run-4")
    assert not c_gate.admitted and c_gate.reason == "decision_required"


def test_consent_ux_n7_nonroutine_scope_makes_s_unavailable() -> None:
    scope = _scope(
        data_classes=("system_policy", "tool_results", "user_messages"),
        sources=(_source("shell stdout", reusable=False),),
        routine=False,
    )
    assert _v2_request(scope=scope).grant_eligible is False


# ── W1/N19：文件来源证明只认 Kernel 校验 ────────────────────────────────


def _executing_state() -> ConversationState:
    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="write the note",
        ),
    ).state
    started = start_tool_batch(
        started, (ToolCall("tool-call-1", "write_file", {"path": "notes/a.txt"}),)
    )
    goal = GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("user-1",),
        workspace_identity_digest="workspace-1",
        user_outcome="write the note",
        beneficiary="user",
        targets=("notes", "notes/a.txt"),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "note exists"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at=_T0,
        updated_at=_T0,
    )
    started = replace(
        started,
        goal=goal,
        workspace_binding=ConversationWorkspaceBindingV1.create(
            workspace_scope_digest="scope-1",
            workspace_identity_digest="workspace-1",
            bound_at=_T0,
        ),
    )
    return mark_executing(
        started,
        tool_call_id="tool-call-1",
        intent_digest=_INTENT_DIGEST,
        idempotency_key="conversation-1:run-1:tool-call-1",
        side_effect=SideEffectClass.WRITE,
        egress=EgressClass.NONE,
        operation="write_file",
        request_identity="conversation-1:run-1:tool-call-1",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )


def _proof(
    *, intent_digest: str = _INTENT_DIGEST, content: str = "ok"
) -> ProviderFileSourceProofV1:
    return ProviderFileSourceProofV1.create(
        conversation_id="conversation-1",
        run_id="run-1",
        workspace_identity_digest="workspace-1",
        tool_call_id="tool-call-1",
        tool_name="write_file",
        tool_identity_digest="0" * 64,
        policy_identity="policy-1",
        execution_authority=ExecutionAuthorityClass.IN_PROCESS.value,
        operation="write_file",
        normalized_target="notes/a.txt",
        target_digest=hashlib.sha256(b"notes/a.txt").hexdigest(),
        goal_id="goal-1",
        goal_revision=1,
        intent_digest=intent_digest,
        result_content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _result_fact(
    proof: ProviderFileSourceProofV1,
    *,
    text: str = "ok",
    fact_id: str = "tool-result-1",
) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "tool-call-1",
            "text": text,
            "is_error": False,
            "runtime_source_proof": proof.to_dict(),
        },
    )


def test_consent_ux_w1_kernel_moves_valid_proof_into_state_and_strips_fact_key() -> None:
    recorded = record_tool_result(
        _executing_state(), _result_fact(_proof()), intent_digest=_INTENT_DIGEST
    )

    assert len(recorded.provider_source_proofs) == 1
    stored = recorded.provider_source_proofs[0]
    assert stored.intent_digest == _INTENT_DIGEST
    assert stored.normalized_target == "notes/a.txt"
    # 证明转存为 Runtime-owned 后，fact 里不得残留可伪造的同名字段。
    assert "runtime_source_proof" not in recorded.facts[-1].content


def test_consent_ux_w1_mismatched_or_fabricated_proof_is_rejected() -> None:
    state = _executing_state()
    with pytest.raises(ValueError, match="does not bind"):
        record_tool_result(
            state,
            _result_fact(_proof(intent_digest="2" * 64)),
            intent_digest=_INTENT_DIGEST,
        )
    with pytest.raises(ValueError, match="does not bind"):
        # 内容 digest 与实际 text 不符：自报 metadata 不算 Kernel 证明。
        record_tool_result(
            state, _result_fact(_proof(content="other")), intent_digest=_INTENT_DIGEST
        )


# ── S7/N12/N13：schema11 编解码 ─────────────────────────────────────────


def _write_state(path, state: ConversationState) -> None:
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation-1"))
    path.write_bytes(_encode_state(state))


def test_consent_ux_n12_schema11_roundtrip_preserves_grant_without_active_run(
    tmp_path,
) -> None:
    state = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=_T0
    )
    state = replace(state, provider_consent_grant=grant)

    document = json.loads(_encode_state(state).decode("utf-8"))
    assert document["schema_version"] == 11

    path = tmp_path / "conversation.json"
    _write_state(path, state)
    assert LocalCheckpointStore(path).load().state.provider_consent_grant == grant


def test_consent_ux_n13_tampered_grant_rejected_and_v10_defaults_stay_empty(
    tmp_path,
) -> None:
    state = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=_T0
    )
    state = replace(state, provider_consent_grant=grant)
    document = json.loads(_encode_state(state).decode("utf-8"))
    document["state"]["provider_consent_grant"]["uses_consumed"] = 5
    path = tmp_path / "conversation.json"
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation-1"))
    path.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    with pytest.raises((ValueError, CheckpointVersionError, CheckpointInvariantError)):
        LocalCheckpointStore(path).load()

    # v10（consent 之前）文档继续按原合同解码；许可字段缺省为空。
    legacy_state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.RUNNABLE),
    )
    legacy_document = json.loads(_encode_state(legacy_state).decode("utf-8"))
    assert legacy_document["schema_version"] == 10
    assert "provider_consent_grant" not in legacy_document["state"]


# ── W3/S2/N1-N3：CLI 解析与渲染 ─────────────────────────────────────────


def _v2_pending_state(
    *, routine: bool = True, paused: bool = False
) -> ConversationState:
    scope = _scope(routine=routine)
    request = _v2_request(scope=scope)
    if paused:
        # E1-B 形态：/pause 已停掉 active run，Goal=PAUSED，披露仍 durable。
        return replace(
            ConversationState.new("conversation-1"),
            provider_disclosure_request=request,
        )
    return replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1", status=ActiveRunStatus.AWAITING_DISCLOSURE
        ),
        provider_disclosure_request=request,
    )


def _paused_goal() -> GoalFrame:
    return GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=("user-1",),
        workspace_identity_digest=NO_WORKSPACE_IDENTITY,
        user_outcome="write the note",
        beneficiary="user",
        targets=("notes",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "note exists"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.PAUSED,
        created_at=_T0,
        updated_at=_T0,
    )


def test_consent_ux_cli_s_parses_to_grant_from_pending_v2_request() -> None:
    state = _v2_pending_state()
    request = state.provider_disclosure_request

    action, error = _parse_action("s", state, lambda: "run-x")

    assert error is None
    assert isinstance(action, GrantProviderConsent)
    assert action.request_digest == request.request_digest
    assert action.scope_digest == request.scope_digest
    assert action.expected_revision == state.revision


def test_consent_ux_cli_s_without_pending_stays_a_plain_message() -> None:
    state = ConversationState.new("conversation-1")

    action, error = _parse_action("s", state, lambda: "run-x")

    assert error is None
    assert isinstance(action, SubmitMessage)
    assert action.message == "s"


def test_consent_ux_cli_s_inapplicable_explains_and_keeps_exact_choice() -> None:
    state = _v2_pending_state(routine=False)

    action, error = _parse_action("s", state, lambda: "run-x")

    assert action is None
    assert error is not None and "unavailable" in error
    # y 语义保持：精确类别仍可批准。
    yes_action, yes_error = _parse_action("y", state, lambda: "run-x")
    assert yes_error is None
    assert yes_action is not None


def test_consent_ux_cli_paused_disclosure_requires_resume_before_s() -> None:
    state = replace(_v2_pending_state(paused=True), goal=_paused_goal())

    action, error = _parse_action("s", state, lambda: "run-x")

    assert action is None
    assert error is not None and "/resume" in error


def _goal_scoped_approval_state(
    *,
    path: str = "notes/idea.md",
    targets: tuple[str, ...] = ("notes", "notes/idea.md"),
) -> ConversationState:
    goal = replace(
        _paused_goal(),
        workspace_identity_digest="workspace-1",
        user_outcome="write the requested note under notes",
        targets=targets,
        status=GoalStatus.GOAL_READY,
    )
    request = ApprovalRequest(
        request_id="approval-scoped-internal-id",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="approval-binding",
        preview=f"write {path} (12 bytes)",
        tool_name="write_file",
        side_effect=SideEffectClass.WRITE.value,
        artifact_confirmation_requirement=None,
    )
    return replace(
        ConversationState.new("conversation-1"),
        goal=goal,
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "write_file", {"path": path}),),
        ),
    )


def test_consent_ux_cli_f_d_match_existing_goal_scoped_commands() -> None:
    state = _goal_scoped_approval_state()
    fixed_clock = lambda: _T0  # noqa: E731

    f_action, f_error = _parse_action(
        "f", state, lambda: "run-x", approval_time_factory=fixed_clock
    )
    slash_action, slash_error = _parse_action(
        "/approve-goal-target", state, lambda: "run-x", approval_time_factory=fixed_clock
    )
    d_action, d_error = _parse_action(
        "d", state, lambda: "run-x", approval_time_factory=fixed_clock
    )
    dir_action, dir_error = _parse_action(
        "/approve-goal-directory", state, lambda: "run-x", approval_time_factory=fixed_clock
    )

    assert f_error is None and slash_error is None
    assert d_error is None and dir_error is None
    # f/d 与既有 slash 构造完全等价（同一 typed action），不是复制的 y 分支。
    assert f_action == slash_action
    assert d_action == dir_action
    assert f_action != d_action


def _artifact_approval_pending_state() -> ConversationState:
    candidate = ProcessAuthorityCandidateV1.create(
        candidate_id="candidate-artifact",
        goal_id="goal-artifact",
        goal_revision=1,
        workspace_identity_digest="workspace-artifact",
        command_fingerprint="f" * 64,
        readable_command="./writer artifact.out",
        executable_digest="e" * 64,
        argv_digest="v" * 64,
        cwd_digest="d" * 64,
        resource_profile="short",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        trust_notice_digest="t" * 64,
        issued_at=_T0,
    )
    request = ApprovalRequest(
        request_id="approval-artifact",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="approval-binding",
        preview="run ./writer artifact.out",
        tool_name="local_process",
        process_authority_candidate=candidate,
        artifact_confirmation_requirement=ArtifactConfirmationRequirementV1(
            criterion_id="criterion-artifact",
            artifact_path="artifact.out",
        ),
    )
    return replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            tool_calls=(ToolCall("call-1", "local_process", {}),),
        ),
    )


def test_consent_ux_cli_artifact_confirmation_rejects_f_d_without_fallback() -> None:
    state = _artifact_approval_pending_state()

    for raw in ("f", "d"):
        action, error = _parse_action(raw, state, lambda: "run-x")
        assert action is None
        assert error is not None and "separate content confirmation" in error


def test_consent_ux_cli_revoke_provider_consent_command_contract() -> None:
    grant = mint_provider_consent_grant(
        state=ConversationState.new("conversation-1"),
        request=_v2_request(),
        action_seq=1,
        now=_T0,
    )
    granted_state = replace(
        ConversationState.new("conversation-1"), provider_consent_grant=grant
    )

    action, error = _parse_action(
        "/revoke-provider-consent", granted_state, lambda: "run-x"
    )
    assert error is None
    assert isinstance(action, RevokeProviderConsent)

    _, arg_error = _parse_action(
        "/revoke-provider-consent extra", granted_state, lambda: "run-x"
    )
    assert arg_error is not None and "does not accept arguments" in arg_error

    _, missing_error = _parse_action(
        "/revoke-provider-consent",
        ConversationState.new("conversation-1"),
        lambda: "run-x",
    )
    assert missing_error is not None and "No provider consent is active" in missing_error


def test_consent_ux_s2_disclosure_render_shows_options_and_legacy_stays_plain() -> None:
    v2_message = TerminalRenderer._disclosure_message(request=_v2_request(), grant=None)
    assert "y  Approve the exact scope shown above" in v2_message
    assert "s  Allow routine conversation data" in v2_message
    assert "32 model sends" in v2_message and "60 minutes" in v2_message
    assert "n  Do not send" in v2_message
    assert "Revoke: /revoke-provider-consent" in v2_message

    ineligible = TerminalRenderer._disclosure_message(
        request=_v2_request(
            scope=_scope(
                data_classes=("system_policy", "tool_results"),
                sources=(_source("shell stdout", reusable=False),),
                routine=False,
            )
        ),
        grant=None,
    )
    assert "s  unavailable" in ineligible


def test_consent_ux_r_unavailable_explains_why_when_sources_not_covered() -> None:
    # 双审计交叉验证（2026-10-25：Oracle #3）：无任务绑定的探索式读逐次披露时
    # r 从不出现，用户不知道 r 为什么不可用、怎样才会可用。与 s-unavailable
    # 同式：覆盖不了时明示原因（r 只覆盖活跃任务下 proof-backed 的读），
    # 而不是静默缺行；覆盖成立时必须提供 r 选项本身。
    goalless_read = TerminalRenderer._disclosure_message(
        request=_v2_request(
            scope=_scope(
                data_classes=("system_policy", "user_messages", "workspace_excerpt"),
                sources=(_source("notes/a.md", reusable=False),),
                routine=False,
            )
        ),
        grant=None,
    )
    assert "r  unavailable" in goalless_read
    assert "verified workspace reads" in goalless_read
    # 第九轮审计 C1：来源未验证时 s-unavailable 保持原句；来源是已验证
    # 可复用读（r 覆盖成立）时不得误述为 "new or unverified"——那是对
    # 验证状态的虚假陈述，须如实指向 s 不覆盖的类别原因与 r。
    assert (
        "s  unavailable — this request includes a new or unverified source"
        in goalless_read
    )
    assert "routine-only permission does not cover" not in goalless_read

    covered = TerminalRenderer._disclosure_message(
        request=_v2_request(
            scope=_scope(
                data_classes=("system_policy", "user_messages", "workspace_excerpt"),
                sources=(_source("notes/a.md", reusable=True),),
                routine=False,
            )
        ),
        grant=None,
    )
    assert (
        "r  Also allow routine conversation data and verified workspace reads"
        in covered
    )
    assert "r  unavailable" not in covered
    assert (
        "s  unavailable — this request includes verified workspace reads" in covered
    )
    assert "choose r" in covered
    assert "new or unverified" not in covered

    legacy = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-legacy",
        provider_descriptor_digest=_descriptor().identity_digest,
        canonical_destination=_descriptor().canonical_destination,
        model=_descriptor().model,
        data_classes=("system_policy", "user_messages"),
    )
    legacy_message = TerminalRenderer._disclosure_message(request=legacy, grant=None)
    assert "Allow this information to be sent? [y/N]" in legacy_message
    assert "Allow routine conversation data" not in legacy_message


def test_consent_ux_s2_disclosure_with_active_grant_shows_remaining_quota() -> None:
    # 决策队列 1（2026-10-24 双轨裁决 C）：保持逐次披露，不扩大静默授权；
    # 活动许可在场时披露文案必须带剩余额度与到期时间——读/验证类新源
    # 逐次披露的场景下，用户能看到常规许可还剩多少、为何这次仍要问。
    state = ConversationState.new("conversation-1")
    # 真实当前时间铸造：_disclosure_message 的可用性判定用真实时钟，
    # 固定 _T0 会把许可判成已过期（走 unavailable 分支）。
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=now
    )
    partially_used = grant
    for _ in range(17):
        partially_used = partially_used.with_use()

    message = TerminalRenderer._disclosure_message(
        request=_v2_request(
            scope=_scope(sources=(_source("test output", reusable=False),))
        ),
        grant=partially_used,
    )

    assert "15 of 32 model sends left" in message
    assert partially_used.expires_at in message
    assert "not covered" in message

    exhausted_grant = grant
    for _ in range(grant.max_uses):
        exhausted_grant = exhausted_grant.with_use()
    exhausted = TerminalRenderer._disclosure_message(
        request=_v2_request(),
        grant=exhausted_grant,
    )
    assert "all 32 model sends used" in exhausted
    assert "model sends left" not in exhausted


def test_consent_ux_s2_render_provider_consent_reports_remaining_and_revoke() -> None:
    state = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=_T0
    )

    output: list[str] = []
    renderer = TerminalRenderer(output.append)
    renderer.render_provider_consent(replace(state, provider_consent_grant=grant))
    active_text = output[-1]
    assert "32 of 32 model sends left" in active_text
    assert grant.expires_at in active_text
    assert "/revoke-provider-consent" in active_text

    renderer.render_provider_consent(
        replace(
            state,
            provider_consent_grant=grant.with_status(ProviderConsentGrantStatus.REVOKED),
        )
    )
    assert "revoked" in output[-1].lower()


def test_consent_ux_r16_numeric_copy_tracks_the_constants() -> None:
    # r16 失败信号（2026-10-24）：CONSENT_MAX_USES/CONSENT_TTL_SECONDS 是
    # 唯一权威值。插值化已在同日调值轮完成（文案由常量 f-string 推导），
    # 本测试断言推导本身——生产侧若退回硬编码数字（与常量失去同步）即红。
    state = ConversationState.new("conversation-1")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    grant = mint_provider_consent_grant(
        state=state, request=_v2_request(), action_seq=1, now=now
    )

    # 铸造侧钉住：许可的额度与时长确实来自权威常量。
    assert grant.max_uses == CONSENT_MAX_USES
    issued = datetime.fromisoformat(grant.issued_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
    assert (expires - issued).total_seconds() == CONSENT_TTL_SECONDS

    # 文案侧钉住：offer 与 exhausted 两个硬编码数字与常量一致。
    offer = TerminalRenderer._disclosure_message(request=_v2_request(), grant=None)
    assert (
        f"up to {CONSENT_MAX_USES} model sends, "
        f"expires in {CONSENT_TTL_SECONDS // 60} minutes" in offer
    )
    exhausted_grant = grant
    for _ in range(grant.max_uses):
        exhausted_grant = exhausted_grant.with_use()
    assert (
        TerminalRenderer._consent_unavailable_reason(exhausted_grant)
        == f"all {CONSENT_MAX_USES} model sends used"
    )


# ── item 1（r）：读/验证类输出的会话许可（2026-10-24 用户裁决采纳）──────


def _excerpt_scope(
    *sources: ProviderDisclosureSourceV1,
    data_classes: tuple[str, ...] | None = None,
) -> ProviderConsentScopeV1:
    return _scope(
        data_classes=data_classes
        or ("system_policy", "user_messages", "workspace_excerpt"),
        # scope 合同要求 sources 按 (data_class, boundary_digest, label) 有序。
        sources=tuple(
            sorted(
                sources,
                key=lambda source: (source.data_class, source.boundary_digest, source.label),
            )
        ),
        routine=False,
        goal_id="goal-1",
        goal_revision=1,
    )


def _read_grant(state: ConversationState):
    return mint_provider_consent_grant(
        state=state,
        request=_v2_request(),
        action_seq=1,
        now=_T0,
        profile=CONSENT_PROFILE_WORKSPACE_READ,
    )


def test_consent_ux_r_grant_admits_excerpt_scopes_including_new_sources() -> None:
    descriptor = _descriptor()
    base = ConversationState.new("conversation-r")
    state = replace(base, provider_consent_grant=_read_grant(base))

    def gate(scope, *, run_id="run-1"):
        return evaluate_provider_dispatch(
            state=state,
            descriptor=descriptor,
            scope=scope,
            now=_T0,
            purpose="runtime_progress",
            run_id=run_id,
        )

    first = gate(_excerpt_scope(_source("read_file app/main.py")))
    assert first.admitted and first.grant_use
    assert first.reason == "grant_workspace_read"

    # 会话级语义本体：同一许可内**新出现**的 excerpt 源也覆盖——这正是
    # 披露疲劳的来源（真实层 E3 旅程 16-23 次决策的主驱动）。
    fresh = gate(_excerpt_scope(_source("read_file lib/util.py")), run_id="run-2")
    assert fresh.admitted and fresh.reason == "grant_workspace_read"

    # 常规 scope 不经 r 分支（通知与语义都按 routine 报告）。
    assert gate(_scope()).reason == "grant_routine"


def test_consent_ux_r_grant_blocks_nonexcerpt_and_nonreusable_classes() -> None:
    descriptor = _descriptor()
    base = ConversationState.new("conversation-r")
    state = replace(base, provider_consent_grant=_read_grant(base))

    def gate(scope):
        return evaluate_provider_dispatch(
            state=state,
            descriptor=descriptor,
            scope=scope,
            now=_T0,
            purpose="runtime_progress",
            run_id="run-1",
        )

    # 混入通用 tool_results 类：超出 r 覆盖，回到逐次披露。
    mixed = _excerpt_scope(
        _source("read_file app/main.py"),
        ProviderDisclosureSourceV1(
            data_class="tool_results",
            boundary_digest="f" * 64,
            label="list_files output",
            reusable=False,
        ),
        data_classes=(
            "system_policy",
            "tool_results",
            "user_messages",
            "workspace_excerpt",
        ),
    )
    mixed_gate = gate(mixed)
    assert not mixed_gate.admitted and mixed_gate.reason == "decision_required"

    # 不可复用的 workspace_excerpt（无有效 file proof 的形状）同样不覆盖。
    nonreusable = gate(
        _excerpt_scope(_source("read_file secret.env", reusable=False))
    )
    assert not nonreusable.admitted and nonreusable.reason == "decision_required"


def test_consent_ux_r_charge_increments_and_notice_reports_quota() -> None:
    base = ConversationState.new("conversation-r")
    state = replace(base, provider_consent_grant=_read_grant(base))
    scope = _excerpt_scope(_source("read_file app/main.py"), _source("read_file lib/util.py"))
    gate = evaluate_provider_dispatch(
        state=state,
        descriptor=_descriptor(),
        scope=scope,
        now=_T0,
        purpose="runtime_progress",
        run_id="run-1",
    )
    assert gate.admitted

    charged = charge_provider_dispatch(
        state,
        gate,
        descriptor=_descriptor(),
        scope=scope,
        purpose="runtime_progress",
        run_id="run-1",
        now=_T0,
    )

    grant = charged.provider_consent_grant
    assert grant is not None and grant.uses_consumed == 1
    notice = workspace_read_dispatch_notice(grant, scope)
    assert "2 workspace file excerpt(s)" in notice
    assert "31 of 32 model sends left" in notice


def test_consent_ux_r_grant_use_burns_pending_exact_receipt() -> None:
    # r2 B3 同款硬化：r 许可放行时，在场未消费的单次 y 一并烧掉，防 grant
    # 失效后 exact_receipt 额外放行一次。
    base = ConversationState.new("conversation-r")
    scope = _excerpt_scope(_source("read_file app/main.py"))
    request = _v2_request(scope=scope)
    state = replace(
        base,
        provider_consent_grant=_read_grant(base),
        provider_disclosure_request=request,
        provider_disclosure_receipt=ProviderDisclosureReceiptV2(
            receipt_id="receipt-r",
            request_digest=request.request_digest,
            acknowledged_action_seq=2,
            acknowledged_at=_T0,
            consumed_at=None,
        ),
    )
    gate = evaluate_provider_dispatch(
        state=state,
        descriptor=_descriptor(),
        scope=scope,
        now=_T0,
        purpose="runtime_progress",
        run_id="run-1",
    )
    assert gate.admitted and gate.mark_receipt_consumed

    charged = charge_provider_dispatch(
        state,
        gate,
        descriptor=_descriptor(),
        scope=scope,
        purpose="runtime_progress",
        run_id="run-1",
        now=_T0,
    )
    receipt = charged.provider_disclosure_receipt
    assert receipt is not None and receipt.consumed_at == _T0


def _r_pending_state() -> ConversationState:
    request = _v2_request(scope=_excerpt_scope(_source("read_file app/main.py")))
    return replace(
        ConversationState.new("conversation-r"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.AWAITING_DISCLOSURE),
        provider_disclosure_request=request,
    )


def test_consent_ux_r_cli_parses_and_reducer_mints_workspace_read_grant() -> None:
    state = _r_pending_state()
    request = state.provider_disclosure_request
    assert isinstance(request, ProviderDisclosureRequestV2)
    assert request.grant_eligible is False

    action, error = _parse_action("r", state, lambda: "run-x")
    assert error is None
    assert isinstance(action, GrantProviderWorkspaceReadConsent)
    assert action.request_digest == request.request_digest
    assert action.scope_digest == request.scope_digest

    transition = accept_action(state, action, now=_T0)
    assert transition.disposition is ActionDisposition.ACCEPTED
    granted = transition.state.provider_consent_grant
    assert granted is not None
    assert granted.profile == CONSENT_PROFILE_WORKSPACE_READ
    assert granted.allowed_data_classes == WORKSPACE_READ_DATA_CLASSES
    assert granted.max_uses == CONSENT_MAX_USES
    assert granted.status is ProviderConsentGrantStatus.ACTIVE
    # 与 s 同一状态形状：pending 披露清空、run 恢复 RUNNABLE。
    assert transition.state.provider_disclosure_request is None
    assert transition.state.active_run is not None
    assert transition.state.active_run.status is ActiveRunStatus.RUNNABLE


def test_consent_ux_r_cli_rejects_routine_and_beyond_excerpt_requests() -> None:
    # 常规可授予的请求上 r 不适用：s 已覆盖，不静默升级。
    routine_state = _v2_pending_state()
    action, error = _parse_action("r", routine_state, lambda: "run-x")
    assert action is None
    assert error is not None and "already covered by the routine scope" in error

    # 混入不可复用来源的请求上 r 不适用。
    nonreusable_request = _v2_request(
        scope=_excerpt_scope(_source("shell stdout", reusable=False))
    )
    mixed_state = replace(
        ConversationState.new("conversation-r"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.AWAITING_DISCLOSURE),
        provider_disclosure_request=nonreusable_request,
    )
    action, error = _parse_action("r", mixed_state, lambda: "run-x")
    assert action is None
    assert error is not None and "beyond verified workspace file excerpts" in error


def test_consent_ux_r_offer_line_shows_only_for_covered_requests() -> None:
    covered = _v2_request(scope=_excerpt_scope(_source("read_file app/main.py")))
    offer = TerminalRenderer._disclosure_message(request=covered, grant=None)
    assert "  r  Also allow routine conversation data and verified workspace reads" in offer

    routine = _v2_request()
    assert "  r  Also allow" not in TerminalRenderer._disclosure_message(
        request=routine, grant=None
    )

    nonreusable = _v2_request(
        scope=_excerpt_scope(_source("shell stdout", reusable=False))
    )
    assert "  r  Also allow" not in TerminalRenderer._disclosure_message(
        request=nonreusable, grant=None
    )


def test_consent_ux_r_numeric_copy_tracks_the_constants() -> None:
    # r16 同款护栏延伸到 r 文案：数字由权威常量推导（插值化同轮完成），
    # 生产侧退回硬编码即红。非 routine 覆盖请求上 s 行显示
    # "unavailable"（无数字），r 行是唯一带数字的 offer 行——恰为 1 份
    # 即同步。
    covered = _v2_request(scope=_excerpt_scope(_source("read_file app/main.py")))
    offer = TerminalRenderer._disclosure_message(request=covered, grant=None)
    assert offer.count(
        f"up to {CONSENT_MAX_USES} model sends, "
        f"expires in {CONSENT_TTL_SECONDS // 60} minutes"
    ) == 1
    assert "  r  Also allow routine conversation data and verified workspace reads" in offer


def test_consent_ux_r_grant_contract_pins_classes_and_rejects_drift() -> None:
    base = ConversationState.new("conversation-r")
    grant = _read_grant(base)
    # profile 与类别集必须恰为 WORKSPACE_READ_DATA_CLASSES（含全部 routine 类）。
    assert grant.allowed_data_classes == WORKSPACE_READ_DATA_CLASSES
    assert "workspace_excerpt" in grant.allowed_data_classes
    issued = datetime.fromisoformat(grant.issued_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
    assert (expires - issued).total_seconds() == CONSENT_TTL_SECONDS

    # 旧不变量保持：routine grant 不得夹带 workspace_excerpt。
    payload = asdict(grant)
    payload["allowed_data_classes"] = list(WORKSPACE_READ_DATA_CLASSES)
    payload["profile"] = CONSENT_PROFILE_ROUTINE
    with pytest.raises(ValueError, match="exceed the routine scope"):
        ProviderConsentGrantV1(**{**payload, "grant_digest": "0" * 64})

    # workspace-read profile 的类别集不接受增删。
    payload = asdict(grant)
    payload["allowed_data_classes"] = list(ROUTINE_DATA_CLASSES)
    with pytest.raises(ValueError, match="must match the workspace-read scope"):
        ProviderConsentGrantV1(**{**payload, "grant_digest": "0" * 64})


def test_consent_ux_r_grant_roundtrips_through_checkpoint_codec(tmp_path) -> None:
    # schema11 编解码对 r 许可（新 profile + workspace_excerpt 类）保持往返
    # 相等——旧 checkpoint 的 routine 许可不受影响由 n12 既有覆盖。
    base = ConversationState.new("conversation-r")
    state = replace(base, provider_consent_grant=_read_grant(base))

    document = json.loads(_encode_state(state).decode("utf-8"))
    assert (
        document["state"]["provider_consent_grant"]["profile"]
        == CONSENT_PROFILE_WORKSPACE_READ
    )
    path = tmp_path / "conversation.json"
    _write_state(path, state)
    assert (
        LocalCheckpointStore(path).load().state.provider_consent_grant
        == state.provider_consent_grant
    )


def _background_binding() -> BackgroundOccurrenceBindingV1:
    return BackgroundOccurrenceBindingV1.create(
        automation_id="automation:nightly-report",
        automation_revision=1,
        occurrence_id="occurrence:0000",
        occurrence_index=0,
        scheduled_for_utc="2026-10-24T00:00:00Z",
        definition_digest="1" * 64,
        grant_digest="2" * 64,
        claim_authority_digest="3" * 64,
        claim_capability_digest="4" * 64,
        checkpoint_identity_digest="5" * 64,
        deadline_utc="2026-10-24T00:10:00Z",
        model_call_limit=4,
        tool_call_limit=8,
        sandbox_command_limit=2,
        browser_action_limit=3,
        max_input_tokens=20_000,
        max_output_tokens=4_000,
    )


@pytest.mark.parametrize(
    "profile", [CONSENT_PROFILE_ROUTINE, CONSENT_PROFILE_WORKSPACE_READ]
)
def test_consent_ux_background_occurrence_never_consumes_session_grant(profile) -> None:
    """调值轮 B2a（2026-10-24）：后台 occurrence 的授权隔离是结构性的。

    loop 的后台分支只认 v1 精确 receipt（``_required_disclosure``），不进
    v2 grant 机器——即使交互会话持有 ACTIVE 的 routine/read-scope grant 且
    类别完全覆盖，后台 send 也必须停在 AWAITING_DISCLOSURE 等待独立的披露
    确认，且全程不扣 grant 次数（uses_consumed 恒 0）。此前该性质只有
    loop.py 的分支注释背书，无测试钉住。
    """
    base = ConversationState.new(
        "conversation-background-consent",
        background_occurrence_binding=_background_binding(),
    )
    grant = mint_provider_consent_grant(
        state=base, request=_v2_request(), action_seq=1, now=_T0, profile=profile
    )
    runtime, store, provider = _runtime(
        replace(base, provider_consent_grant=grant),
        _descriptor(),
        run_time_factory=lambda: _T0,
    )

    result = runtime.run_turn(
        _submit(store.state, run_id="run:background"), store.load()
    )

    # 未借用 grant：停在 v1 披露等待，provider 零调用，次数零扣减。
    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    assert store.state.provider_consent_grant.uses_consumed == 0

    request = store.state.provider_disclosure_request
    assert request is not None
    ack = AcknowledgeProviderDisclosure(
        conversation_id=store.state.conversation_id,
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_digest=request.request_digest,
        acknowledged_at=_T0,
    )
    final = runtime.run_turn(ack, store.load())

    # 精确 ack 后 send 发生，但 grant 次数仍然零扣减（后台有独立权威）。
    assert final.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    assert store.state.provider_consent_grant.uses_consumed == 0
    assert store.state.provider_consent_grant.status is ProviderConsentGrantStatus.ACTIVE


def test_consent_ux_r_dispatch_notice_wired_into_runtime_warnings() -> None:
    """调值轮（2026-10-24）：r 许可放行的派发在 runtime 级逐次附带通知。

    PR #11 只钉了 notice 文案本身（unit），loop 两个扣次点的接线
    （reason == grant_workspace_read → warnings 追加）无测试覆盖。本旅程用
    W1 同款 proof 态 + workspace 绑定的 read-scope grant 走真实 Resume 回合：
    上下文含 proof-backed excerpt source，gate 以 grant_workspace_read 放行
    并扣次，RunResult.delivery_warnings 必须带上逐次通知，grant 恰扣 1 次。
    """
    recorded = record_tool_result(
        _executing_state(),
        # fact_id 必须符合 Kernel 的 run:<run>:tool-result:<call> 约定，
        # 否则 _valid_file_proof 不认（W1 的短 id 只服务于转存断言）。
        _result_fact(_proof(), fact_id="run:run-1:tool-result:tool-call-1:3"),
        intent_digest=_INTENT_DIGEST,
    )
    assert recorded.provider_source_proofs, "前提：proof-backed excerpt source 在场"
    grant = mint_provider_consent_grant(
        state=recorded,
        request=_v2_request(scope=_scope(workspace="workspace-1", routine=False)),
        action_seq=2,
        now=_T0,
        profile=CONSENT_PROFILE_WORKSPACE_READ,
    )
    state = replace(
        recorded,
        provider_consent_grant=grant,
        active_run=ActiveRun("run-r-notice"),
    )
    # goal 未完成时裸文本不终态（会继续追拨耗尽脚本），用 BlockedClaim 控制
    # 响应走可终结路径；旅程只关心扣次点的通知接线，不关心 goal 结局。
    terminal = ModelResponse(
        (),
        control=BlockedClaim(
            correlation_id="blocked-r-notice",
            goal_id="goal-1",
            goal_revision=1,
            blocker="wiring journey only",
            safe_attempts=("recorded the excerpt",),
            resume_condition="n/a",
        ),
    )
    runtime, store, provider = _runtime(
        state, _descriptor(), (terminal,), run_time_factory=lambda: _T0
    )

    action = Resume(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
    )
    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 1
    notices = [
        item for item in result.delivery_warnings if item.startswith("read-scope consent:")
    ]
    assert len(notices) == 1
    assert "1 workspace file excerpt(s)" in notices[0]
    assert "31 of 32 model sends left" in notices[0]
    final_grant = store.state.provider_consent_grant
    assert final_grant is not None
    assert final_grant.uses_consumed == 1


def test_consent_ux_r_boundary_inherited_excerpt_revalidates_goal_revision() -> None:
    """P3-1（2026-10-24 PR #11 审计，调值轮修复）：summary 继承的 excerpt 重验。

    压缩边界继承的 workspace_excerpt source 此前原样进入 scope：活 TOOL_RESULT
    的 excerpt 投影每次都按当前 goal 重验（proof 的 boundary_digest 绑定
    goal_id+goal_revision，修订即降级），而 summary 路径不重验——goal 修订后
    旧 revision 的摘录在 r 许可下仍被静默复用。修复后按 proof store 重验，
    失配降 reusable=False（类别如实申报，退回逐次披露决策，r 不再覆盖）。
    """

    from agent.runtime.context import _summary_consent_sources

    stale_proof = _proof()  # 绑定 goal-1 / revision 1
    inherited = ProviderDisclosureSourceV1(
        data_class="workspace_excerpt",
        boundary_digest=stale_proof.boundary_digest,
        label="write_file notes/a.txt",
        reusable=True,
    )
    boundary = ProviderSummarySourceBoundaryV1.create(
        summary_fact_id="summary-1",
        data_classes=("conversation_summary", "system_policy", "workspace_excerpt"),
        sources=(inherited,),
        routine_compatible=False,
    )
    summary_fact = ConversationFact(
        fact_id="summary-1",
        kind=FactKind.CONTEXT_SUMMARY,
        content={"objective": "write the note"},
    )
    goal_v1 = replace(_executing_state().goal, revision=1)  # type: ignore[union-attr]
    goal_v2 = replace(goal_v1, revision=2)

    # goal 已修订（revision 2）：继承 excerpt 的 proof 只绑 revision 1 → 降级。
    revised = replace(
        ConversationState.new("conversation-1"),  # proof 绑定本会话
        goal=goal_v2,
        facts=(summary_fact,),
        provider_source_proofs=(stale_proof,),
        summary_source_boundaries=(boundary,),
    )
    classes, sources = _summary_consent_sources(summary_fact, revised)
    assert "workspace_excerpt" in classes  # 类别如实申报，不静默缩水
    assert sources[0].reusable is False  # 不再可复用 → r 不覆盖

    # 同一 proof 在其绑定的 revision 下（goal revision 1）保持可复用。
    current = replace(
        ConversationState.new("conversation-1"),
        goal=goal_v1,
        facts=(summary_fact,),
        provider_source_proofs=(stale_proof,),
        summary_source_boundaries=(boundary,),
    )
    _, still = _summary_consent_sources(summary_fact, current)
    assert still[0].reusable is True

    # 降级后的 scope 在 r 许可下回到逐次决策（不进 grant_workspace_read）。
    demoted_scope = _scope(
        data_classes=classes,
        sources=sources,
        routine=False,
        goal_id=goal_v2.goal_id,
        goal_revision=goal_v2.revision,
    )
    base = ConversationState.new("conversation-1")
    grant = mint_provider_consent_grant(
        state=base, request=_v2_request(), action_seq=1, now=_T0,
        profile=CONSENT_PROFILE_WORKSPACE_READ,
    )
    gate = evaluate_provider_dispatch(
        state=replace(base, provider_consent_grant=grant),
        descriptor=_descriptor(),
        scope=demoted_scope,
        now=_T0,
        purpose="runtime_progress",
        run_id="run-1",
    )
    assert not gate.admitted and gate.reason == "decision_required"


def test_consent_ux_active_grant_structure_drift_explains_re_prompt() -> None:
    """C1（2026-10-25 旅程实证，安装物复现）：goal 任务的 bootstrap 发送上
    授予 s 后，goal 准入改变 control_schema_digest/tool_bindings（grant 钉死
    铸造时结构），同一 turn 的下一次发送必然重新披露。渲染必须解释"活动
    许可为何不覆盖本请求"——否则提示自相矛盾：一边显示剩余额度、一边
    无说明地再次询问，用户会认为 s 失效或产品失灵。
    """
    base = ConversationState.new("conversation-1")
    # 渲染层用真实墙钟判定 grant 可用性，铸造时间必须取当前时刻。
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    grant = mint_provider_consent_grant(
        state=base, request=_v2_request(), action_seq=1, now=now,
    )
    state = replace(base, provider_consent_grant=grant)

    # 结构漂移：goal 准入后 control schema 改变 + 产品工具绑定出现。
    drifted_scope = replace(
        _scope(
            data_classes=(
                "control_receipts",
                "goal",
                "system_policy",
                "tool_schemas",
                "user_messages",
            ),
            goal_id="goal-1",
            goal_revision=1,
        ),
        control_schema_digest="a" * 64,
        tool_bindings=(
            ProviderConsentToolBindingV1(
                name="write_file",
                identity_digest="b" * 64,
            ),
        ),
    )
    drifted_request = _v2_request(scope=drifted_scope, grant=grant)
    assert drifted_request.grant_eligible is True
    gate = evaluate_provider_dispatch(
        state=state,
        descriptor=_descriptor(),
        scope=drifted_scope,
        now=_T0,
        purpose="runtime_progress",
        run_id="run-1",
    )
    # 前置事实钉死：结构漂移时 gate 确实不放行（安全语义保持）。
    assert not gate.admitted

    message = TerminalRenderer._disclosure_message(
        request=drifted_request, grant=grant
    )
    assert "structure changed since the permission was granted" in message
    assert "Choose s to renew" in message

    # 反例：结构与 grant 一致时不加该行（此时若有提示，原因是别处已解释
    # 的新源，不得误导成结构漂移）。
    same_request = _v2_request(scope=_scope(), grant=grant)
    same_message = TerminalRenderer._disclosure_message(
        request=same_request, grant=grant
    )
    assert "structure changed" not in same_message
    assert "model sends left" in same_message
