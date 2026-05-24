"""Streaming L3 测试。

验证 core.chat() → model_call (streaming via call_model()) → turn-end hook →
STREAMING_PROVIDER_CALL dispatch 的完整 evidence chain。

call_model() 已支持 streaming（model_call.py）：当 provider.supports_streaming=True 时，
自动调用 provider.stream() 并收集事件。事件通过 LoopDependencies.streaming_events
共享列表传入 turn-end hook，由 STREAMING_PROVIDER_CALL dispatch 处理。

测试分层：
- L1/L2: 已有 test_runtime_action_handlers.py / test_runtime_action_contract.py 覆盖
- L3 (real_core_loop_runtime_e2e): core.chat() → STREAMING_PROVIDER_CALL dispatch via turn-end hook

架构依据：
- docs/specs/streaming-l3/SPEC.md
- docs/specs/streaming-l3/TDD.md
"""

from __future__ import annotations

from typing import Any

import pytest

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
from agent.runtime_integration.streaming_provider import StreamingProviderCallHandler


@pytest.fixture(autouse=True)
def _save_restore_global_state():
    """每次测试前后保存/恢复模块级 state.conversation.messages，防止消息累积污染其他测试。"""
    from agent.core import state

    saved_messages = list(state.conversation.messages)
    yield
    state.conversation.messages[:] = saved_messages


def _build_streaming_dispatcher():
    """构建仅注册 STREAMING_PROVIDER_CALL 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.STREAMING_PROVIDER_CALL,
        StreamingProviderCallHandler(),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class _SpyDispatcher:
    """拦截 dispatcher 调用，捕获 STREAMING_PROVIDER_CALL 的 route_from_runtime_loop 证据。"""

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
# T1-T4: 需要 supports_streaming=True 的 provider。
# FakeProvider 默认 supports_streaming=False（tool_use 走 create() 路径），
# streaming L3 测试显式使用 subclass 开启 streaming。
# ═══════════════════════════════════════════════════════════════════════


class _StreamingFakeProvider:
    """开启 streaming 的 FakeProvider 子类，用于 streaming L3 测试。

    FakeProvider 默认 supports_streaming=False 以支持 tool_use (create() 路径)。
    streaming L3 测试需要 supports_streaming=True 以触发 STREAMING_PROVIDER_CALL dispatch。
    """

    def __new__(cls):
        from agent.provider.fake_provider import FakeProvider

        instance = FakeProvider()
        instance.supports_streaming = True
        return instance


# ═══════════════════════════════════════════════════════════════════════
# T1: core.chat() → STREAMING_PROVIDER_CALL dispatch → L3 evidence
# ═══════════════════════════════════════════════════════════════════════


class TestStreamingL3:
    def test_t1_streaming_provider_call_dispatched_from_turn_end(self):
        """T1: turn-end hook dispatch STREAMING_PROVIDER_CALL with L3 evidence。

        call_model() 对支持 streaming 的 provider 自动使用 streaming，事件通过
        dependencies 传入 turn-end hook。handler 调用 StreamingProtocol.collect_stream_response()
        产生完整 target_module_proof，达到 L3。
        """
        from agent.core import chat

        real_dispatcher = _build_streaming_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=_StreamingFakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        streaming_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_PROVIDER_CALL
        ]
        assert len(streaming_entries) >= 1, (
            f"turn-end hook 应 dispatch 至少 1 次 STREAMING_PROVIDER_CALL，"
            f"实际 {len(streaming_entries)} 次"
        )

        method, request, streaming_result = streaming_entries[0]
        assert method == "route_from_runtime_loop", (
            f"STREAMING_PROVIDER_CALL 必须走 route_from_runtime_loop() 路径，"
            f"实际 {method!r}"
        )

        # L3 evidence 验证
        evidence = dict(streaming_result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"STREAMING_PROVIDER_CALL turn-end dispatch 应达到 L3，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("core_entrypoint") == "core.chat"
        assert evidence.get("runtime_hook_name") == "loop.turn_end"
        assert evidence.get("target_module") == "StreamingProtocol"
        assert evidence.get("target_catalog_allowed") is True
        assert evidence.get("module_invoked") is True

        # handler 正常收集流式事件
        payload = dict(streaming_result.payload)
        assert payload.get("events_received", 0) > 0, (
            f"FakeProvider stream() 应产出事件，实际 events_received={payload.get('events_received')}"
        )
        assert payload.get("final_event_received") is True
        assert payload.get("text_delta_event_received") is True

    def test_t2_provider_supports_streaming_in_payload(self):
        """T2: payload 正确传递 provider streaming capability。

        _StreamingFakeProvider 声明 supports_streaming=True，turn-end hook 应读取并传递。
        """
        from agent.core import chat

        real_dispatcher = _build_streaming_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        chat("hello", provider=_StreamingFakeProvider(), runtime_action_dispatcher=spy)

        streaming_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_PROVIDER_CALL
        ]
        assert len(streaming_entries) >= 1

        _, request, _ = streaming_entries[0]
        payload = dict(request.payload)
        assert payload.get("provider_supports_streaming") is True, (
            f"_StreamingFakeProvider.supports_streaming=True 应传递到 payload，"
            f"实际 {payload.get('provider_supports_streaming')!r}"
        )

    def test_t3_streaming_events_serialized_in_payload(self):
        """T3: 流式事件已正确序列化到 payload 中。

        call_model() 收集 ProviderStreamEvent 对象，turn-end hook 序列化为
        JSON-safe dict 后传入 handler。
        """
        from agent.core import chat

        real_dispatcher = _build_streaming_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        chat("hello", provider=_StreamingFakeProvider(), runtime_action_dispatcher=spy)

        streaming_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_PROVIDER_CALL
        ]
        assert len(streaming_entries) >= 1

        _, request, _ = streaming_entries[0]
        events = list(request.payload.get("events", []))
        # 最后一个事件应为 final
        assert events[-1].get("is_final") is True or events[-1].get("event_type") == "final", (
            f"最后一个事件应为 final，实际 {events[-1]}"
        )
        # 至少有一个 text_delta 事件
        text_deltas = [e for e in events if e.get("event_type") == "text_delta"]
        assert len(text_deltas) > 0, "应有至少一个 text_delta 事件"


# ═══════════════════════════════════════════════════════════════════════
# T4: no real API or env access
# ═══════════════════════════════════════════════════════════════════════


class TestNoRealAPIOrEnv:
    def test_t4_no_real_api_or_env_access(self):
        """T4: Streaming L3 测试不读取真实 API / secret / env。"""
        from agent.core import chat

        real_dispatcher = _build_streaming_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        chat("hello", provider=_StreamingFakeProvider(), runtime_action_dispatcher=spy)

        streaming_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_PROVIDER_CALL
        ]
        assert len(streaming_entries) >= 1

        _, _, result = streaming_entries[0]
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("external_side_effects") is False
        # FakeProvider 不调用真实 API
        assert evidence.get("provider_external_call") is False
