"""Loop 4.1 — Evaluation / Dogfood Harness Honesty guard tests.

红队补审（2026-05-28）指出 14/14 Dogfood/Evaluation Harness 项从 COMPLETE 降级——根因是
把 fake/direct-call/expected_events/no-crash/smoke 当成了 capability completion。

这些 guard tests 验证新创建的 `agent/evaluation_honesty.py` 中的证据分类规则，
确保以下 overclaim 模式在系统的任何地方都不再出现：

1. expected_events 为空时不能 CAPABILITY_PASS
2. no-crash 只能 SMOKE_PASS——不能证明业务能力
3. fake/local dogfood 不能关闭 REAL-EVIDENCE debt
4. capability assertion 成功时才 CAPABILITY_PASS
5. capability assertion 失败时必须 CAPABILITY_FAIL
6. report 能列出 pending real evidence debt
7. 不能出现 "expected_events passed = capability complete" 的 overclaim
"""

from __future__ import annotations

from agent.evaluation_honesty import (
    CAPABILITY_ASSERTIONS,
    NON_CAPABILITY_ASSERTIONS,
    NON_CAPABILITY_PROVIDERS,
    EvaluationEvidence,
    EvaluationReport,
    EvidenceClassification,
    can_fake_harness_close_debt,
    can_no_crash_be_capability,
    classify_evaluation,
    classify_smoke_vs_capability,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. expected_events 为空时不能 CAPABILITY_PASS
# ═══════════════════════════════════════════════════════════════════════════════


class TestExpectedEventsEmptyNoCapabilityPass:
    """expected_events 为空的 evaluation 不能标 CAPABILITY_PASS。"""

    def test_empty_assertions_smoke_only(self):
        """空断言列表 → 只能 SMOKE_PASS，不能 CAPABILITY_PASS。"""
        classification = classify_evaluation(
            provider_type="fake",
            assertion_results=[],
        )
        assert classification == EvidenceClassification.SMOKE_PASS, (
            f"空断言应返回 SMOKE_PASS，得到 {classification}"
        )

    def test_no_capability_assertion_no_capability_pass(self):
        """只有 smoke assertion（如 no-crash）→ 不能 CAPABILITY_PASS。"""
        classification = classify_evaluation(
            provider_type="real",
            assertion_results=[
                EvaluationEvidence("no-crash", satisfied=True),
                EvaluationEvidence("exit_zero", satisfied=True),
                EvaluationEvidence("expected_events_seen", satisfied=True),
            ],
        )
        assert classification != EvidenceClassification.CAPABILITY_PASS, (
            f"只有 non-capability assertion 不应返回 CAPABILITY_PASS，"
            f"实际返回 {classification}"
        )
        assert classification == EvidenceClassification.SMOKE_PASS, (
            f"只有 smoke assertion 应返回 SMOKE_PASS，实际返回 {classification}"
        )

    def test_report_without_capability_assertion_is_not_capability_verified(self):
        """EvaluationReport 无 capability assertion → is_capability_verified()=False。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.SMOKE_PASS,
            assertion_results=[
                EvaluationEvidence("no-crash", satisfied=True),
            ],
            provider_type="fake",
        )
        assert not report.is_capability_verified()
        assert not report.can_close_real_evidence_debt()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. no-crash 只能 SMOKE_PASS
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoCrashOnlySmokePass:
    """no-crash 是最低标准——不能当 capability 证据。"""

    def test_no_crash_be_capability_is_always_false(self):
        """can_no_crash_be_capability() 必须永远返回 False。"""
        assert can_no_crash_be_capability() is False, (
            "no-crash 永远不能支撑 capability completion"
        )

    def test_no_crash_assertion_is_non_capability(self):
        """no-crash 在 NON_CAPABILITY_ASSERTIONS 中。"""
        assert "no-crash" in NON_CAPABILITY_ASSERTIONS

    def test_exit_zero_assertion_is_non_capability(self):
        """exit_zero 在 NON_CAPABILITY_ASSERTIONS 中。"""
        assert "exit_zero" in NON_CAPABILITY_ASSERTIONS

    def test_expected_events_seen_is_non_capability(self):
        """expected_events_seen 在 NON_CAPABILITY_ASSERTIONS 中。"""
        assert "expected_events_seen" in NON_CAPABILITY_ASSERTIONS

    def test_report_only_no_crash_cannot_close_debt(self):
        """只有 no-crash 的 report 不能关闭 REAL-EVIDENCE debt。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.SMOKE_PASS,
            assertion_results=[
                EvaluationEvidence("no-crash", satisfied=True),
            ],
            provider_type="real",
        )
        assert not report.can_close_real_evidence_debt()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. fake/local dogfood 不能关闭 REAL-EVIDENCE debt
