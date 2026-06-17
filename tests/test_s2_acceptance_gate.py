from __future__ import annotations

from agent.acceptance_gate import (
    AcceptanceCheckResult,
    AcceptanceSignal,
    build_s2_acceptance_report,
    classify_acceptance_check,
)


def test_targeted_s2_runtime_failure_is_release_blocking():
    classified = classify_acceptance_check(
        AcceptanceCheckResult(
            name="s2_reference_task_fake_e2e",
            command=".venv/bin/python -m pytest tests/test_s2_reference_task.py",
            exit_code=1,
            failed_tests=("tests/test_s2_reference_task.py::test_fake_e2e",),
        )
    )

    assert classified.signal is AcceptanceSignal.RUNTIME_REGRESSION
    assert classified.release_blocking is True


def test_td006_full_pytest_guard_failures_are_doc_governance_debt():
    classified = classify_acceptance_check(
        AcceptanceCheckResult(
            name="full_pytest",
            command=".venv/bin/python -m pytest -q -rx",
            exit_code=1,
            failed_tests=(
                "tests/test_docs_source_of_truth.py::test_project_status_exists",
                "tests/test_architecture_boundaries.py::test_w3_scheduler_label_precision_avoids_unreachable_overclaim",
                "tests/test_provider_diagnostics.py::test_provider_diagnostics_flag",
            ),
        )
    )

    assert classified.signal is AcceptanceSignal.DOC_GOVERNANCE_DEBT
    assert classified.release_blocking is False
    assert "TD-006" in classified.reason


def test_ruff_failure_is_quality_debt_not_product_gate():
    classified = classify_acceptance_check(
        AcceptanceCheckResult(
            name="ruff",
            command=".venv/bin/ruff check .",
            exit_code=1,
        )
    )

    assert classified.signal is AcceptanceSignal.QUALITY_DEBT
    assert classified.release_blocking is False
    assert "TD-007" in classified.reason


def test_unknown_failure_blocks_until_classified():
    classified = classify_acceptance_check(
        AcceptanceCheckResult(
            name="full_pytest",
            command=".venv/bin/python -m pytest -q -rx",
            exit_code=1,
            failed_tests=("tests/test_unexpected.py::test_new_failure",),
        )
    )

    assert classified.signal is AcceptanceSignal.UNKNOWN_FAILURE
    assert classified.release_blocking is True


def test_report_separates_release_blockers_from_debt_signals():
    report = build_s2_acceptance_report((
        AcceptanceCheckResult(
            name="s2_reference_task_fake_e2e",
            command=".venv/bin/python -m pytest tests/test_s2_reference_task.py",
            exit_code=0,
        ),
        AcceptanceCheckResult(
            name="full_pytest",
            command=".venv/bin/python -m pytest -q -rx",
            exit_code=1,
            failed_tests=(
                "tests/test_docs_source_of_truth.py::test_project_status_exists",
            ),
        ),
        AcceptanceCheckResult(
            name="ruff",
            command=".venv/bin/ruff check .",
            exit_code=1,
        ),
    ))

    assert report.release_blocked is False
    assert report.runtime_regressions == ()
    assert [check.signal for check in report.debt_signals] == [
        AcceptanceSignal.DOC_GOVERNANCE_DEBT,
        AcceptanceSignal.QUALITY_DEBT,
    ]
