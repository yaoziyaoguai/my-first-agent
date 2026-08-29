"""018 Task 5 Step 1：browser candidate/lease 的 Runtime authority Reds（先 Red）。

approval 绑定 Goal/revision/profile/session/browser/origins/page/frame/
observation/action/consequence/expiry/single-use；goal 漂移、revision 变化、
origin expansion、过期或复用使 lease 失效；public-read lease 不能授权
interactive action；expiry 用 RFC3339 字符串（不 checkpoint monotonic）。
"""

import json
from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ApprovalRequest,
    BrowserActionCandidateV1,
    BrowserAuthorityLeaseV1,
    ExecutionAuthorityClass,
)

ISSUED = "2026-08-28T10:00:00+00:00"
EXPIRES = "2026-08-28T11:00:00+00:00"


def make_candidate(**overrides):
    payload = {
        "candidate_id": "browser-candidate-1",
        "goal_id": "goal-1",
        "goal_revision": 2,
        "session_ref": "session-0123456789abcdef",
        "browser_identity_digest": "a" * 64,
        "profile_ref": "profile-0123456789abcdef",
        "profile_revision": 3,
        "allowed_origins": ("https://site.example.test",),
        "mode": "site_bound_interactive",
        "page_id": "session-0123456789abcdef",
        "frame_id": "main",
        "observation_digest": "1" * 64,
        "action_digest": "3" * 64,
        "consequence": "disclose",
        "preview": "disclose; fill_form; https://site.example.test",
        "issued_at": ISSUED,
        "expires_at": EXPIRES,
    }
    payload.update(overrides)
    return BrowserActionCandidateV1.create(**payload)


def make_lease(approved_at=ISSUED, **candidate_overrides):
    candidate = make_candidate(**candidate_overrides)
    return BrowserAuthorityLeaseV1.create(
        lease_id="browser-lease-1",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        session_ref=candidate.session_ref,
        browser_identity_digest=candidate.browser_identity_digest,
        profile_ref=candidate.profile_ref,
        profile_revision=candidate.profile_revision,
        allowed_origins=candidate.allowed_origins,
        mode=candidate.mode,
        page_id=candidate.page_id,
        frame_id=candidate.frame_id,
        observation_digest=candidate.observation_digest,
        action_digest=candidate.action_digest,
        consequence=candidate.consequence,
        approved_request_identity="req-1",
        issued_at=approved_at,
        expires_at=candidate.expires_at,
    )


def test_execution_authority_class_has_browser_session():
    assert ExecutionAuthorityClass.BROWSER_SESSION.value == "browser_session"


def test_candidate_digest_covers_all_bound_fields():
    candidate = make_candidate()
    for mutation in (
        {"goal_revision": 3},
        {"session_ref": "session-ffffffffffffffff"},
        {"profile_revision": 4},
        {"allowed_origins": ("https://other.example.test",)},
        {"mode": "public_read_ephemeral", "profile_ref": None, "profile_revision": None},
        {"observation_digest": "2" * 64},
        {"action_digest": "4" * 64},
        {"consequence": "commit"},
        {"expires_at": "2026-08-28T12:00:00+00:00"},
    ):
        assert make_candidate(**mutation).candidate_digest != candidate.candidate_digest, mutation
    # replace 携带旧 digest 重跑 post_init：篡改在构造层拒。
    with pytest.raises(ValueError):
        replace(candidate, consequence="commit")


def test_approval_request_carries_one_browser_candidate():
    candidate = make_candidate()
    request = ApprovalRequest(
        request_id="req-1",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="b" * 64,
        preview="preview",
        browser_action_candidate=candidate,
    )
    assert request.browser_action_candidate is candidate


def test_browser_approval_candidate_round_trips_through_checkpoint():
    from agent.runtime.checkpoint import _decode_state, _encode_state

    state, pending = _awaiting_approval_state()
    encoded = _encode_state(state)
    document = json.loads(encoded)
    persisted = document["state"]["active_run"]["pending_request"]

    assert persisted["browser_action_candidate"] is not None
    restored = _decode_state(encoded)
    restored_pending = restored.active_run.pending_request
    assert restored_pending.browser_action_candidate == pending.browser_action_candidate


def test_pre_018_v7_pending_approval_migrates_without_browser_authority():
    from agent.runtime.checkpoint import _decode_state, _encode_state

    state, _pending = _awaiting_approval_state()
    state = replace(
        state,
        active_run=replace(
            state.active_run,
            pending_request=replace(
                state.active_run.pending_request,
                browser_action_candidate=None,
            ),
        ),
    )
    document = json.loads(_encode_state(state))
    document["state"]["active_run"]["pending_request"].pop(
        "browser_action_candidate"
    )

    restored = _decode_state(json.dumps(document).encode("utf-8"))
    assert restored.active_run.pending_request.browser_action_candidate is None


