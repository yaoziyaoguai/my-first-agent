"""S4-G08 acceptance gate evidence-fidelity-regression 分类测试（AC-7）。

验证 gate 能区分 S4 evidence-fidelity 回归与既有类（runtime/extension/doc/quality/unknown），
不弱化既有分类。复用 S3-G08 EXTENSION_REGRESSION 模式。
"""
from __future__ import annotations

from agent.acceptance_gate import (
    AcceptanceCheckResult,
    AcceptanceSignal,
    build_s2_acceptance_report,
    classify_acceptance_check,
)


def _check(name: str, command: str, exit_code: int = 1) -> AcceptanceCheckResult:
    return AcceptanceCheckResult(name=name, command=command, exit_code=exit_code)


# ═══════════════════════════════════════════════════════
# A. S4 evidence-fidelity 失败 → EVIDENCE_FIDELITY_REGRESSION（release-blocking）
# ═══════════════════════════════════════════════════════


def test_s4_replay_chain_failure_classified_as_evidence_fidelity():
    classified = classify_acceptance_check(
        _check("s4_replay_chain", ".venv/bin/python -m pytest tests/test_s4_replay_chain.py")
    )
    assert classified.signal is AcceptanceSignal.EVIDENCE_FIDELITY_REGRESSION
    assert classified.release_blocking is True


def test_s4_evidence_verifier_failure_classified_as_evidence_fidelity():
    classified = classify_acceptance_check(
        _check(
            "s4_evidence_verifier",
            ".venv/bin/python -m pytest tests/test_s4_evidence_verifier.py",
        )
    )
    assert classified.signal is AcceptanceSignal.EVIDENCE_FIDELITY_REGRESSION


def test_s4_reference_task_failure_classified_as_evidence_fidelity():
    """S4 reference task（audit/replay E2E）失败 → evidence-fidelity 回归，非 extension/runtime。"""
    classified = classify_acceptance_check(
        _check(
            "s4_reference_task_audit_replay",
            ".venv/bin/python -m pytest tests/test_s4_reference_task_acceptance.py",
        )
    )
    assert classified.signal is AcceptanceSignal.EVIDENCE_FIDELITY_REGRESSION
    assert classified.signal is not AcceptanceSignal.EXTENSION_REGRESSION
    assert classified.signal is not AcceptanceSignal.RUNTIME_REGRESSION


def test_s4_redaction_failure_classified_as_evidence_fidelity():
    classified = classify_acceptance_check(
        _check(
            "s4_redaction",
            ".venv/bin/python -m pytest tests/test_s4_evidence_redaction.py",
        )
    )
    assert classified.signal is AcceptanceSignal.EVIDENCE_FIDELITY_REGRESSION


# ═══════════════════════════════════════════════════════
# B. 既有分类不弱化
# ═══════════════════════════════════════════════════════


def test_s2_runtime_classification_not_weakened():
    classified = classify_acceptance_check(
        _check(
            "s2_reference_task",
            ".venv/bin/python -m pytest tests/test_s2_reference_task_acceptance.py",
        )
    )
    assert classified.signal is AcceptanceSignal.RUNTIME_REGRESSION
    assert classified.release_blocking is True


def test_s3_extension_classification_not_weakened():
    classified = classify_acceptance_check(
        _check(
            "s3_mcp_governed_tool_source",
            ".venv/bin/python -m pytest tests/test_s3_mcp_governed_tool_source.py",
        )
    )
    assert classified.signal is AcceptanceSignal.EXTENSION_REGRESSION
    assert classified.release_blocking is True


def test_ruff_quality_debt_not_weakened():
    classified = classify_acceptance_check(_check("ruff_check", ".venv/bin/ruff check ."))
    assert classified.signal is AcceptanceSignal.QUALITY_DEBT
    assert classified.release_blocking is False


def test_passed_check_not_blocking():
    classified = classify_acceptance_check(
        _check("s4_replay_chain", "pytest tests/test_s4_replay_chain.py", exit_code=0)
    )
    assert classified.signal is AcceptanceSignal.PASSED
    assert classified.release_blocking is False


# ═══════════════════════════════════════════════════════
# C. 聚合报告：evidence_fidelity_regressions 可见、可 release-block
# ═══════════════════════════════════════════════════════


def test_report_surfaces_evidence_fidelity_regressions():
    report = build_s2_acceptance_report(
        (
            _check("s4_replay_chain", "pytest tests/test_s4_replay_chain.py", exit_code=0),
            _check("s4_verifier", "pytest tests/test_s4_evidence_verifier.py", exit_code=1),
            _check("ruff", "ruff check .", exit_code=1),  # quality debt, non-blocking
        )
    )
    assert report.release_blocked is True  # evidence-fidelity 回归阻塞
    assert len(report.evidence_fidelity_regressions) == 1
    assert report.evidence_fidelity_regressions[0].result.name == "s4_verifier"
    # quality debt 仍可见但不阻塞
    assert len(report.debt_signals) == 1
    assert report.runtime_regressions == ()
    assert report.extension_regressions == ()
