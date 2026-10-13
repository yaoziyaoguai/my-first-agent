"""020 长会话压缩:可移除完整 closed turn 集的纯校验合同。

只验证 ``agent.runtime.compaction_rules`` 的 turn grammar 与移除判定边界,
以及 ``agent.runtime.context`` 私有 candidate selector
``_compaction_candidate_fact_ids`` 的确定性候选选择;不涉及 summary 应用、
archive、CAS、trigger/planner 或 Runtime 任何状态迁移。可移除集不必是
``state.facts`` 的连续前缀:精确覆盖若干完整 closed turn(可非连续)即可;
Goal/Evidence 引用的 turn 受保护,未闭合尾 turn 不可选择。
唯一的 ``CONTEXT_SUMMARY`` 可位于完整 turn 之间的边界或末尾(非首位
summary 是第一批压缩后的合法中间产物),但不得多于一个、不得位于 turn 内。
未终止段后的新 user 边界是唯一窄类型的 ineligible 历史:parser 抛
``CompactionIneligibleHistoryError``,选择侧捕获后零候选,移除侧不捕获、
继续拒绝;其余畸形历史与畸形 tool 批次仍抛普通 ValueError。
"""

from __future__ import annotations

import pytest

import agent.runtime.context as context_module
from agent.runtime.compaction_rules import (
    CompactionIneligibleHistoryError,
    parse_compaction_turns,
    validate_compaction_removal,
)
from agent.runtime.contracts import (
    ActiveRun,
    ConversationFact,
    ConversationState,
    EvidenceOracleKind,
    EvidenceRecord,
    FactKind,
    GoalFrame,
    GoalStatus,
    ProposedCriterion,
)


def _user(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.USER_MESSAGE,
        content={"text": fact_id},
    )


def _assistant(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.ASSISTANT_MESSAGE,
        content={"text": fact_id},
    )


def _tool_calls(fact_id: str, *tool_call_ids: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_CALLS,
        content={
            "calls": [
                {"tool_call_id": call_id, "name": "echo", "arguments": {}}
                for call_id in tool_call_ids
            ],
        },
    )


def _tool_result(fact_id: str, tool_call_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_RESULT,
        content={"tool_call_id": tool_call_id, "text": "ok"},
    )


def _summary(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.CONTEXT_SUMMARY,
        content={
            "objective": "earlier conversation objective",
            "constraints": [],
            "decisions": [],
            "completed": [],
            "open_items": [],
            "key_references": [],
            "source_checkpoint_digest": "0" * 64,
            "source_fact_ids_digest": "1" * 64,
        },
    )


def _policy(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.POLICY_RESULT,
        content={"code": "blocked_claim"},
    )


def _goal(*created_from_fact_ids: str) -> GoalFrame:
    return GoalFrame(
        goal_id="goal-1",
        revision=1,
        created_from_fact_ids=created_from_fact_ids,
        workspace_identity_digest="workspace-digest-1",
        user_outcome="persist the note",
        beneficiary="user",
        targets=("workspace",),
        scope=("workspace/fixtures",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-1", "fixture note exists"),),
        admitted_criteria=(),
        authority_snapshot="authority-1",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )


def _evidence(*source_fact_ids: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="evidence-1",
        goal_id="goal-1",
        goal_revision=1,
        criterion_id="criterion-1",
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate_digest="2" * 64,
        source_fact_ids=source_fact_ids,
        source_digest="3" * 64,
        oracle_identity="oracle-1",
        passed=True,
        observed_at="2026-08-02T00:00:00Z",
    )


def _state(
    *facts: ConversationFact,
    goal: GoalFrame | None = None,
    evidence_records: tuple[EvidenceRecord, ...] = (),
    active_run: ActiveRun | None = None,
) -> ConversationState:
    return ConversationState(
        conversation_id="conversation-1",
        facts=facts,
        goal=goal,
        evidence_records=evidence_records,
        active_run=active_run,
    )


def test_full_closed_turn_selection_returns_facts_in_order() -> None:
    summary = _summary("fact:summary:1")
    facts = (
        summary,
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _tool_calls("action:4:calls", "call-a", "call-b"),
        _tool_result("action:5:result", "call-a"),
        _tool_result("action:6:result", "call-b"),
        _assistant("action:7:assistant"),
        _user("action:8:user"),
        _assistant("action:9:assistant"),
    )
    state = _state(*facts)
    # 传入顺序打乱:合法输入不要求按 facts 顺序提交,但返回必须按原顺序。
    removable = ("action:9:assistant", "action:1:user", "fact:summary:1")

    result = validate_compaction_removal(state, (*removable, *(
        fact.fact_id
        for fact in facts
        if fact.fact_id not in removable
    )))

    assert result == facts
    # 纯校验:state 不被修改。
    assert state.facts == facts
    assert state.revision == 0


def test_active_managed_resource_owner_turn_is_not_compactable() -> None:
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "managed-start"),
        ConversationFact(
            fact_id="action:3:result",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": "managed-start",
                "text": '{"resource_ref":"managed-web-1","status":"ready"}',
                "executed": True,
                "is_error": False,
                "metadata": {"tool_name": "managed_web_start"},
            },
        ),
        _assistant("action:4:assistant"),
    )

    with pytest.raises(ValueError, match="active-resource owner turns"):
        validate_compaction_removal(
            _state(*facts),
            tuple(fact.fact_id for fact in facts),
        )


