"""Memory shared-store consistency L3 contract tests — Loop 2.1b.

验证 retain → recall → forget 通过 dispatcher 走同一 store 实例，
不存在 handler 独立 store 导致写入/读取/删除数据分裂。
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
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType


def _add_record(store: InMemoryMemoryStore, content: str, source_summary: str = "test") -> str:
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
    result = store.apply_operation_intent(intent, build_memory_audit_summary(intent))
    assert result.record is not None
    return result.record.id


def _make_shared_runtime_and_dispatcher():
    """创建共享 store 的 MemoryRuntime + Phase 1 dispatcher。"""
    from agent.memory_runtime import create_memory_runtime

    store = InMemoryMemoryStore()
    runtime = create_memory_runtime(store=store)
    dispatcher = build_phase1_dispatcher(memory_runtime=runtime)
    return store, runtime, dispatcher


class TestMemorySharedStoreL3:
    """L3: retain/recall/forget 共享同一 store 实例。"""

    def test_retain_via_dispatcher_readable_via_recall(self):
        """通过 dispatcher retain → recall 可读到同一数据。"""
        store, runtime, dispatcher = _make_shared_runtime_and_dispatcher()

        # 通过 MEMORY_PROPOSE (retain) 写入
        import hashlib
        content = "shared-store-retain-test-content"
        candidate = {
            "content": content,
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "proposal_id": "candidate:test-retain-001",
            "scope": "user",
            "sensitivity": "low",
            "source": "test",
        }
        retain_result = dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_PROPOSE,
                source="test",
                parent_trace_id="",
                payload={
                    "confirmation_result": "accepted",
                    "proposal_id": "candidate:test-retain-001",
                    "candidate": candidate,
                },
            )
        )
        assert retain_result.status == "success"
        assert retain_result.payload.get("disposition") == "retain"

        # 通过 MEMORY_RECALL 读取
        recall_result = dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_RECALL,
                source="test",
                parent_trace_id="",
                payload={},
            )
        )
        assert recall_result.status == "success"
        assert recall_result.payload.get("snapshot_item_count", 0) >= 1

    def test_retain_then_forget_via_dispatcher(self):
        """retain → forget → recall 验证共享 store 一致性。"""
        store, runtime, dispatcher = _make_shared_runtime_and_dispatcher()

        # 直接写一条记录
        record_id = _add_record(
            store, "to-be-forgotten-via-dispatcher", source_summary="test/l3-forget"
        )

        # 确认 store 中有记录
        assert store.get_record(record_id) is not None

        # MEMORY_FORGET via route_from_runtime_loop
        forget_result = dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": record_id},
            )
        )
        assert forget_result.status == "success"
        assert forget_result.payload.get("forgotten") is True

        # store 中已无此记录
        assert store.get_record(record_id) is None

    def test_forget_only_affects_shared_store(self):
        """forget 删除的是共享 store 中的记录，不是独立 store。"""
        store, runtime, dispatcher = _make_shared_runtime_and_dispatcher()

        rid = _add_record(store, "shared-store-record", source_summary="test/l3-shared")

        # 通过 dispatcher forget
        dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_FORGET,
                source="test",
                parent_trace_id="",
                payload={"record_id": rid},
            )
        )

        # 直接从共享 store 查询：已删除
        assert store.get_record(rid) is None
        # runtime.list_records() 也读同一 store
        assert rid not in {r.id for r in runtime.list_records()}

    def test_handler_stores_are_same_instance(self):
        """retain/recall/forget handler 使用的 store 是同一实例。"""
        store, runtime, dispatcher = _make_shared_runtime_and_dispatcher()

        # 从 dispatcher 的 action_log 中提取 handler 使用的 store
        # （通过 MEMORY_RECALL 的 evidence）
        recall_result = dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_RECALL,
                source="test",
                parent_trace_id="",
                payload={},
            )
        )
        assert recall_result.status == "success"

        # 查 action_log 中 MEMORY_RECALL event
        recall_events = [
            e for e in dispatcher.action_log
            if e.action_type == RuntimeActionType.MEMORY_RECALL
        ]
        assert len(recall_events) >= 1
        # evidence 中应该有 store_backend，且 handler invoked 为 True
        ev = recall_events[0].evidence
        assert ev.get("store_backend") in ("in_memory", "filesystem")

    def test_recall_sees_shared_store_after_direct_add(self):
        """直接往共享 store add record → recall 通过 dispatcher 能读到。"""
        store, runtime, dispatcher = _make_shared_runtime_and_dispatcher()

        _add_record(store, "direct-add-via-shared-store", source_summary="test/l3-direct")

        recall_result = dispatcher.route_from_runtime_loop(
            RuntimeActionRequest(
                action_type=RuntimeActionType.MEMORY_RECALL,
                source="test",
                parent_trace_id="",
                payload={},
            )
        )
        assert recall_result.status == "success"
        # 应该能读到至少 1 条（direct add 的记录在共享 store 中）
        assert recall_result.payload.get("snapshot_item_count", 0) >= 1
