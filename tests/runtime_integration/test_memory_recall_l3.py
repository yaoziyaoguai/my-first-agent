"""Memory Recall L3 TDD 测试。

验证 MEMORY_RECALL 从 loop.py turn-end hook 经 dispatcher.route_from_runtime_loop()
dispatch 后产生 real_core_loop_runtime_e2e evidence。

归属已有 turn-end hook branch point 下的 branch behavior——不新增 Anchor、
不新增 branch point、不新增 runtime flow。

架构依据：
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

import json
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
from agent.runtime_integration.memory_recall import MemoryRecallHandler
from agent.runtime_integration.schema import RuntimeActionRequest


def _make_store_with_records(*records):
    from agent.memory_store import InMemoryMemoryStore
    return InMemoryMemoryStore(records=records)


def _approved_record(record_id: str, content: str):
    """构造已批准的 episodic MemoryRecord 用于 recall 测试。"""
    from agent.memory_contracts import MemoryScope
    from agent.memory_store import (
        MemoryOperationType,
        MemoryRecord,
    )
    return MemoryRecord(
        id=record_id,
        content=content,
        scope=MemoryScope.USER,
        source_summary="test-harness",
        safety_summary="safe",
        audit_id=f"audit:{record_id}",
        created_by_operation=MemoryOperationType.RETAIN,
        updated_by_operation=MemoryOperationType.RETAIN,
        memory_type="episodic",
        approval_status="approved",
        metadata={"created_at": "2026-05-20T00:00:00Z"},
    )


def _build_recall_dispatcher(*, store):
    """构建仅注册 MEMORY_RECALL 的 dispatcher。

    loop.py 中其他 action type（MEMORY_TURN_END_PROPOSAL、TOOL_GATE 等）
    在 handler 缺失时会静默 fail——不影响 MEMORY_RECALL 的 dispatch。
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_RECALL,
        MemoryRecallHandler(store=store),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _RecallSpy:
    """拦截 dispatcher 调用，捕获 MEMORY_RECALL 的 route_from_runtime_loop 证据。"""

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self.captured: list[tuple[str, RuntimeActionRequest, Any]] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: RuntimeActionRequest, **kwargs: object) -> Any:
        result = self._real.route_from_runtime_loop(request)
        self.captured.append(("route_from_runtime_loop", request, result))
        return result


# ═══════════════════════════════════════════════════════════════════════
# T1: core.chat() → MEMORY_RECALL → L3 evidence
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryRecallL3:
    def test_recall_dispatched_from_loop_turn_end_is_l3(self):
        """MEMORY_RECALL 从 loop.py turn-end hook dispatch → L3 evidence。

        store 中有已批准 records → handler 生成 snapshot → disposition="recalled"
        → evidence_level=REAL_CORE_LOOP_RUNTIME_E2E。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        records = tuple(
            _approved_record(f"r{i}", "用户偏好 Python 编程，重视类型安全")
            for i in range(3)
        )
        store = _make_store_with_records(*records)

        real_dispatcher = _build_recall_dispatcher(store=store)
        spy = _RecallSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        recall_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_RECALL
        ]
        assert len(recall_entries) == 1, (
            f"turn-end hook 应 dispatch 恰好 1 次 MEMORY_RECALL，"
            f"实际 {len(recall_entries)} 次"
        )

        method, request, recall_result = recall_entries[0]
        assert method == "route_from_runtime_loop", (
            f"MEMORY_RECALL 必须走 route_from_runtime_loop() 路径，"
            f"实际 {method!r}"
        )

        # L3 evidence 验证
        evidence = dict(recall_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"MEMORY_RECALL turn-end dispatch 应达到 L3，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"
        assert evidence.get("target_module") == "MemoryRuntime"
        assert evidence.get("target_catalog_allowed") is True
        assert evidence.get("target_identity_valid") is True

        # payload 验证：有 approved records → recalled disposition
        payload = dict(recall_result.payload)
        assert payload.get("disposition") == "recalled", (
            f"有 approved records → disposition 应为 'recalled'，"
            f"实际 {payload.get('disposition')!r}"
        )
        assert payload.get("snapshot_item_count", 0) > 0

    def test_recall_empty_store_no_memory(self):
        """空 store → MEMORY_RECALL 仍 dispatch 但 disposition=no_memory。

        即使没有 record，L3 evidence chain 仍然完整——disposition 反映的是
        store 状态，不影响 evidence level。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        store = _make_store_with_records()
        real_dispatcher = _build_recall_dispatcher(store=store)
        spy = _RecallSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        recall_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_RECALL
        ]
        assert len(recall_entries) == 1

        method, _, recall_result = recall_entries[0]
        assert method == "route_from_runtime_loop"

        evidence = dict(recall_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"空 store 不影响 L3 classification——dispatch 仍从 runtime loop 出发，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("target_module") == "MemoryRuntime"

        payload = dict(recall_result.payload)
        assert payload.get("disposition") == "no_memory"
        assert payload.get("snapshot_item_count") == 0

    def test_default_chat_pre_loop_recall_reaches_event_log(self, tmp_path):
        """默认 chat() 不显式传 dispatcher 时，pre-loop recall 也进入 evidence 链。"""
        from agent.core import chat
        from agent.event_log import EventLogWriter
        from agent.provider.fake_provider import FakeProvider

        writer = EventLogWriter(tmp_path / "session")

        result = chat(
            "hello",
            provider=FakeProvider(),
            event_log_writer=writer,
        )
        writer.close()

        assert isinstance(result, str)
        events_path = tmp_path / "session" / "events.jsonl"
        lines = events_path.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        recall_events = [
            event for event in events
            if event.get("action_type") == "memory.recall"
        ]
        assert recall_events, "默认 chat() 的 pre-loop MEMORY_RECALL 必须写入 events.jsonl"


# ═══════════════════════════════════════════════════════════════════════
# T2: no real API / .env / secret
# ═══════════════════════════════════════════════════════════════════════


class TestNoRealAPIOrEnv:
    def test_recall_l3_no_real_api_or_env_access(self):
        """MEMORY_RECALL L3 pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        records = tuple(
            _approved_record(f"r{i}", "用户偏好简体中文交互")
            for i in range(3)
        )
        store = _make_store_with_records(*records)

        real_dispatcher = _build_recall_dispatcher(store=store)
        spy = _RecallSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        recall_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_RECALL
        ]
        assert len(recall_entries) == 1
        _, _, recall_result = recall_entries[0]

        evidence = dict(recall_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("no_silent_retain") is True
        assert evidence.get("read_only_operation") is True
        assert evidence.get("store_backend") == "in_memory"
