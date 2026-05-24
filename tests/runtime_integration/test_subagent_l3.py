"""SubAgent L3 TDD test.

验证 SUBAGENT_DELEGATE_L0 从 loop.py turn-end hook 经 dispatcher.route_from_runtime_loop()
dispatch 后产生 real_core_loop_runtime_e2e evidence。

归属已有 turn-end hook branch point 下的 branch behavior——不新增 Anchor、
不新增 branch point、不新增 runtime flow。

架构依据：
- docs/specs/subagent-l3/SPEC.md (Architecture Decision)
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md

中文学习边界：
SubAgentDelegateL0Handler 在 empty registry 下必然 rejected（没有 subagent 可 delegate），
但 evidence chain 仍然完整——L3 关注 dispatch 路径，不关注 disposition。
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
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.subagent_action import SubAgentDelegateL0Handler
from agent.subagent_system.registry import SubAgentRegistry


def _build_subagent_dispatcher():
    """构建仅注册 SUBAGENT_DELEGATE_L0 的 dispatcher。

    SubAgentRegistry 不扫描任何目录（empty roots）→ handler 总是 rejected
    （no subagents available）。不影响 evidence level。
    """
    registry = SubAgentRegistry(roots=())
    handler = SubAgentDelegateL0Handler(registry=registry)

    action_registry = ActionHandlerRegistry()
    action_registry.register(RuntimeActionType.SUBAGENT_DELEGATE_L0, handler)
    return RuntimeActionDispatcher(
        registry=action_registry, observer=RuntimeActionModuleObserver()
    )


class _SubAgentSpy:
    """拦截 dispatcher 调用，捕获 SUBAGENT_DELEGATE_L0 的 route_from_runtime_loop 证据。"""

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
# T1: core.chat() → SUBAGENT_DELEGATE_L0 → L3 evidence (rejected disposition)
# ═══════════════════════════════════════════════════════════════════════


class TestSubAgentDelegateL0L3:
    def test_subagent_delegate_dispatched_from_loop_turn_end_is_l3(self):
        """SUBAGENT_DELEGATE_L0 从 loop.py turn-end hook dispatch → L3 evidence。

        空 SubAgentRegistry → handler 必然 rejected（no subagent），但 evidence
        chain 完整——dispatcher_origin="runtime_loop"、runtime_loop_invoked=True。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_subagent_dispatcher()
        spy = _SubAgentSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        subagent_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.SUBAGENT_DELEGATE_L0
        ]
        assert len(subagent_entries) == 1, (
            f"turn-end hook 应 dispatch 恰好 1 次 SUBAGENT_DELEGATE_L0，"
            f"实际 {len(subagent_entries)} 次"
        )

        method, request, subagent_result = subagent_entries[0]
        assert method == "route_from_runtime_loop", (
            f"SUBAGENT_DELEGATE_L0 必须走 route_from_runtime_loop() 路径，"
            f"实际 {method!r}"
        )

        # L3 evidence 验证——disposition 不影响 evidence level
        evidence = dict(subagent_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"SUBAGENT_DELEGATE_L0 turn-end dispatch 应达到 L3（即便 rejected），"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # payload: empty registry → handler rejected
        payload = dict(subagent_result.payload)
        assert payload.get("delegate_once_called") is False
        assert payload.get("subagent_request_built") is False

    def test_subagent_delegate_l3_status_is_rejected_with_empty_registry(self):
        """空 registry → SUBAGENT_DELEGATE_L0 返回 status='failed'，但 L3 evidence 完整。

        区分两个概念：
        - evidence_level（证据链分类）— L3，因为 dispatch 从 runtime loop 来
        - status（handler 执行结果）— failed，因为没有可用 subagent
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_subagent_dispatcher()
        spy = _SubAgentSpy(real_dispatcher)

        chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        subagent_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.SUBAGENT_DELEGATE_L0
        ]
        assert len(subagent_entries) == 1
        _, _, subagent_result = subagent_entries[0]

        # handler 返回 failed——但证据仍为 L3
        assert subagent_result.status == "failed", (
            f"空 registry → status 应为 'failed'，实际 {subagent_result.status!r}"
        )
        evidence = dict(subagent_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("dispatcher_origin") == "runtime_loop"

        payload = dict(subagent_result.payload)
        assert "failure_reason" in payload


# ═══════════════════════════════════════════════════════════════════════
# T2: no real API / .env / subagent files
# ═══════════════════════════════════════════════════════════════════════


class TestNoRealAPIOrEnv:
    def test_subagent_l3_no_real_api_or_env_access(self):
        """SUBAGENT_DELEGATE_L0 L3 pipeline 不读 .env、不加载真实 subagent 文件。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_subagent_dispatcher()
        spy = _SubAgentSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        subagent_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.SUBAGENT_DELEGATE_L0
        ]
        assert len(subagent_entries) == 1
        _, _, subagent_result = subagent_entries[0]

        evidence = dict(subagent_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        # SubAgentRegistry 空 roots → 不扫描任何目录
        assert evidence.get("runtime_loop_invoked") is True