def test_single_closed_turn_without_summary_is_valid() -> None:
    facts = (_user("action:1:user"), _assistant("action:2:assistant"))
    result = validate_compaction_removal(_state(*facts), ("action:2:assistant", "action:1:user"))
    assert result == facts


def test_turn_without_earlier_prefix_is_removable() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
    )
    result = validate_compaction_removal(
        _state(*facts), ("action:3:user", "action:4:assistant")
    )
    assert result == facts[2:]


def test_noncontiguous_turn_union_with_summary_is_valid() -> None:
    facts = (
        _summary("fact:summary:1"),
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
        _user("action:5:user"),
        _assistant("action:6:assistant"),
    )
    # 保留中间 turn 2,只移除 summary+turn 1+turn 3:非连续并集合法。
    result = validate_compaction_removal(
        _state(*facts),
        (
            "action:5:user",
            "fact:summary:1",
            "action:6:assistant",
            "action:1:user",
            "action:2:assistant",
        ),
    )
    assert result == (
        _summary("fact:summary:1"),
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:5:user"),
        _assistant("action:6:assistant"),
    )


def test_summary_may_be_retained_while_removing_turns() -> None:
    facts = (
        _summary("fact:summary:1"),
        _user("action:1:user"),
        _assistant("action:2:assistant"),
    )
    result = validate_compaction_removal(
        _state(*facts), ("action:1:user", "action:2:assistant")
    )
    assert result == facts[1:]


def test_summary_without_any_turn_is_rejected() -> None:
    facts = (_summary("fact:summary:1"), _user("action:1:user"), _assistant("action:2:assistant"))
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), ("fact:summary:1",))


def test_summary_between_turns_is_valid() -> None:
    # 非首位 summary 是第一批压缩后的合法中间产物:位于完整 turn 之间的
    # 边界。turn 2 可单独移除,也可连同 summary 与 turn 1 一起移除。
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _summary("fact:summary:1"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
    )

    later = validate_compaction_removal(_state(*facts), ("action:3:user", "action:4:assistant"))
    assert later == facts[3:]
    earlier = validate_compaction_removal(
        _state(*facts),
        ("action:1:user", "action:2:assistant", "fact:summary:1"),
    )
    assert earlier == facts[:3]


def test_summary_at_end_is_valid() -> None:
    # 唯一 summary 位于最后一个完整 turn 之后:同样是合法边界。
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _summary("fact:summary:1"),
    )

    turn_only = validate_compaction_removal(
        _state(*facts), ("action:1:user", "action:2:assistant")
    )
    assert turn_only == facts[:2]
    with_summary = validate_compaction_removal(
        _state(*facts), ("action:1:user", "action:2:assistant", "fact:summary:1")
    )
    assert with_summary == facts


