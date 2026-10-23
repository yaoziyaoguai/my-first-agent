"""oracle r3 审计（consent-integration-audit-20261023）采纳缺陷的 Red→Green。

- F1(P1)：单次 y 的 routine 桥不得覆盖任意常规类增长——SPEC S5 只豁免
  "授权自身新增的纯控制回执"；conversation_history 等实质新内容加入时
  必须重新决定（那是 s 的职责）。
- F2(P1)：`_run_invalid_repairs` 尾部连续语义在混布停滞序列（invalid →
  transient → invalid）下欠计数；瞬态重试/no-progress facts 是透明停滞，
  不得打断连续链。
- F3(P2)：digest 相等捷径绕过"ack 后新用户消息"判界（纵深防御加固）。
- F4(P2)：运输前最终重验不拒绝时钟回拨早于 issued_at（SPEC S3）。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent.runtime.contracts import (
    NO_WORKSPACE_IDENTITY,
    ConversationFact,
    ConversationState,
    FactKind,
    ModelResponse,
    ModelTextBlock,
    ProviderConsentScopeV1,
    ProviderDisclosureReceiptV2,
)
from agent.runtime.loop import (
    _run_invalid_repairs,
)
from agent.runtime.provider_consent import (
    CONTROL_SCHEMA_STRUCTURE_DIGEST,
    build_disclosure_request_v2,
    evaluate_provider_dispatch,
    final_dispatch_expiry_check,
    grant_availability,
    mint_provider_consent_grant,
)

_T0 = "2026-10-23T12:00:00Z"
_DONE = ModelResponse((ModelTextBlock("done"),))


def _descriptor():
    from agent.runtime.contracts import ProviderDescriptor

    return ProviderDescriptor(
        family="openai_compatible",
        model="remote-model",
        canonical_destination="https://api.example.com/v1/chat/completions",
        trust_profile="remote-https-v1",
        remote=True,
    )


def _scope(data_classes=("system_policy", "user_messages"), sources=()):
    return ProviderConsentScopeV1(
        workspace_identity_digest=NO_WORKSPACE_IDENTITY,
        goal_id=None,
        goal_revision=None,
        tool_bindings=(),
        control_schema_digest=CONTROL_SCHEMA_STRUCTURE_DIGEST,
        data_classes=data_classes,
        sources=sources,
        routine_compatible=not sources,
    )


def _user_fact(seq: int) -> ConversationFact:
    return ConversationFact(
        fact_id=f"action:{seq}:user",
        kind=FactKind.USER_MESSAGE,
        content={"text": f"message {seq}"},
    )


# ── F1：routine 桥的类别增长只许 control_receipts ─────────────────────


def test_consent_ux_r3_routine_bridge_rejects_history_growth() -> None:
    small = _scope(("system_policy", "user_messages"))
    previous = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=small, grant=None,
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

    # 恢复后 conversation_history 加入：实质新内容，单次 y 不得覆盖（SPEC S5
    # 只豁免 control_receipts；覆盖常规范围是 s 的职责）。
    grown = _scope(
        ("conversation_history", "system_policy", "user_messages")
    )
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=grown,
        now=_T0, purpose="runtime_progress", run_id="resume-1",
    )
    assert not gate.admitted, gate.reason

    # 对照：仅 control_receipts 增长仍可复用（授权自身的簿记）。
    bookkeeping = _scope(
        ("control_receipts", "system_policy", "user_messages")
    )
    ok = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=bookkeeping,
        now=_T0, purpose="runtime_progress", run_id="resume-1",
    )
    assert ok.admitted and ok.consume_receipt


# ── F2：invalid 修复计数的混布停滞重建 ────────────────────────────────


def _state_with_facts(run_id: str, facts) -> ConversationState:
    from agent.runtime.contracts import ActiveRun, ActiveRunStatus

    return replace(
        ConversationState.new("conversation-1"),
        facts=tuple(facts),
        active_run=ActiveRun(run_id, status=ActiveRunStatus.RUNNABLE),
    )


def _policy_fact(run_id: str, seq: int, code: str) -> ConversationFact:
    return ConversationFact(
        fact_id=f"run:{run_id}:policy:{seq}",
        kind=FactKind.POLICY_RESULT,
        content={"code": code, "text": "x"},
    )


def test_consent_ux_r3_invalid_repairs_rebuild_across_transient_stall() -> None:
    facts = [
        _policy_fact("run-1", 10, "invalid_model_output"),
        _policy_fact("run-1", 11, "provider_transient_retry"),
        _policy_fact("run-1", 12, "invalid_model_output"),
    ]
    # 瞬态重试是透明停滞：重建必须看到 2 次连续 invalid 修复。
    assert _run_invalid_repairs(_state_with_facts("run-1", facts)) == 2


def test_consent_ux_r3_invalid_repairs_rebuild_trailing_transient() -> None:
    facts = [
        _policy_fact("run-1", 10, "invalid_model_output"),
        _policy_fact("run-1", 11, "provider_transient_retry"),
    ]
    # 尾部是瞬态重试且此前有未被打断的 invalid 修复：重建必须为 1。
    assert _run_invalid_repairs(_state_with_facts("run-1", facts)) == 1


def test_consent_ux_r3_invalid_repairs_still_reset_on_valid_output() -> None:
    facts = [
        _policy_fact("run-1", 10, "invalid_model_output"),
        _user_fact(11),  # 有效产出（新用户消息后继续）打断链条
        _policy_fact("run-1", 12, "provider_transient_retry"),
    ]
    assert _run_invalid_repairs(_state_with_facts("run-1", facts)) == 0


# ── F3：digest 相等也要过新用户消息判界 ───────────────────────────────


def test_consent_ux_r3_digest_equal_still_blocked_by_new_user_message() -> None:
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
        facts=(_user_fact(5),),  # ack(seq=2) 之后的新用户消息
        provider_disclosure_request=previous,
        provider_disclosure_receipt=receipt,
    )
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert not gate.admitted


# ── F4：运输前重验拒绝时钟回拨 ────────────────────────────────────────


def test_consent_ux_r3_final_check_rejects_clock_rollback() -> None:
    request = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=_scope(), grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    state = replace(
        ConversationState.new("conversation-1"),
        provider_consent_grant=mint_provider_consent_grant(
            state=ConversationState.new("conversation-1"),
            request=request, action_seq=1, now=_T0,
        ),
    )
    assert state.provider_consent_grant is not None
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=_scope(),
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert gate.admitted and gate.grant_use

    charged = replace(
        state, provider_consent_grant=state.provider_consent_grant.with_use()
    )
    t_plus_10 = (
        datetime.fromisoformat(_T0.replace("Z", "+00:00")) + timedelta(seconds=10)
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")
    t_minus_1 = (
        datetime.fromisoformat(_T0.replace("Z", "+00:00")) - timedelta(seconds=1)
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")

    assert final_dispatch_expiry_check(charged, gate, now=t_plus_10) is None
    assert (
        final_dispatch_expiry_check(charged, gate, now=t_minus_1) == "not_yet_valid"
    )


# ── oracle r4 收尾焦点断言 ─────────────────────────────────────────────


def test_consent_ux_r3_no_progress_fact_is_transparent_between_invalids() -> None:
    """oracle r4 F2 焦点：no_progress_replan_required 是被拒响应的停滞痕迹，
    运行中不重置 invalid_repairs——重建必须同样透明。"""

    facts = [
        _policy_fact("run-1", 10, "invalid_model_output"),
        _policy_fact("run-1", 11, "no_progress_replan_required"),
        _policy_fact("run-1", 12, "invalid_model_output"),
    ]
    assert _run_invalid_repairs(_state_with_facts("run-1", facts)) == 2


def test_consent_ux_r3_charge_rejects_tampered_mark_receipt_consumed() -> None:
    """oracle r4 N1：gate 的 mark_receipt_consumed 与重算不一致必须拒绝。"""

    from dataclasses import replace as _replace

    from agent.runtime.provider_consent import charge_provider_dispatch
    from tests.consent_ux.test_consent_ux_r2_hardening import (
        _exception_ready_state,
    )

    state, file_scope, _b, _r = _exception_ready_state()
    correct = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=file_scope,
        now=_T0, purpose="runtime_progress", run_id="run-1",
    )
    assert correct.admitted and correct.reason == "grant_exception"
    assert correct.mark_receipt_consumed

    tampered = _replace(correct, mark_receipt_consumed=False)
    with pytest.raises(ValueError, match="stale or unapproved"):
        charge_provider_dispatch(
            state, tampered,
            descriptor=_descriptor(), scope=file_scope,
            purpose="runtime_progress", run_id="run-1", now=_T0,
        )

    # 正常例外 gate 仍可扣次并消费票据。
    charged = charge_provider_dispatch(
        state, correct,
        descriptor=_descriptor(), scope=file_scope,
        purpose="runtime_progress", run_id="run-1", now=_T0,
    )
    assert charged.provider_disclosure_receipt.consumed_at is not None


def test_consent_ux_r3_thirty_second_use_passes_final_check() -> None:
    """oracle r4：第 32 次已扣的发送在运输前重验仍有效；第 33 次被拦。"""

    request = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=_scope(), grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    grant = mint_provider_consent_grant(
        state=ConversationState.new("conversation-1"),
        request=request, action_seq=1, now=_T0,
    )
    from functools import reduce as _reduce

    from agent.runtime.provider_consent import charge_provider_dispatch

    grant = _reduce(lambda g, _: g.with_use(), range(31), grant)
    state = replace(ConversationState.new("conversation-1"), provider_consent_grant=grant)
    gate = evaluate_provider_dispatch(
        state=state, descriptor=_descriptor(), scope=_scope(),
        now=_T0, purpose="runtime_progress", run_id="run-32",
    )
    assert gate.admitted and gate.grant_use
    charged = charge_provider_dispatch(
        state, gate,
        descriptor=_descriptor(), scope=_scope(),
        purpose="runtime_progress", run_id="run-32", now=_T0,
    )
    assert charged.provider_consent_grant.uses_consumed == 32

    t_late = (
        datetime.fromisoformat(_T0.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).astimezone(UTC).isoformat().replace("+00:00", "Z")
    assert final_dispatch_expiry_check(charged, gate, now=t_late) is None

    gate_33 = evaluate_provider_dispatch(
        state=charged, descriptor=_descriptor(), scope=_scope(),
        now=t_late, purpose="runtime_progress", run_id="run-33",
    )
    assert not gate_33.admitted
    assert grant_availability(charged.provider_consent_grant, now=t_late) == "exhausted"
