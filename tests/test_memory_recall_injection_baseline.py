"""Memory deterministic recall/injection baseline。

本文件只证明当前正式路径的确定性治理边界：
MemoryRuntime/Store -> MemorySnapshot -> prompt_builder。它不调用真实 LLM、
不读取真实 memory episodes，也不声称验证 semantic recall quality。
"""

from __future__ import annotations

from agent.memory_confirmation import MemoryConfirmationChoice
from agent.memory_contracts import MemoryScope, MemorySnapshot
from agent.memory_runtime import MemoryRuntime
from agent.memory_snapshot_generator import (
    MemorySnapshotBuildOptions,
    build_memory_snapshot_from_store,
)
from agent.memory_store import InMemoryMemoryStore, MemoryRecord
from agent.memory_operations import MemoryOperationType
from agent.prompt_builder import build_system_prompt


def _record(
    record_id: str,
    content: str,
    *,
    scope: MemoryScope = MemoryScope.USER,
    safety_summary: str = "safe",
    sensitive_redacted: bool = False,
) -> MemoryRecord:
    """构造已确认 fake record；测试只进入正式 snapshot path，不绕过治理写入。"""

    return MemoryRecord(
        id=record_id,
        content=content,
        scope=scope,
        source_summary=f"fixture:{record_id}",
        safety_summary=safety_summary,
        audit_id=f"audit:{record_id}",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
        sensitive_redacted=sensitive_redacted,
    )


def test_confirmed_memory_can_be_selected_for_prompt_injection() -> None:
    """approved record 可以经 snapshot 进入 prompt，但选择仍是 deterministic。"""

    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)

    pending = runtime.evaluate_user_text("remember that reports should stay concise")
    runtime.resolve_confirmation(pending.candidate_id, MemoryConfirmationChoice.ACCEPT)

    snapshot = runtime.snapshot_for_prompt(selection_reason="deterministic baseline")
    prompt = build_system_prompt(memory_snapshot=snapshot)

    assert isinstance(snapshot, MemorySnapshot)
    assert [item.content for item in snapshot.items] == ["reports should stay concise"]
    assert "deterministic baseline" in prompt
    assert "reports should stay concise" in prompt


def test_rejected_or_pending_memory_cannot_be_injected_as_confirmed() -> None:
    """pending/rejected 候选不能伪装成 confirmed snapshot item。"""

    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store=store)
    pending = runtime.evaluate_user_text("remember that pending memory stays pending")

    assert runtime.snapshot_for_prompt().items == ()

    runtime.resolve_confirmation(pending.candidate_id, MemoryConfirmationChoice.REJECT)

    assert store.list_records() == ()
    assert runtime.snapshot_for_prompt().items == ()


def test_recall_injection_respects_project_and_session_boundaries() -> None:
    """scope filter 防止 project/session/user 记忆互相串入同一 snapshot。"""

    store = InMemoryMemoryStore((
        _record("user-1", "用户偏好短答复", scope=MemoryScope.USER),
        _record("project-1", "项目禁止真实 LLM 调用", scope=MemoryScope.PROJECT),
        _record("session-1", "本会话临时上下文", scope=MemoryScope.SESSION),
    ))

    project_snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(
            selection_reason="project-only deterministic recall",
            scopes=(MemoryScope.PROJECT,),
        ),
    )
    session_snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(
            selection_reason="session-only deterministic recall",
            scopes=(MemoryScope.SESSION,),
        ),
    )

    assert [item.content for item in project_snapshot.items] == ["项目禁止真实 LLM 调用"]
    assert [item.content for item in session_snapshot.items] == ["本会话临时上下文"]


def test_injected_context_excludes_secret_like_values() -> None:
    """敏感 record 默认被 snapshot 过滤，prompt 不出现 secret-like 明文。"""

    store = InMemoryMemoryStore((
        _record("safe-1", "使用 pytest 做验证"),
        _record(
            "secret-1",
            "API_KEY=literal-secret-value",
            safety_summary="sensitive secret",
            sensitive_redacted=True,
        ),
    ))

    snapshot = build_memory_snapshot_from_store(
        store,
        MemorySnapshotBuildOptions(selection_reason="secret filtering baseline"),
    )
    prompt = build_system_prompt(memory_snapshot=snapshot)

    assert [item.content for item in snapshot.items] == ["使用 pytest 做验证"]
    assert "literal-secret-value" not in prompt
    assert "API_KEY=literal-secret-value" not in prompt
    assert snapshot.omitted_count == 1


def test_deterministic_selector_order_and_budget_are_reproducible() -> None:
    """deterministic selector 只按固定 store/order/budget 行为，不测语义质量。"""

    store = InMemoryMemoryStore((
        _record("memory:c", "第三条"),
        _record("memory:a", "第一条"),
        _record("memory:b", "第二条"),
    ))
    options = MemorySnapshotBuildOptions(
        selection_reason="stable deterministic selector",
        max_items=2,
    )

    first = build_memory_snapshot_from_store(store, options)
    second = build_memory_snapshot_from_store(store, options)

    assert first == second
    assert [item.content for item in first.items] == ["第一条", "第二条"]
    assert first.omitted_count == 1
