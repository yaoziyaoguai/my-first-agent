"""019 portable U2A receipt 的 closed schema 与 mutation oracles。"""

from __future__ import annotations

import copy

import pytest

from scripts.run_019_core_e3 import (
    CLAIM_IDS,
    CLAIM_TEST_COUNT,
    COUNT_KEYS,
    JOURNEY_IDS,
    JOURNEY_SUBCHECKS,
    SCHEMA,
    PortableJourneySuite,
    run_attempt,
    validate_receipt,
)


def _gate(count: int) -> dict[str, int]:
    return {"exit_code": 0, "pass_count": count, "node_count": count}


def make_valid_attempt(index: int) -> dict:
    return {
        "attempt_id": f"attempt-{index}",
        "claim_gate": _gate(CLAIM_TEST_COUNT),
        "runtime_gate": _gate(4),
        "journey_subchecks": {
            journey: {key: True for key in JOURNEY_SUBCHECKS[journey]}
            for journey in JOURNEY_IDS
        },
        "counters": {
            "executor_initialize_calls": 1,
            "executor_run_calls": 1,
            "supervisor_run_calls": 1,
            "sandbox_calls": 0,
            "browser_calls": 0,
            "credential_resolutions": 0,
            "host_workspace_mutations": 0,
            "purge_objects_confirmed": 2,
        },
        "repository_identity_sha256": f"{index:x}" * 64,
        "workspace_identity_sha256": f"{index + 3:x}" * 64,
        "supervisor_identity_sha256": f"{index + 6:x}" * 64,
        "executor_identity_sha256": f"{index + 9:x}" * 64,
    }


def make_valid_receipt() -> dict:
    return {
        "schema": SCHEMA,
        "status": "accepted/delivered",
        "materialized_root_sha256": "a" * 64,
        "seal_sha256": "b" * 64,
        "verifier_sha256": "c" * 64,
        "runner_sha256": "d" * 64,
        "wheel_sha256": "e" * 64,
        "spec_product_review_sha256": "f" * 64,
        "standards_architecture_review_sha256": "1" * 64,
        "source_full_gate": _gate(1472),
        "materialized_full_gate": _gate(1472),
        "claims": {claim: True for claim in CLAIM_IDS},
        "attempts": [make_valid_attempt(index) for index in range(1, 4)],
    }


def test_valid_receipt_has_no_errors() -> None:
    assert validate_receipt(make_valid_receipt()) == []


def test_portable_journeys_are_non_vacuous_and_all_green() -> None:
    suite = PortableJourneySuite("focused-attempt", runtime_gate_green=True)

    journeys = suite.run()

    assert tuple(journeys) == JOURNEY_IDS
    assert all(
        set(journeys[journey]) == JOURNEY_SUBCHECKS[journey]
        and all(journeys[journey].values())
        for journey in JOURNEY_IDS
    )
    assert suite.executor_initialize_calls == 1
    assert suite.executor_run_calls == 1
    assert suite.supervisor_run_calls == 1
    assert suite.purge_objects_confirmed > 0


def test_runtime_gate_failure_makes_runtime_owned_journeys_fail() -> None:
    journeys = PortableJourneySuite(
        "runtime-gate-red",
        runtime_gate_green=False,
    ).run()

    assert not journeys["J5"]["runtime_caller_gate"]
    assert not all(journeys["J11"].values())


def test_fresh_attempt_runs_exact_u1_and_runtime_gates() -> None:
    attempt = run_attempt("focused-gated-attempt")

    assert attempt["claim_gate"] == {
        "exit_code": 0,
        "pass_count": CLAIM_TEST_COUNT,
        "node_count": CLAIM_TEST_COUNT,
    }
    assert attempt["runtime_gate"] == {
        "exit_code": 0,
        "pass_count": 4,
        "node_count": 4,
    }
    assert all(
        all(attempt["journey_subchecks"][journey].values())
        for journey in JOURNEY_IDS
    )


def test_receipt_requires_exact_top_level_schema() -> None:
    receipt = make_valid_receipt()
    receipt["injected"] = True
    assert validate_receipt(receipt) == ["receipt keys must match the strict schema"]


