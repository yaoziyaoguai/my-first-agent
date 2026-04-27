"""slash command registry 的边界回归测试。

这些测试只覆盖 UI/control command 执行层：InputIntent 已经负责分类，main.py 负责
把 CommandResult 投影成 RuntimeEvent。CommandRegistry 本身不能写 checkpoint、
conversation.messages、Anthropic API messages，也不能推进 TaskState 或制造
tool_result placeholder。
"""

from __future__ import annotations


def _fresh_state():
    """构造 command 测试所需的最小 state；registry 只能只读它。"""

    from agent.state import create_agent_state

    return create_agent_state(system_prompt="test")


def test_help_command_lists_current_specs_without_runtime_side_effects():
    """`/help` 是本地 UI/control 输出，不进入模型消息或 checkpoint。"""

    from agent.commands import CommandContext, DEFAULT_COMMAND_REGISTRY

    state = _fresh_state()
    before_messages = list(state.conversation.messages)

    result = DEFAULT_COMMAND_REGISTRY.execute("help", context=CommandContext(state=state))

    assert result.kind == "ok"
    assert result.command_name == "help"
    assert "/help" in result.message
    assert "/status" in result.message
    assert "/clear" in result.message
    assert "/reload_skills" in result.message
    assert state.conversation.messages == before_messages


def test_status_command_reads_runtime_state_without_mutating_it():
    """`/status` 只读 TaskState 摘要，不改变 pending 或 messages。"""

    from agent.commands import CommandContext, DEFAULT_COMMAND_REGISTRY

    state = _fresh_state()
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {"question": "预算是多少？"}
    before_messages = list(state.conversation.messages)

    result = DEFAULT_COMMAND_REGISTRY.execute("status", context=CommandContext(state=state))

    assert result.kind == "ok"
    assert "awaiting_user_input" in result.message
    assert "预算是多少？" in result.message
    assert state.task.pending_user_input_request == {"question": "预算是多少？"}
    assert state.conversation.messages == before_messages


def test_clear_command_is_ui_only_result_not_state_reset():
    """`/clear` 只返回 should_clear 信号，不清 Runtime state 或 checkpoint。

    这是 UI/control command 和 Runtime 状态机的边界测试：清屏是 adapter 呈现动作，
    不是 reset_task，不应写 conversation.messages，也不应影响 tool_use/tool_result
    配对。
    """

    from agent.commands import CommandContext, DEFAULT_COMMAND_REGISTRY

    state = _fresh_state()
    state.conversation.messages.append({"role": "user", "content": "保留历史"})

    result = DEFAULT_COMMAND_REGISTRY.execute("clear", context=CommandContext(state=state))

    assert result.kind == "ok"
    assert result.should_clear is True
    assert state.conversation.messages == [{"role": "user", "content": "保留历史"}]


def test_reload_skills_command_uses_injected_loader_and_rejects_args():
    """`/reload_skills` 复用现有 loader，但参数错误不应落入 chat/model。"""

    from agent.commands import CommandContext, DEFAULT_COMMAND_REGISTRY

    class FakeSkillRegistry:
        def count(self):
            return 3

        def get_warnings(self):
            return ["忽略重复 skill"]

    calls = {"reload": 0}

    def fake_reload_registry():
        calls["reload"] += 1
        return FakeSkillRegistry()

    result = DEFAULT_COMMAND_REGISTRY.execute(
        "reload_skills",
        context=CommandContext(reload_registry=fake_reload_registry),
    )
    invalid = DEFAULT_COMMAND_REGISTRY.execute(
        "reload_skills",
        "extra",
        context=CommandContext(reload_registry=fake_reload_registry),
    )

    assert result.kind == "ok"
    assert "3 个可用" in result.message
    assert "忽略重复 skill" in result.message
    assert invalid.kind == "invalid_args"
    assert "不接受参数" in invalid.message
    assert calls == {"reload": 1}


def test_unknown_command_is_consumed_as_control_error():
    """未知 slash command 应由 command 层消费，不能掉到 normal model message。"""

    from agent.commands import DEFAULT_COMMAND_REGISTRY

    result = DEFAULT_COMMAND_REGISTRY.execute("unknown", "abc")

    assert result.kind == "unknown"
    assert result.handled is True
    assert "/unknown" in result.message
    assert result.metadata == {"command_args": "abc"}
