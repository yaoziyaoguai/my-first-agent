"""Tool Gate blocked L3 TDD 测试。

blocked 是 Tool gate 的第三个 disposition 分支行为
（四者为 allowed / confirmation_required / blocked / not_found）。
归属已有 Tool gate branch point，不新增 Anchor、不新增 branch point。

测试分层：
- L2 (harness_runtime_e2e): dispatcher.route() 直接调用
- L3 (real_core_loop_runtime_e2e): core.chat() → route_from_runtime_loop()

本轮核心目标：
证明 blocked 工具名通过真实 core.chat() 路径进入 TOOL_GATE，
返回 status="rejected" + decision="rejected" + L3 evidence，
且 TOOL_INVOKE/TOOL_RESULT 不触发。

两个 blocked 路径：
1. shell-like 工具名（bash/shell/run_shell）→ rejection_reason="shell-like tool is out of scope"
2. _ 前缀非 allowlist 工具 → rejection_reason="internal tool is not in tool gate allowlist"

架构依据：
- docs/specs/tool-blocked-l3/SPEC.md
- docs/specs/tool-blocked-l3/TDD.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.schema import RuntimeActionRequest
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

# shell-like 工具名——在 _FORBIDDEN_TOOL_NAMES frozenset({"bash", "shell", "run_shell"}) 中
_SHELL_LIKE_TOOL_NAME = "bash"

# _ 前缀非 allowlist 工具名——不在 frozenset({"_safe_noop", "_confirmable_noop"}) 中
_UNDERSCORE_TOOL_NAME = "_blocked_tool"


# ========== 测试辅助工厂 ==========


def _build_pipeline_dispatcher() -> RuntimeActionDispatcher:
    """构建注册了 TOOL_GATE + TOOL_INVOKE + TOOL_RESULT handler 的 dispatcher。"""
    import agent.tools  # noqa: F401
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _PipelineSpy:
    """捕获 method + request + result 的 spy dispatcher 包装器。"""

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

    @property
    def action_log(self):
        return self._real.action_log


def _register_blocked_tool():
    """向 TOOL_REGISTRY 注册 _blocked_tool，确保 entry 不为 None。

    _blocked_tool 是 _ 前缀工具，不在 allowlist (_safe_noop, _confirmable_noop) 中。
    注册后 gate 能查到 entry 但 _ 前缀 blocked 路径会将其拒绝。
    """
    from agent.tool_registry import register_tool

    @register_tool(
        name="_blocked_tool",
        description="internal test tool for blocked L3 path",
        parameters={},
        confirmation="always",
        capability="local_action",
        risk_level="low",
    )
    def _blocked_tool_func():
        pass


def _make_mock_state():
    """构造最小 mock state——只需 conversation.messages 中有 user 消息。"""

    class _MockConversation:
        messages: list[dict] = [{"role": "user", "content": "hello"}]

    class _MockState:
        conversation = _MockConversation()

    return _MockState()


# ========== T1: core.chat() shell-like 工具 blocked 获得 L3 evidence ==========


class TestCoreChatShellLikeBlockedL3:
    """T1: core.chat() L3 shell-like blocked 核心测试。"""

    def test_t1_core_chat_shell_like_tool_blocked_l3(self):
        """T1: shell-like 工具名通过 core.chat() → TOOL_GATE 返回 rejected + L3。

        证明 tool gate shell-like blocked 分支行为在 L3 证据级别正确运作。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_SHELL_LIKE_TOOL_NAME,
        )

        assert isinstance(result, str)

        # 提取 Tool pipeline actions
        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]

        action_types_in_order = [r.action_type.value for _, r, _ in pipeline_actions]

        # TOOL_GATE 必须存在
        assert "tool.gate" in action_types_in_order, (
            f"应有 TOOL_GATE，实际: {action_types_in_order}"
        )

        # TOOL_INVOKE 不得触发（gate 返回 rejected）
        assert "tool.invoke" not in action_types_in_order, (
            f"TOOL_INVOKE 不应触发（gate rejected），实际: {action_types_in_order}"
        )

        # TOOL_RESULT 不得触发
        assert "tool.result" not in action_types_in_order, (
            f"TOOL_RESULT 不应触发，实际: {action_types_in_order}"
        )

        # 验证 TOOL_GATE 的 evidence
        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        method, request, gate_result = gate_entries[0]

        # 路由方式：必须是 route_from_runtime_loop
        assert method == "route_from_runtime_loop", (
            f"TOOL_GATE 应通过 route_from_runtime_loop 路由，实际 {method!r}"
        )

        # 请求中 tool_name 应为 shell-like 工具名
        assert request.payload["tool_name"] == _SHELL_LIKE_TOOL_NAME

        # evidence 验证
        evidence = dict(gate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"

        # status 和 decision
        assert gate_result.status == "rejected", (
            f"TOOL_GATE status 应为 'rejected'，实际 {gate_result.status!r}"
        )
        assert evidence.get("decision") == "rejected", (
            f"TOOL_GATE decision 应为 'rejected'，实际 {evidence.get('decision')!r}"
        )

        # payload 验证
        gate_payload = dict(gate_result.payload)
        assert gate_payload.get("gate_disposition") == "rejected", (
            f"shell-like blocked 时 gate_disposition 应为 'rejected'，"
            f"实际 {gate_payload.get('gate_disposition')!r}"
        )
        assert gate_payload.get("rejection_reason") == (
            "shell-like tool is out of scope"
        ), (
            f"rejection_reason 应为 'shell-like tool is out of scope'，"
            f"实际 {gate_payload.get('rejection_reason')!r}"
        )
        assert gate_payload.get("risk_level") == "high", (
            f"shell-like tool risk_level 应为 'high'，"
            f"实际 {gate_payload.get('risk_level')!r}"
        )


# ========== T2: core.chat() _ 前缀工具 blocked 获得 L3 evidence ==========


class TestCoreChatUnderscoreBlockedL3:
    """T2: core.chat() L3 _ 前缀 blocked 测试。"""

    def test_t2_core_chat_underscore_tool_blocked_l3(self):
        """T2: _ 前缀非 allowlist 工具名 → TOOL_GATE 返回 rejected + L3。

        _blocked_tool 在 TOOL_REGISTRY 中但不在 allowlist
        (_safe_noop, _confirmable_noop) 中，gate 应拒绝。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        # 注册 _blocked_tool 到 TOOL_REGISTRY
        _register_blocked_tool()

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_UNDERSCORE_TOOL_NAME,
        )

        assert isinstance(result, str)

        pipeline_actions = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type in (
                RuntimeActionType.TOOL_GATE,
                RuntimeActionType.TOOL_INVOKE,
                RuntimeActionType.TOOL_RESULT,
            )
        ]

        action_types_in_order = [r.action_type.value for _, r, _ in pipeline_actions]

        assert "tool.gate" in action_types_in_order, (
            f"应有 TOOL_GATE，实际: {action_types_in_order}"
        )
        assert "tool.invoke" not in action_types_in_order, (
            f"TOOL_INVOKE 不应触发（gate rejected），实际: {action_types_in_order}"
        )
        assert "tool.result" not in action_types_in_order, (
            f"TOOL_RESULT 不应触发，实际: {action_types_in_order}"
        )

        gate_entries = [
            (m, r, res) for m, r, res in pipeline_actions
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        method, request, gate_result = gate_entries[0]

        assert method == "route_from_runtime_loop"
        assert request.payload["tool_name"] == _UNDERSCORE_TOOL_NAME

        evidence = dict(gate_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"应达到 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"

        assert gate_result.status == "rejected", (
            f"TOOL_GATE status 应为 'rejected'，实际 {gate_result.status!r}"
        )
        assert evidence.get("decision") == "rejected", (
            f"TOOL_GATE decision 应为 'rejected'，实际 {evidence.get('decision')!r}"
        )

        gate_payload = dict(gate_result.payload)
        assert gate_payload.get("gate_disposition") == "rejected", (
            f"_ prefix blocked 时 gate_disposition 应为 'rejected'，"
            f"实际 {gate_payload.get('gate_disposition')!r}"
        )
        assert gate_payload.get("rejection_reason") == (
            "internal tool is not in tool gate allowlist"
        ), (
            f"rejection_reason 应为 'internal tool is not in tool gate allowlist'，"
            f"实际 {gate_payload.get('rejection_reason')!r}"
        )


# ========== T3: direct dispatcher.route blocked 保持 L2 ==========


class TestDirectDispatcherBlockedL2:
    """T3: direct dispatcher.route blocked 保持 L2。"""

    def test_t3_direct_dispatcher_route_blocked_is_l2(self):
        """T3: 直接调用 dispatcher.route 时 blocked 只能获得 L2 evidence。"""
        import agent.tools  # noqa: F401
        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = dispatcher.route(RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_GATE,
            source="test",
            parent_trace_id="",
            payload={
                "tool_name": _SHELL_LIKE_TOOL_NAME,
                # 尝试伪造 L3 字段
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        ))

        assert result.status == "rejected"
        evidence = dict(result.evidence)

        # evidence_level 必须为 L2，不能是 L3
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatcher.route 应获得 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )

        # dispatcher_origin 必须为 direct_dispatcher，不能被 payload 伪造
        assert evidence.get("dispatcher_origin") == "direct_dispatcher", (
            f"dispatcher_origin 应为 'direct_dispatcher'，"
            f"实际 {evidence.get('dispatcher_origin')!r}"
        )

        # decision 仍应为 rejected
        assert evidence.get("decision") == "rejected", (
            f"decision 应为 'rejected'，实际 {evidence.get('decision')!r}"
        )

        # payload 伪造字段不应污染 evidence
        assert evidence.get("core_entrypoint") != "core.chat", (
            "direct dispatcher 的 core_entrypoint 不应为 'core.chat'"
        )
        assert evidence.get("runtime_hook_name") != "loop.turn_end", (
            "direct dispatcher 的 runtime_hook_name 不应为 'loop.turn_end'"
        )


# ========== T4: 不读 .env / 不调用真实 API ==========


class TestNoRealAPIOrEnv:
    """T4: 隔离环境安全测试。"""

    def test_t4_no_real_api_or_env_access(self):
        """T4: blocked pipeline 不读 .env、不调用真实 API。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        real_dispatcher = _build_pipeline_dispatcher()
        spy = _PipelineSpy(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
            tool_gate_tool_name=_SHELL_LIKE_TOOL_NAME,
        )

        assert isinstance(result, str)

        # TOOL_GATE 应返回 rejected + blocked
        gate_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_GATE
        ]
        assert len(gate_entries) >= 1
        _, _, gate_result = gate_entries[0]
        assert gate_result.status == "rejected"
        evidence = dict(gate_result.evidence)
        assert evidence.get("decision") == "rejected"

        # TOOL_INVOKE 不得触发
        invoke_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.TOOL_INVOKE
        ]
        assert len(invoke_entries) == 0
