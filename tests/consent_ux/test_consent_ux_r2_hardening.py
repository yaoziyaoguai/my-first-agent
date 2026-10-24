"""oracle r2 审计（2026-10-23）采纳缺陷的 Red→Green 加固测试。

对应 oracle 会话 consent-ux-arch-audit-20261023-r2 的 §F-1/§F-2 与本地
采纳裁决（RESULTS 2026-10-23 下午章节）：

- 精确回执桥不得跨越工具定义/control schema 变化或另一个 run/purpose
  （S1/S4：工具定义变化重新决定；S5：新用户消息使待发授权失配）。
- `_exception_is_covered` 必须绑定 receipt↔previous.request_digest。
- 文件例外首用时在同一 transition 消费单次票据；grant 失效/耗尽后旧票据
  不得再放行（S6：不因遗留 y 获得 32 次之外的发送）。
- `charge_provider_dispatch` 重算并校验 gate：未批准或陈旧 gate 拒绝扣次。
- checkpoint 之后、transport 之前跨过到期点必须零 provider 调用。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    NO_WORKSPACE_IDENTITY,
    ConversationState,
    GrantProviderConsent,
    ModelResponse,
    ModelTextBlock,
    ProviderConsentScopeV1,
    ProviderConsentToolBindingV1,
    ProviderDescriptor,
    ProviderDisclosureReceiptV2,
    ProviderDisclosureRequestV2,
    ProviderDisclosureSourceV1,
    RunStatus,
    SubmitMessage,
    canonical_json_digest,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.provider_consent import (
    CONTROL_SCHEMA_STRUCTURE_DIGEST,
    build_disclosure_request_v2,
    charge_provider_dispatch,
    evaluate_provider_dispatch,
    grant_availability,
    mint_provider_consent_grant,
)
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

_T0 = "2026-10-23T12:00:00Z"
_DONE = ModelResponse((ModelTextBlock("done"),))


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        family="openai_compatible",
        model="remote-model",
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _binding(name: str, salt: str) -> ProviderConsentToolBindingV1:
    return ProviderConsentToolBindingV1(
        name=name,
        identity_digest=canonical_json_digest({"name": name, "salt": salt}),
    )


def _source(label: str) -> ProviderDisclosureSourceV1:
    return ProviderDisclosureSourceV1(
        data_class="workspace_excerpt",
        boundary_digest=hashlib.sha256(label.encode("utf-8")).hexdigest(),
        label=label,
        reusable=True,
    )


def _scope(
    *,
    tool_bindings=(),
    sources=(),
    routine=True,
    data_classes=("system_policy", "user_messages"),
    goal_id=None,
    goal_revision=None,
) -> ProviderConsentScopeV1:
    return ProviderConsentScopeV1(
        workspace_identity_digest=NO_WORKSPACE_IDENTITY,
        goal_id=goal_id,
        goal_revision=goal_revision,
        tool_bindings=tool_bindings,
        control_schema_digest=CONTROL_SCHEMA_STRUCTURE_DIGEST,
        data_classes=data_classes,
        sources=sources,
        routine_compatible=routine,
    )


def _grant_for(request: ProviderDisclosureRequestV2) -> object:
    return mint_provider_consent_grant(
        state=ConversationState.new("conversation-1"),
        request=request,
        action_seq=1,
        now=_T0,
    )


# ── §F-1：精确回执桥收紧 ───────────────────────────────────────────────


def test_consent_ux_r2_exact_bridge_rejects_tool_definition_change() -> None:
    """S1/S4：同名工具定义变化必须重新披露，不得经桥自动放行。"""

    old_bindings = (_binding("write_file", "v1"),)
    scope = _scope(tool_bindings=old_bindings)
    previous = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=scope, grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    receipt = ProviderDisclosureReceiptV2(
        receipt_id="r1", request_digest=previous.request_digest,
        acknowledged_action_seq=2, acknowledged_at=_T0, consumed_at=None,
    )
    state = replace(
        ConversationState.new("conversation-1"),
        provider_disclosure_request=previous,
        provider_disclosure_receipt=receipt,
    )

    changed = build_disclosure_request_v2(
        descriptor=_descriptor(),
        # 工具定义 digest 变化（schema/描述/执行属性任一漂移的等价模拟）。
        scope=_scope(tool_bindings=(_binding("write_file", "v2"),)),
        grant=None, purpose="runtime_progress", run_id="run-1",
    )
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(),
        scope=_scope(tool_bindings=(_binding("write_file", "v2"),)),
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert changed.request_digest != previous.request_digest
    assert not gate.admitted, gate.reason
    assert gate.reason == "decision_required"


def test_consent_ux_r2_exact_bridge_requires_same_pending_unit() -> None:
    """S5：单次 y 只绑定原待发单元；新用户消息/purpose 变化不得复用旧票据。

    孤儿 pending 跨重启 resume（run_id 重标为 resume-N）不是新内容，仍可
    复用（N14/E1-B：pending 跨 pause/新进程 ack 可点火）。
    """

    from agent.runtime.contracts import ConversationFact, FactKind

    scope = _scope()
    previous = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=scope, grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    receipt = ProviderDisclosureReceiptV2(
        receipt_id="r1", request_digest=previous.request_digest,
        acknowledged_action_seq=2, acknowledged_at=_T0, consumed_at=None,
    )
    state = replace(
        ConversationState.new("conversation-1"),
        provider_disclosure_request=previous,
        provider_disclosure_receipt=receipt,
    )

    # 孤儿 resume 重标 run_id：同内容，允许（digest 漂移经桥覆盖）。
    orphan_resume = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=scope,
        now=_T0, purpose="runtime_progress", run_id="resume-7",
    )
    assert orphan_resume.admitted and orphan_resume.consume_receipt

    cross_purpose = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=scope,
        now=_T0, purpose="compaction", run_id="run-1",
    )
    assert not cross_purpose.admitted

    # ack（action_seq=2）之后来了新用户消息（action_seq=3）：旧票据失配。
    state_new_user = replace(
        state,
        facts=(
            ConversationFact(
                fact_id="action:3:user",
                kind=FactKind.USER_MESSAGE,
                content={"text": "a brand new instruction"},
            ),
        ),
    )
    after_new_message = evaluate_provider_dispatch(
        state=state_new_user, descriptor=_descriptor(), scope=scope,
        now=_T0, purpose="runtime_progress", run_id="resume-7",
    )
    assert not after_new_message.admitted

    same_unit = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert same_unit.admitted and same_unit.consume_receipt


def test_consent_ux_r2_exception_binds_receipt_to_previous_request() -> None:
    """oracle B2：错配 receipt（批准 A、pending B）不得被识别为例外。"""

    routine_scope = _scope()
    file_classes = ("system_policy", "user_messages", "workspace_excerpt")
    request_a = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=routine_scope, grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    receipt_a = ProviderDisclosureReceiptV2(
        receipt_id="ra", request_digest=request_a.request_digest,
        acknowledged_action_seq=2, acknowledged_at=_T0, consumed_at=None,
    )
    grant = _grant_for(request_a)

    file_scope = _scope(
        data_classes=file_classes,
        sources=(_source("write_file notes/a.txt"),),
        routine=False,
        goal_id="goal-1",
        goal_revision=1,
    )
    request_b = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=file_scope, grant=grant,
        purpose="runtime_progress", run_id="run-1",
    )
    # 有效 ConversationState 的构造不变量在状态层拒绝错配对（真实保护点）；
    # helper 层的 receipt↔previous 绑定是纵深防御（见 _exception_is_covered）。
    with pytest.raises(ValueError, match="receipt must bind"):
        replace(
            ConversationState.new("conversation-1"),
            provider_consent_grant=grant,
            provider_disclosure_request=request_b,
            provider_disclosure_receipt=receipt_a,
        )


# ── §F-1/§F-2：例外消费票据 + 旧票据不得跨越额度失效 ──────────────────


def _exception_ready_state():
    routine_scope = _scope()
    request = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=routine_scope, grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    grant = mint_provider_consent_grant(
        state=ConversationState.new("conversation-1"),
        request=request, action_seq=1, now=_T0,
    )
    file_scope = _scope(
        data_classes=("system_policy", "user_messages", "workspace_excerpt"),
        sources=(_source("write_file notes/a.txt"),),
        routine=False,
        goal_id="goal-1",
        goal_revision=1,
    )
    b_request = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=file_scope, grant=grant,
        purpose="runtime_progress", run_id="run-1",
    )
    b_receipt = ProviderDisclosureReceiptV2(
        receipt_id="rb", request_digest=b_request.request_digest,
        acknowledged_action_seq=3, acknowledged_at=_T0, consumed_at=None,
    )
    state = replace(
        ConversationState.new("conversation-1"),
        provider_consent_grant=grant,
        provider_disclosure_request=b_request,
        provider_disclosure_receipt=b_receipt,
    )
    return state, file_scope, b_request, b_receipt


def test_consent_ux_r2_exception_first_use_consumes_one_time_ticket() -> None:
    """oracle B3：例外首用必须在同一 transition 消费单次票据。"""

    state, file_scope, _b, b_receipt = _exception_ready_state()
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=file_scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert gate.admitted and gate.grant_use

    charged = charge_provider_dispatch(
        state, gate,
        descriptor=_descriptor(), scope=file_scope,
        purpose="runtime_progress", run_id="run-1", now=_T0,
    )
    receipt = charged.provider_disclosure_receipt
    assert isinstance(receipt, ProviderDisclosureReceiptV2)
    assert receipt.consumed_at is not None, "例外首用后单次票据必须已消费"


def test_consent_ux_r2_exhausted_grant_cannot_replay_stale_ticket() -> None:
    """oracle B3 反例：grant 耗尽后，旧未重批的 y 不得再放行一次。"""

    state, file_scope, b_request, b_receipt = _exception_ready_state()
    # 例外首用：扣 grant + 消费票据。
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=file_scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    charged = charge_provider_dispatch(
        state, gate,
        descriptor=_descriptor(), scope=file_scope,
        purpose="runtime_progress", run_id="run-1", now=_T0,
    )
    # 把 grant 用到 32/32。
    grant = charged.provider_consent_grant
    while grant.uses_consumed < 32:
        grant = grant.with_use()
    exhausted = replace(charged, provider_consent_grant=grant)
    assert grant_availability(grant, now=_T0) == "exhausted"

    later = evaluate_provider_dispatch(
        state=exhausted, descriptor=_descriptor(), scope=file_scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert not later.admitted, later.reason
    assert later.reason == "grant_unavailable"


# ── §F-2：charge 重验证 + 运输前最终重验 ──────────────────────────────


def test_consent_ux_r2_charge_rejects_unapproved_gate() -> None:
    state = ConversationState.new("conversation-1")
    scope = _scope()
    denied = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert not denied.admitted
    with pytest.raises(ValueError, match="stale|unapproved|usable"):
        charge_provider_dispatch(
            state, denied,
            descriptor=_descriptor(), scope=scope,
            purpose="runtime_progress", run_id="run-1", now=_T0,
        )


def test_consent_ux_r2_charge_rejects_stale_gate_after_scope_change() -> None:
    request = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=_scope(), grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    receipt = ProviderDisclosureReceiptV2(
        receipt_id="r1", request_digest=request.request_digest,
        acknowledged_action_seq=2, acknowledged_at=_T0, consumed_at=None,
    )
    state = replace(
        ConversationState.new("conversation-1"),
        provider_disclosure_request=request,
        provider_disclosure_receipt=receipt,
    )
    stale_gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=_scope(),
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert stale_gate.admitted
    # 调用方拿旧 gate 去扣一份已经变化的 scope：必须拒绝。
    changed_scope = _scope(
        data_classes=("system_policy", "user_messages", "workspace_excerpt"),
        sources=(_source("write_file notes/a.txt"),),
        routine=False,
    )
    with pytest.raises(ValueError, match="stale"):
        charge_provider_dispatch(
            state, stale_gate,
            descriptor=_descriptor(), scope=changed_scope,
            purpose="runtime_progress", run_id="run-1", now=_T0,
        )


def test_consent_ux_r2_pre_transport_expiry_recheck_zero_sends() -> None:
    """S6：校验后跨过到期点，派发前最后重验必须零 provider 调用。"""

    clock = {"n": 0}

    def time_factory() -> str:
        clock["n"] += 1
        if clock["n"] <= 4:
            return _T0
        # gate/charge 通过后，最终重验时已跨过 60 分钟 TTL。
        return (
            datetime.fromisoformat(_T0.replace("Z", "+00:00")) + timedelta(minutes=61)
        ).astimezone(UTC).isoformat().replace("+00:00", "Z")

    state = ConversationState.new("conversation-1")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(_DONE)
    runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=_descriptor(),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "inv-r2",
        run_time_factory=time_factory,
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-1",
        message="hello",
    )
    runtime.run_turn(submit, store.load())
    request = store.state.provider_disclosure_request
    assert isinstance(request, ProviderDisclosureRequestV2)
    grant_action = GrantProviderConsent(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_digest=request.request_digest,
        scope_digest=request.scope_digest,
    )
    result = runtime.run_turn(grant_action, store.load())
    # 扣次可以发生（失败不退款），但到期后不得再发送。
    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []


# ── P4（2026-10-24 审计 r5）：gate→charge 毫秒窗口 ────────────────────


def test_consent_ux_p4_gate_charge_window_routes_to_disclosure_not_fatal() -> None:
    """gate 通过后、扣次前跨过到期点（2026-10-24 P4/r5）。

    charge_provider_dispatch 对陈旧 gate 抛 ValueError；S6 合同要求与
    transport 前最后重验同路——重新要求披露决策（零 provider 调用、
    零扣次），而不是 FAILED_FATAL runtime_failure。
    """

    clock = {"n": 0}

    def time_factory() -> str:
        clock["n"] += 1
        if clock["n"] <= 5:
            return _T0
        # gate（第 5 个时钟调用）用 T0 通过；第 6 个调用是扣次重算，已跨过
        # 60 分钟 grant TTL（探针 /tmp/mfa-improve/p4/probe_charge_index.py
        # 实测本窗口修前 failed_fatal runtime_failure，零 provider 调用）。
        return (
            datetime.fromisoformat(_T0.replace("Z", "+00:00")) + timedelta(minutes=61)
        ).astimezone(UTC).isoformat().replace("+00:00", "Z")

    state = ConversationState.new("conversation-1")
    store = InMemoryCheckpointStore(state)
    provider = ScriptedProvider(_DONE)
    runtime = AgentRuntime(
        provider=provider,
        provider_descriptor=_descriptor(),
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        ),
        tool_runtime=KernelToolRuntime(()),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "inv-p4-window",
        run_time_factory=time_factory,
    )
    submit = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id="run-1",
        message="hello",
    )
    runtime.run_turn(submit, store.load())
    request = store.state.provider_disclosure_request
    assert isinstance(request, ProviderDisclosureRequestV2)
    grant_action = GrantProviderConsent(
        conversation_id="conversation-1",
        action_seq=store.state.next_action_seq,
        expected_revision=store.state.revision,
        request_digest=request.request_digest,
        scope_digest=request.scope_digest,
    )
    result = runtime.run_turn(grant_action, store.load())
    # 陈旧 gate 在扣次处被拦：出路是重新决策，不是致命失败。
    assert result.status is RunStatus.AWAITING_DISCLOSURE
    assert provider.calls == []
    grant = store.state.provider_consent_grant
    assert grant is not None
    assert grant.uses_consumed == 0, "charge 前被拦下，不得产生许可消耗"