def test_summary_inside_closed_turn_is_rejected() -> None:
    # summary 插在 TOOL_CALLS 与 TOOL_RESULT 之间:turn 内 summary,
    # 同时拆开 tool 批次,一律拒绝。
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a"),
        _summary("fact:summary:1"),
        _tool_result("action:3:result", "call-a"),
        _assistant("action:4:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_summary_inside_unclosed_turn_is_rejected() -> None:
    # 尾部未闭合 turn 内出现 summary:规则未覆盖的 turn 内位置一律拒绝。
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _summary("fact:summary:1"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_second_summary_is_rejected() -> None:
    # 至多一个 CONTEXT_SUMMARY:两个(即使都在合法边界)一律拒绝。
    facts = (
        _summary("fact:summary:1"),
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _summary("fact:summary:2"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_half_turn_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(
            _state(*facts),
            ("action:1:user", "action:2:assistant", "action:3:user"),
        )


def test_open_turn_with_active_run_is_rejected() -> None:
    # active_run 存在时,最新尚未闭合的 turn(缺 ASSISTANT_MESSAGE)自然不可移除。
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _tool_calls("action:4:calls", "call-a"),
        _tool_result("action:5:result", "call-a"),
    )
    state = _state(*facts, active_run=ActiveRun(run_id="run-1"))
    with pytest.raises(ValueError):
        validate_compaction_removal(
            state,
            tuple(fact.fact_id for fact in facts),
        )


def test_half_tool_batch_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a", "call-b"),
        _tool_result("action:3:result", "call-a"),
        _assistant("action:4:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_tool_calls_without_any_result_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a"),
        _assistant("action:3:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_orphan_tool_result_without_calls_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _tool_result("action:2:result", "call-a"),
        _assistant("action:3:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_duplicate_tool_result_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a"),
        _tool_result("action:3:result", "call-a"),
        _tool_result("action:4:result", "call-a"),
        _assistant("action:5:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_result_for_unknown_tool_call_id_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a"),
        _tool_result("action:3:result", "call-a"),
        _tool_result("action:4:result", "call-b"),
        _assistant("action:5:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_policy_between_turns_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _policy("action:3:policy"),
        _user("action:4:user"),
        _assistant("action:5:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), tuple(fact.fact_id for fact in facts))


def test_goal_source_fact_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
    )
    state = _state(*facts, goal=_goal("action:1:user"))
    with pytest.raises(ValueError):
        validate_compaction_removal(state, tuple(fact.fact_id for fact in facts))


def test_evidence_source_fact_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
    )
    state = _state(
        *facts,
        goal=_goal("action:3:user"),
        evidence_records=(_evidence("action:2:assistant"),),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(state, tuple(fact.fact_id for fact in facts))


def test_noncontiguous_turns_around_protected_turns_are_removable() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
        _user("action:5:user"),
        _assistant("action:6:assistant"),
        _user("action:7:user"),
        _assistant("action:8:assistant"),
    )
    # turn 1 被 Goal 引用、turn 3 被 Evidence 引用:只有 turn 2 与 turn 4 可移除。
    state = _state(
        *facts,
        goal=_goal("action:1:user"),
        evidence_records=(_evidence("action:6:assistant"),),
    )

    result = validate_compaction_removal(
        state,
        ("action:8:assistant", "action:3:user", "action:4:assistant", "action:7:user"),
    )

    assert result == facts[2:4] + facts[6:8]
    assert state.revision == 0


def test_goal_protected_turn_rejects_selection_with_other_turns() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
        _user("action:5:user"),
        _assistant("action:6:assistant"),
        _user("action:7:user"),
        _assistant("action:8:assistant"),
    )
    state = _state(*facts, goal=_goal("action:1:user"))
    with pytest.raises(ValueError):
        validate_compaction_removal(
            state,
            (
                "action:1:user",
                "action:2:assistant",
                "action:3:user",
                "action:4:assistant",
                "action:7:user",
                "action:8:assistant",
            ),
        )


def test_evidence_protected_turn_rejects_selection_with_other_turns() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _assistant("action:4:assistant"),
        _user("action:5:user"),
        _assistant("action:6:assistant"),
        _user("action:7:user"),
        _assistant("action:8:assistant"),
    )
    state = _state(
        *facts,
        goal=_goal("action:1:user"),
        evidence_records=(_evidence("action:6:assistant"),),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(
            state,
            (
                "action:5:user",
                "action:6:assistant",
                "action:7:user",
                "action:8:assistant",
            ),
        )


def test_policy_fact_is_removed_with_its_turn() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _policy("action:4:policy"),
        _tool_calls("action:5:calls", "call-a"),
        _tool_result("action:6:result", "call-a"),
        _assistant("action:7:assistant"),
    )
    # turn 内 POLICY_RESULT 是普通 fact:随整个 turn 一起移除。
    result = validate_compaction_removal(
        _state(*facts),
        (
            "action:3:user",
            "action:4:policy",
            "action:5:calls",
            "action:6:result",
            "action:7:assistant",
        ),
    )
    assert result == facts[2:]


def test_turn_missing_its_policy_fact_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _policy("action:4:policy"),
        _tool_calls("action:5:calls", "call-a"),
        _tool_result("action:6:result", "call-a"),
        _assistant("action:7:assistant"),
    )
    with pytest.raises(ValueError):
        validate_compaction_removal(
            _state(*facts),
            (
                "action:3:user",
                "action:5:calls",
                "action:6:result",
                "action:7:assistant",
            ),
        )


def test_half_tool_selection_inside_turn_is_rejected() -> None:
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a", "call-b"),
        _tool_result("action:3:result", "call-a"),
        _tool_result("action:4:result", "call-b"),
        _assistant("action:5:assistant"),
        _user("action:6:user"),
        _assistant("action:7:assistant"),
    )
    # turn 1 缺一个 TOOL_RESULT:半 tool 批次不可与完整 turn 2 混合提交。
    with pytest.raises(ValueError):
        validate_compaction_removal(
            _state(*facts),
            (
                "action:1:user",
                "action:2:calls",
                "action:3:result",
                "action:5:assistant",
                "action:6:user",
                "action:7:assistant",
            ),
        )


