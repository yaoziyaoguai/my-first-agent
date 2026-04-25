"""确认流程（plan / step / tool）的集成测试。

这类测试直接走 confirm_handlers，不用真实 input()，覆盖：
- 用户 y/n/feedback 三种回答的状态转换
- 消息历史里是否产出正确的"语义控制事件"而不是裸 y/n
- 工具拒绝时是否写占位 tool_result（半开事务闭合）
"""

from __future__ import annotations


from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    meta_complete_response,
    text_response,
)
from tests.test_main_loop import (
    _reset_core_module,
    _register_test_tool,
    _planner_no_plan_response,
)


def _planner_two_step_response() -> FakeResponse:
    """planner 返回一个两步 plan。"""
    plan_json = """{
        "steps_estimate": 2,
        "goal": "测试任务",
        "thinking": "分两步",
        "needs_confirmation": true,
        "steps": [
            {
                "step_id": "step-1",
                "title": "第一步",
                "description": "做第一件事",
                "step_type": "read",
                "suggested_tool": null,
                "expected_outcome": null,
                "completion_criteria": null
            },
            {
                "step_id": "step-2",
                "title": "第二步",
                "description": "做第二件事",
                "step_type": "report",
                "suggested_tool": null,
                "expected_outcome": null,
                "completion_criteria": null
            }
        ]
    }"""
    return FakeResponse(
        content=[FakeTextBlock(text=plan_json)],
        stop_reason="end_turn",
    )


# ---------- plan confirmation ----------

def test_plan_confirmation_yes_advances_to_running(monkeypatch):
    """用户回 y 之后 status 应当变成 running，进入主循环。"""
    fake = FakeAnthropicClient(
        responses=[
            _planner_two_step_response(),
            meta_complete_response(score=95, text="第一步做完了"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    # 第一次 chat：触发 planning
    reply1 = chat("帮我做个两步任务，每步确认")
    assert state.task.status == "awaiting_plan_confirmation"
    assert reply1 == ""   # 等待用户

    # 第二次 chat：用户 y
    chat("y")

    # 状态应当真的推进到执行态：running / awaiting_step / awaiting_tool
    # 不能是 idle（那表示 reset_task 了，说明 y 被错误当成了别的东西）
    # 也不能是 awaiting_plan_confirmation（y 没被识别为接受）
    assert state.task.current_plan is not None, "y 之后 plan 不应被清"
    assert state.task.status in (
        "running",
        "awaiting_step_confirmation",
        "awaiting_tool_confirmation",
    ), f"y 之后应当进入执行态，实际 status={state.task.status}"
    # messages 里应当有语义事件，而不是裸 "y"
    event_texts = [
        block.get("text", "")
        for msg in state.conversation.messages
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    assert any("用户接受当前计划" in t for t in event_texts), (
        f"plan y 应当写成'用户接受当前计划'事件，实际 events={event_texts}"
    )


def test_plan_confirmation_no_cancels_and_resets(monkeypatch):
    """用户回 n 之后任务应当被取消，state.task 回到 idle。"""
    fake = FakeAnthropicClient(
        responses=[_planner_two_step_response()]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("帮我做个两步任务，每步确认")
    assert state.task.status == "awaiting_plan_confirmation"

    reply = chat("n")

    assert "取消" in reply
    assert state.task.status == "idle"
    assert state.task.current_plan is None


# ---------- tool confirmation ----------

def test_tool_confirmation_no_writes_placeholder_result(monkeypatch):
    """用户拒绝工具时必须写占位 tool_result，让半开事务闭合。

    回归防护：如果"n" 分支忘了写占位，下一轮 API 调用会 400
    （tool_use_id 没有对应 tool_result）。
    """
    from tests.conftest import FakeToolUseBlock

    cleanup = _register_test_tool("risky_tool", confirmation="always")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeTextBlock(text="我要跑危险工具"),
                        FakeToolUseBlock(
                            id="T_RISKY",
                            name="risky_tool",
                            input={"arg": "dangerous"},
                        ),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("好的，跳过了"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑个危险工具")
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool["tool_use_id"] == "T_RISKY"

        # 用户拒绝
        chat("n")

        # T_RISKY 必须有 tool_result（占位也行）
        has_result = False
        for msg in state.conversation.messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") == "T_RISKY"
                    ):
                        has_result = True
                        break
        assert has_result, "用户拒绝工具后，messages 必须有对应的占位 tool_result"

        # pending_tool 应当被清空
        assert state.task.pending_tool is None
    finally:
        cleanup()


def test_tool_confirmation_yes_executes_and_continues(monkeypatch):
    """用户 y 之后工具真执行 + 进入下一次主循环。"""
    from tests.conftest import FakeToolUseBlock

    cleanup = _register_test_tool("safe_tool", confirmation="always", result="tool-ok")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeToolUseBlock(
                            id="T_SAFE",
                            name="safe_tool",
                            input={"arg": "fine"},
                        ),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("工具跑完了"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑个工具")
        assert state.task.status == "awaiting_tool_confirmation"

        reply = chat("y")

        # reply 是控制型 UI 文字，普通 end_turn 应为空（正文走流式）
        assert reply == "", f"end_turn reply 应为空，实际 {reply!r}"
        # 正文验证：最后一条 assistant 消息含模型的话
        last_assistant = [m for m in state.conversation.messages if m["role"] == "assistant"][-1]
        assert "工具跑完了" in str(last_assistant["content"])
        assert state.task.pending_tool is None
        assert state.task.status == "idle"
        assert state.task.tool_execution_log == {}
        from agent.conversation_events import has_tool_result
        assert has_tool_result(state.conversation.messages, "T_SAFE")
    finally:
        cleanup()


# ---------- 幂等性 ----------

def test_tool_execution_log_is_idempotent(monkeypatch):
    """同一个 tool_use_id 出现两次，第二次不应该重复执行工具。

    这是 checkpoint 恢复时的防御——恢复后如果模型历史里已经有某个 tool_use_id
    的结果，幂等表应当直接用缓存，不再跑工具。
    """
    from tests.conftest import FakeToolUseBlock

    call_count = [0]

    # 自己手动注册一个会计数的工具
    from agent.tool_registry import TOOL_REGISTRY, register_tool

    @register_tool(
        name="counter_tool",
        description="counter",
        parameters={"arg": {"type": "string", "description": "arg"}},
        confirmation="never",
    )
    def _counter_tool(**kw):
        call_count[0] += 1
        return f"call #{call_count[0]}"

    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                # 模型连续两次返回同一个 tool_use_id（真实场景可能是 checkpoint 恢复）
                FakeResponse(
                    content=[
                        FakeToolUseBlock(
                            id="T_DUP", name="counter_tool", input={"arg": "x"}
                        ),
                    ],
                    stop_reason="tool_use",
                ),
                FakeResponse(
                    content=[
                        FakeToolUseBlock(
                            id="T_DUP", name="counter_tool", input={"arg": "x"}
                        ),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("done"),
            ]
        )
        _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("跑工具")

        # 工具函数只应当被调用一次（第二次走幂等缓存）
        assert call_count[0] == 1, (
            f"同一个 tool_use_id 出现两次，工具函数应当只跑一次，实际跑了 {call_count[0]} 次"
        )
    finally:
        TOOL_REGISTRY.pop("counter_tool", None)
