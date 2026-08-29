"""018 Task 8：closed browser readback evidence oracle（先 Red）。

completion 需要 durable exact browser action receipt **加** 同一 session 在
receipt 之后的新鲜 task-specific browser_observe readback；页面成功文案/
模型 prose、fake/stale/unknown/denied/old-profile receipt 都 fail closed。
oracle 是纯推导：只读 durable facts，不调用 browser/tools。
"""

import pytest

from agent.runtime.contracts import (
    AdmittedCriterion,
    CompletionClaim,
    ConversationFact,
    EvidenceOracleKind,
    FactKind,
    canonical_json_digest,
)
from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
from tests.kernel.fakes import conversation_with_active_goal

SESSION = "session-0123456789abcdef"
RECEIPT_DIGEST = "1" * 64
READBACK_DIGEST = "2" * 64
OTHER_DIGEST = "3" * 64
PROFILE_REVISION = 4
BROWSER_IDENTITY = "a" * 64


GOAL_ID = "goal-1"
GOAL_REVISION = 1


def _browser_action_fact(*, seq=3, error=False, outcome="effect_applied",
                         receipt_digest=RECEIPT_DIGEST, session_ref=SESSION,
                         fake=False, profile_revision=PROFILE_REVISION,
                         goal_id=GOAL_ID, goal_revision=GOAL_REVISION):
    metadata = {
        "browser_result_kind": "browser_action",
        "browser_receipt_kind": "browser_action_v1",
        "receipt_digest": receipt_digest,
        "action_digest": "a" * 64,
        "pre_observation_digest": "b" * 64,
        "post_observation_digest": "c" * 64,
        "outcome": outcome,
        "session_ref": session_ref,
        "profile_revision": profile_revision,
        "browser_identity_digest": BROWSER_IDENTITY,
        "goal_id": goal_id,
        "goal_revision": goal_revision,
    }
    if fake:
        metadata["fake"] = True
    return ConversationFact(
        fact_id=f"run:run-1:tool-result:call-act:{seq}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-act",
            "text": "browser action applied",
            "is_error": error,
            "executed": True,
            "metadata": metadata,
        },
    )


def _observe_fact(*, seq=4, digest=READBACK_DIGEST, session_ref=SESSION,
                  goal_id=GOAL_ID, goal_revision=GOAL_REVISION):
    return ConversationFact(
        fact_id=f"run:run-1:tool-result:call-obs:{seq}",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-obs",
            "text": "browser observation",
            "is_error": False,
            "executed": True,
            "metadata": {
                "browser_result_kind": "browser_observe",
                "session_ref": session_ref,
                "observation_digest": digest,
                "page_id": session_ref,
                "frame_id": "main",
                "canonical_origin": "https://site.example.test",
                "profile_revision": PROFILE_REVISION,
                "browser_identity_digest": BROWSER_IDENTITY,
                "goal_id": goal_id,
                "goal_revision": goal_revision,
            },
        },
    )


def _state_with_facts(facts):
    state = conversation_with_active_goal()
    return _with_criteria_and_facts(state, facts)


def _with_criteria_and_facts(state, facts):
    from dataclasses import replace

    goal = state.goal
    predicate = {
        "receipt_kind": "browser_readback_v1",
        "receipt_digest": RECEIPT_DIGEST,
        "session_ref": SESSION,
        "readback_observation_digest": READBACK_DIGEST,
        "profile_revision": PROFILE_REVISION,
        "browser_identity_digest": BROWSER_IDENTITY,
    }
    criterion = AdmittedCriterion(
        criterion_id=goal.proposed_criteria[0].criterion_id,
        description=goal.proposed_criteria[0].description,
        source_fact_id=state.facts[0].fact_id,
        oracle_kind=EvidenceOracleKind.BROWSER_READBACK,
        predicate=predicate,
        required_evidence_class="browser_readback_v1",
        admission_digest=canonical_json_digest(predicate),
    )
    goal = replace(goal, admitted_criteria=(criterion,))
    claim = CompletionClaim(
        correlation_id="claim-1",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        criterion_evidence_refs=(
            ClosedEvidenceRegistry.evidence_id(goal.goal_id, goal.revision, criterion.criterion_id),
        ),
    )
    return replace(state, goal=goal, facts=(*state.facts, *facts)), claim


def test_readback_positive_receipt_plus_fresh_observe():
    state, claim = _state_with_facts(
        [_browser_action_fact(), _observe_fact()]
    )
    records = ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
    assert len(records) == 1
    assert records[0].oracle_identity == "browser-readback:v1"


def test_dom_or_prose_alone_cannot_verify():
    prose = ConversationFact(
        fact_id="run:run-1:tool-result:call-prose:9",
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": "call-prose",
            "text": "the page says Payment successful",
            "is_error": False,
            "executed": True,
            "metadata": {"browser_result_kind": "browser_observe",
                         "session_ref": SESSION,
                         "observation_digest": READBACK_DIGEST},
        },
    )
    # 只有 receipt 没有 fresh observe。
    state, claim = _state_with_facts([_browser_action_fact()])
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
    # 只有 prose/observe 没有 durable receipt。
    state, claim = _state_with_facts([prose])
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")


def test_observe_must_follow_receipt_in_same_session():
    # observe 在 receipt 之前：不新鲜。
    state, claim = _state_with_facts(
        [_observe_fact(seq=2), _browser_action_fact(seq=3)]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
    # session 漂移。
    state, claim = _state_with_facts(
        [_browser_action_fact(), _observe_fact(session_ref="session-ffffffffffffffff")]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
    # readback digest 不匹配。
    state, claim = _state_with_facts(
        [_browser_action_fact(), _observe_fact(digest=OTHER_DIGEST)]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")


def test_denied_unknown_and_fake_receipts_fail_closed():
    # denied（is_error）。
    state, claim = _state_with_facts(
        [_browser_action_fact(error=True), _observe_fact()]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
    # unknown outcome。
    state, claim = _state_with_facts(
        [_browser_action_fact(outcome="unknown"), _observe_fact()]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
    # fake marker。
    state, claim = _state_with_facts(
        [_browser_action_fact(fake=True), _observe_fact()]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")


def test_stale_profile_revision_receipt_fails_closed():
    state, claim = _state_with_facts(
        [
            _browser_action_fact(profile_revision=PROFILE_REVISION - 1),
            _observe_fact(),
        ]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")


def test_internally_consistent_old_goal_id_evidence_fails_closed():
    # action+readback 彼此一致，但 goal_id 是旧 Goal：不得满足当前 completion。
    state, claim = _state_with_facts(
        [
            _browser_action_fact(goal_id="goal-old"),
            _observe_fact(goal_id="goal-old"),
        ]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")


def test_internally_consistent_old_goal_revision_evidence_fails_closed():
    # goal_id 相同但 revision 是旧的（Goal correction 后旧证据失效）。
    state, claim = _state_with_facts(
        [
            _browser_action_fact(goal_revision=GOAL_REVISION + 1),
            _observe_fact(goal_revision=GOAL_REVISION + 1),
        ]
    )
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")


def test_predicate_must_be_exact_closed_shape():
    from dataclasses import replace

    state, claim = _state_with_facts([_browser_action_fact(), _observe_fact()])
    goal = state.goal
    loose = replace(
        goal.admitted_criteria[0],
        predicate={"receipt_digest": RECEIPT_DIGEST},
    )
    state = replace(state, goal=replace(goal, admitted_criteria=(loose,)))
    with pytest.raises(EvidenceVerificationError):
        ClosedEvidenceRegistry().derive(state, claim, observed_at="2026-08-28T00:00:00Z")
