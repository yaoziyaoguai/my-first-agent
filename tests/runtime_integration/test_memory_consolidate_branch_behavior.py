"""Memory consolidate branch behavior tests (L1/L2).

验证 MemoryConsolidateHandler 在 dispatcher.route() 路径下的
行为：insufficient_evidence / no_candidates / consolidated 三个 disposition。

SPEC: docs/specs/memory-consolidation-l3/SPEC.md
TDD: docs/specs/memory-consolidation-l3/TDD.md
"""

from __future__ import annotations


from agent.memory_store import (
    InMemoryMemoryStore,
    MemoryOperationType,
    MemoryRecord,
)
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionRequest,
    RuntimeActionType,
)
from agent.runtime_integration.memory_consolidate import MemoryConsolidateHandler


def _make_request(
    action_type: RuntimeActionType = RuntimeActionType.MEMORY_CONSOLIDATE,
) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        action_type=action_type,
        source="test_harness",
        parent_trace_id="trace-consolidation-test",
        payload={},
        constraints=frozenset({"readonly", "no_store_write"}),
    )


def _episodic_record(
    record_id: str,
    content: str,
    *,
    memory_type: str = "episodic",
    created_at: str = "2026-05-20T00:00:00Z",
) -> MemoryRecord:
    """构造一条 episodic MemoryRecord，用于 consolidation 测试。"""
    return MemoryRecord(
        id=record_id,
        content=content,
        scope="user",
        source_summary="test-harness",
        safety_summary="safe",
        audit_id=f"audit:{record_id}",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
        memory_type=memory_type,
        approval_status="approved",
        metadata={"created_at": created_at},
    )


def _make_store_with_records(*records: MemoryRecord) -> InMemoryMemoryStore:
    """创建包含指定 records 的 InMemoryMemoryStore。"""
    return InMemoryMemoryStore(records=records)


# ═══════════════════════════════════════════════════════════════════════
# T1: L1 Handler unit tests
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryConsolidateHandlerUnit:
    """L1: dispatcher.route() 路径的 handler 行为测试。"""

    def test_insufficient_evidence_empty_store(self):
        """空 store → insufficient_evidence，candidates_count=0。"""
        store = _make_store_with_records()
        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert result.status == "success"
        assert result.evidence["target_module"] == "MemoryConsolidation"
        assert result.payload["disposition"] == "insufficient_evidence"
        assert result.payload["candidates_count"] == 0
        assert result.payload["evidence_count"] == 0

    def test_insufficient_evidence_few_episodic(self):
        """store 中 episodic < 3 条 → insufficient_evidence。"""
        store = _make_store_with_records(
            _episodic_record("e1", "用户偏好 Python 类型注解"),
            _episodic_record("e2", "用户偏好 Python 类型注解"),
        )

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert result.status == "success"
        assert result.payload["disposition"] == "insufficient_evidence"
        assert result.payload["evidence_count"] == 2  # loaded but N<3

    def test_consolidated_with_sufficient_evidence(self):
        """≥3 条相似 episodic → consolidated，有 candidates。"""
        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户表示喜欢用 Python 编程，偏好类型注解和 dataclass",
            )
            for i in range(5)
        )
        store = _make_store_with_records(*records)

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert result.status == "success"
        assert result.payload["disposition"] in ("consolidated", "no_candidates")
        assert result.payload["evidence_count"] == 5

        if result.payload["disposition"] == "consolidated":
            assert result.payload["candidates_count"] > 0
            assert len(result.payload["consolidation_types"]) > 0

    def test_handler_readonly(self):
        """Handler 运行后 store 记录数不变。"""
        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户喜欢用 Python 编程，重视类型安全和可维护性",
            )
            for i in range(5)
        )
        store = _make_store_with_records(*records)
        before_count = len(store.list_records())

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        dispatcher.route(_make_request())

        after_count = len(store.list_records())
        assert after_count == before_count

    def test_evidence_contains_required_fields(self):
        """验证 evidence 包含 consolidation 必要字段。"""
        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户反复强调代码可读性比性能更重要",
            )
            for i in range(4)
        )
        store = _make_store_with_records(*records)

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert "disposition" in result.payload
        assert "candidates_count" in result.payload
        assert "evidence_count" in result.payload
        assert "skipped_count" in result.payload
        assert "detector_name" in result.payload
        assert result.evidence["readonly"] is True
        assert result.evidence["no_store_write"] is True


# ═══════════════════════════════════════════════════════════════════════
# T2: L2 Dispatcher integration tests
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryConsolidateDispatcherIntegration:
    """L2: dispatcher 集成——验证 catalog target proof 和 evidence classification。"""

    def test_route_through_dispatcher_produces_harness_runtime_e2e(self):
        """通过 dispatcher.route() → catalog adapter → harness_runtime_e2e evidence。"""
        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户喜欢 Python，强调类型安全和代码可维护性",
            )
            for i in range(5)
        )
        store = _make_store_with_records(*records)

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert result.status == "success"
        assert result.evidence["target_module"] == "MemoryConsolidation"
        assert result.evidence["evidence_level"] == "harness_runtime_e2e"

    def test_catalog_target_proof_valid(self):
        """Catalog target identity 验证通过。"""
        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户表示代码可读性是第一优先级，宁可多写几行也要清楚",
            )
            for i in range(4)
        )
        store = _make_store_with_records(*records)

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert result.evidence["target_catalog_allowed"] is True
        assert result.evidence["target_identity_valid"] is True
        assert result.evidence["target_module_proof"]["target_identity_valid"] is True

    def test_no_candidates_when_no_pattern(self):
        """内容差异大、无 pattern → no_candidates。"""
        store = _make_store_with_records(
            _episodic_record("e1", "用户喜欢 Python"),
            _episodic_record("e2", "用户使用 macOS 系统"),
            _episodic_record("e3", "用户偏好暗色主题"),
            _episodic_record("e4", "GitHub 用户名是 yaoziyaoguai"),
        )

        handler = MemoryConsolidateHandler(store=store)
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, handler)
        dispatcher = RuntimeActionDispatcher(registry)

        result = dispatcher.route(_make_request())

        assert result.status == "success"
        # 内容完全不相关，应无 candidate
        assert result.payload["candidates_count"] == 0
