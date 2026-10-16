from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimitError, ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ContinuationPhase,
    ControlReceipt,
    ConversationFact,
    ConversationState,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    InteractionState,
    RecoveryRequest,
    Resume,
    SubmitMessage,
    ToolCall,
    canonical_json_digest,
)
from tests.continuity.test_contracts import _goal


def _fact(fact_id: str, kind: FactKind, **content):
    return ConversationFact(fact_id=fact_id, kind=kind, content=content)


def _submit() -> SubmitMessage:
    return SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message="current",
    )


def _full_context_cost(state: ConversationState, action) -> int:
    """用当前动态 control surface 计算恰好容纳全部组的输入成本。"""

    probe = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=100_000, output_reserve=1),
    ).build(state, action, ())
    return probe.budget.estimated_input_tokens


def test_goal_authoritative_source_text_stays_visible_under_pressure(
    tmp_path,
) -> None:
    """R2-B：预算压力下 Goal 权威原文必须真实存在于 ContextPack。

    只引用来源 ID 不能称为"读过全部当前要求"。原始输入与已消费 correction
    的原文在有界压力下必须可见；预算连这些 pinned 原文都放不下时必须以
    ContextLimitError 可读失败，而不是静默裁掉后假称材料齐全。durable
    checkpoint 重开后同一合同成立。
    """
    original = _fact(
        "fact:user:original",
        FactKind.USER_MESSAGE,
        text=(
            "ORIGINAL_REQUIREMENT_UNIQUE: fix the service AND the cli adapter. "
            + "supporting detail " * 400
        ),
    )
    correction = _fact(
        "action:5:user",
        FactKind.USER_MESSAGE,
        text="CORRECTION_UNIQUE: keep both components and the shared limit.",
    )
    filler = tuple(
        _fact(
            f"filler-{index}",
            FactKind.USER_MESSAGE,
            text=f"filler {index} " + "x" * 400,
        )
        for index in range(8)
    )
    action = SubmitMessage(
        conversation_id="conversation-review",
        action_seq=1,
        expected_revision=0,
        run_id="run-review",
        message="continue",
    )

    def _review_state(facts) -> ConversationState:
        return replace(
            ConversationState.new("conversation-review"),
            facts=facts,
            goal=replace(
                _goal(),
                created_from_fact_ids=(original.fact_id, correction.fact_id),
            ),
            active_run=ActiveRun("run-review"),
        )

    state = _review_state((original, *filler, correction))
    full = _full_context_cost(state, action)
    core = _full_context_cost(_review_state((original, correction)), action)
    # 预算容纳"权威原文 + 约一半 filler"：历史确实被裁剪，但来源原文可见。
    squeezed = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=core + (full - core) // 2,
            output_reserve=20,
        ),
    )
    pack = squeezed.build(state, action, ())
    assert pack.budget.excluded_ids, "filler history must actually be evicted"

    serialized = json.dumps(
        [list(message.content) for message in pack.messages]
    )
    assert "ORIGINAL_REQUIREMENT_UNIQUE" in serialized, (
        "authoritative original text must survive context pressure"
    )
    assert "CORRECTION_UNIQUE" in serialized, (
        "consumed correction text must survive context pressure"
    )

    # durable reopen：checkpoint 落盘重载后同一可见性合同成立。
    path = tmp_path / "review.json"
    store = LocalCheckpointStore.initialize(path, state)
    reopened = squeezed.build(store.load().state, action, ())
    assert "ORIGINAL_REQUIREMENT_UNIQUE" in json.dumps(
        [list(message.content) for message in reopened.messages]
    )

    # 预算放不下权威原文本身：可读失败，不静默截断成"只有 ID"。
    with pytest.raises(ContextLimitError):
        KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=300, output_reserve=200),
        ).build(state, action, ())


def test_oldest_non_pinned_groups_are_evicted_deterministically() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact("old-user", FactKind.USER_MESSAGE, text="old " * 80),
            _fact("old-assistant", FactKind.ASSISTANT_MESSAGE, text="reply " * 80),
            _fact("recent-user", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    recent_only = replace(state, facts=(state.facts[-1],))
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=_full_context_cost(recent_only, _submit()) + 20,
            output_reserve=20,
        ),
    )

    first = manager.build(state, _submit(), ())
    second = manager.build(state, _submit(), ())

    assert first == second
    assert "recent-user" in first.budget.included_ids
    assert first.budget.excluded_ids == ("old-user", "old-assistant")


