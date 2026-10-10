from __future__ import annotations

import hashlib
import math
from dataclasses import FrozenInstanceError, replace

import pytest

from agent.runtime.compaction_rules import validate_compaction_removal
from agent.runtime.context import (
    ContextLimitError,
    ContextLimits,
    KernelContextManager,
)
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    BrowserTakeoverRequestV1,
    BudgetReport,
    CompactionPlanV1,
    CompactionTrigger,
    ContextCandidate,
    ContextSourceSnapshot,
    ContinuationPhase,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    ExecutionAuthorityClass,
    FactKind,
    GoalFrame,
    GoalStatus,
    InteractionState,
    ProposedCriterion,
    SubmitMessage,
    ToolCall,
    ToolDefinition,
    canonical_json_digest,
    context_source_snapshot_digest,
)
from agent.runtime.state import apply_compaction_summary


def _fact(fact_id: str, kind: FactKind, **content):
    return ConversationFact(fact_id=fact_id, kind=kind, content=content)


def _action(message: str = "current question") -> SubmitMessage:
    return SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-1",
        message=message,
    )


def _answering_state() -> ConversationState:
    return replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        facts=(
            _fact("user-1", FactKind.USER_MESSAGE, text="old question"),
            _fact("assistant-1", FactKind.ASSISTANT_MESSAGE, text="old answer"),
            _fact("user-2", FactKind.USER_MESSAGE, text="current question"),
        ),
    )


def _tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            execution_authority=ExecutionAuthorityClass.IN_PROCESS,
            name="read_file",
            description="Read one bounded file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    )


class _RecordingSource:
    name = "memory"

    def __init__(self, snapshot: ContextSourceSnapshot) -> None:
        self._snapshot = snapshot
        self.calls = 0

    def snapshot(self, _query) -> ContextSourceSnapshot:  # noqa: ANN001
        self.calls += 1
        return self._snapshot


def _source_candidate(
    *,
    content: str = "bounded source content",
    source_name: str = "memory",
    scope: str = "scope-1",
) -> ContextCandidate:
    return ContextCandidate(
        candidate_id="candidate-1",
        source_name=source_name,
        workspace_scope_digest=scope,
        content=content,
        content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        provenance={"origin": "fixture"},
    )


def _source_snapshot(
    candidates: tuple[ContextCandidate, ...],
    *,
    source_name: str = "memory",
) -> ContextSourceSnapshot:
    return ContextSourceSnapshot(
        source_name=source_name,
        revision=1,
        snapshot_digest=context_source_snapshot_digest(source_name, 1, candidates),
        candidates=candidates,
    )


def test_usage_is_a_no_source_projection_while_build_still_queries_sources() -> None:
    source = _RecordingSource(_source_snapshot((_source_candidate(),)))
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        sources=(source,),
        context_scope_digest="scope-1",
    )
    state = _answering_state()

    report = manager.usage(state, _action(), ())

    assert source.calls == 0
    assert report.source_digests == ()
    assert "candidate-1" not in report.included_ids

    pack = manager.build(state, _action(), ())

    assert source.calls == 1
    assert "candidate-1" in pack.budget.included_ids
    assert pack.budget.source_digests != ()


def test_usage_never_mutates_state_and_is_deterministic() -> None:
    state = replace(
        _answering_state(),
        facts=(
            _fact("user-1", FactKind.USER_MESSAGE, text="old question"),
            _fact(
                "calls-1",
                FactKind.TOOL_CALLS,
                calls=[
                    {
                        "tool_call_id": "call-1",
                        "name": "read_file",
                        "arguments": {"path": "notes.txt"},
                    }
                ],
            ),
            _fact(
                "result-1",
                FactKind.TOOL_RESULT,
                tool_call_id="call-1",
                text="x" * 200,
                is_error=False,
                executed=True,
                metadata={},
            ),
            _fact("user-2", FactKind.USER_MESSAGE, text="current question"),
        ),
    )
    before = repr(state)
    manager = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=8_000,
            output_reserve=500,
            max_tool_result_chars=24,
        ),
    )

    first = manager.usage(state, _action(), _tools())
    second = manager.usage(state, _action(), _tools())

    assert first == second
    assert first.clipped_ids == ("result-1",)
    assert repr(state) == before


