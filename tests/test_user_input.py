"""UserInputEvent / UserInputEnvelope 的架构语义测试。

这些测试保护的是：用户输入正在从裸字符串升级成 Runtime 输入事件。
输入层只能描述“发生了什么”，不能提前做 Runtime 决策；submitted 才能携带
文本 envelope，cancelled/closed 不是空输入，不能被送进 chat。
"""

from __future__ import annotations

import pytest

from agent.user_input import (
    UserInputEvent,
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)


def test_build_user_input_envelope_single_line_preserves_text():
    """单行输入应保留 raw_text，并标记为 single_line。"""

    envelope = build_user_input_envelope("hello world", source="cli")

    assert envelope.raw_text == "hello world"
    assert envelope.normalized_text == "hello world"
    assert envelope.input_mode == "single_line"
    assert envelope.source == "cli"
    assert envelope.line_count == 1
    assert envelope.is_empty is False


def test_build_user_input_envelope_multiline_preserves_all_lines():
    """多行输入不能被拆散或丢空行，这是后续 TUI 的核心边界。"""

    raw_text = "北京出发\r\n偏好高铁\r\n\r\n预算 3500"
    envelope = build_user_input_envelope(raw_text, source="tui")

    assert envelope.raw_text == raw_text
    assert envelope.normalized_text == "北京出发\n偏好高铁\n\n预算 3500"
    assert "预算 3500" in envelope.normalized_text
    assert envelope.input_mode == "multiline"
    assert envelope.source == "tui"
    assert envelope.line_count == 4
    assert envelope.is_empty is False


def test_build_user_input_envelope_empty_input_is_still_submitted_text():
    """空白文本只标记 is_empty，不在输入层伪造成 cancel/close。"""

    envelope = build_user_input_envelope("  \n\t", source="cli")

    assert envelope.raw_text == "  \n\t"
    assert envelope.normalized_text == "  \n\t"
    assert envelope.input_mode == "empty"
    assert envelope.line_count == 2
    assert envelope.is_empty is True


def test_submitted_input_event_requires_envelope():
    """submitted 是唯一能进入 Runtime 的输入事件，因此必须带 envelope。"""

    envelope = build_user_input_envelope("go", source="cli")
    event = submitted_input_event(envelope, source="simple", channel="stdin")

    assert event.event_type == "input.submitted"
    assert event.event_source == "simple"
    assert event.event_channel == "stdin"
    assert event.envelope == envelope

    with pytest.raises(ValueError, match="must carry"):
        UserInputEvent(
            event_type="input.submitted",
            event_source="simple",
            event_channel="stdin",
        )


def test_cancelled_input_event_does_not_carry_envelope():
    """cancelled 代表用户取消输入，不是提交空字符串。"""

    event = cancelled_input_event(source="simple", channel="keyboard_interrupt")

    assert event.event_type == "input.cancelled"
    assert event.event_source == "simple"
    assert event.event_channel == "keyboard_interrupt"
    assert event.envelope is None

    envelope = build_user_input_envelope("", source="cli")
    with pytest.raises(ValueError, match="must not carry"):
        UserInputEvent(
            event_type="input.cancelled",
            event_source="simple",
            event_channel="keyboard_interrupt",
            envelope=envelope,
        )


def test_closed_input_event_does_not_carry_envelope():
    """closed 代表 stdin/TUI 关闭，不应进入 chat 或 empty_user_input。"""

    event = closed_input_event(source="tui", channel="ctrl_d")

    assert event.event_type == "input.closed"
    assert event.event_source == "tui"
    assert event.event_channel == "ctrl_d"
    assert event.envelope is None

    envelope = build_user_input_envelope("ignored", source="tui")
    with pytest.raises(ValueError, match="must not carry"):
        UserInputEvent(
            event_type="input.closed",
            event_source="tui",
            event_channel="ctrl_d",
            envelope=envelope,
        )
