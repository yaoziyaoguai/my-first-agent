"""InputIntent 输入边界回归测试。

这些测试保护 UI Adapter -> Runtime 的第一层语义分类：它只能读 raw input 和
TaskState 的 pending/awaiting 字段，不能修改 state、写 checkpoint/messages、触发
RuntimeEvent 或改变 Anthropic API messages。
"""

from __future__ import annotations


def _fresh_state():
    """构造最小 AgentState；测试只读 task 字段，不触发 Runtime。"""

    from agent.state import create_agent_state

    return create_agent_state(system_prompt="test")


def test_classifies_normal_message():
    """普通用户消息应保持 normal_message，不被 adapter 误判成控制输入。"""

    from agent.input_intents import classify_user_input

    intent = classify_user_input("帮我规划三天行程", source="tui")

    assert intent.kind == "normal_message"
    assert intent.raw_text == "帮我规划三天行程"
    assert intent.normalized_text == "帮我规划三天行程"
    assert intent.source == "tui"


def test_classifies_slash_commands_without_writing_runtime_state():
    """slash command 是 UI adapter 控制输入，不应写 messages/checkpoint。

    本测试只验证分类；真正命令执行仍在 main.handle_slash_command。InputIntent
    不能进入 conversation.messages，也不能变成 RuntimeEvent 或 command registry。
    """

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    before_messages = list(state.conversation.messages)

    help_intent = classify_user_input("/help", source="tui", state=state)
    status_intent = classify_user_input("/status now", source="simple", state=state)

    assert help_intent.kind == "slash_command"
    assert help_intent.metadata == {"command": "/help"}
    assert status_intent.kind == "slash_command"
    assert status_intent.metadata == {"command": "/status"}
    assert state.conversation.messages == before_messages


def test_classifies_empty_exit_cancel_and_eof():
    """empty/exit/cancel/eof 是 adapter 控制输入，不应落入普通消息。"""

    from agent.input_intents import classify_user_input

    assert classify_user_input("   ", source="tui").kind == "empty"
    assert classify_user_input("quit", source="simple").kind == "exit"
    assert classify_user_input("/exit", source="tui").kind == "exit"
    assert classify_user_input(
        None,
        source="simple",
        event_type="input.cancelled",
    ).kind == "cancel"
    assert classify_user_input(
        None,
        source="simple",
        event_type="input.closed",
    ).kind == "eof"


def test_classifies_plan_confirmation_accept_and_feedback():
    """awaiting_plan_confirmation 下，输入先被标记为计划确认语义。

    这里只归一 yes/no/反馈，不推进状态；状态推进仍由 confirm_handlers 负责，避免
    InputIntent 替代 TaskState 或写 checkpoint/messages。
    """

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    state.task.status = "awaiting_plan_confirmation"

    for raw in ("y", "yes", "是"):
        intent = classify_user_input(raw, source="tui", state=state)
        assert intent.kind == "plan_confirmation"
        assert intent.metadata["confirmation_response"] == "accept"

    feedback = classify_user_input("第二步先别写文件", source="tui", state=state)
    assert feedback.kind == "plan_confirmation"
    assert feedback.metadata["confirmation_response"] == "feedback"


def test_classifies_tool_confirmation_reject():
    """pending_tool 下，n/no/否 应统一标记为 tool_confirmation reject。"""

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    state.task.status = "awaiting_tool_confirmation"
    state.task.pending_tool = {"tool_use_id": "T1", "tool": "write_file", "input": {}}

    for raw in ("n", "no", "否"):
        intent = classify_user_input(raw, source="tui", state=state)
        assert intent.kind == "tool_confirmation"
        assert intent.metadata["confirmation_response"] == "reject"


def test_classifies_request_user_input_reply_and_collect_input_reply():
    """awaiting_user_input 两种来源都先归入用户回复语义，并保留来源元信息。"""

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {
        "question": "预算是多少？",
        "why_needed": "用于规划",
    }

    runtime_reply = classify_user_input("3000 元", source="tui", state=state)
    assert runtime_reply.kind == "request_user_reply"
    assert runtime_reply.metadata["awaiting_kind"] == "request_user_input"

    state.task.pending_user_input_request = None
    collect_reply = classify_user_input("北京出发", source="simple", state=state)
    assert collect_reply.kind == "request_user_reply"
    assert collect_reply.metadata["awaiting_kind"] == "collect_input"


def test_textual_and_simple_classify_same_raw_input_consistently():
    """Textual 产品路径和 simple CLI fallback 应共享输入语义分类。

    source 字段保留 adapter 来源，但 kind/metadata 对同一 raw input 应一致；这能防止
    simple CLI 的历史协议反向支配 Textual 主路径。
    """

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    state.task.status = "awaiting_step_confirmation"

    textual = classify_user_input("好的", source="tui", state=state)
    simple = classify_user_input("好的", source="simple", state=state)

    assert textual.kind == simple.kind == "step_confirmation"
    assert textual.metadata == simple.metadata == {"confirmation_response": "accept"}
    assert textual.source == "tui"
    assert simple.source == "simple"


def test_input_intent_does_not_enter_messages_or_checkpoint(monkeypatch):
    """分类函数必须无副作用，不能写 messages/checkpoint 或触发持久化。

    InputIntent 是 adapter 边界对象，不是 RuntimeEvent，不是 checkpoint schema，也不是
    conversation.messages 或 Anthropic API messages 的一部分。
    """

    from agent import checkpoint
    from agent.input_intents import classify_user_input

    state = _fresh_state()
    state.task.status = "awaiting_plan_confirmation"
    before_messages = list(state.conversation.messages)
    calls = {"save": 0, "clear": 0}

    monkeypatch.setattr(
        checkpoint,
        "save_checkpoint",
        lambda *_args, **_kwargs: calls.__setitem__("save", calls["save"] + 1),
    )
    monkeypatch.setattr(
        checkpoint,
        "clear_checkpoint",
        lambda *_args, **_kwargs: calls.__setitem__("clear", calls["clear"] + 1),
    )

    intent = classify_user_input("yes", source="tui", state=state)

    assert intent.kind == "plan_confirmation"
    assert state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0}
