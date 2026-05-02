"""Stage 3 Slice 7: deterministic Memory UX dogfooding flows.

这些测试只使用 fake / deterministic scenarios，把 Stage 3 的纯 contract 串起来：
policy -> confirmation -> operation/audit -> provider/snapshot。它们不读取真实
sessions/runs/agent_log，不写真实 memory，也不调用 LLM、network 或真实 provider。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.memory import build_memory_section
from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_contracts import (
    MemoryDecision,
    MemoryDecisionType,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)
from agent.memory_operations import (
    MemoryOperationType,
    build_memory_audit_summary,
    build_memory_operation_intent,
)
from agent.memory_policy import DeterministicMemoryPolicy
from agent.memory_provider import (
    FakeMemoryProvider,
    MemoryProviderCandidate,
    MemoryProviderSnapshotItem,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOGFOODING_DOC = PROJECT_ROOT / "docs" / "MEMORY_DOGFOODING.md"


def _operation_for(text: str, choice: MemoryConfirmationChoice, *, free_text: str | None = None):
    decision = DeterministicMemoryPolicy().decide(text)
    request = build_memory_confirmation_request(decision)
    confirmation = resolve_memory_confirmation_choice(
        request,
        choice,
        free_text=free_text,
    )
    intent = build_memory_operation_intent(confirmation)
    audit = build_memory_audit_summary(intent)
    return decision, request, confirmation, intent, audit


def test_retain_accept_dogfooding_flow_is_explainable_and_no_store_write() -> None:
    """retain accept flow 验证用户能看懂建议、确认后也不写 store。"""

    decision, request, _confirmation, intent, audit = _operation_for(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.ACCEPT,
    )

    assert decision.decision_type is MemoryDecisionType.RETAIN
    assert "长期记住" in request.question
    assert intent.operation_type is MemoryOperationType.RETAIN
    assert audit.user_choice == MemoryConfirmationChoice.ACCEPT.value
    assert not any(hasattr(intent, name) for name in {"write", "save", "persist"})


def test_edit_dogfooding_flow_uses_edited_content_without_store_write() -> None:
    """edit flow 验证用户可修改要记住/更新的内容，但仍是 intent。"""

    _decision, _request, _confirmation, intent, audit = _operation_for(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.EDIT_AND_ACCEPT,
        free_text="I prefer concise but complete answers.",
    )

    assert intent.content_summary == "I prefer concise but complete answers."
    assert audit.user_choice == MemoryConfirmationChoice.EDIT_AND_ACCEPT.value
    assert intent.operation_type is MemoryOperationType.RETAIN


def test_reject_and_use_once_dogfooding_flows_do_not_create_retain() -> None:
    """reject/use_once 是用户控制权边界，不能被升级成长久 retain。"""

    *_reject_prefix, reject_intent, _reject_audit = _operation_for(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.REJECT,
    )
    *_once_prefix, once_intent, _once_audit = _operation_for(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.SESSION_ONLY,
    )

    assert reject_intent.operation_type is MemoryOperationType.REJECT
    assert once_intent.operation_type is MemoryOperationType.USE_ONCE
    assert once_intent.operation_type is not MemoryOperationType.RETAIN


def test_forget_and_update_dogfooding_flows_are_intents_not_mutations() -> None:
    """forget/update dogfooding 只验证 UX 和 intent，不真实删除或更新。"""

    *_forget_prefix, forget_intent, _forget_audit = _operation_for(
        "forget that I prefer concise answers",
        MemoryConfirmationChoice.ACCEPT,
    )
    *_update_prefix, update_intent, _update_audit = _operation_for(
        "update memory: prefer detailed answers",
        MemoryConfirmationChoice.ACCEPT,
    )

    assert forget_intent.operation_type is MemoryOperationType.FORGET
    assert update_intent.operation_type is MemoryOperationType.UPDATE
    assert not any(hasattr(forget_intent, name) for name in {"delete", "remove"})
    assert not any(hasattr(update_intent, name) for name in {"update", "write"})


def test_sensitive_dogfooding_flow_rejects_or_redacts_without_confirmation_bypass() -> None:
    """敏感 dogfooding 场景不能静默记住，也不能泄漏到 audit summary。"""

    policy = DeterministicMemoryPolicy()
    rejected = policy.decide("remember that my api key is sk-secret")

    assert rejected.decision_type is MemoryDecisionType.REJECT
    assert rejected.safety_flags == ("sensitive",)
    with pytest.raises(ValueError, match="retain/update/forget"):
        build_memory_confirmation_request(rejected)

    candidate = rejected.target_candidate
    assert candidate is not None
    redacted_decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="dogfooding sensitive redaction",
        safety_flags=("sensitive",),
        provenance="candidate:sensitive-dogfood",
    )
    request = build_memory_confirmation_request(redacted_decision)
    confirmation = resolve_memory_confirmation_choice(
        request,
        MemoryConfirmationChoice.ACCEPT,
    )
    audit = build_memory_audit_summary(build_memory_operation_intent(confirmation))

    assert "sk-secret" not in request.preview
    assert "sk-secret" not in audit.user_visible_summary
    assert audit.sensitive_redacted is True


def test_fake_provider_dogfooding_flow_cannot_bypass_policy_or_confirmation() -> None:
    """fake provider 只能提供输入，不能直接产生 approved memory。"""

    provider = FakeMemoryProvider(
        provider_name="dogfood_fake",
        candidates=(
            MemoryProviderCandidate(
                content="项目偏好：回答先给结论",
                scope=MemoryScope.PROJECT,
                sensitivity=MemorySensitivity.LOW,
                provenance="dogfood:provider:1",
                reason="deterministic dogfooding fixture",
            ),
        ),
    )

    candidate = provider.to_memory_candidates()[0]
    decision = DeterministicMemoryPolicy().decide(
        candidate.content,
        source=MemorySource.EXTERNAL_PROVIDER,
        source_event=candidate.source_event,
        scope=candidate.scope,
    )

    assert candidate.source is MemorySource.EXTERNAL_PROVIDER
    assert decision.decision_type is MemoryDecisionType.NO_OP
    assert not hasattr(candidate, "requires_user_confirmation")


def test_snapshot_dogfooding_flow_keeps_provenance_budget_and_safety() -> None:
    """snapshot dogfooding 验证 provider snapshot 仍走安全 prompt view。"""

    provider = FakeMemoryProvider(
        provider_name="dogfood_snapshot",
        snapshot_items=(
            MemoryProviderSnapshotItem(
                content="用户偏好简洁回答",
                scope=MemoryScope.USER,
                sensitivity=MemorySensitivity.LOW,
                provenance="dogfood:snapshot:1",
                selection_reason="deterministic snapshot fixture",
            ),
        ),
    )

    snapshot = provider.get_snapshot(selection_reason="dogfooding prompt view")
    prompt_section = build_memory_section(snapshot)

    assert "用户偏好简洁回答" in prompt_section
    assert "provider:dogfood_snapshot:dogfood:snapshot:1" in prompt_section
    assert "Safety filter: provider:dogfood_snapshot:fake-only" in prompt_section


def test_memory_dogfooding_checklist_exists_and_uses_fake_scenarios() -> None:
    """docs checklist 必须可人工 review，且不能要求真实私人资料。"""

    content = DOGFOODING_DOC.read_text(encoding="utf-8")

    required_markers = (
        "Deterministic Memory UX Dogfooding",
        "fake scenarios only",
        "retain / edit / reject / use_once",
        "forget / update",
        "sensitive redaction",
        "fake provider",
        "snapshot rendering",
        "no real sessions/runs/agent_log",
    )
    for marker in required_markers:
        assert marker in content
