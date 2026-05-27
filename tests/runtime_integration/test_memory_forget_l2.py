"""Memory forget dispatcher path contract tests — Loop 2.1.

验证 MEMORY_FORGET 通过 dispatcher 执行 forget：MemoryForgetHandler
正确执行 remove_record 并返回 disposition（forgotten/not_found/rejected）。
"""

from __future__ import annotations

from agent.memory_confirmation import MemoryConfirmationChoice, MemoryConfirmationStatus
from agent.memory_contracts import MemoryDecisionType, MemoryScope
from agent.memory_operations import (
    MemoryOperationIntent,
    MemoryOperationType,
    build_memory_audit_summary,
)
from agent.memory_store import InMemoryMemoryStore
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import RuntimeActionModuleObserver
from agent.runtime_integration.memory_forget import MemoryForgetHandler
from agent.runtime_integration.schema import RuntimeActionRequest


def _add_record(store: InMemoryMemoryStore, content: str, source_summary: str = "test") -> str:
    """直接向 store 添加一条已批准记录，返回 record_id。"""
    intent = MemoryOperationIntent(
        operation_type=MemoryOperationType.RETAIN,
        decision_type=MemoryDecisionType.RETAIN,
        confirmation_status=MemoryConfirmationStatus.APPROVED,
        user_choice=MemoryConfirmationChoice.ACCEPT,
        content_summary=content,
        source_summary=source_summary,
        scope=MemoryScope.USER,
        safety_summary="无额外安全标记",
        sensitive_redacted=False,
        user_visible_summary=content[:80],
    )
    result = store.apply_operation_intent(
        intent,
        audit_summary=build_memory_audit_summary(intent),
    )
    assert result.record is not None
    return result.record.id


def _make_dispatcher(store: InMemoryMemoryStore):
    """创建注册了 MEMORY_FORGET handler 的 dispatcher。"""
    from agent.memory_runtime import create_memory_runtime

    runtime = create_memory_runtime(store=store)
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_FORGET,
        MemoryForgetHandler(memory_runtime=runtime),
    )
    return RuntimeActionDispatcher(
        registry=registry,
        observer=RuntimeActionModuleObserver(),
    )


# ========== L2: Dispatcher route tests ==========


class TestMemoryForgetViaDispatcher:
    """L2: MEMORY_FORGET 通过 dispatcher.route() 走完整路径。"""

    def test_forget_existing_record(self):
        """dispatcher.route(MEMORY_FORGET) 删除存在的记录 → forgotten。"""
        store = InMemoryMemoryStore()
        record_id = _add_record(store, "测试数据ABC")
        dispatcher = _make_dispatcher(store)

        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": record_id},
            )
        )

        assert result.status == "success"
        assert result.payload["forgotten"] is True
        assert result.payload["disposition"] == "forgotten"
        # store 中已无此记录
        remaining = tuple(store.list_records())
        assert all(r.id != record_id for r in remaining)

    def test_forget_nonexistent_record(self):
        """dispatcher.route(MEMORY_FORGET) 不存在的记录 → not_found。"""
        store = InMemoryMemoryStore()
        dispatcher = _make_dispatcher(store)

        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": "does-not-exist"},
            )
        )

        assert result.status == "success"
        assert result.payload["forgotten"] is False
        assert result.payload["disposition"] == "not_found"

    def test_forget_empty_record_id_rejected(self):
        """dispatcher.route(MEMORY_FORGET) 空 record_id → rejected。"""
        store = InMemoryMemoryStore()
        dispatcher = _make_dispatcher(store)

        result = dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": ""},
            )
        )

        assert result.status == "rejected"
        assert result.payload["forgotten"] is False

    def test_forget_evidence_in_action_log(self):
        """dispatcher 在 action_log 中留下 MEMORY_FORGET 证据。"""
        store = InMemoryMemoryStore()
        record_id = _add_record(store, "证据链测试")
        dispatcher = _make_dispatcher(store)

        dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": record_id},
            )
        )

        forget_events = [
            e for e in dispatcher.action_log if e.action_type == "memory.forget"
        ]
        assert len(forget_events) >= 1
        assert forget_events[0].evidence.get("disposition") in (
            "forgotten",
            "not_found",
        )

    def test_forget_leaves_other_records_intact(self):
        """forget 只删除指定记录，不影响其他记录。"""
        store = InMemoryMemoryStore()
        rid_a = _add_record(store, "记录A", source_summary="test/a")
        rid_b = _add_record(store, "记录B", source_summary="test/b")
        dispatcher = _make_dispatcher(store)

        dispatcher.route(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": rid_a},
            )
        )

        remaining = tuple(store.list_records())
        remaining_ids = {r.id for r in remaining}
        assert rid_a not in remaining_ids
        assert rid_b in remaining_ids
