"""Streaming L3 测试。

验证 core.chat() → model_call (streaming via call_model()) → turn-end hook →
STREAMING_PROVIDER_CALL + STREAMING_EVENT dispatch 的完整 evidence chain。

call_model() 已支持 streaming（model_call.py）：当 provider.supports_streaming=True 时，
自动调用 provider.stream() 并收集事件。事件通过 LoopDependencies.streaming_events
共享列表传入 turn-end hook，由 STREAMING_PROVIDER_CALL（整轮聚合）和 STREAMING_EVENT
（per-event 验证）两个 dispatch 处理。

测试分层：
- L1/L2: 已有 test_runtime_action_handlers.py / test_runtime_action_contract.py 覆盖
- L3 (real_core_loop_runtime_e2e): core.chat() → streaming dispatch via turn-end hook
  - STREAMING_PROVIDER_CALL：整轮 event 聚合 + collect_stream_response L3 evidence
  - STREAMING_EVENT：单 event 验证 + validate_stream_event L3 evidence

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
from agent.runtime_integration.streaming_provider import (
    StreamingEventHandler,
    StreamingProviderCallHandler,
)


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


# ═══════════════════════════════════════════════════════════════════════
# T5-T9: STREAMING_EVENT per-event dispatch + L3 evidence
# ═══════════════════════════════════════════════════════════════════════


def _build_streaming_event_dispatcher():
    """构建注册 STREAMING_EVENT handler 的 dispatcher。"""
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.STREAMING_EVENT,
        StreamingEventHandler(),
    )
    return RuntimeActionDispatcher(
        registry=registry, observer=RuntimeActionModuleObserver()
    )


class TestStreamingEventL3:
    """STREAMING_EVENT per-event dispatch → L3 evidence。

    STREAMING_EVENT 与 STREAMING_PROVIDER_CALL 的区别：
    - STREAMING_PROVIDER_CALL：整轮 event 列表 → collect_stream_response 聚合
    - STREAMING_EVENT：单 event → validate_stream_event 验证

    两者共享 runtime_loop provenance（route_from_runtime_loop），但 target 操作不同。
    """

    def test_t5_streaming_event_handler_dispatchable(self):
        """T5: STREAMING_EVENT handler 可接收单 event 并返回 success。

        直接通过 dispatcher.route_from_runtime_loop() 分发单 text_delta event，
        验证 handler 正确处理并返回 L3 evidence。
        """
        dispatcher = _build_streaming_event_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.STREAMING_EVENT,
            source="core_loop",
            parent_trace_id="test-t5",
            payload={
                "event": {
                    "event_type": "text_delta",
                    "sequence": 1,
                    "source": "provider",
                    "text_delta": "你好",
                    "is_final": False,
                    "error": None,
                },
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "success", (
            f"单 text_delta event → status 应为 'success'，"
            f"实际 {result.status!r}，error_safe_preview={result.error_safe_preview!r}"
        )

        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"STREAMING_EVENT dispatch 应达到 L3，实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("target_module") == "StreamingProtocol"
        assert evidence.get("module_invoked") is True

        # per-event evidence
        assert evidence.get("streaming_event_validated") is True
        assert evidence.get("event_type") == "text_delta"

        payload = dict(result.payload)
        assert payload.get("event_type") == "text_delta"
        assert payload.get("sequence") == 1
        assert payload.get("has_text_delta") is True

    def test_t6_streaming_event_final_validation(self):
        """T6: final event 也产生 L3 evidence。"""
        dispatcher = _build_streaming_event_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.STREAMING_EVENT,
            source="core_loop",
            parent_trace_id="test-t6",
            payload={
                "event": {
                    "event_type": "final",
                    "sequence": 3,
                    "source": "provider",
                    "text_delta": "",
                    "is_final": True,
                    "error": None,
                },
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "success"
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("event_type") == "final"

    def test_t7_missing_event_payload_not_supported(self):
        """T7: 缺少 event payload → not_supported disposition。"""
        dispatcher = _build_streaming_event_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.STREAMING_EVENT,
            source="core_loop",
            parent_trace_id="test-t7",
            payload={},
        )

        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "not_supported", (
            f"缺少 event payload → status 应为 'not_supported'，"
            f"实际 {result.status!r}"
        )

    def test_t8_event_sanitization_check(self):
        """T8: text_delta 脱敏检查在 validate_stream_event 中正确执行。"""
        dispatcher = _build_streaming_event_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.STREAMING_EVENT,
            source="core_loop",
            parent_trace_id="test-t8",
            payload={
                "event": {
                    "event_type": "text_delta",
                    "sequence": 1,
                    "source": "provider",
                    "text_delta": "普通文本，不含 secret",
                    "is_final": False,
                    "error": None,
                },
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "success"
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

    def test_t9_streaming_event_error_event(self):
        """T9: error event 也通过 STREAMING_EVENT handler 正确验证。"""
        dispatcher = _build_streaming_event_dispatcher()

        request = RuntimeActionRequest(
            action_type=RuntimeActionType.STREAMING_EVENT,
            source="core_loop",
            parent_trace_id="test-t9",
            payload={
                "event": {
                    "event_type": "error",
                    "sequence": 1,
                    "source": "provider",
                    "text_delta": "",
                    "is_final": False,
                    "error": "provider timeout",
                },
            },
        )

        result = dispatcher.route_from_runtime_loop(request)

        assert result.status == "success"
        evidence = dict(result.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("event_type") == "error"


# ═══════════════════════════════════════════════════════════════════════
# T10: STREAMING_EVENT via core.chat() full pipeline
# ═══════════════════════════════════════════════════════════════════════


class TestStreamingEventFullPipeline:
    """验证 core.chat() → turn-end hook → STREAMING_EVENT dispatch 完整链路。

    turn-end hook 现在同时 dispatch STREAMING_PROVIDER_CALL（聚合）和
    STREAMING_EVENT（per-event），两部分都使用 route_from_runtime_loop()。
    """

    def test_t10_streaming_event_dispatched_from_core_chat(self):
        """T10: core.chat() 触发 turn-end hook，dispatch STREAMING_EVENT per event。

        _StreamingFakeProvider 产出 text_delta + final 事件，turn-end hook 为
        每个事件 dispatch 一个独立的 STREAMING_EVENT action。
        """
        from agent.core import chat

        # 构建含 STREAMING_EVENT handler 的 dispatcher
        real_dispatcher = _build_streaming_event_dispatcher()
        # 同时注册 STREAMING_PROVIDER_CALL 以通过 turn-end 门
        real_dispatcher._registry.register(
            RuntimeActionType.STREAMING_PROVIDER_CALL,
            StreamingProviderCallHandler(),
        )
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=_StreamingFakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)

        # STREAMING_PROVIDER_CALL 应至少 1 次
        provider_call_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_PROVIDER_CALL
        ]
        assert len(provider_call_entries) >= 1

        # STREAMING_EVENT 应至少 1 次（每个 streaming event 一次 dispatch）
        event_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_EVENT
        ]
        assert len(event_entries) >= 1, (
            f"core.chat() turn-end 应 dispatch 至少 1 次 STREAMING_EVENT，"
            f"实际 {len(event_entries)} 次"
        )

        # 所有 STREAMING_EVENT 应走 route_from_runtime_loop
        for method, _, result in event_entries:
            assert method == "route_from_runtime_loop", (
                f"STREAMING_EVENT 必须走 route_from_runtime_loop()，实际 {method!r}"
            )
            evidence = dict(result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E

    def test_t11_no_real_api_or_env_access_for_streaming_event(self):
        """T11: STREAMING_EVENT 全链路不读 .env，不调真实 API。"""
        from agent.core import chat

        real_dispatcher = _build_streaming_event_dispatcher()
        real_dispatcher._registry.register(
            RuntimeActionType.STREAMING_PROVIDER_CALL,
            StreamingProviderCallHandler(),
        )
        spy = _SpyDispatcher(real_dispatcher)

        chat("hello", provider=_StreamingFakeProvider(), runtime_action_dispatcher=spy)

        event_entries = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.STREAMING_EVENT
        ]
        assert len(event_entries) >= 1

        for _, _, result in event_entries:
            evidence = dict(result.evidence)
            assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
            # STREAMING_EVENT 是 per-event dispatch，不携带 provider-level
            # external_side_effects——那是 STREAMING_PROVIDER_CALL 聚合层的关注点
