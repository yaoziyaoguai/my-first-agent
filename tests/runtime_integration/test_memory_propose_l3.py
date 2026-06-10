"""MEMORY_PROPOSE L3 测试。

验证 core.chat() → turn-end hook → MEMORY_PROPOSE dispatch 的完整 evidence chain。
MEMORY_PROPOSE 是 retain execution 的正式路径：已确认的 proposal 在
state.task.pending_retain_proposals 中排队，turn-end hook 中 dispatch
MEMORY_PROPOSE → MemoryRetainHandler → store.write()。

测试分层：
- L1/L2: 已有 test_memory_retain_branch_behavior.py 覆盖
- L3 (real_core_loop_runtime_e2e): core.chat() → MEMORY_PROPOSE dispatch via turn-end hook
"""

from __future__ import annotations

import hashlib
import uuid
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
from agent.runtime_integration.memory_retain import MemoryRetainHandler
from agent.runtime_integration.schema import RuntimeActionRequest


def _make_candidate_payload(
    *,
    content: str = "用户偏好简体中文",
    proposal_id: str | None = None,
    scope: str = "user",
    sensitivity: str = "low",
    source: str = "turn_end_proposal",
) -> dict[str, Any]:
    """构造已确认的 candidate payload，用于 queue 到 pending_retain_proposals。"""
    return {
        "proposal_id": proposal_id or f"prop:{uuid.uuid4().hex[:12]}",
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "scope": scope,
        "sensitivity": sensitivity,
        "source": source,
        "confirmation_result": "accepted",
        "queued_at": "2026-05-24T00:00:00Z",
    }