def test_usage_budget_equals_build_budget_without_sources() -> None:
    state = replace(
        _answering_state(),
        facts=(
            _fact("user-1", FactKind.USER_MESSAGE, text="old " * 80),
            _fact("assistant-1", FactKind.ASSISTANT_MESSAGE, text="reply " * 80),
            _fact(
                "calls-1",
                FactKind.TOOL_CALLS,
                calls=[
                    {
                        "tool_call_id": "call-1",
                        "name": "read_file",
                        "arguments": {"path": "notes.txt"},
                    }
                ],
            ),
            _fact(
                "result-1",
                FactKind.TOOL_RESULT,
                tool_call_id="call-1",
                text="x" * 200,
                is_error=False,
                executed=True,
                metadata={},
            ),
            _fact("user-2", FactKind.USER_MESSAGE, text="current question"),
        ),
    )
    tools = _tools()
    limits = ContextLimits(max_input_tokens=100_000, output_reserve=10, max_tool_result_chars=24)
    full_cost = (
        KernelContextManager(system_policy="policy", limits=limits)
        .build(state, _action(), tools)
        .budget.estimated_input_tokens
    )
    tight = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(
            max_input_tokens=full_cost,
            output_reserve=30,
            max_tool_result_chars=24,
        ),
    )

    report = tight.usage(state, _action(), tools)
    pack = tight.build(state, _action(), tools)

    assert report == pack.budget
    assert report.excluded_ids == ("user-1",)
    assert report.clipped_ids == ("result-1",)
    assert report.input_limit == full_cost
    assert report.output_reserve == 30


def test_usage_raises_context_limit_error_when_pinned_core_is_too_large() -> None:
    state = replace(
        ConversationState.new("conversation-1"),
        facts=(_fact("recent-user", FactKind.USER_MESSAGE, text="x" * 400),),
    )
    manager = KernelContextManager(
        system_policy="policy" * 20,
        limits=ContextLimits(max_input_tokens=30, output_reserve=10),
    )

    with pytest.raises(ContextLimitError) as exc:
        manager.usage(state, _action(), ())

    assert exc.value.code == "context_core_too_large"


def _usage() -> BudgetReport:
    return BudgetReport(input_limit=1_000, estimated_input_tokens=100, output_reserve=100)


_ACTIONABLE_TRIGGERS = (
    CompactionTrigger.MANUAL,
    CompactionTrigger.TOKEN_PRESSURE,
    CompactionTrigger.EXCLUDED_HISTORY,
    CompactionTrigger.CHECKPOINT_PRESSURE,
)

_INERT_TRIGGERS = (
    CompactionTrigger.NONE,
    CompactionTrigger.UNSAFE_BOUNDARY,
    CompactionTrigger.NO_CANDIDATE,
)


def test_compaction_trigger_values_are_closed() -> None:
    assert [trigger.value for trigger in CompactionTrigger] == [
        "none",
        "manual",
        "token_pressure",
        "excluded_history",
        "checkpoint_pressure",
        "unsafe_boundary",
        "no_candidate",
    ]


@pytest.mark.parametrize("trigger", _ACTIONABLE_TRIGGERS)
def test_compaction_plan_accepts_actionable_trigger_with_ids(trigger: CompactionTrigger) -> None:
    plan = CompactionPlanV1(
        trigger=trigger,
        removable_fact_ids=("fact-1", "fact-2"),
        usage=_usage(),
        active_checkpoint_bytes=128,
        soft_threshold_bytes=1_024,
    )

    assert plan.removable_fact_ids == ("fact-1", "fact-2")
    assert plan.actionable is True


