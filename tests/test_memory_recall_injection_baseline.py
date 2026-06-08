"""Memory deterministic recall/injection baseline。

本文件只证明当前正式路径的确定性治理边界：
MemoryRuntime/Store -> MemorySnapshot -> prompt_builder。它不调用真实 LLM、
不读取真实 memory episodes，也不声称验证 semantic recall quality。
"""

from __future__ import annotations

import pytest

from agent.memory_confirmation import MemoryConfirmationChoice
from agent.memory_contracts import MemoryScope, MemorySnapshot
from agent.memory_operations import MemoryOperationType
from agent.memory_runtime import MemoryRuntime
from agent.memory_snapshot_generator import (
    MemorySnapshotBuildOptions,
    build_memory_snapshot_from_store,
)
from agent.memory_store import InMemoryMemoryStore, MemoryRecord
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


def test_dispatcher_none_refresh_does_not_inject_memory_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory v0: dispatcher=None 不能无 evidence 地把 memory 注入 prompt。"""
    from agent import core, evidence_recorder
    from agent.state import create_agent_state

    calls: list[dict] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs) or {"data": {"metadata": kwargs.get("metadata", {})}},
    )
    store = InMemoryMemoryStore((
        _record("u0-direct", "DISPATCHER NONE RAW MEMORY SHOULD NOT INJECT"),
    ))
    runtime = MemoryRuntime(store=store)
    monkeypatch.setattr(core, "state", create_agent_state(system_prompt=""))
    monkeypatch.setattr(core, "_memory_runtime", runtime)

    prompt, count = core.refresh_runtime_system_prompt(dispatcher=None)

    assert count == 0
    assert "DISPATCHER NONE RAW MEMORY SHOULD NOT INJECT" not in prompt
    assert any(
        call.get("metadata", {}).get("event_type") == "memory.recall.skipped"
        and call.get("metadata", {}).get("reason") == "no_dispatcher_fallback"
        for call in calls
    )
    assert "DISPATCHER NONE RAW MEMORY SHOULD NOT INJECT" not in str(calls)


def test_v0_default_memory_runtime_log_records_safe_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory v0: 默认 MemoryRuntime logger 接入 built-in evidence。"""
    import agent.evidence_recorder as evidence_recorder

    calls: list[dict] = []
    monkeypatch.setattr(
        evidence_recorder,
        "record_evidence",
        lambda **kwargs: calls.append(kwargs),
    )

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    result = runtime.evaluate_user_text("remember that U0 log baseline exists")

    assert result.candidate_id is not None
    event_types = [call["metadata"]["event_type"] for call in calls]
    assert "memory.proposed" in event_types
    assert "memory.proposal_surfaced" in event_types
    assert "U0 log baseline exists" not in str(calls)
    assert result.candidate_id not in str(calls)


def test_u0_working_summary_is_hidden_prompt_context_not_user_memory() -> None:
    """U0 characterization: working_summary 进模型上下文，但不进 MemoryStore list。"""
    from agent.context_builder import build_execution_messages
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="")
    state.memory.working_summary = "U0 hidden working summary"
    messages = build_execution_messages(state)

    assert any("U0 hidden working summary" in str(m.get("content")) for m in messages)

    runtime = MemoryRuntime(store=InMemoryMemoryStore())
    listed = runtime.list_records()
    assert listed == ()
    assert "U0 hidden working summary" not in str(listed)
