"""simple backend 的窄测试。

simple backend 是旧 input()/multi 协议的 fallback，不是终局 TUI。它的职责是
保留历史 CLI 行为，同时把结果统一包装成 UserInputEvent；cancelled/closed
不能被伪造成空字符串，也不能直接触发 Runtime 决策。
"""

from __future__ import annotations

from agent.input_backends.simple import read_user_input_event


def _make_reader(lines):
    """把预置行序列伪装成 input()，用于稳定复现终端输入。"""

    queue = list(lines)

    def reader(_prompt: str = "") -> str:
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    return reader


def _silent_writer(*_args, **_kwargs) -> None:
    """吞掉多行模式提示，避免测试输出干扰断言。"""

    return None


def test_simple_backend_single_line_returns_submitted_event():
    """普通一行输入应成为 input.submitted，并完整保留 raw_text。"""

    event = read_user_input_event(
        reader=_make_reader(["hello"]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.event_source == "simple"
    assert event.event_channel == "stdin"
    assert event.envelope is not None
    assert event.envelope.raw_text == "hello"
    assert event.envelope.input_mode == "single_line"


def test_simple_backend_empty_line_is_submitted_empty_envelope():
    """空输入仍是 submitted 文本，后续由 Runtime empty guard 处理。"""

    event = read_user_input_event(
        reader=_make_reader(["   "]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.envelope is not None
    assert event.envelope.raw_text == "   "
    assert event.envelope.is_empty is True
    assert event.envelope.input_mode == "empty"


def test_simple_backend_multi_mode_preserves_multiline_text():
    """/multi fallback 必须保留完整多行内容和空行。"""

    event = read_user_input_event(
        reader=_make_reader([
            "/multi",
            "北京出发",
            "",
            "预算 3500",
            "/done",
        ]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.envelope is not None
    assert event.envelope.raw_text == "北京出发\n\n预算 3500"
    assert event.envelope.normalized_text == "北京出发\n\n预算 3500"
    assert event.envelope.input_mode == "multiline"
    assert event.envelope.line_count == 3


def test_simple_backend_multi_cancel_returns_cancelled_event():
    """/multi 中 /cancel 是取消输入，不是提交空文本。"""

    event = read_user_input_event(
        reader=_make_reader(["/multi", "draft", "/cancel"]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.cancelled"
    assert event.event_source == "simple"
    assert event.event_channel == "multi_cancel"
    assert event.envelope is None


def test_simple_backend_keyboard_interrupt_returns_cancelled_event():
    """首行 Ctrl+C 映射为 input.cancelled，由 main loop 复用中断流程。"""

    event = read_user_input_event(
        reader=_make_reader([KeyboardInterrupt()]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.cancelled"
    assert event.event_channel == "keyboard_interrupt"
    assert event.envelope is None


def test_simple_backend_eof_returns_closed_event():
    """首行 EOF 表示输入流关闭，不应进入 chat。"""

    event = read_user_input_event(
        reader=_make_reader([EOFError()]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.closed"
    assert event.event_source == "simple"
    assert event.event_channel == "eof"
    assert event.envelope is None


def test_simple_backend_eof_during_multi_submits_collected_lines():
    """多行收集中 EOF 按既有 fallback 行为提交已收集内容，避免吞掉输入。"""

    event = read_user_input_event(
        reader=_make_reader(["/multi", "first", "second", EOFError()]),
        writer=_silent_writer,
    )

    assert event.event_type == "input.submitted"
    assert event.envelope is not None
    assert event.envelope.raw_text == "first\nsecond"
    assert event.envelope.input_mode == "multiline"
    assert event.envelope.line_count == 2