# ═══════════════════════════════════════════════════════════════════════════════


class TestFakeHarnessCannotCloseRealEvidenceDebt:
    """fake/local harness 的结果不证明真实外部能力。"""

    def test_can_fake_harness_close_debt_is_always_false(self):
        """can_fake_harness_close_debt() 必须永远返回 False。"""
        assert can_fake_harness_close_debt() is False, (
            "fake harness 永远不能关闭 REAL-EVIDENCE debt"
        )

    def test_fake_provider_cannot_be_capability_verified(self):
        """fake provider 下即使有 capability assertion 全部通过，
        也不能 is_capability_verified()，只能标 REAL_VALIDATION_PENDING。"""
        classification = classify_evaluation(
            provider_type="fake",
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=True),
                EvaluationEvidence("user_visible_business_effect", satisfied=True),
            ],
            pending_debt=["REAL-EVIDENCE-001"],
        )
        assert classification == EvidenceClassification.REAL_VALIDATION_PENDING, (
            f"fake provider 下 capability assertion 通过应返回 REAL_VALIDATION_PENDING，"
            f"实际返回 {classification}"
        )

    def test_report_fake_provider_cannot_close_debt(self):
        """fake provider 的 report 不能关闭 REAL-EVIDENCE debt。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.REAL_VALIDATION_PENDING,
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=True),
            ],
            provider_type="fake",
        )
        assert not report.can_close_real_evidence_debt()

    def test_report_fake_provider_is_not_capability_verified(self):
        """fake provider → is_capability_verified() 必须 False。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.REAL_VALIDATION_PENDING,
            provider_type="fake",
        )
        assert not report.is_capability_verified()

    def test_report_list_pending_debt_fake_provider(self):
        """fake provider report 必须能列出 pending REAL-EVIDENCE debt。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.REAL_VALIDATION_PENDING,
            pending_debt=["REAL-EVIDENCE-001", "REAL-EVIDENCE-002"],
            provider_type="fake",
        )
        assert report.has_pending_real_validation()
        assert "REAL-EVIDENCE-001" in report.pending_debt
        assert "REAL-EVIDENCE-002" in report.pending_debt


# ═══════════════════════════════════════════════════════════════════════════════
# 4. capability assertion 成功时才 CAPABILITY_PASS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityPassRequiresCapabilityAssertion:
    """CAPABILITY_PASS 必须有 concrete capability assertion 全部通过。"""

    def test_capability_assertion_with_real_provider(self):
        """real provider + capability assertion 全部通过 → CAPABILITY_PASS。"""
        classification = classify_evaluation(
            provider_type="kimi-k2.5",
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=True),
                EvaluationEvidence("real_core_loop_e2e", satisfied=True),
                EvaluationEvidence("capability_result_verified", satisfied=True),
            ],
        )
        assert classification == EvidenceClassification.CAPABILITY_PASS, (
            f"real provider + 全部 cap assertion 通过应返回 CAPABILITY_PASS，"
            f"实际返回 {classification}"
        )

    def test_report_capability_pass_is_capability_verified(self):
        """CAPABILITY_PASS → is_capability_verified() = True。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.CAPABILITY_PASS,
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=True),
            ],
            provider_type="kimi-k2.5",
        )
        assert report.is_capability_verified()

    def test_capability_pass_real_provider_can_close_debt(self):
        """real provider + CAPABILITY_PASS → can_close_real_evidence_debt() = True。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.CAPABILITY_PASS,
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=True),
            ],
            provider_type="kimi-k2.5",
        )
        assert report.can_close_real_evidence_debt()

    def test_smoke_pass_report_is_not_capability_verified(self):
        """SMOKE_PASS report → is_capability_verified() = False。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.SMOKE_PASS,
            provider_type="real",
        )
        assert not report.is_capability_verified()