@pytest.mark.parametrize("trigger", _INERT_TRIGGERS)
def test_compaction_plan_accepts_inert_trigger_without_ids(trigger: CompactionTrigger) -> None:
    plan = CompactionPlanV1(
        trigger=trigger,
        removable_fact_ids=(),
        usage=_usage(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
    )

    assert plan.removable_fact_ids == ()
    assert plan.actionable is False


def test_compaction_plan_normalizes_ids_to_tuple() -> None:
    plan = CompactionPlanV1(
        trigger=CompactionTrigger.MANUAL,
        removable_fact_ids=["fact-1", "fact-2"],
        usage=_usage(),
        active_checkpoint_bytes=128,
        soft_threshold_bytes=1_024,
    )

    assert plan.removable_fact_ids == ("fact-1", "fact-2")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trigger", "manual"),
        ("trigger", None),
        ("usage", {"input_limit": 1}),
        ("usage", None),
        ("active_checkpoint_bytes", -1),
        ("active_checkpoint_bytes", 1.5),
        ("soft_threshold_bytes", 0),
        ("soft_threshold_bytes", -10),
        ("removable_fact_ids", ("fact-1", "")),
        ("removable_fact_ids", ("fact-1", "fact-1")),
    ],
)
def test_compaction_plan_rejects_malformed_fields(field: str, value: object) -> None:
    kwargs = {
        "trigger": CompactionTrigger.MANUAL,
        "removable_fact_ids": ("fact-1",),
        "usage": _usage(),
        "active_checkpoint_bytes": 128,
        "soft_threshold_bytes": 1_024,
    }
    kwargs[field] = value

    with pytest.raises((TypeError, ValueError)):
        CompactionPlanV1(**kwargs)


@pytest.mark.parametrize("trigger", _ACTIONABLE_TRIGGERS)
def test_compaction_plan_rejects_actionable_trigger_without_ids(
    trigger: CompactionTrigger,
) -> None:
    with pytest.raises(ValueError):
        CompactionPlanV1(
            trigger=trigger,
            removable_fact_ids=(),
            usage=_usage(),
            active_checkpoint_bytes=128,
            soft_threshold_bytes=1_024,
        )


@pytest.mark.parametrize("trigger", _INERT_TRIGGERS)
def test_compaction_plan_rejects_inert_trigger_with_ids(trigger: CompactionTrigger) -> None:
    with pytest.raises(ValueError):
        CompactionPlanV1(
            trigger=trigger,
            removable_fact_ids=("fact-1",),
            usage=_usage(),
            active_checkpoint_bytes=128,
            soft_threshold_bytes=1_024,
        )


def _compaction_manager(source: _RecordingSource | None = None) -> KernelContextManager:
    return KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        sources=() if source is None else (source,),
        context_scope_digest="" if source is None else "scope-1",
    )


def _closed_turn_state(pairs: int) -> ConversationState:
    """构造 pairs 个完整 closed turns 的 ANSWERING 会话，供压缩规划使用。"""
    facts: list[ConversationFact] = []
    for index in range(1, pairs + 1):
        facts.append(_fact(f"user-{index}", FactKind.USER_MESSAGE, text=f"question {index}"))
        facts.append(
            _fact(f"assistant-{index}", FactKind.ASSISTANT_MESSAGE, text=f"answer {index}")
        )
    return replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        facts=tuple(facts),
    )


def _takeover() -> BrowserTakeoverRequestV1:
    return BrowserTakeoverRequestV1(
        request_id="request-1",
        session_ref="session-1",
        profile_ref="profile-1",
        profile_revision=1,
        browser_identity_digest="digest-1",
        goal_id="goal-1",
        goal_revision=0,
        requested_at="2026-01-01T00:00:00+00:00",
    )


def _full_input_cost(state: ConversationState) -> int:
    """用宽松 manager 测无挤出时的完整 estimated_input_tokens（与 limit 无关）。"""
    roomy = KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=1_000_000, output_reserve=500),
    )
    return roomy.usage(state, _action(), _tools()).estimated_input_tokens


def _available_manager(available: int) -> KernelContextManager:
    """构造 available = max_input_tokens - output_reserve 的 manager。"""
    return KernelContextManager(
        system_policy="policy",
        limits=ContextLimits(max_input_tokens=available + 500, output_reserve=500),
    )


def _token_threshold(report: BudgetReport) -> int:
    return math.ceil(0.70 * (report.input_limit - report.output_reserve))


def _huge_turn_state(huge_index: int) -> ConversationState:
    """pairs=6 的 closed turns，其中第 huge_index 个 assistant 消息被放大。"""
    facts: list[ConversationFact] = []
    for index in range(1, 7):
        facts.append(_fact(f"user-{index}", FactKind.USER_MESSAGE, text=f"question {index}"))
        text = "a" * 24_000 if index == huge_index else f"answer {index}"
        facts.append(_fact(f"assistant-{index}", FactKind.ASSISTANT_MESSAGE, text=text))
    return replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        facts=tuple(facts),
    )


