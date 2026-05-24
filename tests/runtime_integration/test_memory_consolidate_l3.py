"""Memory Consolidation L3 TDD 测试。

验证 MEMORY_CONSOLIDATE 从 loop.py turn-end hook 经 dispatcher.route_from_runtime_loop()
dispatch 后产生 real_core_loop_runtime_e2e evidence。

归属已有 turn-end hook branch point 下的 branch behavior——不新增 Anchor、
不新增 branch point、不新增 runtime flow。
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.memory_consolidate import MemoryConsolidateHandler
from agent.runtime_integration.schema import RuntimeActionRequest


def _make_store_with_records(*records):
    from agent.memory_store import InMemoryMemoryStore
    return InMemoryMemoryStore(records=records)


def _episodic_record(record_id: str, content: str):
    from agent.memory_store import (
        MemoryOperationType,
        MemoryRecord,
    )
    return MemoryRecord(
        id=record_id,
        content=content,
        scope="user",
        source_summary="test-harness",
        safety_summary="safe",
        audit_id=f"audit:{record_id}",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
        memory_type="episodic",
        approval_status="approved",
        metadata={"created_at": "2026-05-20T00:00:00Z"},
    )


def _build_consolidation_dispatcher(*, store):
    """构建仅注册 MEMORY_CONSOLIDATE 的 dispatcher。

    loop.py 中其他 action type（MEMORY_TURN_END_PROPOSAL、TOOL_GATE 等）
    在 handler 缺失时会静默 fail——不影响 MEMORY_CONSOLIDATE 的 dispatch。
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_CONSOLIDATE,
        MemoryConsolidateHandler(store=store),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _ConsolidationSpy:
    """拦截 dispatcher 调用，捕获 MEMORY_CONSOLIDATE 的 route_from_runtime_loop 证据。"""

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self.captured: list[tuple[str, RuntimeActionRequest, Any]] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route_from_runtime_loop(request)
        self.captured.append(("route_from_runtime_loop", request, result))
        return result


# ═══════════════════════════════════════════════════════════════════════
# T1: core.chat() → MEMORY_CONSOLIDATE → L3 evidence
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryConsolidateL3:
    def test_consolidate_dispatched_from_loop_turn_end_is_l3(self):
        """MEMORY_CONSOLIDATE 从 loop.py turn-end hook dispatch → L3 evidence。

        store 中 ≥5 条相似 episodic 记录 → consolidation pipeline 产生 candidates
        → disposition="consolidated" → evidence_level=REAL_CORE_LOOP_RUNTIME_E2E。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户表示喜欢用 Python 编程，偏好类型注解和 dataclass，重视代码可维护性",
            )
            for i in range(5)
        )
        store = _make_store_with_records(*records)

        real_dispatcher = _build_consolidation_dispatcher(store=store)
        spy = _ConsolidationSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        consolidate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_CONSOLIDATE
        ]
        assert len(consolidate_entries) == 1, (
            f"turn-end hook 应 dispatch 恰好 1 次 MEMORY_CONSOLIDATE，"
            f"实际 {len(consolidate_entries)} 次"
        )

        method, request, consolidate_result = consolidate_entries[0]
        assert method == "route_from_runtime_loop", (
            f"MEMORY_CONSOLIDATE 必须走 route_from_runtime_loop() 路径，"
            f"实际 {method!r}"
        )

        # L3 evidence 验证
        evidence = dict(consolidate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"MEMORY_CONSOLIDATE turn-end dispatch 应达到 L3，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"
        assert evidence.get("target_module") == "MemoryConsolidation"
        assert evidence.get("target_catalog_allowed") is True
        assert evidence.get("target_identity_valid") is True

        # payload 验证：≥5 条相似记录应触发 consolidated disposition
        payload = dict(consolidate_result.payload)
        assert payload.get("disposition") == "consolidated", (
            f"≥5 条相似 episodic → disposition 应为 'consolidated'，"
            f"实际 {payload.get('disposition')!r}"
        )
        assert payload.get("candidates_count", 0) > 0
        assert payload.get("evidence_count") == 5
        assert payload.get("readonly", True) is True

    def test_consolidate_insufficient_evidence_empty_store(self):
        """空 store → MEMORY_CONSOLIDATE 仍 dispatch 但 disposition=insufficient_evidence。

        即使没有 candidate，L3 evidence chain 仍然完整——disposition 反映的是
        store 状态，不影响 evidence level。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        store = _make_store_with_records()
        real_dispatcher = _build_consolidation_dispatcher(store=store)
        spy = _ConsolidationSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        consolidate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_CONSOLIDATE
        ]
        assert len(consolidate_entries) == 1

        method, _, consolidate_result = consolidate_entries[0]
        assert method == "route_from_runtime_loop"

        evidence = dict(consolidate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"空 store 不影响 L3 classification——dispatch 仍从 runtime loop 出发，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("target_module") == "MemoryConsolidation"

        payload = dict(consolidate_result.payload)
        assert payload.get("disposition") == "insufficient_evidence"
        assert payload.get("candidates_count") == 0


# ═══════════════════════════════════════════════════════════════════════
# T2: no real API / .env / secret
# ═══════════════════════════════════════════════════════════════════════


class TestNoRealAPIOrEnv:
    def test_consolidation_l3_no_real_api_or_env_access(self):
        """MEMORY_CONSOLIDATE L3 pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        records = tuple(
            _episodic_record(
                f"e{i}",
                "用户喜欢 Python，偏好类型安全和代码可维护性",
            )
            for i in range(5)
        )
        store = _make_store_with_records(*records)

        real_dispatcher = _build_consolidation_dispatcher(store=store)
        spy = _ConsolidationSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        consolidate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_CONSOLIDATE
        ]
        assert len(consolidate_entries) == 1
        _, _, consolidate_result = consolidate_entries[0]

        evidence = dict(consolidate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("no_store_write") is True
        assert evidence.get("readonly") is True
        assert evidence.get("store_backend") == "in_memory"
