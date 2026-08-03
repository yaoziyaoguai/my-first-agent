from __future__ import annotations

from dataclasses import replace

import pytest

from agent.cli.app import load_headless_view
from agent.runtime.contracts import (
    AdmittedCriterion,
    CompletionClaim,
    ConversationState,
    EvidenceOracleKind,
    EvidenceRecord,
    GoalStatus,
    InteractionState,
    LoadedSnapshot,
    canonical_json_digest,
)
from agent.runtime.views import project_goal_view
from agent.tui.adapter import TuiAdapter
from agent.tui.render import project
from tests.kernel.fakes import conversation_with_active_goal


class _Store:
    def __init__(self, state: ConversationState) -> None:
        self.state = state

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, "token-1")


class _NoRuntime:
    def run_turn(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("reopen projection must not call runtime")


@pytest.mark.parametrize(
    ("goal_status", "interaction", "expected_actions"),
    (
        (
            GoalStatus.GOAL_READY,
            InteractionState.IDLE,
            ("pause_goal", "correct_goal", "cancel_goal"),
        ),
        (
            GoalStatus.EXECUTING,
            InteractionState.IDLE,
            ("pause_goal", "correct_goal", "cancel_goal"),
        ),
        (
            GoalStatus.NEEDS_AUTHORITY,
            InteractionState.CLARIFYING,
            ("pause_goal", "correct_goal", "cancel_goal"),
        ),
        (GoalStatus.PAUSED, InteractionState.IDLE, ("resume_goal", "correct_goal", "cancel_goal")),
        (GoalStatus.BLOCKED, InteractionState.IDLE, ("resume_goal", "correct_goal", "cancel_goal")),
        (GoalStatus.CANCELLED, InteractionState.IDLE, ()),
        (GoalStatus.VERIFIED_DONE, InteractionState.IDLE, ()),
    ),
)
def test_shared_goal_view_matches_cli_tui_and_headless(
    goal_status: GoalStatus,
    interaction: InteractionState,
    expected_actions: tuple[str, ...],
) -> None:
    state = conversation_with_active_goal()
    evidence_records = ()
    completion_claim = None
    admitted_criteria = state.goal.admitted_criteria
    if goal_status is GoalStatus.VERIFIED_DONE:
        predicate = {"path": "reports/final.md", "sha256": "a" * 64}
        criterion = AdmittedCriterion(
            criterion_id="criterion-1",
            description="report exists",
            source_fact_id="action:1:user",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            predicate=predicate,
            required_evidence_class="workspace_file",
            admission_digest="admission-1",
        )
        evidence = EvidenceRecord(
            evidence_id="evidence-1",
            goal_id="goal-1",
            goal_revision=1,
            criterion_id="criterion-1",
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            predicate_digest=canonical_json_digest(predicate),
            source_fact_ids=("action:1:user",),
            source_digest="source-1",
            oracle_identity="filesystem-digest:v1",
            passed=True,
            observed_at="2026-08-02T01:00:00Z",
        )
        evidence_records = (evidence,)
        completion_claim = CompletionClaim(
            correlation_id="claim-1",
            goal_id="goal-1",
            goal_revision=1,
            criterion_evidence_refs=("evidence-1",),
        )
        admitted_criteria = (criterion,)
    state = replace(
        state,
        goal=replace(
            state.goal,
            status=goal_status,
            admitted_criteria=admitted_criteria,
        ),
        evidence_records=evidence_records,
        completion_claim=completion_claim,
        interaction_state=interaction,
    )
    store = _Store(state)

    shared = project_goal_view(state)
    cli_or_headless = load_headless_view(store)
    tui_loaded = TuiAdapter(_NoRuntime(), store).load_view().goal
    tui_rendered = project(state).goal

    assert shared == cli_or_headless == tui_loaded == tui_rendered
    assert shared.legal_actions == expected_actions
    assert shared.goal_id == "goal-1"
    assert shared.goal_revision == 1


def test_answering_and_clarifying_without_goal_remain_visible() -> None:
    answering = replace(
        ConversationState.new("conversation-1"),
        interaction_state=InteractionState.ANSWERING,
    )
    clarifying = replace(
        answering,
        interaction_state=InteractionState.CLARIFYING,
    )

    assert project_goal_view(answering).status == "answering"
    assert project_goal_view(clarifying).status == "clarifying"


def test_reopen_projection_has_zero_provider_and_tool_calls() -> None:
    state = conversation_with_active_goal()
    store = _Store(state)
    view = TuiAdapter(_NoRuntime(), store).load_view()

    assert view.goal.goal_id == "goal-1"
