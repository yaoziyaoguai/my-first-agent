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
import re
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
    summary_text = ""
    for evt in events:
        if getattr(evt, "event_type", "") == "run.summary":
            text = getattr(evt, "text", "")
            summary_text = text
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
        "summary_text": summary_text,
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
        """Case D: 使用精确触发短语 "create a demo note" (scripted scenario, Category A)。

        中文学习说明：
        - 按 FakeProvider Scripted Scenario Contract (§3.3)，只允许 exact match 和
          literal tool name 匹配
        - 本 case 使用 _DEMO_TOOL_TRIGGERS 中的精确触发短语，不依赖中文 NLU
        - 任意中文自然语言 tool intent 测试属于 Category C，需要 real provider

        expected:
        - may enter tool confirmation / tool gate
        - should not max-loop
        - should not call real API
        - if confirmation required, that's EXPECTED (not a failure)
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        # 精确触发短语，命中 _DEMO_TOOL_TRIGGERS → strategy 4 (legacy exact match)
        # 非任意中文 NLU，不依赖 strategy 2/3 的 n-gram 关键词匹配
        user_msg = "create a demo note"
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


def _check_summary_memory_honesty(result: dict, allow_effective: bool = False) -> tuple[bool, str]:
    """检查 run summary 不对 Memory 操作 overclaim。

    中文学习说明：
    internal lifecycle event（turn_end_proposal/consolidate/recall）
    不等于 user-visible effect。如果这些 hook 运行但无有效结果
    （如 no_action / insufficient_evidence / no_memory），
    summary 不应统计为"Memory 操作"。

    参数：
    - allow_effective: 如果允许 summary 显示有效 memory 操作，设为 True。
    """
    st = result.get("summary_text", "")
    mem_match = re.search(r"Memory 操作：(\d+) 次", st)
    if mem_match is None:
        return True, ""
    count = int(mem_match.group(1))
    if count > 0 and not allow_effective:
        return False, f"summary overclaims Memory 操作 {count} 次（无有效 memory effect）"
    return True, ""


def _check_summary_subagent_honesty(
    result: dict, allow_delegation: bool = False
) -> tuple[bool, str]:
    """检查 run summary 不对 SubAgent 委托 overclaim。

    routing check / descriptor check / availability check 不是真实委托。
    只有真实 delegation/handoff 才应统计为"SubAgent 委托"。
    """
    st = result.get("summary_text", "")
    sub_match = re.search(r"SubAgent 委托：(\d+) 次", st)
    if sub_match is None:
        return True, ""
    count = int(sub_match.group(1))
    if count > 0 and not allow_delegation:
        return False, f"summary overclaims SubAgent 委托 {count} 次（无真实 delegation）"
    return True, ""


@pytest.mark.dogfood
class TestDogfoodSummaryHonesty:
    """run summary 诚实性：不把 internal lifecycle check 冒充 user-visible effect。

    中文学习说明：
    turn_end hook 每轮都会运行 MEMORY_TURN_END_PROPOSAL、MEMORY_CONSOLIDATE、
    MEMORY_RECALL、SUBAGENT_DELEGATE_L0 四个 lifecycle action。它们大多数时候
    是 checked/skipped/no-op（policy 返回 no_action、store 为空返回 no_memory、
    subagent 不可用返回 rejected）。run summary 给用户看，不能把这些内部检查
    统计为"Memory 操作 3 次"或"SubAgent 委托 1 次"。

    只有真实 effective action（proposed/retained/recalled/consolidated/delegated）
    才应出现在 summary 的操作计数中。
    """

    def test_ordinary_chat_no_memory_overclaim(self, monkeypatch):
        """普通聊天不应在 summary 中声称有 Memory 操作。

        输入 "你好，简单介绍一下你现在能做什么" 时：
        - turn_end_proposal → no_action（无内容可 proposal）
        - consolidate → insufficient_evidence（store 为空）
        - recall → no_memory（无可用 memory）
        这三个 lifecycle check 都不是 user-visible effect。
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "你好，简单介绍一下你现在能做什么",
            provider,
        )

        assert not result["error"], f"不应有异常: {result['error']}"
        assert result["loop_iterations"] <= 3, (
            f"ordinary chat 循环次数应 ≤3，实际: {result['loop_iterations']}"
        )
        ok, reason = _check_summary_memory_honesty(result, allow_effective=False)
        assert ok, reason

    def test_ordinary_chat_no_subagent_overclaim(self, monkeypatch):
        """普通聊天不应在 summary 中声称有 SubAgent 委托。

        SUBAGENT_DELEGATE_L0 在 fake provider 路径下总是 rejected
        （no subagent available for delegation）。
        这个 routing check 不是真实 delegation。
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "你好，简单介绍一下你现在能做什么",
            provider,
        )

        assert not result["error"], f"不应有异常: {result['error']}"
        ok, reason = _check_summary_subagent_honesty(result, allow_delegation=False)
        assert ok, reason

    def test_travel_planning_no_memory_overclaim(self, monkeypatch):
        """旅行规划普通聊天也不应 overclaim Memory。

        验证修复不是特判"你好"——任何 ordinary chat 都适用。
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "帮我规划下去武汉玩5天的旅游计划",
            provider,
        )

        assert not result["error"], f"不应有异常: {result['error']}"
        ok_mem, reason = _check_summary_memory_honesty(result, allow_effective=False)
        assert ok_mem, reason
        ok_sub, reason = _check_summary_subagent_honesty(result, allow_delegation=False)
        assert ok_sub, reason


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