def test_empty_ids_are_rejected() -> None:
    facts = (_user("action:1:user"), _assistant("action:2:assistant"))
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), ())


def test_duplicate_ids_are_rejected() -> None:
    facts = (_user("action:1:user"), _assistant("action:2:assistant"))
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), ("action:1:user", "action:1:user"))


def test_unknown_id_is_rejected() -> None:
    facts = (_user("action:1:user"), _assistant("action:2:assistant"))
    with pytest.raises(ValueError):
        validate_compaction_removal(_state(*facts), ("action:1:user", "action:missing"))


# --------------------------------------------------------------------------- #
# ineligible 历史:未终止段后的新 user 边界(合法但保守不可压缩)
# --------------------------------------------------------------------------- #


def test_parse_raises_ineligible_subtype_for_new_user_boundary() -> None:
    # failed_fatal 只留下 user+policy 的未终止段,新的 user 边界出现在
    # ASSISTANT_MESSAGE 终结之前:抛窄类型子异常,而不是普通 ValueError。
    facts = (
        _user("action:1:user"),
        _policy("action:2:policy"),
        _user("action:3:user"),
    )

    with pytest.raises(CompactionIneligibleHistoryError):
        parse_compaction_turns(facts)


def test_parse_raises_ineligible_subtype_after_covered_tool_batches() -> None:
    # 段内 TOOL_CALLS 批次已通过 exact-result 覆盖检查后出现新 user 边界:
    # 同样是识别出的 ineligible 历史。
    facts = (
        _user("action:1:user"),
        _tool_calls("action:2:calls", "call-a", "call-b"),
        _tool_result("action:3:result", "call-a"),
        _tool_result("action:4:result", "call-b"),
        _policy("action:5:policy"),
        _user("action:6:user"),
    )

    with pytest.raises(CompactionIneligibleHistoryError):
        parse_compaction_turns(facts)


def test_validate_removal_rejects_ineligible_history_via_subtype() -> None:
    # 移除校验不捕获子类型:任何缩减尝试都被同一异常拒绝。
    facts = (
        _user("action:1:user"),
        _policy("action:2:policy"),
        _user("action:3:user"),
    )
    state = _state(*facts)

    with pytest.raises(CompactionIneligibleHistoryError):
        validate_compaction_removal(state, tuple(fact.fact_id for fact in facts))


def test_malformed_tool_batches_raise_plain_value_error_not_ineligible() -> None:
    # 孤立/重复/缺失/错配的 tool result 与段内 summary 即使出现在新 user
    # 边界之前,也仍是普通 ValueError,不得被重分类为窄类型子异常。
    malformed = (
        # 孤立 TOOL_RESULT。
        (
            _user("action:1:user"),
            _tool_result("action:2:result", "call-a"),
            _user("action:3:user"),
        ),
        # 重复 TOOL_RESULT。
        (
            _user("action:1:user"),
            _tool_calls("action:2:calls", "call-a"),
            _tool_result("action:3:result", "call-a"),
            _tool_result("action:4:result", "call-a"),
            _user("action:5:user"),
        ),
        # 缺失 TOOL_RESULT:批次被新 user 边界拆开。
        (
            _user("action:1:user"),
            _tool_calls("action:2:calls", "call-a", "call-b"),
            _tool_result("action:3:result", "call-a"),
            _user("action:4:user"),
        ),
        # 错配 TOOL_RESULT:绑定了批次外/未知的 tool_call_id。
        (
            _user("action:1:user"),
            _tool_calls("action:2:calls", "call-a"),
            _tool_result("action:3:result", "call-b"),
            _user("action:4:user"),
        ),
        # 未终止段内出现 summary:仍不是合法边界。
        (
            _user("action:1:user"),
            _policy("action:2:policy"),
            _summary("fact:summary:1"),
            _user("action:3:user"),
        ),
    )
    for facts in malformed:
        with pytest.raises(ValueError) as parse_error:
            parse_compaction_turns(facts)
        assert not isinstance(
            parse_error.value, CompactionIneligibleHistoryError
        )
        with pytest.raises(ValueError) as validate_error:
            validate_compaction_removal(
                _state(*facts), tuple(fact.fact_id for fact in facts)
            )
        assert not isinstance(
            validate_error.value, CompactionIneligibleHistoryError
        )


