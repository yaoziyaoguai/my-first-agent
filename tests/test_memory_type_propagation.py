"""Phase 4 G1-G6: memory_type pipeline propagation tests.

验证 memory_type (semantic/episodic/procedural) 和 source_type
从 suggestion candidate metadata → MemoryOperationIntent → MemoryRecord
→ filesystem store → MemorySnapshot 的完整流通链路。

这些测试保护 G1-G6 修复的正确性，不引入 LLM / T2 / extraction 逻辑。
"""

from __future__ import annotations

from agent.memory_confirmation import (
    MemoryConfirmationChoice,
    MemoryConfirmationResult,
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
from agent.memory_operations import (
    build_memory_operation_intent,
)
from agent.memory_snapshot_generator import (
    MemorySnapshotBuildOptions,
    build_memory_snapshot_from_store,
)
from agent.memory_store import (
    InMemoryMemoryStore,
    _record_from_intent,
)

# ── helpers ────────────────────────────────────────────────────────────────


def _candidate_with_metadata(
    memory_type: str, source_type: str = "agent_suggested"
) -> MemoryCandidate:
    """构造携带 metadata 的 candidate，模拟 suggestion engine 的输出。"""
    return MemoryCandidate(
        id=f"candidate:test:{memory_type}",
        content=f"测试 {memory_type} 记忆内容",
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type=memory_type,
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="stable",
        confidence=0.75,
        reason=f"测试 {memory_type} propagation",
        metadata={
            "source_type": source_type,
            "memory_type": memory_type,
        },
    )


def _confirmed_result_for(candidate: MemoryCandidate) -> MemoryConfirmationResult:
    """模拟用户 ACCEPT 确认，产生 MemoryConfirmationResult。"""
    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=candidate,
        action="retain",
        requires_user_confirmation=True,
        reason="测试 propagation",
        safety_flags=(),
        provenance=f"candidate:{candidate.id}",
    )
    request = build_memory_confirmation_request(decision)
    return resolve_memory_confirmation_choice(request, MemoryConfirmationChoice.ACCEPT)


# ── G1+G2: MemoryOperationIntent 携带 memory_type/source_type ──────────────


def test_intent_carries_episodic_memory_type_from_candidate_metadata() -> None:
    """G1+G2: episodic candidate metadata 中的 memory_type 流入 MemoryOperationIntent。"""
    candidate = _candidate_with_metadata("episodic")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    assert intent.memory_type == "episodic"
    assert intent.source_type == "agent_suggested"


def test_intent_carries_procedural_memory_type_from_candidate_metadata() -> None:
    """G1+G2: procedural candidate metadata 中的 memory_type 流入 MemoryOperationIntent。"""
    candidate = _candidate_with_metadata("procedural")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    assert intent.memory_type == "procedural"
    assert intent.source_type == "agent_suggested"


def test_intent_carries_semantic_memory_type_from_candidate_metadata() -> None:
    """G1+G2: semantic candidate metadata 中的 memory_type 流入 MemoryOperationIntent。"""
    candidate = _candidate_with_metadata("semantic")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    assert intent.memory_type == "semantic"
    assert intent.source_type == "agent_suggested"


def test_intent_defaults_when_candidate_has_no_metadata() -> None:
    """G2: explicit_user_request 路径（policy 直接生成的 candidate）无 metadata，
    memory_type 回退到默认 "semantic"。"""
    # 模拟 policy 层构造的 candidate（无 metadata）
    candidate = MemoryCandidate(
        id="candidate:test:explicit",
        content="用户显式要求记住的内容",
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="stable",
        confidence=0.9,
        reason="用户显式要求记住",
    )
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    assert intent.memory_type == "semantic"
    assert intent.source_type == "explicit_user_request"


def test_intent_defaults_when_candidate_is_none() -> None:
    """G2: target_candidate 为 None 时，回退到默认值，不崩溃。"""
    decision = MemoryDecision(
        decision_type=MemoryDecisionType.RETAIN,
        target_candidate=None,
        action="retain",
        requires_user_confirmation=True,
        reason="无候选的 retain",
    )
    request = build_memory_confirmation_request(decision)
    result = resolve_memory_confirmation_choice(request, MemoryConfirmationChoice.ACCEPT)
    intent = build_memory_operation_intent(result)

    assert intent.memory_type == "semantic"
    assert intent.source_type == "explicit_user_request"


