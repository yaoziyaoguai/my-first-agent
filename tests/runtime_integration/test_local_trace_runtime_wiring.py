"""Local trace runtime wiring L3 测试。

验证 core.chat() → turn-end hook → on_trace_event sink 的 trace event
emission 是完整的。Trace 是纯观测基础设施——不通过 dispatcher routing，
直接在 turn-end hook 上构造 TraceEvent 后调用 sink。

测试分层：
- L3 (real_core_loop_runtime_e2e): core.chat() → on_trace_event 被调用
"""

from __future__ import annotations


class TestCoreChatTraceEventEmissionL3:
    """T1/T2: core.chat() 通过 on_trace_event sink 发射 TraceEvent。"""

    def test_t1_core_chat_emits_state_transition_trace_event(self):
        """T1: core.chat() 发射 state_transition TraceEvent。

        on_trace_event sink 捕获所有 TraceEvent——至少应有一条
        span_type="state_transition", name="loop.turn_end"。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        captured: list = []

        result = chat(
            "hello",
            provider=FakeProvider(),
            on_trace_event=captured.append,
        )

        # chat() 正常返回（空串是正常行为：handle_end_turn_response
        # 不返回模型正文——正文已由流式阶段输出。返回值只包含控制型 UI 文字。）
        assert isinstance(result, str)

        # 至少发射了一条 state_transition event
        transition_events = [
            e for e in captured
            if getattr(e, "span_type", None) == "state_transition"
        ]
        assert len(transition_events) >= 1, (
            f"expected at least 1 state_transition event, got {len(transition_events)}"
        )

        # 验证 event 字段完整
        te = transition_events[0]
        assert te.name == "loop.turn_end"
        assert te.run_id and te.run_id != "run:unknown"
        assert te.trace_id and te.trace_id != "trace:unknown"
        assert te.status == "ok"

    def test_t2_core_chat_emits_tool_call_trace_event(self):
        """T2: core.chat() TOOL_INVOKE 后发射 tool_call TraceEvent。

        默认 tool_gate_tool_name="_safe_noop"，gate allowed → invoke → result，
        turn-end hook 应为该工具调用发射 tool_call TraceEvent。
        """
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        captured: list = []

        chat(
            "hello",
            provider=FakeProvider(),
            on_trace_event=captured.append,
        )

        # 至少发射了一条 tool_call event
        tool_events = [
            e for e in captured
            if getattr(e, "span_type", None) == "tool_call"
        ]
        assert len(tool_events) >= 1, (
            f"expected at least 1 tool_call event, got {len(tool_events)}"
        )

        # 验证 tool_call event 字段
        te = tool_events[0]
        assert "_safe_noop" in te.name, (
            f"tool_call event name should contain '_safe_noop', got: {te.name}"
        )
        assert te.run_id
        assert te.trace_id


class TestDefaultPathNoOverhead:
    """T3: 不传 on_trace_event → 默认路径零开销。"""

    def test_t3_no_trace_event_sink_no_crash(self):
        """T3: 不传 on_trace_event 时 chat() 正常返回——零开销默认路径。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        result = chat("hello", provider=FakeProvider())
        # chat() 正常返回（空串是正常行为：handle_end_turn_response
        # 不返回模型正文——正文已由流式阶段输出。返回值只包含控制型 UI 文字。）
        assert isinstance(result, str)


class TestNoRealAPIOrEnv:
    """T4: 不读取真实 API / secret / env。"""

    def test_t4_no_real_api_or_env_access(self):
        """T4: 本测试只使用 FakeProvider，不访问真实外部服务。"""
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider

        captured: list = []
        chat("hello", provider=FakeProvider(), on_trace_event=captured.append)

        assert len(captured) >= 1
        # 所有 event 都是 TraceEvent 实例
        from agent.local_trace import TraceEvent
        for e in captured:
            assert isinstance(e, TraceEvent)