def test_plan_compaction_selects_only_oldest_eligible_turn() -> None:
    # planner 固定 max_turns=1:summary + 7 个 closed turns,turn 1 受 goal
    # 保护,retain=4 保留最新 4 个,eligible 区只剩 turns 2/3,但每次压缩
    # 只取最老的一个 eligible turn(turn 2),summary 随之放首位。
    facts: list[ConversationFact] = [
        _fact("summary-1", FactKind.CONTEXT_SUMMARY),
    ]
    for index in range(1, 8):
        facts.append(_fact(f"user-{index}", FactKind.USER_MESSAGE, text=f"question {index}"))
        facts.append(
            _fact(f"assistant-{index}", FactKind.ASSISTANT_MESSAGE, text=f"answer {index}")
        )
    state = replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        facts=tuple(facts),
        goal=GoalFrame(
            goal_id="goal-1",
            revision=1,
            created_from_fact_ids=("user-1",),
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
        ),
    )
    manager = _compaction_manager()

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
        force=True,
    )

    assert plan.trigger is CompactionTrigger.MANUAL
    assert plan.removable_fact_ids == ("summary-1", "user-2", "assistant-2")
    removed = validate_compaction_removal(state, plan.removable_fact_ids)
    assert tuple(fact.fact_id for fact in removed) == plan.removable_fact_ids
    assert plan.actionable is True


def test_plan_compaction_manual_returns_candidates_with_usage_and_no_sources() -> None:
    source = _RecordingSource(_source_snapshot((_source_candidate(),)))
    manager = _compaction_manager(source)
    state = _closed_turn_state(pairs=6)
    before = repr(state)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=128,
        soft_threshold_bytes=1_024,
        force=True,
    )

    # retain_recent_turns=4 且 planner 固定 max_turns=1：只有最旧的一个
    # closed turn 成为候选，且必须通过 validator。
    assert plan.trigger is CompactionTrigger.MANUAL
    assert plan.removable_fact_ids == (
        "user-1",
        "assistant-1",
    )
    removed = validate_compaction_removal(state, plan.removable_fact_ids)
    assert tuple(fact.fact_id for fact in removed) == plan.removable_fact_ids
    assert plan.actionable is True
    # 同一 usage：等于 manager.usage 的 no-source 投影；bytes 原样回传。
    assert plan.usage == manager.usage(state, _action(), _tools())
    assert plan.usage.source_digests == ()
    assert plan.active_checkpoint_bytes == 128
    assert plan.soft_threshold_bytes == 1_024
    # 零 source、零 mutation。
    assert source.calls == 0
    assert repr(state) == before


def test_plan_compaction_reports_no_candidate_when_nothing_is_removable() -> None:
    manager = _compaction_manager()
    state = _closed_turn_state(pairs=4)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
        force=True,
    )

    # 最近 4 个 closed turn 全部保留：无候选可移除。
    assert plan.trigger is CompactionTrigger.NO_CANDIDATE
    assert plan.removable_fact_ids == ()
    assert plan.actionable is False
    assert plan.usage == manager.usage(state, _action(), _tools())
    assert plan.active_checkpoint_bytes == 0
    assert plan.soft_threshold_bytes == 1


def test_plan_compaction_refuses_unsafe_boundary_even_with_candidates() -> None:
    tool_phase_run = ActiveRun(
        run_id="run-1",
        phase=ContinuationPhase.TOOL,
        tool_calls=(
            ToolCall(tool_call_id="call-1", name="read_file", arguments={"path": "a.txt"}),
        ),
    )
    paused_run = ActiveRun("run-1", status=ActiveRunStatus.PAUSED_LIMIT)
    unsafe_states = (
        # status 不是 RUNNABLE：压缩必须 fail closed。
        replace(_closed_turn_state(pairs=6), active_run=paused_run),
        # RUNNABLE 但 phase 是 TOOL：模型/工具边界尚未静止。
        replace(_closed_turn_state(pairs=6), active_run=tool_phase_run),
        # browser takeover pending：控制面被接管，不暴露任何候选。
        replace(_closed_turn_state(pairs=6), browser_takeover_pending=_takeover()),
    )
    manager = _compaction_manager()

    for state in unsafe_states:
        plan = manager.plan_compaction(
            state,
            _action(),
            _tools(),
            active_checkpoint_bytes=64,
            soft_threshold_bytes=512,
            force=True,
        )

        assert plan.trigger is CompactionTrigger.UNSAFE_BOUNDARY
        assert plan.removable_fact_ids == ()
        assert plan.actionable is False
        assert plan.usage == manager.usage(state, _action(), _tools())
        assert plan.active_checkpoint_bytes == 64
        assert plan.soft_threshold_bytes == 512


