"""018 Task 9：E3 harness closed schemas、per-journey subchecks 与 mutation oracles。

冻结 E3 的 13 journey 每个都有 exact subcheck 集合——journey 通过当且仅当
其全部 subcheck 存在、为 bool True、且无多余键。mutation 对任一 subcheck
的翻转/删除/注入必须 fail。runner 不得 import tests.* 或使用 fake transport。
"""

from __future__ import annotations

import pytest

from scripts.browser_e3_journeys import (
    _browser_denial_explanation_accurate,
    _closed_rejection_observed,
    _headed_takeover_transition_observed,
    _OwnedBrowserProcesses,
    _storage_isolation_observed,
)
from scripts.run_018_e3 import (
    CLAIM_TEST_COUNT,
    JOURNEY_IDS,
    JOURNEY_SUBCHECKS,
    SCHEMA,
    _sha256_tree,
    validate_receipt,
)

# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


def make_valid_journey(journey_id: str) -> dict:
    return {key: True for key in JOURNEY_SUBCHECKS[journey_id]}


def make_valid_attempt(attempt_id: str = "attempt-1") -> dict:
    index = int(attempt_id.rsplit("-", 1)[-1])
    return {
        "attempt_id": attempt_id,
        "claim_gate": {
            "exit_code": 0,
            "pass_count": CLAIM_TEST_COUNT,
            "node_count": CLAIM_TEST_COUNT,
        },
        "journey_subchecks": {
            journey: make_valid_journey(journey) for journey in JOURNEY_IDS
        },
        "counters": {
            "provider_calls": 3,
            "browser_prepare_calls": 20,
            "browser_execute_calls": 10,
            "network_guard_attempts": 12,
            "network_sends": 8,
            "browser_submit_count": 1,
            "browser_upload_count": 1,
            "browser_download_count": 1,
            "profile_revision_at_start": 1,
            "profile_revision_at_end": 2,
            "quarantine_mutations": 1,
            "workspace_mutations": 0,
            "completion_claims": 2,
        },
        "profile_identity_sha256": f"{index:x}" * 64,
        "session_identity_sha256": f"{index + 3:x}" * 64,
        "quarantine_identity_sha256": f"{index + 6:x}" * 64,
    }


def make_valid_receipt() -> dict:
    return {
        "schema": SCHEMA,
        "materialized_root_sha256": "a" * 64,
        "seal_sha256": "b" * 64,
        "verifier_sha256": "c" * 64,
        "runner_sha256": "d" * 64,
        "wheel_sha256": "e" * 64,
        "playwright_version": "1.62.0",
        "chromium_revision": "130000",
        "chromium_executable_sha256": "f" * 64,
        "egress_fixture_sha256": "1" * 64,
        "attempts": [
            make_valid_attempt("attempt-1"),
            make_valid_attempt("attempt-2"),
            make_valid_attempt("attempt-3"),
        ],
    }


def test_browser_process_cleanup_requires_exact_descendant_identity_to_exit() -> None:
    snapshots = iter(
        (
            {100: (1, "parent-start")},
            {
                100: (1, "parent-start"),
                200: (100, "browser-start"),
            },
            {
                100: (1, "parent-start"),
                200: (100, "browser-start"),
            },
            {100: (1, "parent-start")},
        )
    )
    tracker = _OwnedBrowserProcesses(
        parent_pid=100,
        snapshotter=lambda: next(snapshots),
    )
    assert tracker.observe()
    assert not tracker.confirmed_gone(timeout=0)
    assert tracker.confirmed_gone(timeout=0)


def test_j2_storage_isolation_requires_nonempty_cookie_and_local_storage_seed() -> None:
    fresh = "Local storage absent Cookie absent Storage clean"
    both_seeded = "Local storage present Cookie present Storage leaked"

    assert _storage_isolation_observed(
        both_seeded,
        fresh,
        first_session_cleaned=True,
    )
    assert not _storage_isolation_observed(
        "Storage seeded",
        fresh,
        first_session_cleaned=True,
    )
    assert not _storage_isolation_observed(
        "Local storage present Storage leaked",
        fresh,
        first_session_cleaned=True,
    )
    assert not _storage_isolation_observed(
        "Cookie present Storage leaked",
        fresh,
        first_session_cleaned=True,
    )


