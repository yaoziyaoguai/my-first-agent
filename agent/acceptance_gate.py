"""S2 acceptance gate classification.

This module separates product-release runtime signals from health/debt signals.
It does not make full pytest or ruff green; it prevents those known debt classes
from being confused with S2 runtime regressions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AcceptanceSignal(str, Enum):
    """Classification for one verification result."""

    PASSED = "passed"
    RUNTIME_REGRESSION = "runtime_regression"
    EXTENSION_REGRESSION = "extension_regression"
    DOC_GOVERNANCE_DEBT = "doc_governance_debt"
    QUALITY_DEBT = "quality_debt"
    UNKNOWN_FAILURE = "unknown_failure"


@dataclass(frozen=True, slots=True)
class AcceptanceCheckResult:
    """Raw command/test result supplied to the S2 acceptance classifier."""

    name: str
    command: str
    exit_code: int
    failed_tests: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ClassifiedAcceptanceCheck:
    """One classified S2 acceptance/health check."""

    result: AcceptanceCheckResult
    signal: AcceptanceSignal
    release_blocking: bool
    reason: str


@dataclass(frozen=True, slots=True)
class S2AcceptanceReport:
    """Aggregated S2 acceptance report."""

    checks: tuple[ClassifiedAcceptanceCheck, ...]

    @property
    def release_blocked(self) -> bool:
        return any(check.release_blocking for check in self.checks)

    @property
    def runtime_regressions(self) -> tuple[ClassifiedAcceptanceCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.signal is AcceptanceSignal.RUNTIME_REGRESSION
        )

    @property
    def extension_regressions(self) -> tuple[ClassifiedAcceptanceCheck, ...]:
        """S3-G08: extension（MCP/SubAgent）接入引入的回归，单独可见、不被 debt 掩盖。"""
        return tuple(
            check
            for check in self.checks
            if check.signal is AcceptanceSignal.EXTENSION_REGRESSION
        )

    @property
    def debt_signals(self) -> tuple[ClassifiedAcceptanceCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.signal
            in {AcceptanceSignal.DOC_GOVERNANCE_DEBT, AcceptanceSignal.QUALITY_DEBT}
        )


_DOC_GOVERNANCE_TEST_PREFIXES = (
    "tests/test_docs_source_of_truth.py::",
    "tests/runtime_integration/test_v6_drift_addendum_boundary.py::",
    "tests/test_architecture_boundaries.py::",
    "tests/test_evidence_taxonomy_guard.py::",
    "tests/test_streaming_protocol.py::",
    "tests/test_provider_diagnostics.py::",
    "tests/test_capability_boundary_contract.py::",
)


def classify_acceptance_check(
    result: AcceptanceCheckResult,
) -> ClassifiedAcceptanceCheck:
    """Classify a verification result for the S2 release gate."""

    if result.exit_code == 0:
        return ClassifiedAcceptanceCheck(
            result=result,
            signal=AcceptanceSignal.PASSED,
            release_blocking=False,
            reason="check passed",
        )

    command = result.command.lower()
    name = result.name.lower()
    if "ruff" in command or "ruff" in name:
        return ClassifiedAcceptanceCheck(
            result=result,
            signal=AcceptanceSignal.QUALITY_DEBT,
            release_blocking=False,
            reason="ruff failure is tracked quality debt (TD-007)",
        )

    if result.failed_tests and all(
        _is_doc_governance_guard(test_id) for test_id in result.failed_tests
    ):
        return ClassifiedAcceptanceCheck(
            result=result,
            signal=AcceptanceSignal.DOC_GOVERNANCE_DEBT,
            release_blocking=False,
            reason="all pytest failures are TD-006 doc/governance guard debt",
        )

    if _looks_like_s3_extension_check(name, command):
        return ClassifiedAcceptanceCheck(
            result=result,
            signal=AcceptanceSignal.EXTENSION_REGRESSION,
            release_blocking=True,
            reason="S3 extension (MCP/SubAgent) acceptance failed",
        )

    if _looks_like_targeted_s2_runtime_check(name, command):
        return ClassifiedAcceptanceCheck(
            result=result,
            signal=AcceptanceSignal.RUNTIME_REGRESSION,
            release_blocking=True,
            reason="targeted S2 runtime acceptance failed",
        )

    return ClassifiedAcceptanceCheck(
        result=result,
        signal=AcceptanceSignal.UNKNOWN_FAILURE,
        release_blocking=True,
        reason="failure is not classified as known S2 debt",
    )


def build_s2_acceptance_report(
    results: tuple[AcceptanceCheckResult, ...],
) -> S2AcceptanceReport:
    """Build an aggregated S2 acceptance report."""

    return S2AcceptanceReport(
        checks=tuple(classify_acceptance_check(result) for result in results),
    )


def _is_doc_governance_guard(test_id: str) -> bool:
    return test_id.startswith(_DOC_GOVERNANCE_TEST_PREFIXES)


def _looks_like_targeted_s2_runtime_check(name: str, command: str) -> bool:
    text = f"{name} {command}"
    return "s2" in text or "golden_e2e" in text or "runtime" in text


def _looks_like_s3_extension_check(name: str, command: str) -> bool:
    """S3-G08：判定一个失败是否来自 S3 extension（MCP/SubAgent/extension/reference_task）路径。

    判据：名字或命令同时含 ``s3`` 与 extension 标记（mcp / subagent / extension /
    reference_task）。纯新增口径，不影响既有 S2 runtime / debt 分类（S2 测试名含 ``s2`` 不含
    ``s3``，不会误命中）。
    """
    text = f"{name} {command}".lower()
    if "s3" not in text:
        return False
    return any(
        marker in text
        for marker in ("mcp", "subagent", "extension", "reference_task")
    )