def test_plan_compaction_defaults_to_none_without_force_and_validates_arguments() -> None:
    manager = _compaction_manager()
    state = _closed_turn_state(pairs=6)
    before = repr(state)

    # 安全边界、候选存在；自动触发全部关闭（无挤出、token 低、checkpoint 低）→ NONE。
    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=32,
        soft_threshold_bytes=256,
    )

    assert plan.trigger is CompactionTrigger.NONE
    assert plan.removable_fact_ids == ()
    assert plan.actionable is False
    assert plan.usage == manager.usage(state, _action(), _tools())
    assert plan.active_checkpoint_bytes == 32
    assert plan.soft_threshold_bytes == 256
    assert repr(state) == before

    # 参数校验 fail closed：越界与非整数 bytes 都拒绝。
    for kwargs in (
        {"active_checkpoint_bytes": -1, "soft_threshold_bytes": 256},
        {"active_checkpoint_bytes": 1.5, "soft_threshold_bytes": 256},
        {"active_checkpoint_bytes": 32, "soft_threshold_bytes": 0},
        {"active_checkpoint_bytes": 32, "soft_threshold_bytes": True},
    ):
        with pytest.raises((TypeError, ValueError)):
            manager.plan_compaction(state, _action(), _tools(), **kwargs)


def test_plan_compaction_prefers_excluded_history_over_token_and_checkpoint() -> None:
    # assistant-1 属于唯一候选 turn（max_turns=1 取最老 eligible turn）：紧凑
    # 预算把它挤出投影，即 excluded∩candidates 非空。
    state = _huge_turn_state(huge_index=1)
    full = _full_input_cost(state)
    # available 落在 [保留基线, 保留基线+巨大组成本) 内：挤出恰好深入到候选
    # assistant-1，且挤出后 estimated 仍高于 70% 阈值（token 同时过阈，用于
    # 验证优先级）。
    manager = _available_manager(full - 6_000)
    candidates = ("user-1", "assistant-1")
    report = manager.usage(state, _action(), _tools())
    # 前置：三种压力同时成立，优先级必须是 excluded > token > checkpoint。
    assert set(report.excluded_ids) & set(candidates)
    assert report.estimated_input_tokens >= _token_threshold(report)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=9_000,
        soft_threshold_bytes=128,
    )

    assert plan.trigger is CompactionTrigger.EXCLUDED_HISTORY
    assert plan.removable_fact_ids == candidates
    removed = validate_compaction_removal(state, plan.removable_fact_ids)
    assert tuple(fact.fact_id for fact in removed) == candidates
    assert plan.actionable is True
    assert plan.usage == report


def test_plan_compaction_maps_oldest_first_exclusion_to_candidate() -> None:
    # 即使压力由 retain 窗内的巨大 assistant-5 造成，普通上下文也应先淘汰
    # 最旧历史；该历史正是 compaction 候选，因此必须报 EXCLUDED_HISTORY。
    state = _huge_turn_state(huge_index=5)
    full = _full_input_cost(state)
    manager = _available_manager(full - 3_000)
    report = manager.usage(state, _action(), _tools())
    candidates = {"user-1", "assistant-1"}
    assert report.excluded_ids
    assert set(report.excluded_ids) & candidates
    assert report.estimated_input_tokens < _token_threshold(report)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
    )

    assert plan.trigger is CompactionTrigger.EXCLUDED_HISTORY
    assert plan.removable_fact_ids == ("user-1", "assistant-1")
    assert plan.actionable is True
    assert plan.usage == report