def test_candidate_returns_empty_for_ineligible_history() -> None:
    # 混合历史:若无未终止段,turn 1 本会被选中(retain=0);解析在新的
    # user 边界处抛窄类型子异常,选择侧捕获后降级为零候选,不升级为错误。
    facts = (
        _user("action:1:user"),
        _assistant("action:2:assistant"),
        _user("action:3:user"),
        _policy("action:4:policy"),
        _user("action:5:user"),
    )
    state = _state(*facts, active_run=ActiveRun(run_id="run-1"))

    assert _candidate()(state, retain_recent_turns=0) == ()


# --------------------------------------------------------------------------- #
# _compaction_candidate_fact_ids:KernelContextManager 私有确定性候选选择
# (只选 ids,不做 trigger/planner/context/provider 的任何事)
# --------------------------------------------------------------------------- #


def _candidate():
    helper = getattr(context_module, "_compaction_candidate_fact_ids", None)
    if helper is None:
        pytest.fail("020 requires context._compaction_candidate_fact_ids")
    return helper


def _turn(n: int) -> tuple[ConversationFact, ConversationFact]:
    """第 n 个 closed turn:user fact id 为 2n-1,assistant 为 2n。"""

    return (
        _user(f"action:{2 * n - 1}:user"),
        _assistant(f"action:{2 * n}:assistant"),
    )


def _turn_ids(n: int) -> tuple[str, str]:
    return (f"action:{2 * n - 1}:user", f"action:{2 * n}:assistant")


def test_candidate_retains_latest_four_closed_turns_by_default() -> None:
    facts = tuple(fact for n in range(1, 9) for fact in _turn(n))
    state = _state(*facts)

    candidate = _candidate()(state)

    # 默认 retain_recent_turns=4:最新 4 个 closed turn 无条件保留,其余全选。
    expected = tuple(fact_id for n in range(1, 5) for fact_id in _turn_ids(n))
    assert candidate == expected
    # 合同:非空候选必须通过 validate_compaction_removal。
    removed = validate_compaction_removal(state, candidate)
    assert tuple(fact.fact_id for fact in removed) == candidate


def test_candidate_protects_goal_turn_but_selects_later_unprotected_turns() -> None:
    facts = tuple(fact for n in range(1, 7) for fact in _turn(n))
    # goal 引用 turn 1;retain=2 时最新两个保留,turn 1 受保护,turns 2-4 可选。
    state = _state(*facts, goal=_goal("action:1:user"))

    candidate = _candidate()(state, retain_recent_turns=2)

    expected = tuple(fact_id for n in range(2, 5) for fact_id in _turn_ids(n))
    assert candidate == expected


def test_candidate_protects_evidence_turn_in_the_middle() -> None:
    facts = tuple(fact for n in range(1, 7) for fact in _turn(n))
    # goal 保护 turn 1,evidence 引用 turn 3 的 assistant fact;retain=1 时
    # 最新 1 个保留,turns 2/4/5 可选(混合两类保护均原位保留)。
    state = _state(
        *facts,
        goal=_goal("action:1:user"),
        evidence_records=(_evidence("action:6:assistant"),),
    )

    candidate = _candidate()(state, retain_recent_turns=1)

    expected = tuple(fact_id for n in (2, 4, 5) for fact_id in _turn_ids(n))
    assert candidate == expected


