"""Stage 3 Slice 5: memory operation intent / audit summary contract tests.

这些测试保护 forget/update safety 边界：Slice 5 只能把已确认的
MemoryConfirmationResult 转成 operation intent 和安全 audit summary，不能真实
写 store、删除 memory、更新 memory，也不能读取 sessions/runs/agent_log。
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_contracts import (
    MemoryCandidate,
    MemoryDecision,
    MemoryDecisionType,
    MemoryScope,
    MemorySensitivity,
    MemorySource,
)
from agent.memory_policy import DeterministicMemoryPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPERATION_MODULE = PROJECT_ROOT / "agent" / "memory_operations.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _agent_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


def _called_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _retain_confirmation(choice: MemoryConfirmationChoice, *, free_text: str | None = None):
    decision = DeterministicMemoryPolicy().decide("remember that I prefer concise answers")
    request = build_memory_confirmation_request(decision)
    return resolve_memory_confirmation_choice(request, choice, free_text=free_text)


def _update_confirmation(choice: MemoryConfirmationChoice, *, free_text: str | None = None):
    decision = DeterministicMemoryPolicy().decide("update memory: prefer detailed answers")
    request = build_memory_confirmation_request(decision)
    return resolve_memory_confirmation_choice(request, choice, free_text=free_text)


def test_accept_retain_response_creates_retain_operation_intent_not_store_write() -> None:
    """accept retain 只生成 retain intent，不写 MemoryStore。"""

    from agent.memory_operations import (
        MemoryOperationType,
        build_memory_operation_intent,
    )

    result = _retain_confirmation(MemoryConfirmationChoice.ACCEPT)

    intent = build_memory_operation_intent(result)

    assert intent.operation_type is MemoryOperationType.RETAIN
    assert intent.decision_type is MemoryDecisionType.RETAIN
    assert "concise answers" in intent.content_summary
    assert not any(hasattr(intent, name) for name in {"write", "save", "persist"})


def test_edit_response_creates_edited_retain_or_update_intent_without_store_write() -> None:
    """edit choice 可以携带改写内容，但仍然只是 operation intent。"""

    from agent.memory_operations import (
        MemoryOperationType,
        build_memory_operation_intent,
    )

    retain_result = _retain_confirmation(
        MemoryConfirmationChoice.EDIT_AND_ACCEPT,
        free_text="I prefer concise but complete answers.",
    )
    update_result = _update_confirmation(
        MemoryConfirmationChoice.EDIT_AND_ACCEPT,
        free_text="I now prefer detailed implementation notes.",
    )

    retain_intent = build_memory_operation_intent(retain_result)
    update_intent = build_memory_operation_intent(update_result)

    assert retain_intent.operation_type is MemoryOperationType.RETAIN
    assert retain_intent.content_summary == "I prefer concise but complete answers."
    assert update_intent.operation_type is MemoryOperationType.UPDATE
    assert update_intent.content_summary == "I now prefer detailed implementation notes."
    assert not hasattr(update_intent, "record_id")


def test_reject_response_creates_reject_intent_not_write_operation() -> None:
    """reject 不能被转成 durable retain/update。"""

    from agent.memory_operations import (
        MemoryOperationType,
        build_memory_operation_intent,
    )

    result = _retain_confirmation(MemoryConfirmationChoice.REJECT)

    intent = build_memory_operation_intent(result)

    assert intent.operation_type is MemoryOperationType.REJECT
    assert intent.content_summary == "[用户拒绝长期记忆操作]"


def test_use_once_response_creates_use_once_intent_not_retain() -> None:
    """use_once/session-only 不能被升级成长久 retain。"""

    from agent.memory_operations import (
        MemoryOperationType,
        build_memory_operation_intent,
    )

    result = _retain_confirmation(MemoryConfirmationChoice.SESSION_ONLY)

    intent = build_memory_operation_intent(result)

    assert intent.operation_type is MemoryOperationType.USE_ONCE
    assert intent.operation_type is not MemoryOperationType.RETAIN
    assert "不授权长期记忆" in intent.safety_summary


def test_forget_response_creates_forget_intent_without_real_delete() -> None:
    """forget 是一等 operation intent，但不执行真实删除。"""

    from agent.memory_operations import (
        MemoryOperationType,
        build_memory_operation_intent,
    )

    decision = DeterministicMemoryPolicy().decide("forget that I prefer concise answers")
    request = build_memory_confirmation_request(decision)
    result = resolve_memory_confirmation_choice(request, MemoryConfirmationChoice.ACCEPT)

    intent = build_memory_operation_intent(result)

    assert intent.operation_type is MemoryOperationType.FORGET
    assert intent.decision_type is MemoryDecisionType.FORGET
    assert not any(hasattr(intent, name) for name in {"delete", "remove", "persist"})


def test_update_response_creates_update_intent_without_real_update() -> None:
    """update intent 不代表已经更新任何真实 memory。"""

    from agent.memory_operations import (
        MemoryOperationType,
        build_memory_operation_intent,
    )

    result = _update_confirmation(MemoryConfirmationChoice.ACCEPT)

    intent = build_memory_operation_intent(result)

    assert intent.operation_type is MemoryOperationType.UPDATE
    assert intent.decision_type is MemoryDecisionType.UPDATE
    assert not any(hasattr(intent, name) for name in {"update", "write", "save"})


def test_audit_summary_redacts_sensitive_content() -> None:
    """audit summary 不能变成敏感全文日志。"""

    from agent.memory_operations import (
        build_memory_audit_summary,
        build_memory_operation_intent,
    )

    candidate = MemoryCandidate(
        id="candidate:sensitive",
        content="api token is sk-secret",
        source=MemorySource.USER_INPUT,
        source_event="turn:1",
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.SECRET,
        stability="user_asserted",
        confidence=0.8,
        reason="用户显式提出长期记住这段信息",
    )
    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="高敏 retain 必须确认",
        safety_flags=("sensitive",),
        provenance="candidate:sensitive",
    )
    request = build_memory_confirmation_request(decision)
    result = resolve_memory_confirmation_choice(request, MemoryConfirmationChoice.ACCEPT)

    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)

    assert "api token is sk-secret" not in intent.content_summary
    assert "api token is sk-secret" not in audit.user_visible_summary
    assert audit.sensitive_redacted is True
    assert audit.safety_summary == "sensitive"


def test_audit_summary_has_provenance_without_reading_real_history() -> None:
    """audit 有来源摘要，但不读取真实 sessions/runs/logs。"""

    from agent.memory_operations import build_memory_audit_summary, build_memory_operation_intent

    result = _retain_confirmation(MemoryConfirmationChoice.ACCEPT)

    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)

    assert audit.source_summary.startswith("candidate:")
    assert audit.user_choice == MemoryConfirmationChoice.ACCEPT.value
    assert not any(
        token in audit.source_summary
        for token in ("sessions/", "runs/", "agent_log.jsonl")
    )


def test_memory_operations_module_has_no_policy_store_prompt_runtime_or_io_dependency() -> None:
    """operation/audit contract 不能反向调用 policy/store/prompt/runtime。"""

    imports = _agent_imports(OPERATION_MODULE)
    calls = _called_names(OPERATION_MODULE)

    assert imports <= {"agent.memory_confirmation", "agent.memory_contracts"}
    assert calls.isdisjoint({
        "open",
        "read_text",
        "write_text",
        "mkdir",
        "save_checkpoint",
        "load_checkpoint",
        "connect",
        "request",
        "urlopen",
    })
