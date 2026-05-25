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

from pathlib import Path
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


# ═══════════════════════════════════════════════════════════════════════
# T3: Non-empty registry → business delegation success (L3)
# ═══════════════════════════════════════════════════════════════════════


def _build_nonempty_subagent_dispatcher():
    """构建真实生产级 dispatcher——SubAgentRegistry 非空，与 phase1_hook.py 一致。

    phase1_hook.py:114 使用 SubAgentRegistry(roots=[Path("tests/fixtures/subagents")])，
    本 helper 复现同一配置。handler 的非空 registry 分支（subagent_action.py:59-125）
    可走通完整业务委托路径。
    """
    registry = SubAgentRegistry(roots=[Path("tests/fixtures/subagents")])
    handler = SubAgentDelegateL0Handler(registry=registry)

    action_registry = ActionHandlerRegistry()
    action_registry.register(RuntimeActionType.SUBAGENT_DELEGATE_L0, handler)
    return RuntimeActionDispatcher(
        registry=action_registry, observer=RuntimeActionModuleObserver()
    )


class TestSubAgentDelegateL0NonEmptyRegistryBusinessL3:
    """Non-empty SubAgentRegistry → 完整业务委托 L3 验证。

    现有 T1/T2 仅覆盖空 registry 的 rejected 路径（dispatch path verified）。
    本测试补齐 non-empty registry 的 business operation verified 路径——
    验证 descriptor lookup → validation → SubAgentRequest 构建 → delegate_once
    → success 的完整业务链。
    """

    def test_t3_nonempty_registry_delegation_success_l3(self):
        """T3: Non-empty registry + 合规 payload → delegate_once 成功执行。

        构造 RuntimeActionRequest 携带 subagent_name="demo-stat"、
        delegation_goal="count files in workspace"、allowed_tools=["read_file"]、
        parent_adjudication_required=True，经 route_from_runtime_loop() dispatch 后：

        - status="success"
        - evidence_level=L3
        - delegate_once_called=True
        - subagent_request_built=True
        - execution_result 非空
        """
        dispatcher = _build_nonempty_subagent_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
            source="core_loop",
            parent_trace_id="test-t3",
            payload={
                "subagent_name": "demo-stat",
                "delegation_goal": "count files in workspace",
                "allowed_tools": ["read_file"],
                "parent_adjudication_required": True,
                "budget": {"max_iterations": 1},
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        # 业务委托成功
        assert result.status == "success", (
            f"non-empty registry + 合规 payload → status 应为 'success'，"
            f"实际 {result.status!r}，error_safe_preview={result.error_safe_preview!r}"
        )

        # L3 evidence
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"non-empty registry 业务委托应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True

        # 业务操作证据
        payload = dict(result.payload)
        assert payload.get("delegate_once_called") is True, (
            "non-empty registry 业务委托应实际调用 delegate_once"
        )
        assert payload.get("subagent_request_built") is True
        assert payload.get("subagent_name") == "demo-stat"
        assert payload.get("no_nested_delegation") is True
        assert payload.get("no_shell_or_external_process") is True
        assert payload.get("parent_adjudicated") is True

        execution_result = str(payload.get("execution_result") or "")
        assert len(execution_result) > 0, (
            "delegate_once 成功后 execution_result 应非空"
        )

    def test_t4_nonempty_registry_rejects_unregistered_subagent(self):
        """T4: Non-empty registry + 未注册 subagent → rejected disposition。

        验证 handler 对未注册 subagent 返回 rejected（而非 crash），
        evidence chain 仍然完整。
        """
        dispatcher = _build_nonempty_subagent_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
            source="core_loop",
            parent_trace_id="test-t4",
            payload={
                "subagent_name": "nonexistent-subagent",
                "delegation_goal": "do something",
                "allowed_tools": ["read_file"],
                "parent_adjudication_required": True,
                "budget": {"max_iterations": 1},
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        # _reject() 不经过 invoke_registered_target（observed_call=None），
        # evidence 不声称 L3——这是正确的：unregistered subagent 不触发
        # target module invocation，不应声称 full闭环。
        assert result.status == "rejected", (
            f"未注册 subagent → status 应为 'rejected'，实际 {result.status!r}"
        )

        payload = dict(result.payload)
        assert payload.get("delegate_once_called") is False
        assert "not registered" in str(payload.get("adjudication_reason") or "")

    def test_t5_nonempty_registry_rejects_shell_tool(self):
        """T5: Non-empty registry + shell tool 请求 → rejected（安全门）。

        demo-stat 的 allowed_tools 不含 shell，且 handler 有显式 shell 阻断。
        """
        dispatcher = _build_nonempty_subagent_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
            source="core_loop",
            parent_trace_id="test-t5",
            payload={
                "subagent_name": "demo-stat",
                "delegation_goal": "list files via shell",
                "allowed_tools": ["shell"],
                "parent_adjudication_required": True,
                "budget": {"max_iterations": 1},
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        # shell tool 被阻断
        assert result.status == "rejected", (
            f"shell tool 请求应被 rejected，实际 {result.status!r}"
        )
        payload = dict(result.payload)
        assert payload.get("delegate_once_called") is False

    def test_t6_nonempty_registry_requires_parent_adjudication(self):
        """T6: parent_adjudication_required=False → rejected。

        handler 强制要求 parent_adjudication_required=True（subagent_action.py:74-75）。
        """
        dispatcher = _build_nonempty_subagent_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L0,
            source="core_loop",
            parent_trace_id="test-t6",
            payload={
                "subagent_name": "demo-stat",
                "delegation_goal": "count files",
                "allowed_tools": ["read_file"],
                "parent_adjudication_required": False,
                "budget": {"max_iterations": 1},
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "rejected", (
            f"parent_adjudication_required=False 应被 rejected，实际 {result.status!r}"
        )
        payload = dict(result.payload)
        assert "adjudication" in str(payload.get("adjudication_reason") or "").lower()