def test_candidate_never_selects_unclosed_trailing_turn() -> None:
    closed = tuple(fact for n in range(1, 5) for fact in _turn(n))
    # 尾部未闭合 turn(缺 ASSISTANT_MESSAGE),与 active_run 并存。
    open_turn = (
        _user("action:9:user"),
        _tool_calls("action:10:calls", "call-open"),
        _tool_result("action:11:result", "call-open"),
    )
    state = _state(*closed, *open_turn, active_run=ActiveRun(run_id="run-1"))

    candidate = _candidate()(state, retain_recent_turns=1)

    expected = tuple(fact_id for n in range(1, 4) for fact_id in _turn_ids(n))
    assert candidate == expected
    assert not frozenset(candidate) & {
        "action:9:user",
        "action:10:calls",
        "action:11:result",
    }
    removed = validate_compaction_removal(state, candidate)
    assert tuple(fact.fact_id for fact in removed) == candidate


def test_candidate_includes_existing_summary_for_incremental_replacement() -> None:
    facts = (
        _summary("fact:summary:1"),
        *(fact for n in range(1, 7) for fact in _turn(n)),
    )
    state = _state(*facts)

    candidate = _candidate()(state, retain_recent_turns=2)

    # 至少选中一个 turn 时,开头已有 CONTEXT_SUMMARY 一并选中以便增量替换。
    expected = (
        "fact:summary:1",
        *(fact_id for n in range(1, 5) for fact_id in _turn_ids(n)),
    )
    assert candidate == expected


def test_candidate_returns_empty_when_no_turn_is_selectable() -> None:
    # turns 数不超过 retain:无候选 turn,summary 也不被单独选中。
    facts = (_summary("fact:summary:1"), *_turn(1), *_turn(2))

    assert _candidate()(_state(*facts)) == ()


def test_candidate_with_retain_zero_selects_all_unprotected_closed_turns() -> None:
    facts = tuple(fact for n in range(1, 5) for fact in _turn(n))
    state = _state(*facts)

    candidate = _candidate()(state, retain_recent_turns=0)

    assert candidate == tuple(fact.fact_id for fact in facts)


def test_candidate_max_turns_limits_selection_to_oldest_eligible_turns() -> None:
    # summary + 7 turns:turn 1 受 goal 保护,retain=4 保留 turns 4-7,
    # eligible 区是 turns 1-3,其中 turns 2/3 可选。
    facts = (
        _summary("fact:summary:1"),
        *(fact for n in range(1, 8) for fact in _turn(n)),
    )
    state = _state(*facts, goal=_goal("action:1:user"))

    # 默认不传 max_turns:全部两个 eligible turn 都被选中。
    default = _candidate()(state, retain_recent_turns=4)
    assert default == (
        "fact:summary:1",
        *_turn_ids(2),
        *_turn_ids(3),
    )

    # max_turns=1:只取最老的一个 eligible turn(turn 2);protected turn 1
    # 不消耗名额;summary 仍随被选中的 turn 一并放首位。
    limited = _candidate()(state, retain_recent_turns=4, max_turns=1)
    assert limited == ("fact:summary:1", *_turn_ids(2))
    removed = validate_compaction_removal(state, limited)
    assert tuple(fact.fact_id for fact in removed) == limited


def test_candidate_rejects_invalid_max_turns() -> None:
    state = _state(*_turn(1))
    # 0/负数/bool/非 int 一律拒绝,与 retain_recent_turns 同一 fail-closed 风格。
    for value in (0, -1, True, False, "1", 1.0):
        with pytest.raises(ValueError):
            _candidate()(state, max_turns=value)  # type: ignore[arg-type]


def test_candidate_rejects_invalid_retain_recent_turns() -> None:
    state = _state(*_turn(1))
    with pytest.raises(ValueError):
        _candidate()(state, retain_recent_turns=-1)
    with pytest.raises(ValueError):
        _candidate()(state, retain_recent_turns="4")  # type: ignore[arg-type]


def test_candidate_is_deterministic_and_zero_mutation() -> None:
    facts = (
        _summary("fact:summary:1"),
        *(fact for n in range(1, 7) for fact in _turn(n)),
    )
    state = _state(*facts, goal=_goal("action:1:user"))
    # FrozenJSON 容器与 deepcopy 不兼容:snapshot 用确定性 fixture 重建。
    snapshot = _state(*facts, goal=_goal("action:1:user"))

    first = _candidate()(state, retain_recent_turns=3)
    second = _candidate()(state, retain_recent_turns=3)

    assert first == second
    assert first == (
        "fact:summary:1",
        *(fact_id for n in (2, 3) for fact_id in _turn_ids(n)),
    )
    assert state == snapshot
    assert state.revision == 0
