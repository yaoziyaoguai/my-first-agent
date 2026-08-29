"""018 Task 2 Step 3：opaque session ledger 的 Reds（先 Red）。

覆盖冻结 plan Task 2 Step 3/4：exact phase 迁移
OPENING→ACTIVE→ACTION_PREPARED→EXECUTING→RESULT_OBSERVED→CLOSED、CAS、
corruption fail closed、action-observation binding、ledger 只存 opaque
IDs/digests（无 URL/body/cookie/account 原文）、EXECUTING 无 result 为
recoverable unknown（绝不静默转 not-executed）、profile revision drift
阻断推进。
"""

import json
import stat

import pytest

from agent.browser.contracts import BrowserMode, BrowserSessionSpecV1
from agent.browser.session_store import (
    BrowserSessionRecordV1,
    BrowserSessionStore,
    SessionActionOutcome,
    SessionIntegrityError,
    SessionNotFoundError,
    SessionObservationBindingError,
    SessionPhase,
    SessionPhaseConflict,
    SessionProfileDriftError,
    SessionRecovery,
)

SPEC = BrowserSessionSpecV1.public_read(goal_id="goal-1", goal_revision=1)
BROWSER_DIGEST = "b" * 64
OBSERVATION_A = "1" * 64
OBSERVATION_B = "2" * 64
ACTION_A = "3" * 64


def make_store(tmp_path) -> BrowserSessionStore:
    return BrowserSessionStore(root=tmp_path / "sessions")


def ledger_path(tmp_path, record) -> str:
    return tmp_path / "sessions" / record.session_id / "ledger.json"


def begin_session(tmp_path):
    return make_store(tmp_path).begin(
        spec=SPEC, profile_revision=None, browser_identity_digest=BROWSER_DIGEST,
    )


def active_session(tmp_path):
    store = make_store(tmp_path)
    record = store.begin(
        spec=SPEC, profile_revision=None, browser_identity_digest=BROWSER_DIGEST,
    )
    record = store.compare_and_swap(
        record, new_phase=SessionPhase.ACTIVE, expected_profile_revision=None,
    )
    return store, store.record_observation(
        record, observation_digest=OBSERVATION_A, expected_profile_revision=None,
    )


def test_begin_creates_opaque_owner_only_opening_ledger(tmp_path):
    record = begin_session(tmp_path)
    assert record.phase is SessionPhase.OPENING
    assert record.session_id.startswith("session-")
    assert record.spec_digest == SPEC.identity_digest
    assert record.last_action_digest is None
    directory = tmp_path / "sessions" / record.session_id
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    metadata = directory / "ledger.json"
    assert stat.S_IMODE(metadata.stat().st_mode) == 0o600
    raw = metadata.read_bytes()
    # 只存 opaque IDs/digests：goal/URL/account 原文不得出现。
    assert b"goal-1" not in raw
    assert b"https://" not in raw


def test_record_exposes_only_closed_digest_fields(tmp_path):
    from dataclasses import fields

    begin_session(tmp_path)
    assert {item.name for item in fields(BrowserSessionRecordV1)} == {
        "session_id",
        "spec_digest",
        "profile_ref",
        "profile_revision",
        "browser_identity_digest",
        "phase",
        "observation_digest",
        "last_action_digest",
        "last_action_outcome",
        "action_count",
    }


def test_full_lifecycle_follows_frozen_transitions(tmp_path):
    store, record = active_session(tmp_path)
    assert record.phase is SessionPhase.ACTIVE
    assert record.observation_digest == OBSERVATION_A
    prepared = store.begin_action(
        record,
        action_digest=ACTION_A,
        observation_digest=OBSERVATION_A,
        expected_profile_revision=None,
    )
    assert prepared.phase is SessionPhase.ACTION_PREPARED
    assert prepared.action_count == 1
    executing = store.compare_and_swap(
        prepared, new_phase=SessionPhase.EXECUTING, expected_profile_revision=None,
    )
    observed = store.record_result(
        executing, outcome=SessionActionOutcome.APPLIED, expected_profile_revision=None,
    )
    assert observed.phase is SessionPhase.RESULT_OBSERVED
    assert observed.last_action_outcome is SessionActionOutcome.APPLIED
    # 新 observation 后可以再次进入 action 循环。
    refreshed = store.record_observation(
        observed, observation_digest=OBSERVATION_B, expected_profile_revision=None,
    )
    again = store.begin_action(
        refreshed,
        action_digest="4" * 64,
        observation_digest=OBSERVATION_B,
        expected_profile_revision=None,
    )
    assert again.action_count == 2
    closed = store.close(
        store.record_result(
            store.compare_and_swap(
                again,
                new_phase=SessionPhase.EXECUTING,
                expected_profile_revision=None,
            ),
            outcome=SessionActionOutcome.NOT_EXECUTED,
            expected_profile_revision=None,
        ),
        expected_profile_revision=None,
    )
    assert closed.phase is SessionPhase.CLOSED