# ── G5: InMemoryMemoryStore._record_from_intent ───────────────────────────


def test_record_from_intent_preserves_episodic_memory_type() -> None:
    """G5: _record_from_intent 使用 intent 的 memory_type 而非硬编码 "semantic"。"""
    candidate = _candidate_with_metadata("episodic")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    record = _record_from_intent(intent, "audit:test:episodic")
    assert record.memory_type == "episodic"
    assert record.source_type == "agent_suggested"


def test_record_from_intent_preserves_procedural_memory_type() -> None:
    """G5: _record_from_intent 保留 procedural 类型。"""
    candidate = _candidate_with_metadata("procedural")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    record = _record_from_intent(intent, "audit:test:procedural")
    assert record.memory_type == "procedural"


def test_record_from_intent_defaults_for_explicit_request() -> None:
    """G5: 无 metadata 的 explicit request 路径，record 默认为 semantic。"""
    # 构造无 metadata 的 candidate（模拟 policy 路径）
    candidate = MemoryCandidate(
        id="candidate:test:no_meta",
        content="记住我喜欢 pytest",
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="stable",
        confidence=0.9,
        reason="用户显式指令",
    )
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)

    record = _record_from_intent(intent, "audit:test:explicit")
    assert record.memory_type == "semantic"
    assert record.source_type == "explicit_user_request"


# ── G6: Snapshot 包含 memory_type 信息 ────────────────────────────────────


def test_snapshot_provenance_includes_memory_type() -> None:
    """G6: MemorySnapshot 的 provenance 中包含 record 的 memory_type。"""
    store = InMemoryMemoryStore()
    from agent.memory_operations import build_memory_audit_summary

    # 写入一条 episodic record
    candidate = _candidate_with_metadata("episodic")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)
    store.apply_operation_intent(intent, audit)

    options = MemorySnapshotBuildOptions(
        selection_reason="测试 memory_type visibility",
        max_items=5,
    )
    snapshot = build_memory_snapshot_from_store(store, options)

    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert "type:episodic" in item.provenance
    assert "type:episodic" in item.selection_reason


def test_snapshot_shows_procedural_type_in_provenance() -> None:
    """G6: procedural record 在 snapshot 中可见 memory_type。"""
    store = InMemoryMemoryStore()
    from agent.memory_operations import build_memory_audit_summary

    candidate = _candidate_with_metadata("procedural")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)
    store.apply_operation_intent(intent, audit)

    options = MemorySnapshotBuildOptions(
        selection_reason="测试 procedural visibility",
        max_items=5,
    )
    snapshot = build_memory_snapshot_from_store(store, options)

    assert len(snapshot.items) == 1
    assert "type:procedural" in snapshot.items[0].provenance


def test_snapshot_shows_semantic_type_for_explicit_retain() -> None:
    """G6: explicit retain 的 record 在 snapshot 中显示 semantic 类型。"""
    store = InMemoryMemoryStore()
    from agent.memory_operations import build_memory_audit_summary

    # 构造无 metadata 的 candidate（模拟 policy explicit retain）
    candidate = MemoryCandidate(
        id="candidate:test:sem_explicit",
        content="用户偏好 pytest",
        source=MemorySource.USER_INPUT,
        source_event=None,
        proposed_type="explicit_retain",
        scope=MemoryScope.USER,
        sensitivity=MemorySensitivity.LOW,
        stability="stable",
        confidence=0.9,
        reason="用户显式指令",
    )
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)
    store.apply_operation_intent(intent, audit)

    options = MemorySnapshotBuildOptions(
        selection_reason="测试 explicit retain type",
        max_items=5,
    )
    snapshot = build_memory_snapshot_from_store(store, options)

    assert len(snapshot.items) == 1
    assert "type:semantic" in snapshot.items[0].provenance


# ── 端到端：suggestion → store → snapshot ─────────────────────────────────