def test_j2_storage_isolation_rejects_any_fresh_session_reuse() -> None:
    seeded = "Local storage present Cookie present Storage leaked"

    assert not _storage_isolation_observed(
        seeded,
        "Local storage present Cookie absent Storage leaked",
        first_session_cleaned=True,
    )
    assert not _storage_isolation_observed(
        seeded,
        "Local storage absent Cookie present Storage leaked",
        first_session_cleaned=True,
    )
    assert not _storage_isolation_observed(
        seeded,
        "Local storage absent Cookie absent Storage clean",
        first_session_cleaned=False,
    )


@pytest.mark.parametrize("missing_index", range(5))
def test_j4_each_disallowed_kind_requires_its_own_rejection(
    missing_index: int,
) -> None:
    before = [(0, 0, 0)] * 5
    after = [(1, 1, 0)] * 5
    after[missing_index] = (0, 0, 0)

    assert not all(
        _closed_rejection_observed(old, new)
        for old, new in zip(before, after, strict=True)
    )


def test_j4_disallowed_kind_rejects_any_network_send() -> None:
    assert _closed_rejection_observed((0, 0, 0), (1, 1, 0))
    assert not _closed_rejection_observed((0, 0, 0), (1, 1, 1))


def test_materialized_root_ignores_runtime_caches_but_binds_source(tmp_path) -> None:
    source = tmp_path / "agent.py"
    source.write_text("value = 1\n", encoding="utf-8")
    initial = _sha256_tree(tmp_path)

    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "agent.cpython-312.pyc").write_bytes(b"generated")
    pytest_cache = tmp_path / ".pytest_cache" / "v" / "cache"
    pytest_cache.mkdir(parents=True)
    (pytest_cache / "nodeids").write_text("[]", encoding="utf-8")
    assert _sha256_tree(tmp_path) == initial

    source.write_text("value = 2\n", encoding="utf-8")
    assert _sha256_tree(tmp_path) != initial


# ---------------------------------------------------------------------------
# Mutation oracles：对每个 journey 的 load-bearing subcheck + counters + gate
# ---------------------------------------------------------------------------


def _mutate_subcheck(receipt: dict, journey: str, subcheck: str) -> dict:
    mutated = make_valid_receipt()
    mutated["attempts"][0]["journey_subchecks"][journey][subcheck] = False
    return mutated


def _all_subcheck_mutations() -> list[tuple[str, str]]:
    return [
        (journey, subcheck)
        for journey in JOURNEY_IDS
        for subcheck in sorted(JOURNEY_SUBCHECKS[journey])
    ]


@pytest.mark.parametrize(
    ("journey", "subcheck"),
    _all_subcheck_mutations(),
    ids=[f"{j}_{s}" for j, s in _all_subcheck_mutations()],
)
def test_mutation_subcheck_false(journey: str, subcheck: str) -> None:
    receipt = _mutate_subcheck(make_valid_receipt(), journey, subcheck)
    errors = validate_receipt(receipt)
    assert errors, f"J{journey}.{subcheck}=False must produce errors"
    assert any(journey in err for err in errors)


@pytest.mark.parametrize("journey", JOURNEY_IDS)
def test_mutation_subcheck_missing(journey: str) -> None:
    receipt = make_valid_receipt()
    subchecks = receipt["attempts"][0]["journey_subchecks"][journey]
    first = sorted(subchecks)[0]
    del subchecks[first]
    errors = validate_receipt(receipt)
    assert any("missing" in err for err in errors), journey


@pytest.mark.parametrize("journey", JOURNEY_IDS)
def test_mutation_subcheck_extra(journey: str) -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["journey_subchecks"][journey]["injected"] = True
    errors = validate_receipt(receipt)
    assert any("extra" in err for err in errors), journey


