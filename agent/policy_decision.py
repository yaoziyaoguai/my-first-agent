"""PolicyDecision — OD-7 Phase 1 golden model.

PolicyDecision 是横切 policy 决策层的最小模型。
不集成 runtime、不调 provider、不做 IO、不做 side effect。

结构：
- PolicyDecisionType: ALLOW / REQUIRE_APPROVAL / DENY / AUDIT_ONLY
- PolicyActionKind: 13 个 action 分类
- PolicyDecision: 决策结果（type + reason + audit_required + human_required）
- classify_policy_action(): 纯函数，从 action_kind 分类为 PolicyDecision

这是 OD-7 Phase 1 golden model。
不实现 runtime integration。Policy 仍为 L2。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PolicyDecisionType(StrEnum):
    """Policy decision 枚举。

    ALLOW           — 允许执行
    REQUIRE_APPROVAL — 需要人类审批（OD-7 target）
    DENY            — 系统拒绝
    AUDIT_ONLY      — 允许执行，必须 audit，不需要审批
    """

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
    AUDIT_ONLY = "audit_only"


class PolicyActionKind(StrEnum):
    """Policy 分类覆盖的 action 类型。

    不是 runtime action type；这是 policy 层的抽象分类。
    """

    MEMORY_RETAIN = "memory_retain"
    MEMORY_FORGET = "memory_forget"
    MEMORY_UPDATE = "memory_update"
    TOOL_READ = "tool_read"
    TOOL_WRITE = "tool_write"
    EXTERNAL_SERVICE = "external_service"
    PROVIDER_REAL_CALL = "provider_real_call"
    SUBAGENT_DELEGATION = "subagent_delegation"
    SCHEDULER_ASYNC = "scheduler_async"
    CAPABILITY_CONFIG_CHANGE = "capability_config_change"
    CHECKPOINT_RESUME = "checkpoint_resume"
    DOCS_ONLY = "docs_only"
    TEST_ONLY = "test_only"


@dataclass(frozen=True)
class PolicyDecision:
    """Policy decision 结果。

    decision_type 是枚举值。
    reason 描述为什么给出这个 decision。
    audit_required 标记是否需要审计。
    human_required 标记是否需要 human approval。
    """

    decision_type: PolicyDecisionType
    reason: str
    audit_required: bool = field(default=True)
    human_required: bool = field(default=False)


def classify_policy_action(action_kind: str, **_metadata) -> PolicyDecision:
    """从 action_kind 分类为 PolicyDecision。

    这是纯函数：不做 IO、不调 provider、不做 side effect。

    默认分类（与 OD-7 design spike 对齐）：
    - TOOL_READ → ALLOW (no side effect)
    - TOOL_WRITE → REQUIRE_APPROVAL (side effect risk)
    - MEMORY_RETAIN → AUDIT_ONLY (explicit user intent, confirmed)
    - MEMORY_FORGET → REQUIRE_APPROVAL (destructive)
    - MEMORY_UPDATE → REQUIRE_APPROVAL (overwrites existing)
    - EXTERNAL_SERVICE → REQUIRE_APPROVAL (external risk, cost)
    - PROVIDER_REAL_CALL → REQUIRE_APPROVAL (cost, credential)
    - SUBAGENT_DELEGATION → REQUIRE_APPROVAL (child runtime)
    - SCHEDULER_ASYNC → REQUIRE_APPROVAL (delayed execution)
    - CAPABILITY_CONFIG_CHANGE → REQUIRE_APPROVAL (topology change)
    - CHECKPOINT_RESUME → ALLOW (recovery)
    - DOCS_ONLY → ALLOW
    - TEST_ONLY → ALLOW
    - unknown → REQUIRE_APPROVAL (fail-closed safe default)
    """
    kind = PolicyActionKind(action_kind) if action_kind in PolicyActionKind else None

    if kind is None:
        return PolicyDecision(
            decision_type=PolicyDecisionType.REQUIRE_APPROVAL,
            reason=f"unknown action kind: {action_kind}; defaulting to require_approval",
            audit_required=True,
            human_required=True,
        )

    # ── ALLOW ──
    if kind in {
        PolicyActionKind.TOOL_READ,
        PolicyActionKind.CHECKPOINT_RESUME,
        PolicyActionKind.DOCS_ONLY,
        PolicyActionKind.TEST_ONLY,
    }:
        return PolicyDecision(
            decision_type=PolicyDecisionType.ALLOW,
            reason=f"allow: {kind.value} has no side effect risk",
            audit_required=kind in {PolicyActionKind.CHECKPOINT_RESUME},
            human_required=False,
        )

    # ── AUDIT_ONLY ──
    if kind == PolicyActionKind.MEMORY_RETAIN:
        return PolicyDecision(
            decision_type=PolicyDecisionType.AUDIT_ONLY,
            reason="memory retain: explicit user intent, confirmed; audit required",
            audit_required=True,
            human_required=False,
        )

    # ── REQUIRE_APPROVAL (default for all other actions) ──
    return PolicyDecision(
        decision_type=PolicyDecisionType.REQUIRE_APPROVAL,
        reason=f"require_approval: {kind.value} has side effect, cost, or persistence risk",
        audit_required=True,
        human_required=True,
    )
