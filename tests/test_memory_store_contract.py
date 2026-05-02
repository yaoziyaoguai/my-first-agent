"""Stage 4: fake/local MemoryStore skeleton contract tests.

这些测试先固定 Store seam 的边界：Store 只能消费已经经过
MemoryPolicy -> Confirmation UX -> OperationIntent -> AuditSummary 的结果，
不能自己做 policy、confirmation、retrieval、prompt 注入、runtime 接入或真实持久化。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    build_memory_confirmation_request,
    resolve_memory_confirmation_choice,
)
from agent.memory_contracts import MemoryScope
from agent.memory_operations import (
    MemoryAuditSummary,
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
    build_memory_operation_intent,
)
from agent.memory_policy import DeterministicMemoryPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORE_MODULE = PROJECT_ROOT / "agent" / "memory_store.py"
PROMPT_BUILDER = PROJECT_ROOT / "agent" / "prompt_builder.py"


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
    """扫描调用名，确认 fake store 没有文件/网络/LLM/MCP 副作用。"""

    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _audited_intent(
    text: str,
    choice: MemoryConfirmationChoice,
    *,
    free_text: str | None = None,
) -> tuple[MemoryOperationIntent, MemoryAuditSummary]:
    """构造已经过 policy/confirmation/operation/audit 的 store 输入。

    Store 测试不直接伪造 MemoryDecision：这样能证明 Stage 4 不绕过 Stage 3 的治理链。
    """

    decision = DeterministicMemoryPolicy().decide(text)
    request = build_memory_confirmation_request(decision)
    confirmation = resolve_memory_confirmation_choice(
        request,
        choice,
        free_text=free_text,
    )
    intent = build_memory_operation_intent(confirmation)
    return intent, build_memory_audit_summary(intent)


def test_retain_operation_intent_creates_fake_memory_record_without_real_io() -> None:
    """retain 只能写入 fake/in-memory store，不能写真实长期记忆。"""

    from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus

    intent, audit = _audited_intent(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.ACCEPT,
    )
    store = InMemoryMemoryStore()

    result = store.apply_operation_intent(intent, audit)

    assert result.status is MemoryStoreApplyStatus.APPLIED
    assert result.record is not None
    assert result.record.content == "I prefer concise answers"
    assert result.record.scope is MemoryScope.USER
    assert result.record.source_summary.startswith("candidate:")
    assert result.record.audit_id == result.audit_id
    assert store.list_records() == (result.record,)


def test_update_operation_updates_only_existing_fake_record() -> None:
    """update 只作用于 fake store 里的既有 record，不触碰真实数据。"""

    from agent.memory_store import (
        InMemoryMemoryStore,
        MemoryRecord,
        MemoryStoreApplyStatus,
        derive_memory_record_id,
    )

    intent, audit = _audited_intent(
        "update memory: prefer detailed answers",
        MemoryConfirmationChoice.EDIT_AND_ACCEPT,
        free_text="I now prefer detailed implementation notes.",
    )
    record_id = derive_memory_record_id(intent.source_summary)
    store = InMemoryMemoryStore(records=(
        MemoryRecord(
            id=record_id,
            content="old fake content",
            scope=MemoryScope.USER,
            source_summary=intent.source_summary,
            safety_summary="fake preload",
            audit_id="audit:preload",
            created_by_operation=MemoryOperationType.RETAIN,
            updated_by_operation=MemoryOperationType.RETAIN,
        ),
    ))

    result = store.apply_operation_intent(intent, audit)

    assert result.status is MemoryStoreApplyStatus.APPLIED
    assert result.record is not None
    assert result.record.id == record_id
    assert result.record.content == "I now prefer detailed implementation notes."
    assert result.record.updated_by_operation is MemoryOperationType.UPDATE
    assert store.get_record(record_id) == result.record


def test_forget_operation_removes_only_fake_record() -> None:
    """forget 是 fake/local 删除语义，不删除任何文件或真实记忆。"""

    from agent.memory_store import (
        InMemoryMemoryStore,
        MemoryRecord,
        MemoryStoreApplyStatus,
        derive_memory_record_id,
    )

    intent, audit = _audited_intent(
        "forget that I prefer concise answers",
        MemoryConfirmationChoice.ACCEPT,
    )
    record_id = derive_memory_record_id(intent.source_summary)
    existing = MemoryRecord(
        id=record_id,
        content="fake content to forget",
        scope=MemoryScope.USER,
        source_summary=intent.source_summary,
        safety_summary="fake preload",
        audit_id="audit:preload",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
    )
    store = InMemoryMemoryStore(records=(existing,))

    result = store.apply_operation_intent(intent, audit)

    assert result.status is MemoryStoreApplyStatus.APPLIED
    assert result.record == existing
    assert store.get_record(record_id) is None
    assert store.list_records() == ()


def test_use_once_and_reject_do_not_write_store() -> None:
    """use_once/reject 是用户控制权边界，不能升级成 store write。"""

    from agent.memory_store import InMemoryMemoryStore, MemoryStoreApplyStatus

    use_once_intent, use_once_audit = _audited_intent(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.SESSION_ONLY,
    )
    reject_intent, reject_audit = _audited_intent(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.REJECT,
    )
    store = InMemoryMemoryStore()

    use_once_result = store.apply_operation_intent(use_once_intent, use_once_audit)
    reject_result = store.apply_operation_intent(reject_intent, reject_audit)

    assert use_once_result.status is MemoryStoreApplyStatus.SKIPPED
    assert reject_result.status is MemoryStoreApplyStatus.SKIPPED
    assert store.list_records() == ()


def test_store_requires_operation_intent_and_matching_audit_summary() -> None:
    """Store apply 必须有 OperationIntent + 匹配 AuditSummary，不能直接吃 decision。"""

    from agent.memory_store import InMemoryMemoryStore

    intent, audit = _audited_intent(
        "remember that I prefer concise answers",
        MemoryConfirmationChoice.ACCEPT,
    )
    bad_audit = MemoryAuditSummary(
        operation_type=audit.operation_type,
        decision_type=audit.decision_type,
        source_summary="candidate:wrong",
        user_choice=audit.user_choice,
        safety_summary=audit.safety_summary,
        sensitive_redacted=audit.sensitive_redacted,
        user_visible_summary=audit.user_visible_summary,
    )
    store = InMemoryMemoryStore()

    with pytest.raises(TypeError, match="MemoryOperationIntent"):
        store.apply_operation_intent(object(), audit)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="MemoryAuditSummary"):
        store.apply_operation_intent(intent, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="audit summary does not match"):
        store.apply_operation_intent(intent, bad_audit)


def test_sensitive_retain_record_stores_redacted_summary_not_secret_text() -> None:
    """敏感内容进入 fake record 前必须保持 redacted summary。"""

    from agent.memory_confirmation import build_memory_confirmation_request
    from agent.memory_contracts import (
        MemoryCandidate,
        MemoryDecision,
        MemoryDecisionType,
        MemorySensitivity,
        MemorySource,
    )
    from agent.memory_store import InMemoryMemoryStore

    candidate = MemoryCandidate(
        id="candidate:sensitive-store",
        content="api token is sk-secret",
        source=MemorySource.USER_INPUT,
        source_event="fake-turn",
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.SECRET,
        stability="user_asserted",
        confidence=0.8,
        reason="fake sensitive store fixture",
    )
    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="sensitive retain must be redacted",
        safety_flags=("sensitive",),
        provenance=candidate.id,
    )
    request = build_memory_confirmation_request(decision)
    confirmation = resolve_memory_confirmation_choice(
        request,
        MemoryConfirmationChoice.ACCEPT,
    )
    intent = build_memory_operation_intent(confirmation)
    audit = build_memory_audit_summary(intent)

    result = InMemoryMemoryStore().apply_operation_intent(intent, audit)

    assert result.record is not None
    assert "sk-secret" not in result.record.content
    assert result.record.content == "[已隐藏敏感内容]"
    assert result.record.sensitive_redacted is True


def test_memory_record_is_not_memory_candidate() -> None:
    """MemoryRecord 是确认+审计+应用后的 fake store 结果，不是候选。"""

    from agent.memory_store import MemoryRecord

    field_names = set(MemoryRecord.__dataclass_fields__)

    assert {"audit_id", "created_by_operation", "updated_by_operation"}.issubset(field_names)
    assert {"confidence", "proposed_type", "source_event"}.isdisjoint(field_names)


def test_store_module_has_no_runtime_prompt_provider_io_network_or_mcp_dependency() -> None:
    """Store skeleton 只能是 fake/local seam，不能偷偷接 runtime 或真实外部系统。"""

    imports = _agent_imports(STORE_MODULE)
    calls = _called_names(STORE_MODULE)

    assert imports <= {"agent.memory_contracts", "agent.memory_operations"}
    assert calls.isdisjoint({
        "open",
        "read_text",
        "write_text",
        "mkdir",
        "unlink",
        "glob",
        "iterdir",
        "connect",
        "request",
        "urlopen",
        "save_checkpoint",
        "load_checkpoint",
    })


def test_prompt_builder_does_not_directly_read_memory_store() -> None:
    """prompt_builder 仍只能消费 MemorySnapshot，不能直接读 store。"""

    imports = _agent_imports(PROMPT_BUILDER)

    assert "agent.memory_store" not in imports


def test_store_protocol_is_minimal_and_not_a_runtime_gateway() -> None:
    """Protocol 只表达 store seam，不承载 runtime/checkpoint/tool 入口。"""

    from agent.memory_store import MemoryStoreProtocol

    protocol_methods = {
        name
        for name, value in inspect.getmembers(MemoryStoreProtocol, inspect.isfunction)
        if not name.startswith("_")
    }

    assert protocol_methods == {
        "apply_operation_intent",
        "get_record",
        "list_records",
    }