@pytest.mark.parametrize("journey", JOURNEY_IDS)
def test_mutation_subcheck_non_bool(journey: str) -> None:
    receipt = make_valid_receipt()
    subchecks = receipt["attempts"][0]["journey_subchecks"][journey]
    subchecks[sorted(subchecks)[0]] = 1  # int, not bool
    errors = validate_receipt(receipt)
    assert any("must be bool" in err for err in errors), journey


def test_mutation_journey_missing() -> None:
    receipt = make_valid_receipt()
    del receipt["attempts"][0]["journey_subchecks"]["J13"]
    errors = validate_receipt(receipt)
    assert any("journey set mismatch" in err for err in errors)


def test_mutation_journey_extra() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["journey_subchecks"]["J14"] = {"x": True}
    errors = validate_receipt(receipt)
    assert any("journey set mismatch" in err for err in errors)


def test_mutation_counter_negative() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["counters"]["network_sends"] = -1
    errors = validate_receipt(receipt)
    assert any("non-negative" in err for err in errors)


def test_mutation_counter_bool() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["counters"]["browser_submit_count"] = True
    errors = validate_receipt(receipt)
    assert any("non-negative int" in err for err in errors)


def test_mutation_counter_missing() -> None:
    receipt = make_valid_receipt()
    del receipt["attempts"][0]["counters"]["completion_claims"]
    errors = validate_receipt(receipt)
    assert any("counter set mismatch" in err for err in errors)


@pytest.mark.parametrize(
    ("counter", "value"),
    (
        ("provider_calls", 1),
        ("browser_prepare_calls", 0),
        ("browser_execute_calls", 0),
        ("network_guard_attempts", 5),
        ("network_sends", 0),
        ("browser_submit_count", 0),
        ("browser_upload_count", 2),
        ("browser_download_count", 0),
        ("quarantine_mutations", 0),
        ("workspace_mutations", 1),
        ("completion_claims", 1),
        ("profile_revision_at_end", 3),
    ),
)
def test_mutation_counter_semantics(counter: str, value: int) -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["counters"][counter] = value
    assert validate_receipt(receipt), counter


def test_mutation_claim_gate_nonzero() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["claim_gate"]["exit_code"] = 1
    errors = validate_receipt(receipt)
    assert any("exit_code must be 0" in err for err in errors)


def test_mutation_attempt_count_two() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"] = receipt["attempts"][:2]
    errors = validate_receipt(receipt)
    assert any("exactly three" in err for err in errors)


def test_mutation_attempt_identity_reused() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][1]["session_identity_sha256"] = (
        receipt["attempts"][0]["session_identity_sha256"]
    )
    errors = validate_receipt(receipt)
    assert any("must be fresh" in err for err in errors)


def test_mutation_claim_gate_partial_pass() -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["claim_gate"]["pass_count"] -= 1
    errors = validate_receipt(receipt)
    assert any("every exact node" in err for err in errors)


def test_mutation_empty_chromium_revision() -> None:
    receipt = make_valid_receipt()
    receipt["chromium_revision"] = ""
    errors = validate_receipt(receipt)
    assert any("non-empty" in err for err in errors)


def test_valid_receipt_zero_errors() -> None:
    assert validate_receipt(make_valid_receipt()) == []


def test_journey_count_thirteen() -> None:
    assert len(JOURNEY_IDS) == 13
    assert len(JOURNEY_SUBCHECKS) == 13


def test_j6_headed_takeover_oracle_rejects_noop_and_wrong_mode() -> None:
    assert _headed_takeover_transition_observed((True,), (True, False))
    assert not _headed_takeover_transition_observed((True,), (True,))
    assert not _headed_takeover_transition_observed((True,), (True, True))
    assert not _headed_takeover_transition_observed((), (False,))


def test_j8_denial_explanation_oracle_rejects_opposite_semantics() -> None:
    assert _browser_denial_explanation_accurate(
        "The requested browser commit action was not run because you declined "
        "approval. No browser effect was executed."
    )
    assert not _browser_denial_explanation_accurate(
        "The requested browser commit action ran because approval was granted. "
        "A browser effect was executed."
    )