def record_at_phase(tmp_path, phase: SessionPhase):
    """推进到指定 phase 的最少合法步骤（迁移类测试共用）。"""
    store = make_store(tmp_path)
    record = store.begin(
        spec=SPEC, profile_revision=None, browser_identity_digest=BROWSER_DIGEST,
    )
    if phase is SessionPhase.OPENING:
        return store, record
    record = store.compare_and_swap(
        record, new_phase=SessionPhase.ACTIVE, expected_profile_revision=None,
    )
    record = store.record_observation(
        record, observation_digest=OBSERVATION_A, expected_profile_revision=None,
    )
    if phase is SessionPhase.ACTIVE:
        return store, record
    record = store.begin_action(
        record,
        action_digest=ACTION_A,
        observation_digest=OBSERVATION_A,
        expected_profile_revision=None,
    )
    record = store.compare_and_swap(
        record, new_phase=SessionPhase.EXECUTING, expected_profile_revision=None,
    )
    if phase is SessionPhase.EXECUTING:
        return store, record
    record = store.record_result(
        record, outcome=SessionActionOutcome.APPLIED, expected_profile_revision=None,
    )
    if phase is SessionPhase.RESULT_OBSERVED:
        return store, record
    return store, store.close(record, expected_profile_revision=None)


@pytest.mark.parametrize(
    ("start_phase", "new_phase"),
    [
        (SessionPhase.OPENING, SessionPhase.ACTION_PREPARED),
        (SessionPhase.OPENING, SessionPhase.EXECUTING),
        (SessionPhase.OPENING, SessionPhase.RESULT_OBSERVED),
        (SessionPhase.ACTIVE, SessionPhase.EXECUTING),
        (SessionPhase.ACTIVE, SessionPhase.RESULT_OBSERVED),
        (SessionPhase.RESULT_OBSERVED, SessionPhase.EXECUTING),
        (SessionPhase.EXECUTING, SessionPhase.CLOSED),
        (SessionPhase.CLOSED, SessionPhase.ACTIVE),
        (SessionPhase.CLOSED, SessionPhase.ACTION_PREPARED),
    ],
)
def test_illegal_phase_transitions_fail_closed(tmp_path, start_phase, new_phase):
    store, record = record_at_phase(tmp_path, start_phase)
    with pytest.raises(SessionPhaseConflict):
        store.compare_and_swap(record, new_phase=new_phase, expected_profile_revision=None)


@pytest.mark.parametrize(
    ("start_phase", "new_phase"),
    [
        (SessionPhase.ACTIVE, SessionPhase.ACTION_PREPARED),
        (SessionPhase.RESULT_OBSERVED, SessionPhase.ACTION_PREPARED),
        (SessionPhase.EXECUTING, SessionPhase.RESULT_OBSERVED),
        (SessionPhase.ACTIVE, SessionPhase.CLOSED),
        (SessionPhase.RESULT_OBSERVED, SessionPhase.CLOSED),
    ],
)
def test_cas_cannot_bypass_domain_specific_apis(tmp_path, start_phase, new_phase):
    # 这些迁移虽然存在于冻结迁移集，但只能经 begin_action/record_result/close
    # 完成（binding + profile revision 检查）；公开 CAS 只做机械迁移。
    store, record = record_at_phase(tmp_path, start_phase)
    with pytest.raises(SessionPhaseConflict):
        store.compare_and_swap(record, new_phase=new_phase, expected_profile_revision=None)


def test_stale_record_cannot_drive_cas(tmp_path):
    store, record = active_session(tmp_path)
    store.begin_action(
        record,
        action_digest=ACTION_A,
        observation_digest=OBSERVATION_A,
        expected_profile_revision=None,
    )
    # record 仍停在 ACTIVE：stale phase 必须被 CAS 拒绝。
    with pytest.raises(SessionPhaseConflict):
        store.compare_and_swap(
            record, new_phase=SessionPhase.EXECUTING, expected_profile_revision=None,
        )


