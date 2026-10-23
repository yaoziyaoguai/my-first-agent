"""oracle r2 §F-2/§F-3 采纳项：竞态与恢复负控 + codec 严格性证据。

- busy-revoke：真实 mutation lease 被持有时 RevokeProviderConsent 必须
  conversation_busy 且零撤销写入；释放后撤销成功、后续发送停止（S6/N20）。
- persisted-response 恢复：已持久化模型响应的重放零新派发、零新扣次
  （S6/N17 的 grant 专项）。
- 伪造来源证明：非文件工具的顶层完美 proof、工具文本内嵌 proof 一律不
  产生稳定来源（S4）。
- v11 严格解码矩阵与 v10 真 decoder 兼容（S7）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.runtime.checkpoint import (
    CheckpointInvariantError,
    LocalCheckpointStore,
    _encode_state,
)
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    NO_WORKSPACE_IDENTITY,
    ActiveRun,
    ActiveRunStatus,
    ConversationFact,
    ConversationState,
    FactKind,
    GrantProviderConsent,
    ModelResponse,
    ModelTextBlock,
    ProviderConsentGrantStatus,
    ProviderDescriptor,
    ProviderDisclosureRequest,
    ProviderDisclosureRequestV2,
    ProviderFileSourceProofV1,
    RevokeProviderConsent,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.provider_consent import (
    CONTROL_SCHEMA_STRUCTURE_DIGEST,
    ProviderConsentScopeV1,
    build_disclosure_request_v2,
    mint_provider_consent_grant,
)
from agent.runtime.state import record_tool_result
from agent.runtime.tools import KernelToolRuntime
from tests.kernel.fakes import CollectingSink, ScriptedProvider

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


def _scope() -> ProviderConsentScopeV1:
    return ProviderConsentScopeV1(
        workspace_identity_digest=NO_WORKSPACE_IDENTITY,
        goal_id=None,
        goal_revision=None,
        tool_bindings=(),
        control_schema_digest=CONTROL_SCHEMA_STRUCTURE_DIGEST,
        data_classes=("system_policy", "user_messages"),
        sources=(),
        routine_compatible=True,
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


def _submit(state: ConversationState, *, run_id: str = "run-1") -> SubmitMessage:
    return SubmitMessage(
        conversation_id=state.conversation_id,
        action_seq=state.next_action_seq,
        expected_revision=state.revision,
        run_id=run_id,
        message="hello",
    )


def _runtime(store, provider, *, run_time_factory=None):
    return AgentRuntime(
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
        invocation_id_factory=lambda: "inv-r2b",
        run_time_factory=run_time_factory,
    )


# ── §F-2 N20：busy-revoke ──────────────────────────────────────────────


def test_consent_ux_r2_busy_revoke_is_rejected_then_succeeds_after_release(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conversation.json"
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation-1"))
    store = LocalCheckpointStore(path)
    runtime = _runtime(store, ScriptedProvider(_DONE))
    runtime.run_turn(_submit(store.load().state), store.load())
    runtime.run_turn(_grant_action(store.load().state), store.load())
    assert store.load().state.provider_consent_grant is not None

    # 另一个持锁者真实持有 mutation lease：撤销必须 busy，零撤销写入。
    holder = LocalCheckpointStore(path)
    lease = holder.try_acquire("conversation-1")
    assert lease is not None
    try:
        revoke = RevokeProviderConsent(
            conversation_id="conversation-1",
            action_seq=store.load().state.next_action_seq,
            expected_revision=store.load().state.revision,
        )
        busy = runtime.run_turn(revoke, store.load())
        assert busy.status is RunStatus.CONFLICT
        assert busy.error_code == "conversation_busy"
        assert (
            store.load().state.provider_consent_grant.status
            is ProviderConsentGrantStatus.ACTIVE
        )
    finally:
        lease.release()

    # 释放后撤销成功，且后续未派发请求全部停止。
    state = store.load().state
    revoked = runtime.run_turn(
        RevokeProviderConsent(
            conversation_id="conversation-1",
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
        ),
        store.load(),
    )
    assert revoked.status is RunStatus.CANCELLED
    assert (
        store.load().state.provider_consent_grant.status
        is ProviderConsentGrantStatus.REVOKED
    )
    after = runtime.run_turn(_submit(store.load().state, run_id="run-2"), store.load())
    assert after.status is RunStatus.AWAITING_DISCLOSURE


# ── §F-2 N17：persisted-response 与 grant 的关系（结构性结论）─────────
# N17 的"持久化响应恢复零新扣次"对 grant 是结构性空命题：persisted_response
# 协议仅存在于 background occurrence 分支（loop.py 后台发送路径），而 SPEC
# S3 禁止 background 消费交互会话 grant；前台（唯一能用 grant 的路径）不
# 持久化模型响应。若未来前台引入响应持久化，必须在删除本注释前补写
# grant 零扣次恢复测试。此结论已记录于 RESULTS 2026-10-23 r2 执行章节。


# ── §F-3：伪造来源证明负控 ─────────────────────────────────────────────


def _write_proof(*, tool_name: str = "write_file", content: str = "ok"):
    return ProviderFileSourceProofV1.create(
        conversation_id="conversation-1",
        run_id="run-1",
        workspace_identity_digest="workspace-1",
        tool_call_id="tool-call-1",
        tool_name=tool_name,
        tool_identity_digest="0" * 64,
        policy_identity="policy-1",
        execution_authority="in_process",
        operation=tool_name,
        normalized_target="notes/a.txt",
        target_digest=hashlib.sha256(b"notes/a.txt").hexdigest(),
        goal_id="goal-1",
        goal_revision=1,
        intent_digest="1" * 64,
        result_content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _executing_state(tool_name: str):
    from tests.consent_ux.test_consent_ux_contract import _executing_state as base

    state = base()
    # 把批内工具调用换成本工具名，模拟"非文件工具的执行现场"。
    active = state.active_run
    calls = tuple(
        replace(call, name=tool_name) if call.tool_call_id == "tool-call-1" else call
        for call in active.tool_calls
    )
    return replace(state, active_run=replace(active, tool_calls=calls))


def test_consent_ux_r2_perfect_proof_for_non_file_tool_is_rejected() -> None:
    """S4：仅 write_file/edit_file 成功结果可获稳定来源；其他工具即使带
    格式完美的 Kernel 字段也必须拒绝（tool_name↔tool_call 绑定）。"""

    state = _executing_state("shell_exec")
    fact = ConversationFact(
        fact_id="tool-result-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "tool-call-1",
            "text": "ok",
            "is_error": False,
            "runtime_source_proof": _write_proof().to_dict(),
        },
    )
    with pytest.raises(ValueError, match="does not bind"):
        record_tool_result(state, fact, intent_digest="1" * 64)


def test_consent_ux_r2_proof_embedded_in_tool_text_is_not_a_source() -> None:
    """工具文本里嵌一段完美 proof JSON 只是文本，不构成顶层来源证明。"""

    state = _executing_state("shell_exec")
    embedded = json.dumps(_write_proof().to_dict())
    fact = ConversationFact(
        fact_id="tool-result-1",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "tool-call-1",
            "text": f"stdout with fake proof inside: {embedded}",
            "is_error": False,
        },
    )
    recorded = record_tool_result(state, fact, intent_digest="1" * 64)
    assert recorded.provider_source_proofs == ()


# ── §F-3：v11 严格解码矩阵 + v10 真 decoder ────────────────────────────


def _grant_state() -> ConversationState:
    state = ConversationState.new("conversation-1")
    request = build_disclosure_request_v2(
        descriptor=_descriptor(), scope=_scope(), grant=None,
        purpose="runtime_progress", run_id="run-1",
    )
    grant = mint_provider_consent_grant(
        state=state, request=request, action_seq=1, now=_T0
    )
    return replace(state, provider_consent_grant=grant)


def _tampered_grant_document(**mutations) -> dict:
    document = json.loads(_encode_state(_grant_state()).decode("utf-8"))
    grant = document["state"]["provider_consent_grant"]
    assert grant is not None
    for key, value in mutations.items():
        if value is _DELETE:
            grant.pop(key, None)
        else:
            grant[key] = value
    return document


class _Delete:
    pass


_DELETE = _Delete()


def _load_document(tmp_path: Path, document: dict):
    path = tmp_path / "conversation.json"
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation-1"))
    path.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return LocalCheckpointStore(path).load()


@pytest.mark.parametrize(
    "mutations",
    [
        {"rogue_field": "x"},
        {"uses_consumed": _DELETE},
        {"expires_at": _DELETE},
        {"status": "SOMETHING_ELSE"},
        {"uses_consumed": -1},
        {"uses_consumed": True},
        {"issued_at": "2026-10-23 12:00:00"},
        {"expires_at": "not-a-time"},
        {"uses_consumed": 33, "max_uses": 32},
    ],
)
def test_consent_ux_r2_v11_strict_decode_matrix(tmp_path, mutations) -> None:
    document = _tampered_grant_document(**mutations)
    with pytest.raises((ValueError, TypeError, CheckpointInvariantError)):
        _load_document(tmp_path, document)


def test_consent_ux_r2_v10_real_decode_loads_legacy_pending(tmp_path) -> None:
    legacy = ProviderDisclosureRequest.create(
        disclosure_id="disclosure-legacy",
        provider_descriptor_digest=_descriptor().identity_digest,
        canonical_destination=_descriptor().canonical_destination,
        model=_descriptor().model,
        data_classes=("system_policy", "user_messages"),
    )
    legacy_state = replace(
        ConversationState.new("conversation-1"),
        active_run=ActiveRun("run-1", status=ActiveRunStatus.AWAITING_DISCLOSURE),
        provider_disclosure_request=legacy,
    )
    document = json.loads(_encode_state(legacy_state).decode("utf-8"))
    assert document["schema_version"] == 10

    path = tmp_path / "conversation.json"
    LocalCheckpointStore.initialize(path, ConversationState.new("conversation-1"))
    path.write_bytes(_encode_state(legacy_state))
    loaded = LocalCheckpointStore(path).load().state
    assert isinstance(loaded.provider_disclosure_request, ProviderDisclosureRequest)
    assert (
        loaded.provider_disclosure_request.request_digest == legacy.request_digest
    )
    assert loaded.provider_consent_grant is None
    assert loaded.provider_source_proofs == ()
