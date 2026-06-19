"""S3-G08: acceptance gate extension-regression 分类（AC-7）。

让 acceptance gate 把 **extension regression**（MCP/SubAgent 接入引入的失败）与
runtime regression / known debt(TD-006/007) / unknown failure 区分，extension 失败不被
混入或掩盖。纯新增分类口径，不弱化既有四类（PASSED/QUALITY_DEBT/DOC_GOVERNANCE_DEBT/
RUNTIME_REGRESSION/UNKNOWN_FAILURE）。
"""
from __future__ import annotations

from agent.acceptance_gate import (
    AcceptanceCheckResult,
    AcceptanceSignal,
    build_s2_acceptance_report,
    classify_acceptance_check,
)


def _failed(
    name: str, command: str, *, failed_tests: tuple[str, ...] = ("x",)
) -> AcceptanceCheckResult:
    return AcceptanceCheckResult(name=name, command=command, exit_code=1, failed_tests=failed_tests)


def test_extension_failures_classified_as_extension_regression():
    """S3 extension（MCP/SubAgent/extension/reference_task）失败 → EXTENSION_REGRESSION。"""
    cases = [
        ("s3_reference_task_fake_e2e", "pytest tests/test_s3_reference_task_acceptance.py"),
        ("s3_mcp_governed_tool_source", "pytest tests/test_s3_mcp_governed_tool_source.py"),
        (
            "s3_subagent_parent_mediated",
            "pytest tests/test_s3_subagent_parent_mediated_acceptance.py",
        ),
        ("s3_extension_evidence", "pytest tests/test_s3_extension_evidence_checkpoint.py"),
    ]
    for name, command in cases:
        classified = classify_acceptance_check(_failed(name, command))
        assert classified.signal is AcceptanceSignal.EXTENSION_REGRESSION, (
            f"{name} 应分类为 EXTENSION_REGRESSION，实际 {classified.signal}"
        )
        assert classified.release_blocking is True  # extension 回归是 S3 release blocker


def test_extension_regression_is_release_blocking_and_distinct_from_debt():
    """extension 回归 release-blocking，且与 TD-006/007 debt 区分（不掩盖）。"""
    report = build_s2_acceptance_report(
        (
            _failed("s3_mcp", "pytest tests/test_s3_mcp_governed_tool_source.py"),
            AcceptanceCheckResult(name="ruff", command="ruff check .", exit_code=1),
            _failed(
                "docs_guard",
                "pytest tests/test_docs_source_of_truth.py::test_x",
                failed_tests=("tests/test_docs_source_of_truth.py::test_x",),
            ),
        )
    )
    # extension 回归单独可见
    assert len(report.extension_regressions) == 1
    # release blocked（extension 回归是 blocker）
    assert report.release_blocked is True
    # TD-006/007 仍是 debt 信号（不被弱化、不被 extension 掩盖）
    assert len(report.debt_signals) == 2


def test_existing_classifications_not_weakened():
    """既有四类分类不被新增 extension_regression 弱化。"""
    # PASSED
    assert classify_acceptance_check(
        AcceptanceCheckResult("s3_ref", "pytest tests/test_s3_reference_task_acceptance.py", 0)
    ).signal is AcceptanceSignal.PASSED
    # ruff -> QUALITY_DEBT (TD-007)
    assert classify_acceptance_check(
        AcceptanceCheckResult("ruff", "ruff check .", 1)
    ).signal is AcceptanceSignal.QUALITY_DEBT
    # doc-governance -> DOC_GOVERNANCE_DEBT (TD-006)
    assert classify_acceptance_check(
        _failed(
            "docs_guard",
            "pytest tests/test_docs_source_of_truth.py::test_x",
            failed_tests=("tests/test_docs_source_of_truth.py::test_x",),
        )
    ).signal is AcceptanceSignal.DOC_GOVERNANCE_DEBT
    # S2 runtime -> RUNTIME_REGRESSION
    assert classify_acceptance_check(
        _failed(
            "s2_reference",
            "pytest tests/test_s2_reference_task_acceptance.py",
            failed_tests=("tests/test_s2_reference_task_acceptance.py::test_x",),
        )
    ).signal is AcceptanceSignal.RUNTIME_REGRESSION
    # unknown -> UNKNOWN_FAILURE
    assert classify_acceptance_check(
        _failed("random_other", "pytest tests/test_unrelated.py")
    ).signal is AcceptanceSignal.UNKNOWN_FAILURE
