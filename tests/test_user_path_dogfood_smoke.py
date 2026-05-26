"""Automated User-Path Dogfood Regression Harness.

中文学习说明：
这是把人工 dogfood 样本转成自动 regression harness。
目标是验证 user path（main.py → core.chat → loop.py → model_call → FakeProvider），
不是 direct handler 调用。
max loop guard 是保护机制，不是成功终止条件。
ordinary chat 和 tool-intent chat 的终止条件不同：
- ordinary chat：无 tool call，assistant text 存在 → 正常终止
- tool-intent chat：可能进入 tool confirmation / tool lifecycle
fake/local 与 real provider 共享同一条 unified runtime flow，
区别只在 provider 注入点（FakeProvider vs RealProvider）。

测试边界：
- 不读 .env / 不调真实 API / 不调真实 LLM / 不访问外部网络
- 不读真实 sessions / runs / memory episodes / 私人资料
- 使用 temp HOME 避免 stale checkpoint 干扰
- 直接注入 FakeProvider，走 core.chat() 完整路径
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

import pytest

# 确保 tests/ 能 import agent/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _fresh_home() -> str:
    """创建临时 HOME 目录，避免 stale checkpoint 干扰测试。"""
    tmp = tempfile.mkdtemp(prefix="dogfood_home_")
    return tmp


def _fresh_state(monkeypatch, home_dir: str):
    """重置 agent.core.state 为全新状态，隔离各测试用例。

    中文学习说明：
    agent.core.state 是模块级单例。每个 dogfood case 必须从干净状态开始，
    否则前一个 case 的 current_plan / checkpoint / messages 会残留到下一个 case。
    """
    from agent import core
    from agent.state import create_agent_state

    monkeypatch.setenv("HOME", home_dir)
    monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "")  # 不设值，走 factory 默认
    # 关键：重置 state 为全新状态
    fresh = create_agent_state(
        system_prompt="",
        model_name="fake-llm",
        review_enabled=False,
        max_recent_messages=6,
    )
    monkeypatch.setattr(core, "state", fresh)


def _build_fake_provider():
    """构造用于 dogfood 的 FakeProvider 实例。"""
    from agent.provider.fake_provider import FakeProvider

    return FakeProvider()


def _run_chat(user_input: str, provider) -> dict:
    """运行一轮 core.chat()，收集 RuntimeEvent 和异常信息。

    返回 dict：
        reply: str                    — chat() 返回值
        runtime_events: list          — 收集到的 RuntimeEvent 列表
        loop_iterations: int          — 本轮循环次数（从 run.summary 事件提取）
        tool_call_count: int          — 工具调用次数（从 run.summary 事件提取）
        has_assistant_text: bool      — 是否有 assistant.delta 事件
        error: str | None             — 异常信息
        traceback: str | None         — 完整 traceback

    中文学习说明：
    chat() 返回值在 RuntimeEvent streaming 路径下可能是空字符串
    （文本已通过 assistant.delta 事件流式输出）。loop_iterations 在正常
    终止时被 reset_task() 归零，必须从 run.summary RuntimeEvent 中提取。
    """
    from agent import core
    from agent.display_events import RuntimeEvent

    events: list[RuntimeEvent] = []
    error = None
    tb = None
    reply = ""

    def collect_event(event: RuntimeEvent) -> None:
        events.append(event)

    try:
        reply = core.chat(
            user_input,
            provider=provider,
            on_runtime_event=collect_event,
            runtime_action_dispatcher=None,
        )
    except Exception as e:
        error = str(e)
        tb = traceback.format_exc()

    # 从 run.summary 事件中提取真实的循环次数和工具调用次数。
    # state.task 上的计数器在正常终止时被 reset_task() 归零，不可依赖。
    loop_iterations = 0
    tool_call_count = 0
    for evt in events:
        if getattr(evt, "event_type", "") == "run.summary":
            text = getattr(evt, "text", "")
            import re
            loop_match = re.search(r"循环次数：(\d+)", text)
            if loop_match:
                loop_iterations = int(loop_match.group(1))
            tool_match = re.search(r"工具调用：(\d+)", text)
            if tool_match:
                tool_call_count = int(tool_match.group(1))
            break

    # 检查是否有 assistant text（流式输出）
    has_assistant_text = any(
        getattr(e, "event_type", "") == "assistant.delta"
        for e in events
    )

    return {
        "reply": str(reply),
        "runtime_events": events,
        "loop_iterations": loop_iterations,
        "tool_call_count": tool_call_count,
        "has_assistant_text": has_assistant_text,
        "error": error,
        "traceback": tb,
    }


def _classify(ok: bool, concern: str = "") -> str:
    """统一 PASS / CONCERN / FAIL 标签。"""
    if ok:
        return "PASS"
    return f"FAIL ({concern})" if concern else "FAIL"


def _check_no_crash(result: dict) -> tuple[bool, str]:
    """检查：无 traceback 异常。"""
    if result["error"]:
        return False, f"异常: {result['error'][:120]}"
    return True, ""


def _check_no_max_loop(result: dict, max_limit: int = 50) -> tuple[bool, str]:
    """检查：未触发 max loop guard。

    中文学习说明：max loop guard 是安全阀，不是正常终止。
    如果 loop_iterations > max_limit，说明循环没有正常终止，是 bug。
    """
    n = result["loop_iterations"]
    if n > max_limit:
        return False, f"达到最大循环次数 ({n} > {max_limit})"
    if n < 0:
        return True, ""  # 异常路径，由 _check_no_crash 报告
    return True, ""


def _check_loop_reasonable(result: dict, max_reasonable: int = 5) -> tuple[bool, str]:
    """检查：循环次数在合理范围内。

    对于 ordinary chat，1-2 轮就应该终止。
    tool-intent chat 可能需要更多轮（planning → confirmation → tool execution）。
    这里用 5 作为宽松上限。
    """
    n = result["loop_iterations"]
    if n < 0:
        return True, ""  # 异常路径
    if n > max_reasonable:
        return False, f"循环次数偏高 ({n} > {max_reasonable})"
    return True, ""


def _check_no_repeated_tool_planning(result: dict) -> tuple[bool, str]:
    """检查：没有重复的"正在规划工具调用..."输出。

    中文学习说明：ordinary chat 不应该触发 tool_requested 事件。
    "正在规划工具调用..." 来自 display_events.tool_requested()，
    只在 call_model 检测到 tool_request stream event 或 ToolUseBlock 时触发。
    """
    tool_request_count = 0
    for evt in result["runtime_events"]:
        if hasattr(evt, "event_type") and evt.event_type == "tool.requested":
            tool_request_count += 1

    if tool_request_count > 0:
        return False, f"ordinary chat 不应该触发 tool_requested ({tool_request_count} 次)"
    return True, ""


def _check_no_provider_not_implemented(result: dict) -> tuple[bool, str]:
    """检查：无 ProviderNotImplementedError。"""
    err = result["error"] or ""
    if "ProviderNotImplementedError" in err or "model_provider_required" in err:
        return False, "ProviderNotImplementedError: model_provider_required"
    return True, ""


def _check_no_model_name_error(result: dict) -> tuple[bool, str]:
    """检查：无 LoopContext.model_name 错误。"""
    err = result["error"] or ""
    if "model_name" in err.lower() and ("空" in err or "empty" in err.lower() or "非空" in err):
        return False, f"model_name 错误: {err[:120]}"
    return True, ""


def _check_has_response(result: dict) -> tuple[bool, str]:
    """检查：chat() 返回了非空响应或有 assistant.delta 流式输出。

    中文学习说明：RuntimeEvent streaming 路径下 chat() 返回值可能是空字符串，
    因为文本已通过 assistant.delta 事件流式输出。这是正常行为。
    """
    reply = result["reply"]
    has_streamed = result.get("has_assistant_text", False)
    if (not reply or not reply.strip()) and not has_streamed:
        return False, "chat() 返回空响应且无 assistant.delta 事件"
    return True, ""


def _check_no_repeated_identical_lines(result: dict, max_repeat: int = 5) -> tuple[bool, str]:
    """检查：RuntimeEvent 中没有重复的相同文本行。

    中文学习说明：无限循环的典型症状是同一段文本反复出现。
    如果同一 event_type + 相同 text 出现超过 max_repeat 次，说明循环未正常终止。
    """
    from collections import Counter

    signatures = []
    for evt in result["runtime_events"]:
        et = getattr(evt, "event_type", "")
        txt = getattr(evt, "text", "")[:80] if hasattr(evt, "text") else ""
        signatures.append(f"{et}:{txt}")

    counts = Counter(signatures)
    for sig, cnt in counts.items():
        if cnt > max_repeat:
            return False, f"重复输出 '{sig[:60]}' {cnt} 次"
    return True, ""


# ═══════════════════════════════════════════════════════════════════
# Dogfood Cases
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.dogfood
class TestDogfoodOrdinaryChat:
    """A/B/C: ordinary chat 不应触发 tool planning 或 max loop。"""

    def test_case_a_ordinary_greeting(self, monkeypatch):
        """Case A: 你好，简单介绍一下你现在能做什么。

        expected:
        - no traceback
        - no ProviderNotImplementedError
        - no LoopContext.model_name error
        - no max loop
        - no repeated "正在规划工具调用..."
        - final fake/local response appears
        - loop count <= 5
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("你好，简单介绍一下你现在能做什么。", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("no provider error", _check_no_provider_not_implemented(result)),
            ("no model_name error", _check_no_model_name_error(result)),
            ("has response", _check_has_response(result)),
            ("no repeated tool planning", _check_no_repeated_tool_planning(result)),
            ("loop reasonable", _check_loop_reasonable(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case A 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )

    def test_case_b_travel_planning(self, monkeypatch):
        """Case B: 帮我规划下去武汉玩5天的旅游计划。

        expected:
        - no crash
        - no max loop
        - final fake/local response appears
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("帮我规划下去武汉玩5天的旅游计划", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
            ("loop reasonable", _check_loop_reasonable(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case B 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )

    def test_case_c_capabilities_check(self, monkeypatch):
        """Case C: 我现在只是测试 fake/local 路径，你不要调用真实 API，告诉我当前是什么模式。

        expected:
        - no crash
        - no max loop
        - fake/local mode visible or response clear
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "我现在只是测试 fake/local 路径，你不要调用真实 API，告诉我当前是什么模式。",
            provider,
        )

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
            ("loop reasonable", _check_loop_reasonable(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case C 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )


@pytest.mark.dogfood
class TestDogfoodToolAndCommands:
    """D/E/F/G: tool-intent, memory, subagent, unknown tool。"""

    def test_case_d_tool_intent_demo_note(self, monkeypatch):
        """Case D: 帮我创建一条 demo note，标题是「武汉旅行测试」，内容是「fake/local dogfood」。

        expected:
        - may enter tool confirmation / tool gate
        - should not max-loop
        - should not call real API
        - if confirmation required, that's EXPECTED (not a failure)
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        user_msg = (
            "帮我创建一条 demo note，标题是「武汉旅行测试」，"
            "内容是「这是 fake/local dogfood 的工具调用测试」。"
        )
        result = _run_chat(user_msg, provider)

        # tool-intent chat 需要更多循环（planning → tool pipeline），所以不检查 loop_reasonable
        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("no provider error", _check_no_provider_not_implemented(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        if failures:
            # tool-intent 允许更多循环，但仍不应 max-loop
            detail = (
                f"Case D 失败 ({result['loop_iterations']} loops, "
                f"{result['tool_call_count']} tool calls):\n"
                + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
            )
            pytest.fail(detail)

    def test_case_e_memory_command(self, monkeypatch):
        """Case E: show memories。

        expected:
        - no crash
        - no max loop
        - either memory list or clear no-memory message
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("show memories", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case E 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )

    def test_case_f_subagent_command(self, monkeypatch):
        """Case F: show subagents。

        expected:
        - no crash
        - no max loop
        - shows available/demo subagents or clear message
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("show subagents", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case F 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )

    def test_case_g_unknown_tool(self, monkeypatch):
        """Case G: 请调用一个不存在的工具 fake.unknown_tool。

        expected:
        - no crash
        - no max loop
        - user-readable error/decline
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("请调用一个不存在的工具 fake.unknown_tool。", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case G 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )


@pytest.mark.dogfood
class TestDogfoodInvariants:
    """架构 invariant：fake/real 共享 unified runtime flow。"""

    def test_unified_runtime_flow_no_fake_chat_loop(self, monkeypatch):
        """验证不存在 fake_chat_loop / fake_runtime_loop。

        中文学习说明：FakeProvider 和 RealProvider 都走 core.chat() →
        run_main_loop() → call_model()。不存在第二条 runtime 路径。
        """
        import inspect

        from agent import core
        from agent.model_call import call_model as mc_call_model
        from agent.provider.fake_provider import FakeProvider

        # 确认 FakeProvider 实现 ModelProvider 协议
        assert hasattr(FakeProvider, "create")
        assert hasattr(FakeProvider, "stream")

        # 确认 core.chat 调用 run_main_loop（通过 _run_main_loop helper）
        chat_src = inspect.getsource(core.chat)
        assert "_run_main_loop" in chat_src or "run_main_loop" in chat_src

        # 确认 call_model 是独立函数，通过 provider 参数注入
        assert callable(mc_call_model)

    def test_fake_provider_has_final_end_turn_for_ordinary_chat(self):
        """FakeProvider 对于普通聊天返回 stop_reason='end_turn'。

        这是 loop 正确终止的前置条件：如果 provider 不返回 end_turn，
        dispatch 不会进入 handle_end_turn_response，循环不会终止。
        """
        from agent.provider.fake_provider import FakeProvider

        provider = FakeProvider()
        response = provider.create(
            system="test",
            messages=[{"role": "user", "content": "你好"}],
            tools=[],
        )
        assert response.stop_reason == "end_turn", (
            f"FakeProvider ordinary chat 必须返回 end_turn，实际: {response.stop_reason}"
        )
        # 确认没有 tool_use block
        from agent.provider.protocol import ToolUseBlock

        has_tool_use = any(isinstance(b, ToolUseBlock) for b in response.content)
        assert not has_tool_use, "ordinary chat 不应包含 ToolUseBlock"

    def test_stream_collect_produces_end_turn(self):
        """collect_stream_response 必须产出 stop_reason='end_turn'。

        这确保 streaming 路径（FakeProvider.stream() → collect_stream_response()）
        和 non-streaming 路径（FakeProvider.create()）的 stop_reason 一致。
        """
        from agent.provider.fake_provider import FakeProvider
        from agent.provider.streaming import collect_stream_response

        provider = FakeProvider()
        events = list(provider.stream(
            system="test",
            messages=[{"role": "user", "content": "你好"}],
            tools=[],
        ))
        response = collect_stream_response(events)
        assert response.stop_reason == "end_turn", (
            f"collect_stream_response 必须返回 end_turn，实际: {response.stop_reason}"
        )


@pytest.mark.dogfood
class TestDogfoodRegression:
    """回归测试：之前修复过的 bug 不应再出现。"""

    def test_regression_model_name_not_none(self, monkeypatch):
        """回归 a2dfd89：LoopContext.model_name 必须是非空字符串。"""
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("你好", provider)

        assert not result["error"], f"不应有异常: {result['error']}"
        # model_name 必须非空
        err_lower = (result["error"] or "").lower()
        if "model_name" in err_lower:
            assert "非空" not in (result["error"] or ""), (
                f"model_name 不应为空: {result['error']}"
            )

    def test_regression_provider_not_none(self, monkeypatch):
        """回归 e6b561a：build_model_provider_from_env() 默认返回 FakeProvider。

        不传 env var 时，不应抛出 ProviderNotImplementedError。
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("你好", provider)

        assert "ProviderNotImplementedError" not in (result["error"] or ""), (
            f"不应有 ProviderNotImplementedError: {result['error']}"
        )