def test_mint_browser_lease_anchors_rfc3339_expiry():
    from agent.runtime.state import _mint_browser_authority_lease
    from tests.kernel.fakes import conversation_with_active_goal

    state = conversation_with_active_goal()
    candidate = make_candidate()
    pending = ApprovalRequest(
        request_id="req-1",
        run_id="run-1",
        tool_call_id="call-1",
        binding_digest="b" * 64,
        preview="preview",
        browser_action_candidate=candidate,
    )
    minted = _mint_browser_authority_lease(state, pending, approved_at=ISSUED)
    leases = minted.browser_leases
    assert len(leases) == 1
    lease = leases[0]
    assert lease.expires_at == EXPIRES
    assert "T" in lease.expires_at and "+" in lease.expires_at
    assert lease.max_uses == 1


def test_lease_requires_exact_binding_identity():
    lease = make_lease()
    base = {
        "goal_id": "goal-1",
        "goal_revision": 2,
        "session_ref": "session-0123456789abcdef",
        "browser_identity_digest": "a" * 64,
        "profile_ref": "profile-0123456789abcdef",
        "profile_revision": 3,
        "allowed_origins": ("https://site.example.test",),
        "mode": "site_bound_interactive",
        "page_id": "session-0123456789abcdef",
        "frame_id": "main",
        "observation_digest": "1" * 64,
        "action_digest": "3" * 64,
        "consequence": "disclose",
        "now": ISSUED,
    }
    assert lease.authorizes(**base) is True
    for mutation in (
        {"goal_revision": 3},
        {"session_ref": "session-ffffffffffffffff"},
        {"browser_identity_digest": "c" * 64},
        {"profile_revision": 4},
        {"allowed_origins": ("https://site.example.test", "https://expanded.test")},
        {"page_id": "other-page"},
        {"frame_id": "frame-2"},
        {"observation_digest": "2" * 64},
        {"action_digest": "4" * 64},
        {"consequence": "commit"},
    ):
        payload = {**base, **mutation}
        assert lease.authorizes(**payload) is False, mutation


def test_lease_single_use_and_reuse_rejected():

    lease = make_lease()
    assert lease.uses_consumed == 0
    consumed = lease.with_use_consumed(1)
    assert consumed.uses_consumed == 1
    # 超过 max_uses 在构造层 fail closed。
    with pytest.raises(ValueError):
        consumed.with_use_consumed(2)


def test_public_read_lease_cannot_authorize_interactive_action():
    lease = make_lease(
        mode="public_read_ephemeral",
        consequence="observe",
        profile_ref=None,
        profile_revision=None,
        allowed_origins=(),
    )
    assert (
        lease.authorizes(
            goal_id="goal-1",
            goal_revision=2,
            session_ref="session-0123456789abcdef",
            browser_identity_digest="a" * 64,
            profile_ref=None,
            profile_revision=None,
            allowed_origins=(),
            mode="public_read_ephemeral",
            page_id="session-0123456789abcdef",
            frame_id="main",
            observation_digest="1" * 64,
            action_digest="3" * 64,
            consequence="disclose",
            now=ISSUED,
        )
        is False
    )


def test_expired_lease_rejected_by_rfc3339_now():
    lease = make_lease()
    assert lease.authorizes(
        goal_id="goal-1",
        goal_revision=2,
        session_ref="session-0123456789abcdef",
        browser_identity_digest="a" * 64,
        profile_ref="profile-0123456789abcdef",
        profile_revision=3,
        allowed_origins=("https://site.example.test",),
        mode="site_bound_interactive",
        page_id="session-0123456789abcdef",
        frame_id="main",
        observation_digest="1" * 64,
        action_digest="3" * 64,
        consequence="disclose",
        now="2026-08-28T12:00:00+00:00",
    ) is False


def test_goal_terminal_invalidates_browser_leases():
    from agent.runtime.state import cancel_goal
    from tests.kernel.fakes import conversation_with_active_goal

    state = conversation_with_active_goal()
    lease = make_lease()
    from dataclasses import replace

    state = replace(state, browser_leases=(lease,))
    goal = state.goal
    cancelled = cancel_goal(
        state, goal_id=goal.goal_id, expected_revision=goal.revision
    )
    assert cancelled.browser_leases == ()