@pytest.mark.parametrize("journey", JOURNEY_IDS)
def test_each_journey_requires_exact_subcheck_set(journey: str) -> None:
    missing = make_valid_receipt()
    first = sorted(JOURNEY_SUBCHECKS[journey])[0]
    del missing["attempts"][0]["journey_subchecks"][journey][first]
    assert any("missing subchecks" in item for item in validate_receipt(missing))

    extra = make_valid_receipt()
    extra["attempts"][0]["journey_subchecks"][journey]["injected"] = True
    assert any("extra subchecks" in item for item in validate_receipt(extra))


@pytest.mark.parametrize(
    ("journey", "subcheck"),
    [
        (journey, subcheck)
        for journey in JOURNEY_IDS
        for subcheck in sorted(JOURNEY_SUBCHECKS[journey])
    ],
)
def test_every_journey_subcheck_false_fails_receipt(
    journey: str,
    subcheck: str,
) -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["journey_subchecks"][journey][subcheck] = False
    assert any(
        item == f"{journey}.{subcheck}: must be True"
        for item in validate_receipt(receipt)
    )


@pytest.mark.parametrize("claim", CLAIM_IDS)
def test_every_claim_false_fails_receipt(claim: str) -> None:
    receipt = make_valid_receipt()
    receipt["claims"][claim] = False
    assert f"claim {claim} must be True" in validate_receipt(receipt)


@pytest.mark.parametrize(
    "counter",
    (
        "sandbox_calls",
        "browser_calls",
        "credential_resolutions",
        "host_workspace_mutations",
    ),
)
def test_platform_effect_counters_must_remain_zero(counter: str) -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["counters"][counter] = 1
    assert f"counter {counter} must equal 0" in validate_receipt(receipt)


@pytest.mark.parametrize(
    "counter",
    (
        "executor_initialize_calls",
        "executor_run_calls",
        "supervisor_run_calls",
        "purge_objects_confirmed",
    ),
)
def test_non_vacuous_counters_must_be_positive(counter: str) -> None:
    receipt = make_valid_receipt()
    receipt["attempts"][0]["counters"][counter] = 0
    assert f"counter {counter} must be positive" in validate_receipt(receipt)


def test_attempt_adapter_identities_must_be_fresh() -> None:
    for key in (
        "repository_identity_sha256",
        "workspace_identity_sha256",
        "supervisor_identity_sha256",
        "executor_identity_sha256",
    ):
        receipt = make_valid_receipt()
        receipt["attempts"][1][key] = receipt["attempts"][0][key]
        assert any(
            item == f"{key} values must be fresh across attempts"
            for item in validate_receipt(receipt)
        )


def test_two_review_axes_must_be_distinct() -> None:
    receipt = make_valid_receipt()
    receipt["standards_architecture_review_sha256"] = receipt[
        "spec_product_review_sha256"
    ]
    assert "the two independent review digests must differ" in validate_receipt(receipt)


def test_three_attempts_and_complete_gates_are_required() -> None:
    two = make_valid_receipt()
    two["attempts"].pop()
    assert "receipt requires exactly three attempts" in validate_receipt(two)

    partial = make_valid_receipt()
    partial["attempts"][0]["claim_gate"]["pass_count"] -= 1
    assert "claim_gate must pass every exact node once" in validate_receipt(partial)

    runtime = make_valid_receipt()
    runtime["attempts"][0]["runtime_gate"]["exit_code"] = 1
    assert "runtime_gate exit_code must be 0" in validate_receipt(runtime)


def test_source_and_materialized_full_gates_cannot_be_skipped() -> None:
    for key in ("source_full_gate", "materialized_full_gate"):
        receipt = make_valid_receipt()
        receipt[key]["node_count"] = 0
        receipt[key]["pass_count"] = 0
        assert f"{key} node_count must be a positive int" in validate_receipt(receipt)


def test_receipt_contains_no_unbounded_or_private_fields() -> None:
    receipt = make_valid_receipt()
    encoded = repr(receipt).casefold()
    for forbidden in (
        "task_text",
        "credential_value",
        "absolute_path",
        "model_output",
        "tool_result",
        "transcript",
    ):
        assert forbidden not in encoded
    assert set(receipt["attempts"][0]["counters"]) == COUNT_KEYS


def test_bool_as_int_and_unknown_claim_are_rejected() -> None:
    receipt = make_valid_receipt()
    receipt["claims"]["C1"] = 1
    assert "claim C1 must be bool" in validate_receipt(receipt)

    extra = copy.deepcopy(receipt)
    extra["claims"]["C26"] = True
    assert "claim set must be exactly C1..C25" in validate_receipt(extra)