@pytest.mark.parametrize(
    ("overshoot", "expected"),
    [
        (0, CompactionTrigger.TOKEN_PRESSURE),
        (1, CompactionTrigger.NONE),
    ],
)
def test_plan_compaction_token_pressure_boundary_at_seventy_percent(
    overshoot: int,
    expected: CompactionTrigger,
) -> None:
    # 阈值恰好等于 full 时触发（>=），少 1 不触发；其余 trigger 配置为关闭。
    state = _closed_turn_state(pairs=6)
    full = _full_input_cost(state)
    available = math.floor((full + overshoot) / 0.70)
    manager = _available_manager(available)
    report = manager.usage(state, _action(), _tools())
    # 前置：同一公式下阈值恰为 full+overshoot，且无任何挤出。
    assert _token_threshold(report) == full + overshoot
    assert report.excluded_ids == ()

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
    )

    assert plan.trigger is expected
    if expected is CompactionTrigger.TOKEN_PRESSURE:
        candidates = ("user-1", "assistant-1")
        assert plan.removable_fact_ids == candidates
        removed = validate_compaction_removal(state, plan.removable_fact_ids)
        assert tuple(fact.fact_id for fact in removed) == candidates
        assert plan.actionable is True
    else:
        assert plan.removable_fact_ids == ()
        assert plan.actionable is False
    assert plan.usage == report


def test_plan_compaction_checkpoint_pressure_fires_at_soft_threshold() -> None:
    manager = _compaction_manager()
    state = _closed_turn_state(pairs=6)
    report = manager.usage(state, _action(), _tools())
    # 前置：无挤出且 token 低于阈值，隔离 checkpoint 触发。
    assert report.excluded_ids == ()
    assert report.estimated_input_tokens < _token_threshold(report)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=512,
        soft_threshold_bytes=512,
    )

    assert plan.trigger is CompactionTrigger.CHECKPOINT_PRESSURE
    candidates = ("user-1", "assistant-1")
    assert plan.removable_fact_ids == candidates
    removed = validate_compaction_removal(state, plan.removable_fact_ids)
    assert tuple(fact.fact_id for fact in removed) == candidates
    assert plan.actionable is True
    assert plan.usage == report


def test_plan_compaction_prefers_token_pressure_over_checkpoint() -> None:
    state = _closed_turn_state(pairs=6)
    full = _full_input_cost(state)
    manager = _available_manager(full)
    report = manager.usage(state, _action(), _tools())
    # 前置：available=full → 无挤出但 token 过阈，checkpoint 同时过阈。
    assert report.excluded_ids == ()
    assert report.estimated_input_tokens >= _token_threshold(report)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=9_999,
        soft_threshold_bytes=1,
    )

    assert plan.trigger is CompactionTrigger.TOKEN_PRESSURE
    assert plan.removable_fact_ids == ("user-1", "assistant-1")
    assert plan.actionable is True


def test_plan_compaction_auto_trigger_without_candidates_reports_no_candidate() -> None:
    # 最近 4 个 closed turn 全部保留：token 或 checkpoint 过阈也无候选可移除。
    state = _closed_turn_state(pairs=4)
    full = _full_input_cost(state)
    token_manager = _available_manager(full)
    token_report = token_manager.usage(state, _action(), _tools())
    assert token_report.excluded_ids == ()
    assert token_report.estimated_input_tokens >= _token_threshold(token_report)

    plan = token_manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
    )

    assert plan.trigger is CompactionTrigger.NO_CANDIDATE
    assert plan.removable_fact_ids == ()
    assert plan.actionable is False

    checkpoint_manager = _compaction_manager()
    checkpoint_report = checkpoint_manager.usage(state, _action(), _tools())
    assert checkpoint_report.excluded_ids == ()
    assert checkpoint_report.estimated_input_tokens < _token_threshold(checkpoint_report)

    plan = checkpoint_manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=64,
        soft_threshold_bytes=32,
    )

    assert plan.trigger is CompactionTrigger.NO_CANDIDATE
    assert plan.removable_fact_ids == ()
    assert plan.actionable is False