def test_full_pipeline_episodic_propagation() -> None:
    """端到端：episodic candidate metadata → intent → record → snapshot，完整流通。"""
    store = InMemoryMemoryStore()
    from agent.memory_operations import build_memory_audit_summary

    candidate = _candidate_with_metadata("episodic")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)

    # 写入 store
    apply_result = store.apply_operation_intent(intent, audit)
    assert apply_result.record is not None
    assert apply_result.record.memory_type == "episodic"
    assert apply_result.record.source_type == "agent_suggested"

    # 从 store 读取
    retrieved = store.get_record(apply_result.record.id)
    assert retrieved is not None
    assert retrieved.memory_type == "episodic"

    # Snapshot 可见
    options = MemorySnapshotBuildOptions(
        selection_reason="端到端 episodic test",
        max_items=5,
    )
    snapshot = build_memory_snapshot_from_store(store, options)
    assert len(snapshot.items) == 1
    assert "type:episodic" in snapshot.items[0].provenance


def test_full_pipeline_procedural_propagation() -> None:
    """端到端：procedural candidate metadata → intent → record → snapshot，完整流通。"""
    store = InMemoryMemoryStore()
    from agent.memory_operations import build_memory_audit_summary

    candidate = _candidate_with_metadata("procedural")
    result = _confirmed_result_for(candidate)
    intent = build_memory_operation_intent(result)
    audit = build_memory_audit_summary(intent)

    apply_result = store.apply_operation_intent(intent, audit)
    assert apply_result.record is not None
    assert apply_result.record.memory_type == "procedural"

    retrieved = store.get_record(apply_result.record.id)
    assert retrieved is not None
    assert retrieved.memory_type == "procedural"

    options = MemorySnapshotBuildOptions(
        selection_reason="端到端 procedural test",
        max_items=5,
    )
    snapshot = build_memory_snapshot_from_store(store, options)
    assert len(snapshot.items) == 1
    assert "type:procedural" in snapshot.items[0].provenance


def test_full_pipeline_multiple_types_coexist() -> None:
    """端到端：三种类型共存于同一 store，各自保留正确的 memory_type。"""
    store = InMemoryMemoryStore()
    from agent.memory_operations import build_memory_audit_summary

    for mtype in ("episodic", "semantic", "procedural"):
        candidate = _candidate_with_metadata(mtype)
        result = _confirmed_result_for(candidate)
        intent = build_memory_operation_intent(result)
        audit = build_memory_audit_summary(intent)
        store.apply_operation_intent(intent, audit)

    records = list(store.list_records())
    assert len(records) == 3

    types_found = {r.memory_type for r in records}
    assert types_found == {"episodic", "semantic", "procedural"}

    # Snapshot 包含所有三种类型
    options = MemorySnapshotBuildOptions(
        selection_reason="三种类型共存",
        max_items=5,
    )
    snapshot = build_memory_snapshot_from_store(store, options)
    assert len(snapshot.items) == 3

    provenances = [item.provenance for item in snapshot.items]
    assert any("type:episodic" in p for p in provenances)
    assert any("type:semantic" in p for p in provenances)
    assert any("type:procedural" in p for p in provenances)


# ── Backward compatibility ───────────────────────────────────────────────


def test_existing_explicit_retain_unchanged() -> None:
    """向后兼容：显式 "remember that X" 路径产生的 record 仍为 semantic。"""
    from agent.memory_policy import DeterministicMemoryPolicy

    policy = DeterministicMemoryPolicy()
    decision = policy.decide("remember that I prefer pytest for testing")

    request = build_memory_confirmation_request(decision)
    result = resolve_memory_confirmation_choice(request, MemoryConfirmationChoice.ACCEPT)

    intent = build_memory_operation_intent(result)
    # 显式 retain 的 candidate.metadata 为空，回退到 semantic
    assert intent.memory_type == "semantic"
    assert intent.source_type == "explicit_user_request"

    record = _record_from_intent(intent, "audit:test:backward_compat")
    assert record.memory_type == "semantic"
    assert record.source_type == "explicit_user_request"