def test_forged_record_identity_is_rejected(tmp_path):
    from dataclasses import replace

    store, record = active_session(tmp_path)
    forged = replace(record, spec_digest="9" * 64)
    with pytest.raises(SessionIntegrityError):
        store.compare_and_swap(
            forged, new_phase=SessionPhase.ACTION_PREPARED, expected_profile_revision=None,
        )
    with pytest.raises(SessionIntegrityError):
        store.begin_action(
            forged,
            action_digest=ACTION_A,
            observation_digest=OBSERVATION_A,
            expected_profile_revision=None,
        )


def test_action_must_bind_current_observation(tmp_path):
    store, record = active_session(tmp_path)
    with pytest.raises(SessionObservationBindingError):
        store.begin_action(
            record,
            action_digest=ACTION_A,
            observation_digest=OBSERVATION_B,
            expected_profile_revision=None,
        )
    # 拒绝零副作用：phase 与 observation 绑定未动。
    reloaded = store.load(record.session_id)
    assert reloaded.phase is SessionPhase.ACTIVE
    assert reloaded.observation_digest == OBSERVATION_A


def test_record_result_binds_last_action_and_phase(tmp_path):
    from dataclasses import replace

    store, record = active_session(tmp_path)
    executing = store.compare_and_swap(
        store.begin_action(
            record,
            action_digest=ACTION_A,
            observation_digest=OBSERVATION_A,
            expected_profile_revision=None,
        ),
        new_phase=SessionPhase.EXECUTING,
        expected_profile_revision=None,
    )
    forged = replace(executing, last_action_digest="5" * 64)
    with pytest.raises(SessionIntegrityError):
        store.record_result(
            forged, outcome=SessionActionOutcome.APPLIED, expected_profile_revision=None,
        )
    # 非 EXECUTING 阶段不能记 result。
    with pytest.raises(SessionPhaseConflict):
        store.record_result(
            record, outcome=SessionActionOutcome.APPLIED, expected_profile_revision=None,
        )


def test_executing_without_result_is_recoverable_unknown(tmp_path):
    store, record = active_session(tmp_path)
    store.compare_and_swap(
        store.begin_action(
            record,
            action_digest=ACTION_A,
            observation_digest=OBSERVATION_A,
            expected_profile_revision=None,
        ),
        new_phase=SessionPhase.EXECUTING,
        expected_profile_revision=None,
    )
    reopened = make_store(tmp_path)
    loaded = reopened.load(record.session_id)
    assert loaded.phase is SessionPhase.EXECUTING
    assert loaded.last_action_outcome is None
    # 重启视角：pending 分类必须是 unknown，绝不静默转 not-executed。
    assert reopened.pending_recovery(loaded) is SessionRecovery.UNKNOWN_OUTCOME
    # load 是只读的：ledger 未被改写。
    assert reopened.load(record.session_id).phase is SessionPhase.EXECUTING
    assert reopened.load(record.session_id).last_action_outcome is None
    # settled session 没有 pending recovery。
    settled = make_store(tmp_path).load(
        active_session(tmp_path)[1].session_id
    )
    assert make_store(tmp_path).pending_recovery(settled) is SessionRecovery.NONE


def test_profile_revision_drift_blocks_progress(tmp_path):
    store = make_store(tmp_path)
    spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-0123456789abcdef",
        allowed_origins=("https://example.test",),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
    )
    record = store.begin(
        spec=spec, profile_revision=1, browser_identity_digest=BROWSER_DIGEST,
    )
    record = store.compare_and_swap(
        record, new_phase=SessionPhase.ACTIVE, expected_profile_revision=1,
    )
    record = store.record_observation(
        record, observation_digest=OBSERVATION_A, expected_profile_revision=1,
    )
    # profile revision 已前进（takeover complete 等场景）：旧 session 不得推进。
    with pytest.raises(SessionProfileDriftError):
        store.begin_action(
            record,
            action_digest=ACTION_A,
            observation_digest=OBSERVATION_A,
            expected_profile_revision=2,
        )
    with pytest.raises(SessionProfileDriftError):
        store.close(record, expected_profile_revision=2)