def test_plan_compaction_force_still_wins_over_auto_pressure() -> None:
    state = _closed_turn_state(pairs=6)
    full = _full_input_cost(state)
    manager = _available_manager(full)

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=9_999,
        soft_threshold_bytes=1,
        force=True,
    )

    assert plan.trigger is CompactionTrigger.MANUAL
    assert plan.removable_fact_ids == ("user-1", "assistant-1")
    assert plan.actionable is True


def test_compaction_plan_is_frozen() -> None:
    plan = CompactionPlanV1(
        trigger=CompactionTrigger.NONE,
        removable_fact_ids=(),
        usage=_usage(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
    )

    with pytest.raises(FrozenInstanceError):
        plan.trigger = CompactionTrigger.MANUAL  # type: ignore[misc]


def _nonleading_summary_state() -> ConversationState:
    """第一批压缩后的状态：turn 2 被换成非首位 summary（index 2）。

    goal 保护 turn 1，reducer 把新 summary 插在最早被移除 fact 的原位置，
    因此合法的中间产物不是“summary 位于首位”的形状。
    """

    summary = ConversationSummaryV1(
        objective="turn 2 archived",
        constraints=(),
        decisions=(),
        completed=(),
        open_items=(),
        key_references=(),
        source_checkpoint_digest="a" * 64,
        source_fact_ids_digest="b" * 64,
    )
    facts: list[ConversationFact] = [
        _fact("user-1", FactKind.USER_MESSAGE, text="question 1"),
        _fact("assistant-1", FactKind.ASSISTANT_MESSAGE, text="answer 1"),
        _fact(
            "fact:context-summary:first",
            FactKind.CONTEXT_SUMMARY,
            **summary.to_content(),
        ),
    ]
    for index in range(3, 8):
        facts.append(_fact(f"user-{index}", FactKind.USER_MESSAGE, text=f"question {index}"))
        facts.append(
            _fact(f"assistant-{index}", FactKind.ASSISTANT_MESSAGE, text=f"answer {index}")
        )
    return replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
        facts=tuple(facts),
        goal=GoalFrame(
            goal_id="goal-1",
            revision=1,
            created_from_fact_ids=("user-1",),
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
        ),
    )


def test_nonleading_summary_replans_builds_and_reduces_next_batch() -> None:
    """非首位 summary 是合法中间产物：下一轮可再次 plan/build/reduce。"""

    state = _nonleading_summary_state()
    manager = _compaction_manager()

    plan = manager.plan_compaction(
        state,
        _action(),
        _tools(),
        active_checkpoint_bytes=0,
        soft_threshold_bytes=1,
        force=True,
    )

    # retain=4 保留 turns 4-7，eligible 区是 turn 1(protected) 与 turn 3；
    # max_turns=1 选 turn 3，旧 summary 随之替换。
    assert plan.trigger is CompactionTrigger.MANUAL
    assert plan.removable_fact_ids == (
        "fact:context-summary:first",
        "user-3",
        "assistant-3",
    )
    removed = validate_compaction_removal(state, plan.removable_fact_ids)
    assert tuple(fact.fact_id for fact in removed) == plan.removable_fact_ids
    assert plan.actionable is True

    # build：专用 pack 能在非首位 summary 状态上构建。
    token = "sha256:" + "c" * 64
    pack = manager.build_compaction(state, plan, token)
    block = pack.messages[0].content[0]
    assert block["source_checkpoint_digest"] == "c" * 64
    assert block["source_fact_ids_digest"] == canonical_json_digest(
        list(plan.removable_fact_ids)
    )

    # reduce：铸造绑定 pack digests 的 summary 并应用，链条闭合。
    summary = ConversationSummaryV1(
        objective="turn 3 archived",
        constraints=(),
        decisions=(),
        completed=(),
        open_items=(),
        key_references=(),
        source_checkpoint_digest=block["source_checkpoint_digest"],
        source_fact_ids_digest=block["source_fact_ids_digest"],
    )
    reduced = apply_compaction_summary(state, summary, plan.removable_fact_ids)
    assert tuple(fact.kind for fact in reduced.facts) == (
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
        FactKind.CONTEXT_SUMMARY,
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
        FactKind.USER_MESSAGE,
        FactKind.ASSISTANT_MESSAGE,
    )
    restored = ConversationSummaryV1.from_content(reduced.facts[2].content)
    assert restored.source_checkpoint_digest == "c" * 64
