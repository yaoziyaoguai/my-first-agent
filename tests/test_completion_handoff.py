"""Completion handoff diagnostics.

These tests capture the current shutdown semantics around planned tasks. They
are intentionally narrow: no real API calls, only fake model responses.
"""

from __future__ import annotations

from tests.conftest import FakeAnthropicClient, meta_complete_response, text_response
from tests.test_complex_scenarios import _plan_response, _tool_use_resp
from tests.test_main_loop import _register_test_tool, _reset_core_module


def test_planned_step_text_end_turn_without_meta_is_reprompted_then_auto_advances(monkeypatch):
    """Text-only end_turn during a planned step is reprompted inside the loop.

    If the executor model ends the assistant turn with text only, the agent
    should not hand CLI control back while keeping the task running. It should
    ask the model for the missing mark_step_complete signal in the same loop.
    """
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "执行任务", "report"), ("s2", "收尾", "report")]),
            text_response("我已经完成了第 1 步。"),
            meta_complete_response(score=95, text="补充完成信号"),
            meta_complete_response(score=95, text="第 2 步完成"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    assert chat("做一个两步任务") == ""
    assert state.task.status == "awaiting_plan_confirmation"

    reply = chat("y")

    assert reply == "好的，任务已完成。"
    assert state.task.status == "idle"
    assert state.task.current_plan is None
    assert len(fake.requests) == 3


def test_explicit_confirm_each_step_keeps_step_confirmation(monkeypatch):
    """Only explicit user intent should keep the old per-step confirmation gate."""
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "执行任务", "report"), ("s2", "收尾", "report")]),
            meta_complete_response(score=95, text="第 1 步完成"),
            meta_complete_response(score=95, text="第 2 步完成"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    assert chat("做一个两步任务，每步确认后再继续") == ""
    assert state.task.status == "awaiting_plan_confirmation"
    assert state.task.confirm_each_step is True

    first_reply = chat("y")

    assert "请确认" in first_reply
    assert state.task.status == "awaiting_step_confirmation"
    assert state.task.current_step_index == 0

    final_reply = chat("y")

    assert final_reply == "好的，任务已完成。"
    assert state.task.status == "idle"


def test_planned_step_user_clarification_hands_control_back_to_cli(monkeypatch):
    """A collect-input step should pause for user reply and then resume."""
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "确认需求", "collect_input"), ("s2", "生成方案", "report")]),
            text_response(
                "## 需求确认\n\n"
                "请告诉我这些信息：\n"
                "1. 方案类型是什么？\n"
                "2. 预算范围是多少？\n"
                "3. 计划安排几天？"
            ),
            meta_complete_response(score=95, text="方案已生成"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    assert chat("帮我做武汉和宜昌的三套对比方案") == ""
    assert state.task.status == "awaiting_plan_confirmation"

    reply = chat("y")

    assert "补充" in reply
    assert state.task.status == "awaiting_user_input"
    assert state.task.current_plan is not None
    assert state.task.current_step_index == 0
    assert len(fake.requests) == 1, "需求追问后应等待用户输入，不能同一 loop 里重复追问模型"

    final_reply = chat("旅游出行，舒适型，5天，2人，偏好景点和美食，从北京出发")

    assert final_reply == "好的，任务已完成。"
    assert state.task.status == "idle"


def test_planned_step_reprompt_loop_limit_stops_and_clears_task(monkeypatch):
    """模型连续 end_turn 不调工具时，必须有打断机制防死循环。

    旧行为：靠 MAX_LOOP_ITERATIONS 兜到 50 轮才停（中间会一直刷"请打分"提示）。
    新行为：双层兜底（response_handlers.handle_end_turn_response）连续 2 次
    end_turn 没工具调用就切到 awaiting_user_input，把控制权交给用户。
    这条测试覆盖的不变量是"loop 不能无限刷"，但触发机制和断言都按新行为更新。
    """
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "执行任务", "report"), ("s2", "收尾", "report")]),
            # 第 1 次 end_turn：陈述句不命中启发式 → counter=1，注入软驱动
            text_response("我已经完成了，但不调用工具。"),
            # 第 2 次 end_turn：依然不调工具 → counter=2 → 强制切 awaiting_user_input
            text_response("还是只说文本。"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    assert chat("做一个两步任务") == ""
    chat("y")

    # 双层兜底应当切到 awaiting_user_input，而不是清掉任务
    assert state.task.status == "awaiting_user_input", (
        f"双层兜底未生效，实际 status={state.task.status}"
    )
    assert state.task.current_plan is not None, (
        "兜底是把控制权交给用户、不是清任务——plan 必须保留"
    )
    assert state.task.pending_user_input_request is not None, (
        "兜底必须写入 pending_user_input_request 让 handle_user_input_step 识别"
    )
    assert state.task.current_step_index == 0, "兜底不能推进 step"


def test_max_loop_iterations_terminal_guard_still_fires_when_double_layer_bypassed(monkeypatch):
    """终极兜底回归：双层兜底（end_turn 启发式 + 计数器）兜不住的场景，
    MAX_LOOP_ITERATIONS 必须仍能停止任务并清干净 state。

    场景构造：模型每轮都调业务工具（不同 arg 避开 MAX_REPEATED_TOOL_INPUTS=3 同输入兜底）。
    业务工具调用每轮都触发 handle_tool_use_response 把
    consecutive_end_turn_without_progress 清零——双层兜底永远不累计、永远不触发。
    但任务也永远不打 mark_step_complete，永远不收敛。这种 case 只能靠
    MAX_LOOP_ITERATIONS 终极兜底兜住。

    本测试的"反向证明"：检查 fake.requests 数量等于 MAX_LOOP_ITERATIONS——证明 loop
    确实跑满了（如果双层兜底中途生效，stream 调用次数会少于上限）。
    """
    cleanup = _register_test_tool("loop_tool", confirmation="never", result="ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _plan_response([("s1", "永不收敛", "read"), ("s2", "看不到", "report")]),
                # 每轮调 loop_tool 但 arg 不同，避开 MAX_REPEATED_TOOL_INPUTS（同输入 3 次兜底）
                _tool_use_resp("loop_tool", "T1", arg="a"),
                _tool_use_resp("loop_tool", "T2", arg="b"),
                _tool_use_resp("loop_tool", "T3", arg="c"),
                _tool_use_resp("loop_tool", "T4", arg="d"),  # off-by-one 余量
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent import core
        from agent.core import chat

        # 把 MAX_LOOP_ITERATIONS 缩成 3 让测试跑得快；行为不变
        monkeypatch.setattr(core, "MAX_LOOP_ITERATIONS", 3)

        assert chat("做一个两步任务") == ""
        reply = chat("y")

        # 终极兜底必须触发并清干净任务
        assert "循环次数过多" in reply, (
            f"MAX_LOOP_ITERATIONS 终极兜底未触发，实际 reply={reply!r}"
        )
        assert state.task.status == "idle", "终极兜底必须 reset_task"
        assert state.task.current_plan is None, "终极兜底必须清 plan"
        assert state.task.pending_tool is None
        assert state.task.pending_user_input_request is None

        # 反向证明：本测试场景**绕过了**双层兜底——_call_model 实际跑满了
        # MAX_LOOP_ITERATIONS 次（每次都消费一个工具响应）。如果双层兜底
        # 中途生效，stream 调用次数会小于 MAX_LOOP_ITERATIONS。
        assert len(fake.requests) == 3, (
            f"应当跑满 3 次 _call_model 才被终极兜底，实际 stream 次数="
            f"{len(fake.requests)}；少于 3 说明双层兜底先生效，本测试场景失效"
        )
    finally:
        cleanup()


def test_final_step_meta_completion_clears_state_and_returns_cli_signal(monkeypatch):
    """Default planned tasks auto-advance and final completion clears task state."""
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "执行任务", "report"), ("s2", "最终收尾", "report")]),
            meta_complete_response(score=95, text="第 1 步完成"),
            meta_complete_response(score=95, text="第 2 步完成"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("做一个两步任务")
    final_reply = chat("y")

    assert final_reply == "好的，任务已完成。"
    assert state.task.status == "idle"
    assert state.task.current_plan is None
    boundary_texts = [
        block.get("text", "")
        for msg in state.conversation.messages
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    assert any("任务已完成" in text for text in boundary_texts), (
        "计划完成必须写入 conversation 边界事件，避免下一轮单步命令继续旧任务语境"
    )


def test_single_step_tool_completion_resets_task_after_end_turn(monkeypatch):
    """A no-plan tool task must not stay in running after final end_turn."""
    from tests.conftest import tool_use_response
    from tests.test_main_loop import _planner_no_plan_response, _register_test_tool

    cleanup = _register_test_tool("test_ls", confirmation="always", result="file-a\nfile-b")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                tool_use_response("test_ls", {"arg": "-al"}, tool_id="T_ls"),
                text_response("file-a\nfile-b"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        assert chat("ls -al") == ""
        assert state.task.status == "awaiting_tool_confirmation"

        reply = chat("y")

        assert reply == ""
        assert state.task.status == "idle"
        assert state.task.current_plan is None
        assert state.task.pending_tool is None
        assert state.task.tool_execution_log == {}
    finally:
        cleanup()