def rewrite_ledger(tmp_path, record, mutation):
    path = ledger_path(tmp_path, record)
    payload = json.loads(path.read_text())
    mutation(payload)
    path.write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda p: p.update(extra=1), id="extra-key"),
        pytest.param(lambda p: p.update(phase="dreaming"), id="unknown-phase"),
        pytest.param(lambda p: p.update(action_count=True), id="bool-count"),
        pytest.param(lambda p: p.update(observation_digest="https://evil.test"), id="raw-url"),
        pytest.param(lambda p: p.update(spec_digest="Z" * 64), id="bad-digest"),
        pytest.param(lambda p: p.pop("browser_identity_digest"), id="missing-key"),
    ],
)
def test_corrupt_ledger_fails_closed(tmp_path, mutation):
    record = begin_session(tmp_path)
    rewrite_ledger(tmp_path, record, mutation)
    with pytest.raises(SessionIntegrityError):
        make_store(tmp_path).load(record.session_id)


def test_ledger_symlink_and_missing_fail_closed(tmp_path):
    record = begin_session(tmp_path)
    path = ledger_path(tmp_path, record)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(SessionIntegrityError):
        make_store(tmp_path).load(record.session_id)
    with pytest.raises(SessionNotFoundError):
        make_store(tmp_path).load("session-doesnotexist0")


# --------------------------------------------------------------------------- #
# Task 2 session-store 审计（2026-08-28）：CAS seam 限定、跨字段矛盾、
# begin 配对校验
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda p: p.update(observation_digest=OBSERVATION_A),
            id="opening-with-observation",
        ),
        pytest.param(lambda p: p.update(action_count=1), id="opening-with-count"),
        pytest.param(
            lambda p: p.update(
                phase="action_prepared",
                observation_digest=OBSERVATION_A,
                action_count=1,
                last_action_digest=None,
            ),
            id="prepared-without-action",
        ),
        pytest.param(
            lambda p: p.update(
                phase="action_prepared",
                observation_digest=OBSERVATION_A,
                action_count=1,
                last_action_digest=ACTION_A,
                last_action_outcome="applied",
            ),
            id="prepared-with-outcome",
        ),
        pytest.param(
            lambda p: p.update(
                phase="executing",
                observation_digest=OBSERVATION_A,
                last_action_digest=ACTION_A,
                action_count=0,
            ),
            id="executing-with-zero-count",
        ),
        pytest.param(
            lambda p: p.update(
                phase="result_observed",
                observation_digest=OBSERVATION_A,
                action_count=1,
                last_action_digest=ACTION_A,
                last_action_outcome=None,
            ),
            id="observed-without-outcome",
        ),
        pytest.param(
            lambda p: p.update(
                phase="result_observed",
                observation_digest=OBSERVATION_A,
                action_count=1,
                last_action_digest=None,
                last_action_outcome="applied",
            ),
            id="observed-without-action",
        ),
    ],
)
def test_cross_field_contradictions_fail_closed(tmp_path, mutation):
    record = begin_session(tmp_path)
    rewrite_ledger(tmp_path, record, mutation)
    with pytest.raises(SessionIntegrityError):
        make_store(tmp_path).load(record.session_id)


def test_begin_rejects_incoherent_profile_binding(tmp_path):
    store = make_store(tmp_path)
    # public-read spec 不得携带 profile revision。
    with pytest.raises(SessionIntegrityError):
        store.begin(
            spec=SPEC, profile_revision=1, browser_identity_digest=BROWSER_DIGEST,
        )
    site_spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-0123456789abcdef",
        allowed_origins=("https://example.test",),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
    )
    # site-bound spec 必须携带 positive revision（None/bool 都拒绝）。
    with pytest.raises(SessionIntegrityError):
        store.begin(
            spec=site_spec, profile_revision=None, browser_identity_digest=BROWSER_DIGEST,
        )
    with pytest.raises(SessionIntegrityError):
        store.begin(
            spec=site_spec, profile_revision=True, browser_identity_digest=BROWSER_DIGEST,
        )
    # 非 canonical profile_ref 不得建立 ledger。
    forged_spec = BrowserSessionSpecV1(
        mode=BrowserMode.SITE_BOUND_INTERACTIVE,
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="not-a-canonical-profile-id",
        allowed_origins=("https://example.test",),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
    )
    with pytest.raises(SessionIntegrityError):
        store.begin(
            spec=forged_spec, profile_revision=1, browser_identity_digest=BROWSER_DIGEST,
        )
    # 拒绝必须零副作用：sessions root 下没有任何 ledger。
    sessions_root = tmp_path / "sessions"
    if sessions_root.exists():
        assert list(sessions_root.glob("session-*")) == []


