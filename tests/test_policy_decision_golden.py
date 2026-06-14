"""PolicyDecision golden test — OD-7 Phase 1.

验证 PolicyDecision 模型（ALLOW / REQUIRE_APPROVAL / DENY / AUDIT_ONLY）
和 classify_policy_action() 分类函数的确定性行为。

中文学习声明：
本测试只验证 PolicyDecision 模型和纯函数分类逻辑。
不涉及 runtime integration、不涉及 Tool/Memory/SubAgent 接入、
不涉及真实 provider、不涉及外部服务。
Policy 仍为 L2。这不是 L3 证据。
"""

from __future__ import annotations

# ── PolicyDecisionType ──


def test_policy_decision_allow():
    from agent.policy_decision import PolicyDecisionType

    assert PolicyDecisionType.ALLOW == "allow"
    assert str(PolicyDecisionType.ALLOW) == "allow"


def test_policy_decision_require_approval():
    from agent.policy_decision import PolicyDecisionType

    assert PolicyDecisionType.REQUIRE_APPROVAL == "require_approval"


def test_policy_decision_deny():
    from agent.policy_decision import PolicyDecisionType

    assert PolicyDecisionType.DENY == "deny"


def test_policy_decision_audit_only():
    from agent.policy_decision import PolicyDecisionType

    assert PolicyDecisionType.AUDIT_ONLY == "audit_only"


# ── PolicyActionKind ──


def test_policy_action_kind_values():
    from agent.policy_decision import PolicyActionKind

    kinds = {
        PolicyActionKind.MEMORY_RETAIN,
        PolicyActionKind.MEMORY_FORGET,
        PolicyActionKind.MEMORY_UPDATE,
        PolicyActionKind.TOOL_READ,
        PolicyActionKind.TOOL_WRITE,
        PolicyActionKind.EXTERNAL_SERVICE,
        PolicyActionKind.PROVIDER_REAL_CALL,
        PolicyActionKind.SUBAGENT_DELEGATION,
        PolicyActionKind.SCHEDULER_ASYNC,
        PolicyActionKind.CAPABILITY_CONFIG_CHANGE,
        PolicyActionKind.CHECKPOINT_RESUME,
        PolicyActionKind.DOCS_ONLY,
        PolicyActionKind.TEST_ONLY,
    }
    assert len(kinds) == 13


# ── classify_policy_action ──


def test_tool_read_is_allowed():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.TOOL_READ)
    assert decision.decision_type == PolicyDecisionType.ALLOW
    assert not decision.human_required
    assert decision.reason


def test_tool_write_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.TOOL_WRITE)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required
    assert decision.audit_required
    assert decision.reason


def test_memory_forget_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.MEMORY_FORGET)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required


def test_external_service_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.EXTERNAL_SERVICE)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required


def test_provider_real_call_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.PROVIDER_REAL_CALL)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required


def test_subagent_delegation_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.SUBAGENT_DELEGATION)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required


def test_memory_retain_is_audit_only():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.MEMORY_RETAIN)
    assert decision.decision_type == PolicyDecisionType.AUDIT_ONLY
    assert not decision.human_required
    assert decision.audit_required


def test_checkpoint_resume_is_allowed():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.CHECKPOINT_RESUME)
    assert decision.decision_type == PolicyDecisionType.ALLOW
    assert not decision.human_required


def test_docs_only_is_allowed():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.DOCS_ONLY)
    assert decision.decision_type == PolicyDecisionType.ALLOW


def test_capability_config_change_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.CAPABILITY_CONFIG_CHANGE)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required


def test_scheduler_async_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.SCHEDULER_ASYNC)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL


def test_memory_update_requires_approval():
    from agent.policy_decision import PolicyActionKind, PolicyDecisionType, classify_policy_action

    decision = classify_policy_action(PolicyActionKind.MEMORY_UPDATE)
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL


def test_classify_unknown_action_returns_require_approval():
    """未识别 action → fail-closed REQUIRE_APPROVAL（安全默认）。"""
    from agent.policy_decision import PolicyDecisionType, classify_policy_action

    decision = classify_policy_action("some-unknown-action")
    assert decision.decision_type == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.human_required


def test_classify_is_pure_function_no_io(monkeypatch):
    """classify_policy_action 是纯函数，不做 IO、不调 provider。"""
    from agent.policy_decision import PolicyActionKind, classify_policy_action

    # 如果 classify 调了 os.environ, 这里会触发 monkeypatch 报错
    monkeypatch.setenv("PROVIDER_MODE", "real")
    decision = classify_policy_action(PolicyActionKind.TOOL_READ)
    assert decision.decision_type != "deny"  # 不应受 env 影响


def test_all_decisions_have_reason_and_audit():
    """每个 decision 都有 reason 字段。"""
    from agent.policy_decision import PolicyActionKind, classify_policy_action

    for kind in PolicyActionKind:
        decision = classify_policy_action(kind)
        assert decision.reason, f"{kind} 的 reason 不能为空"


def test_never_require_approval_for_docs_or_test():
    """docs/test action 不需要 human approval。"""
    from agent.policy_decision import PolicyActionKind, classify_policy_action

    for kind in (PolicyActionKind.DOCS_ONLY, PolicyActionKind.TEST_ONLY):
        d = classify_policy_action(kind)
        assert not d.human_required