# ═══════════════════════════════════════════════════════════════════════════════
# 5. capability assertion 失败时必须 CAPABILITY_FAIL
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityFailOnFailedAssertion:
    """capability assertion 失败 → CAPABILITY_FAIL——不能降级为 CONCERN 或 SMOKE。"""

    def test_failed_capability_assertion_is_capability_fail(self):
        """capability assertion 失败 → CAPABILITY_FAIL。"""
        classification = classify_evaluation(
            provider_type="kimi-k2.5",
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=False),
                EvaluationEvidence("real_core_loop_e2e", satisfied=True),
            ],
        )
        assert classification == EvidenceClassification.CAPABILITY_FAIL, (
            f"capability assertion 失败应返回 CAPABILITY_FAIL，实际返回 {classification}"
        )

    def test_failed_capability_trumps_smoke(self):
        """capability assertion 失败优先级高于 smoke assertion 通过。"""
        classification = classify_evaluation(
            provider_type="kimi-k2.5",
            assertion_results=[
                EvaluationEvidence("no-crash", satisfied=True),
                EvaluationEvidence("exit_zero", satisfied=True),
                EvaluationEvidence("concrete_business_outcome", satisfied=False),
            ],
        )
        assert classification == EvidenceClassification.CAPABILITY_FAIL, (
            "capability assertion 失败时必须 CAPABILITY_FAIL，"
            "即使所有 smoke assertion 都通过"
        )

    def test_capability_fail_report_not_capability_verified(self):
        """CAPABILITY_FAIL report → is_capability_verified() = False。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.CAPABILITY_FAIL,
            assertion_results=[
                EvaluationEvidence("concrete_business_outcome", satisfied=False),
            ],
            provider_type="kimi-k2.5",
            notes=["能力目标未达成: 用户未收到正确响应"],
        )
        assert not report.is_capability_verified()
        assert not report.can_close_real_evidence_debt()

    def test_capability_fail_report_captures_failure_notes(self):
        """CAPABILITY_FAIL report 的 notes 应包含失败信息。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.CAPABILITY_FAIL,
            notes=["capability assertion failed: user_visible_business_effect"],
        )
        assert len(report.notes) > 0
        assert "capability assertion failed" in report.notes[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. report 能列出 pending real evidence debt
# ═══════════════════════════════════════════════════════════════════════════════


class TestReportPendingRealEvidenceDebt:
    """report 必须能列出 pending REAL-EVIDENCE debt。"""

    def test_empty_pending_debt_has_pending_is_false(self):
        """pending_debt 为空 → has_pending_real_validation() = False。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.REAL_VALIDATION_PENDING,
            pending_debt=[],
            provider_type="fake",
        )
        assert not report.has_pending_real_validation()

    def test_pending_debt_has_pending_is_true(self):
        """pending_debt 非空 → has_pending_real_validation() = True。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.REAL_VALIDATION_PENDING,
            pending_debt=["REAL-EVIDENCE-001"],
            provider_type="fake",
        )
        assert report.has_pending_real_validation()

    def test_report_pending_debt_preserved(self):
        """report 的 pending_debt 完整保留。"""
        debts = ["REAL-EVIDENCE-001", "REAL-EVIDENCE-005", "REAL-EVIDENCE-008"]
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.SMOKE_PASS,
            pending_debt=list(debts),
            provider_type="fake",
        )
        assert report.pending_debt == debts

    def test_capability_pass_no_pending_debt(self):
        """CAPABILITY_PASS 且已关闭所有 debt → pending_debt 为空。"""
        report = EvaluationReport(
            report_id="test",
            evidence_classification=EvidenceClassification.CAPABILITY_PASS,
            pending_debt=[],
            provider_type="kimi-k2.5",
        )
        assert not report.has_pending_real_validation()


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 不能再出现 "expected_events passed = capability complete" 的 overclaim
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoExpectedEventsEqualsCapabilityOverclaim:
    """expected_events 通过 ≠ capability complete。"""

    def test_expected_events_seen_is_not_capability_assertion(self):
        """expected_events_seen 在 NON_CAPABILITY_ASSERTIONS 中，不在 CAPABILITY_ASSERTIONS 中。"""
        assert "expected_events_seen" in NON_CAPABILITY_ASSERTIONS
        assert "expected_events_seen" not in CAPABILITY_ASSERTIONS, (
            "expected_events_seen 是 smoke 证据，不能作为 capability assertion"
        )

    def test_expected_fragments_seen_is_not_capability_assertion(self):
        """expected_fragments_seen 在 NON_CAPABILITY_ASSERTIONS 中。"""
        assert "expected_fragments_seen" in NON_CAPABILITY_ASSERTIONS

    def test_business_action_detected_is_not_capability_assertion(self):
        """business_action_detected 在 NON_CAPABILITY_ASSERTIONS 中——
        事件出现只能证明 smoke，不能单独证明 business outcome 正确。"""
        assert "business_action_detected" in NON_CAPABILITY_ASSERTIONS

    def test_event_detection_not_capability_pass_fake(self):
        """fake provider 下 expected_events 全部检测到 → 只能 REAL_VALIDATION_PENDING，
        不能 CAPABILITY_PASS。"""
        classification = classify_evaluation(
            provider_type="fake",
            assertion_results=[
                EvaluationEvidence("no-crash", satisfied=True),
                EvaluationEvidence("expected_events_seen", satisfied=True),
                EvaluationEvidence("business_action_detected", satisfied=True),
            ],
            pending_debt=["REAL-EVIDENCE-001"],
        )
        assert classification != EvidenceClassification.CAPABILITY_PASS, (
            "fake provider + event detection → 不能 CAPABILITY_PASS"
        )

    def test_event_detection_not_capability_pass_real(self):
        """real provider 下只有 event detection → 只能 SMOKE_PASS，
        不能 CAPABILITY_PASS——缺 concrete capability assertion。"""
        classification = classify_evaluation(
            provider_type="kimi-k2.5",
            assertion_results=[
                EvaluationEvidence("no-crash", satisfied=True),
                EvaluationEvidence("expected_events_seen", satisfied=True),
                EvaluationEvidence("business_action_detected", satisfied=True),
            ],
        )
        assert classification == EvidenceClassification.SMOKE_PASS, (
            f"real provider 下只有 event detection → 应 SMOKE_PASS 而非 {classification}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. classify_smoke_vs_capability 快捷分类器契约
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifySmokeVsCapability:
    """classify_smoke_vs_capability() 契约测试。"""

    def test_fake_with_capability_pass_is_real_validation_pending(self):
        result = classify_smoke_vs_capability(
            has_capability_assertions=True,
            all_capability_assertions_passed=True,
            provider_is_fake=True,
            has_pending_real_debt=True,
        )
        assert result == EvidenceClassification.REAL_VALIDATION_PENDING

    def test_real_with_capability_pass_is_capability_pass(self):
        result = classify_smoke_vs_capability(
            has_capability_assertions=True,
            all_capability_assertions_passed=True,
            provider_is_fake=False,
            has_pending_real_debt=False,
        )
        assert result == EvidenceClassification.CAPABILITY_PASS

    def test_capability_fail_trumps_all(self):
        result = classify_smoke_vs_capability(
            has_capability_assertions=True,
            all_capability_assertions_passed=False,
            provider_is_fake=False,
            has_pending_real_debt=False,
        )
        assert result == EvidenceClassification.CAPABILITY_FAIL

    def test_no_capability_with_pending_debt(self):
        result = classify_smoke_vs_capability(
            has_capability_assertions=False,
            all_capability_assertions_passed=False,
            provider_is_fake=False,
            has_pending_real_debt=True,
        )
        assert result == EvidenceClassification.REAL_VALIDATION_PENDING

    def test_no_capability_no_debt_smoke(self):
        result = classify_smoke_vs_capability(
            has_capability_assertions=False,
            all_capability_assertions_passed=False,
            provider_is_fake=True,
            has_pending_real_debt=False,
        )
        assert result == EvidenceClassification.SMOKE_PASS


# ═══════════════════════════════════════════════════════════════════════════════
# 9. NON_CAPABILITY_PROVIDERS 完整性
# ═══════════════════════════════════════════════════════════════════════════════


class TestNonCapabilityProviders:
    """所有不可信 provider 必须在 NON_CAPABILITY_PROVIDERS 中注册。"""

    def test_fake_in_non_capability_providers(self):
        assert "fake" in NON_CAPABILITY_PROVIDERS

    def test_mock_in_non_capability_providers(self):
        assert "mock" in NON_CAPABILITY_PROVIDERS

    def test_demo_in_non_capability_providers(self):
        assert "demo" in NON_CAPABILITY_PROVIDERS

    def test_stub_in_non_capability_providers(self):
        assert "stub" in NON_CAPABILITY_PROVIDERS


# ═══════════════════════════════════════════════════════════════════════════════
# 10. EvidenceClassification enum 完整性
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidenceClassificationEnum:
    """EvidenceClassification enum 包含所有 4 种等级。"""

    def test_all_four_levels_present(self):
        levels = set(e.value for e in EvidenceClassification)
        expected = {"capability_pass", "real_validation_pending", "capability_fail", "smoke_pass"}
        assert levels == expected, f"missing levels: {expected - levels}"

    def test_smoke_pass_not_equal_capability_pass(self):
        assert EvidenceClassification.SMOKE_PASS != EvidenceClassification.CAPABILITY_PASS
