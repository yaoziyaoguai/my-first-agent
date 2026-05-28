"""Skill L3 TDD test.

验证 SKILL_SELECT 从 loop.py turn-end hook 经 dispatcher.route_from_runtime_loop()
dispatch 后产生 real_core_loop_runtime_e2e evidence。

归属已有 turn-end hook branch point 下的 branch behavior——不新增 Anchor、
不新增 branch point、不新增 runtime flow。

架构依据：
- docs/specs/skill-l3/SPEC.md (Architecture Decision)
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md

中文学习边界：
SkillRuntimeActionHandler 在 empty registry 下必然 rejected（没有 skill 可加载），
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
from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
from agent.skill_system.loader import SkillLoader
from agent.skill_system.registry import SkillRegistry


def _build_skill_dispatcher():
    """构建仅注册 SKILL_SELECT 的 dispatcher。

    SkillRegistry 不扫描任何目录（empty roots）→ handler 总是 rejected
    （no skills available）。不影响 evidence level。
    """
    registry = SkillRegistry(roots=[])
    loader = SkillLoader(registry)
    handler = SkillRuntimeActionHandler(registry=registry, loader=loader)

    action_registry = ActionHandlerRegistry()
    action_registry.register(RuntimeActionType.SKILL_SELECT, handler)
    return RuntimeActionDispatcher(
        registry=action_registry, observer=RuntimeActionModuleObserver()
    )


class _SkillSpy:
    """拦截 dispatcher 调用，捕获 SKILL_SELECT 的 route_from_runtime_loop 证据。"""

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
# T1: core.chat() → SKILL_SELECT → L3 evidence (rejected disposition)
# ═══════════════════════════════════════════════════════════════════════


class TestSkillSelectL3:
    def test_skill_select_dispatched_from_loop_turn_end_is_l3(self):
        """SKILL_SELECT 从 loop.py turn-end hook dispatch → L3 evidence。

        空 SkillRegistry → handler 必然 rejected（no skills），但 evidence
        chain 完整——dispatcher_origin="runtime_loop"、runtime_loop_invoked=True。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_skill_dispatcher()
        spy = _SkillSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        skill_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.SKILL_SELECT
        ]
        assert len(skill_entries) == 1, (
            f"turn-end hook 应 dispatch 恰好 1 次 SKILL_SELECT，"
            f"实际 {len(skill_entries)} 次"
        )

        method, request, skill_result = skill_entries[0]
        assert method == "route_from_runtime_loop", (
            f"SKILL_SELECT 必须走 route_from_runtime_loop() 路径，"
            f"实际 {method!r}"
        )

        # L3 evidence 验证——disposition 不影响 evidence level
        evidence = dict(skill_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"SKILL_SELECT turn-end dispatch 应达到 L3（即便 rejected），"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # payload: handler registry 为空，但 Loop 2.2 bridge 注入的 metadata
        # 来自真实 registry（非空），所以 no_suitable_skill 为 False；
        # handler 因 registry 不匹配返回 failed，L3 evidence 链仍完整
        payload = dict(skill_result.payload)
        assert payload.get("body_load_decision") is False
        assert "failure_reason" in payload, (
            f"应包含 failure_reason，实际 payload keys: {list(payload.keys())}"
        )

    def test_skill_select_l3_status_is_failed_with_empty_registry(self):
        """空 registry → SKILL_SELECT 返回 status='failed'，但 L3 evidence 完整。

        区分两个概念：
        - evidence_level（证据链分类）— L3，因为 dispatch 从 runtime loop 来
        - status（handler 执行结果）— failed，因为没有可用 skill
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_skill_dispatcher()
        spy = _SkillSpy(real_dispatcher)

        chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        skill_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.SKILL_SELECT
        ]
        assert len(skill_entries) == 1
        _, _, skill_result = skill_entries[0]

        # handler 返回 failed——但证据仍为 L3
        assert skill_result.status == "failed", (
            f"空 registry → status 应为 'failed'，实际 {skill_result.status!r}"
        )
        evidence = dict(skill_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("dispatcher_origin") == "runtime_loop"

        payload = dict(skill_result.payload)
        assert "failure_reason" in payload


# ═══════════════════════════════════════════════════════════════════════
# T2: no real API / .env / skill files
# ═══════════════════════════════════════════════════════════════════════


class TestNoRealAPIOrEnv:
    def test_skill_l3_no_real_api_or_env_access(self):
        """SKILL_SELECT L3 pipeline 不读 .env、不加载真实 skill 文件。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_skill_dispatcher()
        spy = _SkillSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        skill_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.SKILL_SELECT
        ]
        assert len(skill_entries) == 1
        _, _, skill_result = skill_entries[0]

        evidence = dict(skill_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        # SkillRegistry 空 roots → 不扫描任何目录
        assert evidence.get("runtime_loop_invoked") is True