def test_pressure_evicts_oldest_history_group_before_newer_history() -> None:
    # 三个等成本、从旧到新的非 pinned 历史组 + pinned 当前 user。
    # 预算只允许淘汰一个历史组：必须淘汰最旧的 user-old 并保留较新组，
    # 而不是先忘掉较新内容。
    state = replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        facts=(
            _fact("user-old", FactKind.USER_MESSAGE, text="a" * 120),
            _fact("user-mid", FactKind.USER_MESSAGE, text="b" * 120),
            _fact("user-new", FactKind.USER_MESSAGE, text="c" * 120),
            _fact("user-current", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    full = _full_context_cost(state, _submit())
    core = _full_context_cost(replace(state, facts=(state.facts[-1],)), _submit())
    # 恰好容纳“核心 + 两个历史组”：只淘汰一个组就能进入预算。
    keep_one_group = core + math.ceil((full - core) * 2 / 3)
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=keep_one_group + 20, output_reserve=20),
    )

    pack = manager.build(state, _submit(), ())

    assert pack.budget.excluded_ids == ("user-old",)
    assert {"user-mid", "user-new", "user-current"} <= set(pack.budget.included_ids)
    serialized = repr(pack.messages)
    assert "ccc" in serialized
    assert "aaa" not in serialized


def test_exact_input_budget_keeps_all_groups() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact("user-old", FactKind.USER_MESSAGE, text="old context"),
            _fact("user-current", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    full_cost = _full_context_cost(state, _submit())
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=full_cost + 20, output_reserve=20),
    )

    pack = manager.build(state, _submit(), ())

    assert pack.budget.estimated_input_tokens == full_cost
    assert pack.budget.excluded_ids == ()


def test_pending_recovery_tool_group_is_pinned_under_pressure() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        active_run=ActiveRun(
            run_id="run-1",
            status=ActiveRunStatus.AWAITING_RECOVERY,
            phase=ContinuationPhase.EXECUTING,
            pending_request=RecoveryRequest(
                request_id="recovery-1",
                run_id="run-1",
                tool_call_id="call-1",
                binding_digest="intent-1",
                summary="unknown outcome",
            ),
            executing_intent=ExecutingIntentRecord(
                execution_authority=ExecutionAuthorityClass.IN_PROCESS,
                tool_call_id="call-1",
                intent_digest="intent-1",
                idempotency_key="key-1",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
        facts=(
            _fact(
                "calls-1",
                FactKind.TOOL_CALLS,
                calls=[{"tool_call_id": "call-1", "name": "write_file", "arguments": {}}],
            ),
            _fact("old-user", FactKind.USER_MESSAGE, text="old " * 80),
            _fact("recent-user", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    action = Resume(
        conversation_id="conversation-1",
        action_seq=2,
        expected_revision=1,
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=_full_context_cost(state, action),
            output_reserve=20,
        ),
    )

    pack = manager.build(state, action, ())

    assert "calls-1" in pack.budget.included_ids
    assert "recent-user" in pack.budget.included_ids
    assert "old-user" in pack.budget.excluded_ids


def test_pinned_core_too_large_fails_before_any_provider_boundary() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("recent-user", FactKind.USER_MESSAGE, text="x" * 400),),
    )
    manager = KernelContextManager(
        system_policy="policy" * 20,
        limits=ContextLimits(max_input_tokens=30, output_reserve=10),
    )

    with pytest.raises(ContextLimitError) as exc:
        manager.build(state, _submit(), ())

    assert exc.value.code == "context_core_too_large"


def test_context_module_has_no_semantic_compaction_or_provider_call(monkeypatch) -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("recent-user", FactKind.USER_MESSAGE, text="current"),),
    )
    input_limit = _full_context_cost(state, _submit()) + 144
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=input_limit,
            output_reserve=10,
        ),
    )
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("unexpected input"))

    pack = manager.build(state, _submit(), ())

    assert (
        pack.budget.estimated_input_tokens + pack.budget.output_reserve
        <= input_limit
    )


def test_output_reserve_reduces_the_available_input_budget() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(
            _fact("old-user", FactKind.USER_MESSAGE, text="old " * 40),
            _fact("recent-user", FactKind.USER_MESSAGE, text="current"),
        ),
    )
    full_context_cost = _full_context_cost(state, _submit())
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=full_context_cost,
            output_reserve=30,
        ),
    )

    pack = manager.build(state, _submit(), ())

    assert (
        pack.budget.estimated_input_tokens + pack.budget.output_reserve
        <= full_context_cost
    )
    assert "old-user" in pack.budget.excluded_ids


def test_control_receipt_continuity_is_pinned_and_budgeted() -> None:
    receipts = tuple(
        ControlReceipt.create(
            correlation_id=f"control-{index}",
            control_kind="goal_progress",
            goal_id="goal-1",
            goal_revision=1,
            accepted_state_revision=7,
            payload_digest=canonical_json_digest({"note": "progress", "index": index}),
        )
        for index in range(12)
    )
    state = replace(
        ConversationState.new("conversation-1"),
        control_receipts=receipts,
    )
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=100, output_reserve=20),
    )

    with pytest.raises(ContextLimitError) as exc:
        manager.build(state, _submit(), ())

    assert exc.value.code == "context_core_too_large"
