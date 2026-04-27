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

    本测试只验证分类；真正命令执行在 CommandRegistry/main adapter。InputIntent
    不能进入 conversation.messages，也不能变成 RuntimeEvent 或 CommandResult。
    """

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    before_messages = list(state.conversation.messages)

    help_intent = classify_user_input("/help", source="tui", state=state)
    status_intent = classify_user_input("/status now", source="simple", state=state)

    assert help_intent.kind == "slash_command"
    assert help_intent.metadata == {
        "command": "/help",
        "command_name": "help",
        "command_args": "",
        "is_exit_command": False,
    }
    assert status_intent.kind == "slash_command"
    assert status_intent.metadata == {
        "command": "/status",
        "command_name": "status",
        "command_args": "now",
        "is_exit_command": False,
    }
    assert state.conversation.messages == before_messages


def test_slash_command_metadata_covers_known_unknown_and_exit_inputs():
    """slash metadata 只服务 adapter 控制输入，不执行 command。

    `/exit` 当前先归类为 exit，说明退出是 shell 控制输入；其它 slash command 只
    解析名称和参数，不写 checkpoint/messages，不触发 RuntimeEvent，也不替代
    CommandRegistry 的执行结果。
    """

    from agent.input_intents import classify_user_input

    cases = {
        "/clear": ("clear", ""),
        "/unknown abc": ("unknown", "abc"),
        "/reload_skills": ("reload_skills", ""),
    }

    for raw, (name, args) in cases.items():
        intent = classify_user_input(raw, source="tui")
        assert intent.kind == "slash_command"
        assert intent.metadata["command_name"] == name
        assert intent.metadata["command_args"] == args
        assert intent.metadata["is_exit_command"] is False

    exit_intent = classify_user_input("/exit", source="tui")
    assert exit_intent.kind == "exit"


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


def test_classify_confirmation_response_words_and_feedback():
    """确认词表应集中在 InputIntent 层，覆盖大小写、空格和中文。

    这是输入边界的回归测试：plan/step/tool confirmation 共享同一分类 helper；
    helper 不能把空文本或中文反馈误判为 accept/reject，也不能写 checkpoint/messages
    或影响 tool_result placeholder。
    """

    from agent.input_intents import classify_confirmation_response

    for raw in ("y", "yes", "Y", "YES", "  yes  ", "是", "确认", "可以", "好"):
        assert classify_confirmation_response(raw) == "accept"

    for raw in ("n", "no", "N", "NO", "  no  ", "否", "不", "取消"):
        assert classify_confirmation_response(raw) == "reject"

    for raw in ("", "   ", "请把第二步改成先分析", "不是这个意思，换一种方案"):
        assert classify_confirmation_response(raw) == "feedback"


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


def test_request_user_reply_priority_keeps_yes_as_pending_reply():
    """pending_user_input_request 下的 yes 是用户答复，不是 confirmation。

    这条保护 request_user_input 的输入边界：pending 请求的回复会在 Runtime 层继续
    投影为 user_replied/step_input 语义，而不是被 adapter 误判成普通新任务或
    plan/tool confirmation。这里不改变 tool_result placeholder 或 checkpoint schema。
    """

    from agent.input_intents import classify_user_input

    state = _fresh_state()
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "是否需要高铁？",
        "why_needed": "用于继续当前步骤",
    }

    intent = classify_user_input("yes", source="tui", state=state)

    assert intent.kind == "request_user_reply"
    assert intent.metadata == {"awaiting_kind": "request_user_input"}


def test_control_inputs_keep_current_priority_over_pending_states():
    """固化当前 adapter 优先级：control 输入先于 pending 状态。

    这是当前产品语义，不在本阶段私自改变：empty/exit/slash 属于 UI/control
    输入，可以在 pending_user_input_request、pending_tool 或 plan confirmation
    期间被 adapter 先识别。后续若要禁止 slash 打断 pending 状态，应单独设计，
    不能把 InputIntent 写进 checkpoint/messages 或混入 RuntimeEvent。
    """

    from agent.input_intents import classify_user_input

    request_state = _fresh_state()
    request_state.task.status = "awaiting_user_input"
    request_state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "预算？",
    }

    slash = classify_user_input("/status", source="tui", state=request_state)
    assert slash.kind == "slash_command"
    assert slash.metadata["command_name"] == "status"
    help_command = classify_user_input("/help", source="simple", state=request_state)
    assert help_command.kind == "slash_command"
    assert help_command.metadata["command_name"] == "help"
    assert "awaiting_kind" not in help_command.metadata
    assert classify_user_input("   ", source="tui", state=request_state).kind == "empty"
    assert classify_user_input("/exit", source="tui", state=request_state).kind == "exit"

    tool_state = _fresh_state()
    tool_state.task.status = "awaiting_tool_confirmation"
    tool_state.task.pending_tool = {"tool_use_id": "T1", "tool": "write_file"}
    tool_slash = classify_user_input("/status", source="simple", state=tool_state)
    assert tool_slash.kind == "slash_command"
    assert tool_slash.metadata["command_name"] == "status"

    plan_state = _fresh_state()
    plan_state.task.status = "awaiting_plan_confirmation"
    plan_slash = classify_user_input("/status", source="tui", state=plan_state)
    assert plan_slash.kind == "slash_command"
    assert plan_slash.metadata["command_name"] == "status"


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


def test_textual_and_simple_classify_slash_commands_consistently():
    """Textual 和 simple 对 slash command 的 metadata 应一致。

    source 只记录 adapter 来源；command_name/command_args 这类输入语义必须共享，
    避免 simple CLI 历史字符串协议继续散落到 Textual 产品主路径。
    """

    from agent.input_intents import classify_user_input

    textual = classify_user_input("/status now", source="tui")
    simple = classify_user_input("/status now", source="simple")

    assert textual.kind == simple.kind == "slash_command"
    assert textual.metadata == simple.metadata
    assert textual.metadata["command_name"] == "status"
    assert textual.metadata["command_args"] == "now"


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


# ---------------------------------------------------------------------------
# classify_feedback_intent: feedback 输入二次分类（结构化策略）
# ---------------------------------------------------------------------------
# 这一组测试保护“awaiting_plan/step confirmation 反馈分支”上的二次分类边界：
# 它只读 raw text 和 plan metadata，不修改 state、不写 messages/checkpoint、不发
# RuntimeEvent，也不影响 tool_use_id / tool_result placeholder / request_user_input
# 语义。结构性规则：明确的“新任务祈使前缀”+ 与 plan 词表零字符重叠 → 视为话题
# 切换；其它一律保守落在 feedback_to_current_plan，避免反馈语义漂移。


def _plan(goal: str, *step_titles: str) -> dict:
    """构造最小 plan dict 供分类器消费；不触发 planner 或 schema 校验。"""

    return {
        "goal": goal,
        "steps": [
            {"title": title, "description": title, "step_type": "read"}
            for title in step_titles
        ],
    }


def test_classify_feedback_intent_detects_obvious_topic_switch():
    """“帮我写一首关于春天的诗” 与“分析文档”任务零重叠 → 话题切换。"""

    from agent.input_intents import classify_feedback_intent

    plan = _plan("原任务：分析文档", "原任务-s1", "原任务-s2")
    assert (
        classify_feedback_intent("帮我写一首关于春天的诗", plan=plan)
        == "new_task_topic_switch"
    )


def test_classify_feedback_intent_keeps_plan_modifying_inputs_as_feedback():
    """历史反馈用例不应被误判为话题切换，避免 confirm_handlers 反馈语义漂移。"""

    from agent.input_intents import classify_feedback_intent

    plan = _plan("做个复杂任务", "方案A-第一步", "方案A-第二步")
    # 没有强“新任务祈使前缀”——一律走 feedback。
    assert (
        classify_feedback_intent("我想要更详细一点的分解", plan=plan)
        == "feedback_to_current_plan"
    )
    assert (
        classify_feedback_intent("又改主意了，还是两步就行", plan=plan)
        == "feedback_to_current_plan"
    )
    assert (
        classify_feedback_intent("换成 edit 类型的", plan=plan)
        == "feedback_to_current_plan"
    )


def test_classify_feedback_intent_blocks_switch_when_text_overlaps_plan_vocab():
    """带“帮我”祈使但仍引用 plan 词汇时，结构性回退为 feedback。

    这条用例固化“正向信号 + 结构性零重叠”双条件——避免引入反馈关键词黑名单。
    """

    from agent.input_intents import classify_feedback_intent

    plan = _plan("整理报告", "读取文档", "撰写小结")
    # “帮我”祈使语，但内容仍然在谈“文档/小结/报告”——仍是反馈。
    assert (
        classify_feedback_intent("帮我把读取文档那一步拆成两步", plan=plan)
        == "feedback_to_current_plan"
    )


def test_classify_feedback_intent_handles_missing_plan_safely():
    """无 plan / 空白输入下行为可预测，不抛错。"""

    from agent.input_intents import classify_feedback_intent

    assert classify_feedback_intent("", plan=None) == "feedback_to_current_plan"
    assert classify_feedback_intent("   ", plan=None) == "feedback_to_current_plan"
    # 没有 plan 时，新任务祈使语足以归类为 topic_switch。
    assert (
        classify_feedback_intent("帮我写一首诗", plan=None)
        == "new_task_topic_switch"
    )
