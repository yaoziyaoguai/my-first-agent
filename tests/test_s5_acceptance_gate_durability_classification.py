"""S5-G08 durability 回归验收信号测试。

锁定 AC-9：durability/recovery 失败必须有稳定验收分类，且不得弱化既有
runtime / extension / evidence-fidelity / debt 分类。本测试镜像 S4 的
``test_s4_acceptance_gate_evidence_classification.py``，新增 ``DURABILITY_REGRESSION``。

这些测试在 ``DURABILITY_REGRESSION`` 加入 ``acceptance_gate.py`` 前必须失败（RED）。
"""

from __future__ import annotations

from agent.acceptance_gate import (
    AcceptanceCheckResult,
    AcceptanceSignal,
    build_s2_acceptance_report,
    classify_acceptance_check,
)


def _check(name: str, command: str) -> AcceptanceSignal:
    return classify_acceptance_check(
        AcceptanceCheckResult(name=name, command=command, exit_code=1)
    ).signal


def test_durability_failure_classified_as_durability_regression():
    signal = _check(
        "s5_durability_ledger_recovery",
        ".venv/bin/python -m pytest tests/test_s5_ledger_cooperation.py",
    )
    assert signal is AcceptanceSignal.DURABILITY_REGRESSION


def test_passed_durability_check_still_passed():
    result = classify_acceptance_check(
        AcceptanceCheckResult(
            name="s5_durability_ledger_recovery",
            command=".venv/bin/python -m pytest tests/test_s5_ledger_store.py",
            exit_code=0,
        )
    )
    assert result.signal is AcceptanceSignal.PASSED
    assert result.release_blocking is False


def test_durability_regression_is_release_blocking():
    result = classify_acceptance_check(
        AcceptanceCheckResult(
            name="s5_recovery_e2e",
            command=".venv/bin/python -m pytest tests/test_s5_reference_task_acceptance.py",
            exit_code=1,
        )
    )
    assert result.signal is AcceptanceSignal.DURABILITY_REGRESSION
    assert result.release_blocking is True


def test_non_durability_s5_failure_not_misclassified_as_durability():
    # 含 s5 但无 durability 标记 —— 不应判为 durability（落回既有分类链）。
    signal = _check("s5_misc_unrelated", "pytest tests/test_s5_misc_unrelated.py")
    assert signal is not AcceptanceSignal.DURABILITY_REGRESSION


def test_durability_classification_does_not_weaken_existing_classes():
    # s4 / s3 / s2 失败仍各自归到既有 signal。
    assert _check(
        "s4_replay_chain", ".venv/bin/python -m pytest tests/test_s4_replay_chain.py"
    ) is AcceptanceSignal.EVIDENCE_FIDELITY_REGRESSION
    assert _check(
        "s3_extension_mcp_reference_task",
        ".venv/bin/python -m pytest tests/test_mcp_registration_policy.py",
    ) is AcceptanceSignal.EXTENSION_REGRESSION
    assert _check(
        "s2_runtime_golden_e2e", ".venv/bin/python -m pytest golden_e2e"
    ) is AcceptanceSignal.RUNTIME_REGRESSION


def test_report_exposes_durability_regressions():
    report = build_s2_acceptance_report(
        (
            AcceptanceCheckResult(
                name="s5_durability_ledger_recovery",
                command=".venv/bin/python -m pytest tests/test_s5_ledger_cooperation.py",
                exit_code=1,
            ),
            AcceptanceCheckResult(
                name="s4_replay_chain",
                command=".venv/bin/python -m pytest tests/test_s4_replay_chain.py",
                exit_code=0,
            ),
        )
    )
    assert report.release_blocked is True
    assert len(report.durability_regressions) == 1
    assert report.durability_regressions[0].signal is AcceptanceSignal.DURABILITY_REGRESSION
