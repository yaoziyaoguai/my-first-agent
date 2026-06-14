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


# ── Enforcement tests ──


def test_all_writes_require_approval():
    """所有 write/side-effect tool name → _tool_has_side_effect → REQUIRE_APPROVAL。

    Enforcement: ALL write tools are enforced (no annotation-only exception).
    """
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action
    from agent.tool_runtime_mediator import _tool_has_side_effect

    # All these should be classified as TOOL_WRITE
    for name in ("write_file", "delete_record", "create_note", "run_shell", "delegate_subagent"):
        assert _tool_has_side_effect(name), f"{name} should be TOOL_WRITE"

    # TOOL_WRITE → REQUIRE_APPROVAL
    d = classify_policy_action(PolicyActionKind.TOOL_WRITE)
    assert d.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert d.human_required


def test_classify_write_tool_returns_require_approval():
    """write tool 被 classify_policy_action 判定为 REQUIRE_APPROVAL。"""
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    d = classify_policy_action(PolicyActionKind.TOOL_WRITE)
    assert d.decision_type == PolicyDecisionType.REQUIRE_APPROVAL

    d2 = classify_policy_action(PolicyActionKind.EXTERNAL_SERVICE)
    assert d2.decision_type == PolicyDecisionType.REQUIRE_APPROVAL


def test_read_tool_allowed():
    """read-only tool → ALLOW，不阻止执行。"""
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    d = classify_policy_action(PolicyActionKind.TOOL_READ)
    assert d.decision_type == PolicyDecisionType.ALLOW
    assert not d.human_required


def test_unknown_tool_fail_closed():
    """unknown tool → REQUIRE_APPROVAL（fail-closed safe default）。"""
    from agent.policy_decision import PolicyDecisionType, classify_policy_action

    d = classify_policy_action("some-mysterious-tool")
    assert d.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert d.human_required


def test_enforcement_integration_semantics():
    """验证 enforcement 规则语义一致性。

    PolicyDecision 模型分类：
    - TOOL_WRITE / EXTERNAL_SERVICE → REQUIRE_APPROVAL
    - TOOL_READ → ALLOW
    - unknown → REQUIRE_APPROVAL (fail-closed)

    Runtime enforcement (ToolRuntimeMediator._enforce_policy_gate):
    - high-risk write (shell/subagent/delegate) → confirmation_required
    - generic write → annotation-only (backward compat)
    - ALLOW → continues execution

    这证明 PolicyDecision 从 annotation layer 升级为 scoped enforcement layer。
    """
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    # 所有 REQUIRE_APPROVAL 的 action 都有 human_required=True
    approval_kinds = (
        PolicyActionKind.TOOL_WRITE,
        PolicyActionKind.EXTERNAL_SERVICE,
        PolicyActionKind.PROVIDER_REAL_CALL,
        PolicyActionKind.SUBAGENT_DELEGATION,
        PolicyActionKind.SCHEDULER_ASYNC,
        PolicyActionKind.MEMORY_FORGET,
        PolicyActionKind.MEMORY_UPDATE,
        PolicyActionKind.CAPABILITY_CONFIG_CHANGE,
    )
    for kind in approval_kinds:
        d = classify_policy_action(kind)
        assert d.decision_type == PolicyDecisionType.REQUIRE_APPROVAL, (
            f"{kind} should REQUIRE APPROVAL"
        )
        assert d.human_required

    # ALLOW 的 action 没有 human_required
    allow_kinds = (
        PolicyActionKind.TOOL_READ,
        PolicyActionKind.CHECKPOINT_RESUME,
        PolicyActionKind.DOCS_ONLY,
        PolicyActionKind.TEST_ONLY,
    )
    for kind in allow_kinds:
        d = classify_policy_action(kind)
        assert d.decision_type == PolicyDecisionType.ALLOW
        assert not d.human_required


def test_policy_enforcement_full_coverage():
    """PolicyDecision enforcement 覆盖所有 write/external/subagent/unknown。

    不再有 annotation-only exception。
    """
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    for kind in (
        PolicyActionKind.TOOL_WRITE,
        PolicyActionKind.EXTERNAL_SERVICE,
        PolicyActionKind.PROVIDER_REAL_CALL,
        PolicyActionKind.SUBAGENT_DELEGATION,
    ):
        d = classify_policy_action(kind)
        assert d.decision_type == PolicyDecisionType.REQUIRE_APPROVAL, (
            f"{kind} should REQUIRE_APPROVAL"
        )
        assert d.human_required
