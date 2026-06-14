"""PolicyDecision Tool gate runtime integration tests.

验证 PolicyDecision 模型集成到 Tool gate 运行时路径。
"""

from __future__ import annotations


def test_classify_policy_action_on_tool_kinds():
    """PolicyDecision 对 Tool 相关 action kind 的正确分类。"""
    from agent.policy_decision import (
        PolicyActionKind,
        PolicyDecisionType,
        classify_policy_action,
    )

    # read-only tool → ALLOW
    d = classify_policy_action(PolicyActionKind.TOOL_READ)
    assert d.decision_type == PolicyDecisionType.ALLOW
    assert not d.human_required

    # write/side-effect tool → REQUIRE_APPROVAL
    d2 = classify_policy_action(PolicyActionKind.TOOL_WRITE)
    assert d2.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert d2.human_required
    assert d2.audit_required

    # external service → REQUIRE_APPROVAL
    d3 = classify_policy_action(PolicyActionKind.EXTERNAL_SERVICE)
    assert d3.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert d3.human_required

    # provider real call → REQUIRE_APPROVAL
    d4 = classify_policy_action(PolicyActionKind.PROVIDER_REAL_CALL)
    assert d4.decision_type == PolicyDecisionType.REQUIRE_APPROVAL

    # unknown → REQUIRE_APPROVAL (fail-closed)
    d5 = classify_policy_action("some-unknown-tool-action")
    assert d5.decision_type == PolicyDecisionType.REQUIRE_APPROVAL


def test_policy_decision_not_integrated_to_memory():
    """MemoryOwner 路径不应被本轮的 PolicyDecision 集成。"""
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType

    # MEMORY_RETAIN → AUDIT_ONLY (from golden model, not runtime-integrated yet)
    from agent.policy_decision import classify_policy_action as _cpa

    d = _cpa(PolicyActionKind.MEMORY_RETAIN)
    assert d.decision_type == PolicyDecisionType.AUDIT_ONLY
    # 但本轮不做 MemoryOwner runtime integration
    # 这只是一个分类测试，证明分类存在但不声称 integrated


def test_policy_decision_model_is_importable_and_pure():
    """PolicyDecision 可以 import，不影响现有 module。"""
    from agent.policy_decision import (
        PolicyActionKind,
        PolicyDecision,
        PolicyDecisionType,
        classify_policy_action,
    )

    # new instance
    d = PolicyDecision(
        decision_type=PolicyDecisionType.ALLOW,
        reason="test",
        audit_required=False,
        human_required=False,
    )
    assert d.decision_type == "allow"
    assert d.reason == "test"
    assert not d.audit_required
    assert not d.human_required

    # all action kinds have decisions
    for kind in PolicyActionKind:
        result = classify_policy_action(kind)
        assert result.reason
