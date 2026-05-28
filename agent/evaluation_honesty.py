"""Loop 4.1 — Evaluation / Dogfood Harness Evidence Honesty.

红队补审（2026-05-28）指出：Dogfood / Evaluation Harness 14/14 项从 COMPLETE 降级。
根因是把 fake/direct-call/expected_events/no-crash/smoke 当成了 capability completion。

本模块定义 Evaluation Report 的证据分类 schema 和验证规则：

- SMOKE_PASS：流程没崩、事件出现、no-crash —— 不证明业务能力完成
- CAPABILITY_PASS：具体能力结果真的达成 —— 必须有 concrete business outcome assertion
- REAL_VALIDATION_PENDING：代码路径完成但真实 API / real dogfood 未验证
- CAPABILITY_FAIL：能力目标未达成

规则（不可变式）：
1. expected_events 为空 → 不能 CAPABILITY_PASS
2. no-crash / exit 0 → 只能 SMOKE_PASS（除非满足 CAPABILITY_PASS 条件）
3. fake/local provider → 只能 SMOKE_PASS / REAL_VALIDATION_PENDING
4. CAPABILITY_PASS → 必须有 concrete business outcome assertion
5. capability assertion 失败 → CAPABILITY_FAIL
6. fake/local harness 不能关闭 REAL-EVIDENCE debt
7. report 必须能列出 pending real evidence debt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvidenceClassification(Enum):
    """Evaluation result 的证据等级。

    从高到低排列——越高越接近「能力真实验证」。
    """

    CAPABILITY_PASS = "capability_pass"
    """具体业务能力目标真的达成——有 concrete business outcome assertion。"""

    REAL_VALIDATION_PENDING = "real_validation_pending"
    """代码路径完成 + 合约测试通过，但真实 API / real dogfood 未验证。"""

    CAPABILITY_FAIL = "capability_fail"
    """能力目标未达成——capability assertion 失败。"""

    SMOKE_PASS = "smoke_pass"
    """流程没崩、事件出现、no-crash、exit 0 —— 不证明业务能力完成。"""


# ── 降级规则 ──────────────────────────────────────────────────────────────

# 不能支撑 CAPABILITY_PASS 的证据来源
NON_CAPABILITY_PROVIDERS: frozenset[str] = frozenset({"fake", "mock", "stub", "demo"})

# 不能支撑 CAPABILITY_PASS 的断言类型
NON_CAPABILITY_ASSERTIONS: frozenset[str] = frozenset({
    "no-crash",
    "exit_zero",
    "expected_events_seen",
    "expected_fragments_seen",
    "traceback_not_detected",
    "business_action_detected",
})

# 能支撑 CAPABILITY_PASS 的断言类型
CAPABILITY_ASSERTIONS: frozenset[str] = frozenset({
    "real_provider",
    "real_api_roundtrip",
    "real_core_loop_e2e",
    "concrete_business_outcome",
    "capability_result_verified",
    "user_visible_business_effect",
})


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    """单条 evaluation result 的证据描述。"""

    assertion_type: str
    """断言类型（如 "no-crash"、"concrete_business_outcome"）。"""

    satisfied: bool
    """断言是否被满足。"""

    detail: str = ""
    """可选详细描述。"""


@dataclass
class EvaluationReport:
    """Harness / dogfood evaluation 的结构化报告。

    必须显式区分证据等级——不允许把 smoke 当 capability。
    """

    report_id: str
    """报告唯一标识。"""

    evidence_classification: EvidenceClassification
    """本次 evaluation 的证据等级。"""

    assertion_results: list[EvaluationEvidence] = field(default_factory=list)
    """所有断言结果列表。"""

    pending_debt: list[str] = field(default_factory=list)
    """本次 evaluation 未关闭的 REAL-EVIDENCE debt（如 REAL-EVIDENCE-001）。"""

    provider_type: str = "unknown"
    """本次 evaluation 使用的 provider 类型（fake / real / kimi-k2.5 等）。"""

    notes: list[str] = field(default_factory=list)
    """附加说明。"""

    def is_capability_verified(self) -> bool:
        """本次 evaluation 是否证明了 capability completion。

        只有 CAPABILITY_PASS 才返回 True——SMOKE_PASS / REAL_VALIDATION_PENDING 都不行。
        """
        return self.evidence_classification == EvidenceClassification.CAPABILITY_PASS

    def can_close_real_evidence_debt(self) -> bool:
        """本次 evaluation 能否关闭 REAL-EVIDENCE debt。

        只有 CAPABILITY_PASS + real provider 才能关闭。
        """
        return (
            self.evidence_classification == EvidenceClassification.CAPABILITY_PASS
            and self.provider_type not in NON_CAPABILITY_PROVIDERS
        )

    def has_pending_real_validation(self) -> bool:
        """是否有待真实 API 验证的债务。"""
        return bool(self.pending_debt)


# ── 分类规则引擎 ──────────────────────────────────────────────────────────


def classify_evaluation(
    *,
    provider_type: str,
    assertion_results: list[EvaluationEvidence],
    pending_debt: list[str] | None = None,
) -> EvidenceClassification:
    """根据 provider type 和 assertion results 判定 evidence classification。

    规则（按优先级）：
    1. 任何 capability assertion 失败 → CAPABILITY_FAIL
    2. fake/local provider → 不能 CAPABILITY_PASS（只能 SMOKE_PASS 或 REAL_VALIDATION_PENDING）
    3. 无 concrete capability assertion → 不能 CAPABILITY_PASS
    4. 有 concrete capability assertion 全部满足 + real provider → CAPABILITY_PASS
    5. 有 concrete capability assertion 全部满足 + fake provider → REAL_VALIDATION_PENDING
    6. 无 crash + 无 capability assertion → SMOKE_PASS
    """
    pending = list(pending_debt) if pending_debt else []
    is_fake = provider_type in NON_CAPABILITY_PROVIDERS

    # 查找 concrete capability assertions
    cap_assertions = [
        a for a in assertion_results
        if a.assertion_type in CAPABILITY_ASSERTIONS
    ]
    has_cap_assertions = bool(cap_assertions)

    # 规则 1：capability assertion 失败 → CAPABILITY_FAIL
    for a in cap_assertions:
        if not a.satisfied:
            return EvidenceClassification.CAPABILITY_FAIL

    # 规则 2-4：capability assertion 存在 + 全部满足
    if has_cap_assertions and all(a.satisfied for a in cap_assertions):
        if is_fake:
            # fake provider 下 capability assertion 通过 → 只能证明 code path
            return EvidenceClassification.REAL_VALIDATION_PENDING
        return EvidenceClassification.CAPABILITY_PASS

    # 规则 5：无 concrete capability assertion
    if is_fake and pending:
        return EvidenceClassification.REAL_VALIDATION_PENDING

    # 规则 6：no-crash / smoke only
    return EvidenceClassification.SMOKE_PASS


def can_no_crash_be_capability() -> bool:
    """no-crash 是否足以支撑 capability completion。

    严格禁止——no-crash 是最低标准，不是能力证据。
    """
    return False


def can_fake_harness_close_debt() -> bool:
    """fake/local harness 能否关闭 REAL-EVIDENCE debt。

    严格禁止——fake provider 下所有验证都不证明真实外部能力。
    """
    return False


def classify_smoke_vs_capability(
    *,
    has_capability_assertions: bool,
    all_capability_assertions_passed: bool,
    provider_is_fake: bool,
    has_pending_real_debt: bool,
) -> EvidenceClassification:
    """简化的分类器——从布尔标志判定 evidence classification。

    用于不需要完整 EvaluationEvidence 列表的场景（如决策框架、文档生成）。
    """
    if has_capability_assertions and not all_capability_assertions_passed:
        return EvidenceClassification.CAPABILITY_FAIL

    if has_capability_assertions and all_capability_assertions_passed:
        if provider_is_fake:
            return EvidenceClassification.REAL_VALIDATION_PENDING
        return EvidenceClassification.CAPABILITY_PASS

    if has_pending_real_debt and not has_capability_assertions:
        return EvidenceClassification.REAL_VALIDATION_PENDING

    return EvidenceClassification.SMOKE_PASS
