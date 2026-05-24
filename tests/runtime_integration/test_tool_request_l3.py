"""TOOL_REQUEST L3 evidence tests.

Follows the same Architecture Extension Loop pattern as Skill L3 and SubAgent L3:
turn-end hook dispatch → ToolGateHandler.handle() → early-return for tool.request →
invoke_registered_target("ToolRegistry", "lookup_and_risk_check") → context.failed()
→ real_core_loop_runtime_e2e evidence.

All 3 tests use empty ToolGateHandler — no real tools are executed.
"""

from __future__ import annotations

from typing import Any

from agent.runtime_integration.dispatcher import ActionHandlerRegistry, RuntimeActionDispatcher
from agent.runtime_integration.evidence import (
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
    is_runtime_e2e_evidence,
)
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from agent.runtime_integration.tool_gate import ToolGateHandler


def _build_tool_request_dispatcher() -> RuntimeActionDispatcher:
    """构建仅注册 TOOL_REQUEST handler 的最小 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.TOOL_REQUEST, ToolGateHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


class _ToolRequestSpy:
    """记录 dispatcher 的 (method, request, result) 调用三元组。"""

    def __init__(self, dispatcher: RuntimeActionDispatcher) -> None:
        self.calls: list[tuple[str, RuntimeActionRequest, Any]] = []
        self._original = dispatcher.route_from_runtime_loop
        dispatcher.route_from_runtime_loop = self._wrap  # type: ignore[method-assign]

    def _wrap(self, request: RuntimeActionRequest, **kwargs: Any) -> Any:
        result = self._original(request, **kwargs)
        self.calls.append(("route_from_runtime_loop", request, result))
        return result


class TestToolRequestL3:
    """TOOL_REQUEST L3 evidence from loop turn-end dispatch."""

    def test_tool_request_dispatched_from_loop_turn_end_is_l3(self):
        """turn-end hook 分发的 tool.request 返回 real_core_loop_runtime_e2e 证据。"""
        dispatcher = _build_tool_request_dispatcher()
        spy = _ToolRequestSpy(dispatcher)

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_REQUEST,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        )
        result = dispatcher.route_from_runtime_loop(request)

        assert len(spy.calls) == 1
        method, captured_request, captured_result = spy.calls[0]
        assert method == "route_from_runtime_loop"
        assert captured_result is result
        assert captured_result.evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert is_runtime_e2e_evidence(captured_result.evidence)

    def test_tool_request_l3_status_is_failed_with_empty_tool_name(self):
        """空 tool_name 的 tool.request 返回 status=failed 且 disposition 正确。"""
        dispatcher = _build_tool_request_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_REQUEST,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        )
        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "failed"
        evidence = result.evidence
        assert evidence.get("handler_name") == "ToolGateHandler"
        assert evidence.get("target_module") == "ToolRegistry"
        assert evidence.get("no_tool_requested") is True
        # 不应包含 runtime_e2e_disqualified_reason
        assert "runtime_e2e_disqualified_reason" not in evidence


class TestNoRealAPIOrEnv:
    """确保 TOOL_REQUEST L3 不调用真实 API 或读取环境变量。"""

    def test_tool_request_l3_no_real_api_or_env_access(self):
        """tool.request L3 路径不调用真实 API、不读取 .env。"""
        dispatcher = _build_tool_request_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.TOOL_REQUEST,
            source="core_loop",
            parent_trace_id="",
            payload={
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
            },
        )
        result = dispatcher.route_from_runtime_loop(request)

        assert result.evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert result.status == "failed"
        assert is_runtime_e2e_evidence(result.evidence)