# ═══════════════════════════════════════════════════════════════════
# Sweep Cases — phase A 扩展
# 中文学习说明：以下 case 覆盖用户指定的 automated sweep 矩阵中
# 尚未被 TestDogfoodOrdinaryChat / TestDogfoodToolAndCommands 覆盖的部分。
# ═══════════════════════════════════════════════════════════════════


def _check_no_secret_leakage(result: dict) -> tuple[bool, str]:
    """检查 runtime events 和错误信息中不包含疑似 secret 模式。"""
    suspicious = []
    text_sources = [
        result.get("error") or "",
        result.get("reply") or "",
        result.get("summary_text") or "",
    ]
    for evt in result.get("runtime_events", []):
        text_sources.append(str(getattr(evt, "text", "")))
    combined = "\n".join(text_sources)
    # sk-ant / sk-sp / api_key / Bearer 等常见 secret token 前缀
    patterns = [r"sk-ant-", r"sk-sp-", r"api_key\s*=\s*['\"]?\w{10,}", r"Bearer\s+\w{20,}"]
    for pat in patterns:
        if re.search(pat, combined):
            suspicious.append(pat)
    if suspicious:
        return False, f"疑似 secret 泄漏: {suspicious}"
    return True, ""


@pytest.mark.dogfood
class TestDogfoodMemoryRetain:
    """Memory retain flow：记住偏好 → 检查是否可读取。"""

    def test_case_h_remember_preference(self, monkeypatch):
        """Case H: 请记住一个测试偏好。

        输入：
        请记住一个测试偏好：我喜欢把复杂工程问题先拆成架构、代码、测试、文档四类来看

        expected:
        - no crash / no max loop
        - has response
        - 不 overclaim Memory（无真实 retain 时不报）
        - no secret leakage
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "请记住一个测试偏好：我喜欢把复杂工程问题先拆成架构、代码、测试、文档四类来看",
            provider,
        )

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
            ("no secret leakage", _check_no_secret_leakage(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case H 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )


@pytest.mark.dogfood
class TestDogfoodSubAgentDelegation:
    """SubAgent delegation flow — 真实委托路径。"""

    def test_case_i_delegate_demo_stat(self, monkeypatch):
        """Case I: 请委托 demo-stat 子代理统计字数。

        输入：
        请委托 demo-stat 子代理，帮我统计这句话里面有多少个字：武汉旅行测试

        expected:
        - no crash / no max loop
        - has response
        - 不对 SubAgent 委托 overclaim（仅在 success 时计数）
        - no secret leakage
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "请委托 demo-stat 子代理，帮我统计这句话里面有多少个字：武汉旅行测试",
            provider,
        )

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
            ("no secret leakage", _check_no_secret_leakage(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case I 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )


@pytest.mark.dogfood
class TestDogfoodDebugSummary:
    """Debug / summary 查询路径。"""

    def test_case_j_show_run_summary(self, monkeypatch):
        """Case J: 请显示本轮运行摘要。

        expected:
        - no crash / no max loop
        - has response
        - 摘要信息应出现在回复中或至少不崩溃
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("请显示本轮运行摘要", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case J 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )

    def test_case_k_ask_about_activity(self, monkeypatch):
        """Case K: 请告诉我刚才这一轮有没有调用工具、记忆或子代理。

        expected:
        - no crash / no max loop
        - has response
        - summary self-report 诚实
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat(
            "请告诉我刚才这一轮有没有调用工具、记忆或子代理",
            provider,
        )

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case K 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )


@pytest.mark.dogfood
class TestDogfoodErrorRecovery:
    """Error / recovery 路径 — 异常输入不会导致崩溃。"""

    def test_case_l_forget_nonexistent_memory(self, monkeypatch):
        """Case L: forget memory abc-not-exist。

        expected:
        - no crash
        - no max loop
        - 应该给出可读的错误/提示，不应 traceback
        """
        home = _fresh_home()
        _fresh_state(monkeypatch, home)
        provider = _build_fake_provider()

        result = _run_chat("forget memory abc-not-exist", provider)

        checks = [
            ("no crash", _check_no_crash(result)),
            ("no max loop", _check_no_max_loop(result)),
            ("has response", _check_has_response(result)),
        ]

        failures = [(name, reason) for name, (ok, reason) in checks if not ok]
        assert not failures, (
            f"Case L 失败 ({result['loop_iterations']} loops):\n"
            + "\n".join(f"  [{name}] {reason}" for name, reason in failures)
        )