def _build_propose_dispatcher(*, store=None):
    """构建仅注册 MEMORY_PROPOSE 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_PROPOSE,
        MemoryRetainHandler(store=store),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _ProposeSpy:
    """拦截 dispatcher 调用，捕获 MEMORY_PROPOSE 的 route_from_runtime_loop 证据。"""

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
# T1: core.chat() → MEMORY_PROPOSE dispatch → L3 evidence
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryProposeL3:
    def test_t1_memory_propose_dispatched_from_loop_turn_end(self):
        """T1: turn-end hook dispatch MEMORY_PROPOSE 当 pending_retain_proposals 非空。

        验证：state.task.pending_retain_proposals 中有已确认 proposal 时，
        turn-end hook 应构造并 dispatch MEMORY_PROPOSE RuntimeActionRequest。
        """
        from agent import core
        from agent.core import chat
        from agent.memory_store import InMemoryMemoryStore
        from agent.provider.fake_provider import FakeProvider

        store = InMemoryMemoryStore()
        real_dispatcher = _build_propose_dispatcher(store=store)
        spy = _ProposeSpy(real_dispatcher)

        # Queue confirmed proposal
        candidate = _make_candidate_payload()
        core.state.task.pending_retain_proposals.append(candidate)

        try:
            result = chat(
                "hello",
                provider=FakeProvider(),
                runtime_action_dispatcher=spy,
            )

            assert isinstance(result, str)

            propose_entries = [
                (m, r, res) for m, r, res in spy.captured
                if r.action_type == RuntimeActionType.MEMORY_PROPOSE
            ]
            assert len(propose_entries) >= 1, (
                f"turn-end hook 应 dispatch 至少 1 次 MEMORY_PROPOSE，"
                f"实际 {len(propose_entries)} 次"
            )

            method, request, propose_result = propose_entries[0]
            assert method == "route_from_runtime_loop", (
                f"MEMORY_PROPOSE 必须走 route_from_runtime_loop() 路径，"
                f"实际 {method!r}"
            )

            # L3 evidence 验证
            evidence = dict(propose_result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
                f"MEMORY_PROPOSE turn-end dispatch 应达到 L3，"
                f"实际 {evidence.get('evidence_level')!r}"
            )
            assert evidence.get("dispatcher_origin") == "runtime_loop"
            assert evidence.get("runtime_loop_invoked") is True
            assert evidence.get("core_entrypoint") == "core.chat"
            assert evidence.get("runtime_hook_name") == "loop.turn_end"
            assert evidence.get("target_module") == "MemoryStore"
            assert evidence.get("target_catalog_allowed") is True

            # payload 验证：confirmed proposal 应成功 retain
            payload = dict(propose_result.payload)
            assert payload.get("disposition") == "retain", (
                f"confirmed proposal → disposition 应为 'retain'，"
                f"实际 {payload.get('disposition')!r}"
            )
            assert payload.get("stored") is True
            assert payload.get("store_backend") == "in_memory"
            assert payload.get("proposal_id") == candidate["proposal_id"]

            # 验证队列已清空
            assert len(core.state.task.pending_retain_proposals) == 0, (
                "MEMORY_PROPOSE dispatch 后 pending_retain_proposals 应被清空"
            )
        finally:
            # 清理：确保不遗留测试数据污染其他测试
            core.state.task.pending_retain_proposals.clear()

    def test_t2_empty_queue_no_memory_propose_dispatch(self):
        """T2: pending_retain_proposals 为空 → 不 dispatch MEMORY_PROPOSE。"""
        from agent import core
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_propose_dispatcher()
        spy = _ProposeSpy(real_dispatcher)

        # 确保队列为空
        core.state.task.pending_retain_proposals.clear()

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        propose_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.MEMORY_PROPOSE
        ]
        assert len(propose_entries) == 0, (
            f"空队列不应 dispatch MEMORY_PROPOSE，实际 {len(propose_entries)} 次"
        )

    def test_t3_rejected_confirmation_not_retained(self):
        """T3: confirmation_result="rejected" → dispatch 但不写入 store。"""
        from agent import core
        from agent.core import chat
        from agent.memory_store import InMemoryMemoryStore
        from agent.provider.fake_provider import FakeProvider

        store = InMemoryMemoryStore()
        real_dispatcher = _build_propose_dispatcher(store=store)
        spy = _ProposeSpy(real_dispatcher)

        candidate = _make_candidate_payload()
        candidate["confirmation_result"] = "rejected"
        core.state.task.pending_retain_proposals.append(candidate)

        try:
            result = chat(
                "hello",
                provider=FakeProvider(),
                runtime_action_dispatcher=spy,
            )

            assert isinstance(result, str)

            propose_entries = [
                (m, r, res) for m, r, res in spy.captured
                if r.action_type == RuntimeActionType.MEMORY_PROPOSE
            ]
            assert len(propose_entries) >= 1

            _, _, propose_result = propose_entries[0]
            payload = dict(propose_result.payload)
            assert payload.get("disposition") == "not_retained", (
                f"rejected → disposition 应为 'not_retained'，"
                f"实际 {payload.get('disposition')!r}"
            )
            assert payload.get("stored") is False

            assert len(core.state.task.pending_retain_proposals) == 0
        finally:
            core.state.task.pending_retain_proposals.clear()


# ═══════════════════════════════════════════════════════════════════════
# T4: no real API or env access
# ═══════════════════════════════════════════════════════════════════════


class TestNoRealAPIOrEnv:
    def test_t4_no_real_api_or_env_access(self):
        """T4: MEMORY_PROPOSE L3 测试不读取真实 API / secret / env。"""
        from agent import core
        from agent.core import chat
        from agent.memory_store import InMemoryMemoryStore
        from agent.provider.fake_provider import FakeProvider

        store = InMemoryMemoryStore()
        real_dispatcher = _build_propose_dispatcher(store=store)
        spy = _ProposeSpy(real_dispatcher)

        candidate = _make_candidate_payload()
        core.state.task.pending_retain_proposals.append(candidate)

        try:
            result = chat(
                "hello",
                provider=FakeProvider(),
                runtime_action_dispatcher=spy,
            )

            assert isinstance(result, str)

            propose_entries = [
                (m, r, res) for m, r, res in spy.captured
                if r.action_type == RuntimeActionType.MEMORY_PROPOSE
            ]
            assert len(propose_entries) >= 1

            _, _, propose_result = propose_entries[0]
            evidence = dict(propose_result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
            assert evidence.get("no_silent_retain") is True
            assert evidence.get("real_episodes_read") is False
            assert evidence.get("external_side_effects") is False
            # store_backend 在 payload 中（执行结果），不在 evidence 中（证据元数据）
            payload = dict(propose_result.payload)
            assert payload.get("store_backend") == "in_memory"
        finally:
            core.state.task.pending_retain_proposals.clear()