# --------------------------------------------------------------------------- #
# Task 5 二轮审计：真实 Runtime 路径（mint、goal correction、时区比较、
# 混合 candidate 拒绝）
# --------------------------------------------------------------------------- #


def _awaiting_approval_state():
    from agent.runtime.contracts import (
        ActiveRun,
        ActiveRunStatus,
        ContinuationPhase,
        ToolCall,
    )
    from tests.kernel.fakes import conversation_with_active_goal

    state = conversation_with_active_goal()
    run_id = state.active_run.run_id if state.active_run else "run-1"
    pending = ApprovalRequest(
        request_id="req-1",
        run_id=run_id,
        tool_call_id="call-1",
        binding_digest="b" * 64,
        preview="preview",
        state_revision=state.revision,
        browser_action_candidate=make_candidate(),
    )
    active = ActiveRun(
        run_id=run_id,
        status=ActiveRunStatus.AWAITING_APPROVAL,
        phase=ContinuationPhase.TOOL,
        pending_request=pending,
        tool_calls=(ToolCall(tool_call_id="call-1", name="browser_act", arguments={}),),
    )
    return replace(state, active_run=active), pending


def test_resolve_approval_mints_browser_lease_through_reducer():
    from agent.runtime.contracts import ResolveApproval
    from agent.runtime.state import accept_action

    state, pending = _awaiting_approval_state()
    transition = accept_action(
        state,
        ResolveApproval(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_id=pending.request_id,
            binding_digest=pending.binding_digest,
            approved=True,
            approved_at=ISSUED,
        ),
    )
    assert transition.disposition.value == "accepted"
    leases = transition.state.browser_leases
    assert len(leases) == 1
    assert leases[0].approved_request_identity == pending.request_id


def test_browser_rejection_records_an_accurate_zero_effect_explanation():
    from agent.runtime.contracts import ResolveApproval
    from agent.runtime.state import accept_action

    state, pending = _awaiting_approval_state()
    transition = accept_action(
        state,
        ResolveApproval(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_id=pending.request_id,
            binding_digest=pending.binding_digest,
            approved=False,
        ),
    )

    assert transition.state.facts[-1].content["text"] == (
        "The requested browser disclose action was not run because you declined "
        "approval. No browser effect was executed."
    )
    assert transition.state.facts[-1].content["executed"] is False


def test_mixed_candidates_fail_closed():
    from agent.runtime.contracts import ProcessAuthorityCandidateV1

    candidate = make_candidate()
    process = ProcessAuthorityCandidateV1.create(
        candidate_id="pc-1",
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="w" * 64,
        command_fingerprint="f" * 64,
        readable_command="echo hi",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="c" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        trust_notice_digest="t" * 64,
        issued_at=ISSUED,
    )
    with pytest.raises(ValueError):
        ApprovalRequest(
            request_id="req-2",
            run_id="run-1",
            tool_call_id="call-1",
            binding_digest="b" * 64,
            preview="preview",
            process_authority_candidate=process,
            browser_action_candidate=candidate,
        )


def test_goal_correction_invalidates_browser_leases():
    from agent.runtime.contracts import (
        ActiveRun,
        ControlInboxRequest,
        ControlRequestKind,
    )
    from agent.runtime.state import apply_control_request
    from tests.kernel.fakes import conversation_with_active_goal

    state = conversation_with_active_goal()
    goal = state.goal
    state = replace(
        state,
        active_run=ActiveRun(run_id="run-1", owner_invocation_id="inv-1"),
        browser_leases=(make_lease(),),
    )
    request = ControlInboxRequest(
        request_id="ctrl-1",
        kind=ControlRequestKind.CORRECT,
        conversation_id=state.conversation_id,
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        invocation_id="inv-1",
        message="stop doing that",
    )
    corrected = apply_control_request(state, request)
    assert corrected.browser_leases == ()


def test_lease_expiry_compares_zoned_datetimes_not_strings():
    lease = make_lease()  # expires 2026-08-28T11:00+00:00
    # 10:00-07:00 == 17:00 UTC：实际已过期，但字符串序会误判未过期。
    assert (
        lease.authorizes(
            goal_id="goal-1",
            goal_revision=2,
            session_ref="session-0123456789abcdef",
            browser_identity_digest="a" * 64,
            profile_ref="profile-0123456789abcdef",
            profile_revision=3,
            allowed_origins=("https://site.example.test",),
            mode="site_bound_interactive",
            page_id="session-0123456789abcdef",
            frame_id="main",
            observation_digest="1" * 64,
            action_digest="3" * 64,
            consequence="disclose",
            now="2026-08-28T10:00:00-07:00",
        )
        is False
    )