def test_site_bound_drift_blocks_every_public_mutation(tmp_path):
    # spec §4.2：profile revision 变化使整个 site-bound session authority 失效——
    # 包括机械 CAS 与 observation 绑定；effect 前（ACTION_PREPARED→EXECUTING）
    # 必须重验，封住 prepare 后 drift 的 TOCTOU。
    spec = BrowserSessionSpecV1.site_bound(
        goal_id="goal-1",
        goal_revision=1,
        profile_ref="profile-0123456789abcdef",
        allowed_origins=("https://example.test",),
        action_budget=8,
        profile_revision=1,
        browser_identity_digest="b" * 64,
        expiry_monotonic=10000.0,
    )
    store = make_store(tmp_path)
    record = store.begin(
        spec=spec, profile_revision=1, browser_identity_digest=BROWSER_DIGEST,
    )
    with pytest.raises(SessionProfileDriftError):
        store.compare_and_swap(
            record, new_phase=SessionPhase.ACTIVE, expected_profile_revision=2,
        )
    assert store.load(record.session_id).phase is SessionPhase.OPENING
    activated = store.compare_and_swap(
        record, new_phase=SessionPhase.ACTIVE, expected_profile_revision=1,
    )
    with pytest.raises(SessionProfileDriftError):
        store.record_observation(
            activated, observation_digest=OBSERVATION_A, expected_profile_revision=2,
        )
    assert store.load(record.session_id).observation_digest is None
    observed = store.record_observation(
        activated, observation_digest=OBSERVATION_A, expected_profile_revision=1,
    )
    prepared = store.begin_action(
        observed,
        action_digest=ACTION_A,
        observation_digest=OBSERVATION_A,
        expected_profile_revision=1,
    )
    with pytest.raises(SessionProfileDriftError):
        store.compare_and_swap(
            prepared, new_phase=SessionPhase.EXECUTING, expected_profile_revision=2,
        )
    assert store.load(record.session_id).phase is SessionPhase.ACTION_PREPARED


# --------------------------------------------------------------------------- #
# Task 2 durable-ledger 审计（2026-08-28 第三轮）：profile binding 配对、
# CLOSED 来源形态 union、begin/load 单一 decode truth
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda p: p.update(profile_ref="profile-0123456789abcdef"),
            id="ref-without-revision",
        ),
        pytest.param(lambda p: p.update(profile_revision=1), id="revision-without-ref"),
    ],
)
def test_ledger_profile_binding_must_be_paired(tmp_path, mutation):
    # 一边有值一边 null 的损坏 ledger 必须被 load 拒绝。
    record = begin_session(tmp_path)
    rewrite_ledger(tmp_path, record, mutation)
    with pytest.raises(SessionIntegrityError):
        make_store(tmp_path).load(record.session_id)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            lambda p: p.update(phase="closed", action_count=1),
            id="closed-count-without-action",
        ),
        pytest.param(
            lambda p: p.update(phase="closed", action_count=1, last_action_digest=ACTION_A),
            id="closed-action-without-outcome",
        ),
        pytest.param(
            lambda p: p.update(phase="closed", action_count=1, last_action_outcome="applied"),
            id="closed-outcome-without-action",
        ),
    ],
)
def test_closed_ledger_rejects_mixed_source_shapes(tmp_path, mutation):
    record = begin_session(tmp_path)
    rewrite_ledger(tmp_path, record, mutation)
    with pytest.raises(SessionIntegrityError):
        make_store(tmp_path).load(record.session_id)


def test_closed_ledger_accepts_both_legal_source_shapes(tmp_path):
    # from ACTIVE：无 action 数据的空形态。
    store, record = record_at_phase(tmp_path, SessionPhase.ACTIVE)
    closed_active = store.close(record, expected_profile_revision=None)
    assert make_store(tmp_path).load(closed_active.session_id).phase is SessionPhase.CLOSED
    # from RESULT_OBSERVED：action+outcome+observation+count 完整形态。
    store, record = record_at_phase(tmp_path, SessionPhase.RESULT_OBSERVED)
    closed_observed = store.close(record, expected_profile_revision=None)
    reopened = make_store(tmp_path)
    assert reopened.load(closed_observed.session_id).phase is SessionPhase.CLOSED
    assert reopened.load(closed_observed.session_id).last_action_outcome is not None
