"""main.read_user_input 多行输入协议单元测试。

不触发真实 input() / 主循环——通过依赖注入 reader/writer 喂预录序列。
覆盖：
- 单行输入原样返回（不破坏历史行为）
- /multi + /done 拼接所有中间行
- /multi + /cancel 返回 None（让主循环跳过本轮）
- ``` 围栏 + ``` 结束 拼接所有中间行
- /multi 中 stdin 提前关闭（EOFError）→ 把已收集行当 done 提交，不丢数据
"""

from __future__ import annotations

from agent.user_input import (
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)


def _make_reader(lines):
    """把字符串列表包成一个一次性 reader：每次 reader() 弹出一行。"""
    queue = list(lines)

    def reader(_prompt: str = "") -> str:
        if not queue:
            raise EOFError("test reader exhausted")
        return queue.pop(0)

    return reader


def _silent_writer(*_args, **_kwargs) -> None:
    """吞掉 _collect_multiline 的提示文案，避免污染 pytest 输出。"""
    return None


# ============================================================
# 1. 普通单行输入：与历史行为一致
# ============================================================

def test_single_line_input_returned_verbatim():
    """普通一行输入应原样返回（不 strip——strip 由 main_loop 外层做）。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader(["hello world"]),
        writer=_silent_writer,
    )
    assert out == "hello world"


def test_single_line_with_leading_slash_not_misrouted():
    """非 /multi / /``` 的普通输入即便以斜杠开头也直接返回，
    交给主循环的 handle_slash_command 处理（如 /reload_skills）。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader(["/reload_skills"]),
        writer=_silent_writer,
    )
    assert out == "/reload_skills"


# ============================================================
# 2. /multi + /done：完整拼接多行
# ============================================================

def test_multi_mode_with_done_returns_joined_lines():
    """/multi → 收集 line1/line2/line3 → /done → 返回 "\\n".join。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "/multi",
            "下周一到周三出行",
            "从北京出发偏好高铁",
            "豪华型住宿",
            "自然风光",
            "单人出行",
            "/done",
        ]),
        writer=_silent_writer,
    )
    assert out == (
        "下周一到周三出行\n"
        "从北京出发偏好高铁\n"
        "豪华型住宿\n"
        "自然风光\n"
        "单人出行"
    )


def test_multi_mode_done_with_surrounding_whitespace_still_terminates():
    """/done 周围有空白也应识别为终止信号——_collect_multiline 用 strip 比对。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader(["/multi", "line1", "  /done  "]),
        writer=_silent_writer,
    )
    assert out == "line1"


# ============================================================
# 3. /multi + /cancel：返回 None
# ============================================================

def test_multi_mode_cancel_returns_none():
    """/multi → 中途 /cancel → 返回 None；调用方应跳过本轮，**不**调 chat。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "/multi",
            "我打错了",
            "再来一行",
            "/cancel",
        ]),
        writer=_silent_writer,
    )
    assert out is None


# ============================================================
# 4. ``` 围栏：进入粘贴模式，``` 结束
# ============================================================

def test_paste_fence_collects_until_closing_fence():
    """``` 起头 → 收集到下一个单独的 ``` → 返回中间所有行拼接。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "```",
            "def foo():",
            "    return 42",
            "",
            "print(foo())",
            "```",
        ]),
        writer=_silent_writer,
    )
    assert out == "def foo():\n    return 42\n\nprint(foo())"


def test_paste_fence_no_cancel_token():
    """围栏模式下 /cancel 不应被识别为取消——应当作普通内容收集。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "```",
            "/cancel",   # 在围栏里这是普通内容
            "more",
            "```",
        ]),
        writer=_silent_writer,
    )
    assert out == "/cancel\nmore"


# ============================================================
# 5. EOF 鲁棒性：多行模式下 stdin 关闭不丢数据
# ============================================================

def test_multi_mode_eof_treats_as_done():
    """收集中途 stdin 关闭（EOFError）→ 把已收集行当 done 提交，避免 stdin 关闭吞掉用户输入。"""
    from main import read_user_input

    out = read_user_input(
        reader=_make_reader([
            "/multi",
            "first",
            "second",
            # 后面没有 /done——reader 队列耗尽抛 EOFError
        ]),
        writer=_silent_writer,
    )
    assert out == "first\nsecond"


def test_main_loop_passes_latest_reply_to_next_input_event(monkeypatch):
    """Textual 下一轮输入应拿到上一轮用户可见回复，但 main 不解释输出语义。"""

    import main

    seen_latest_outputs = []
    events = [
        submitted_input_event(
            build_user_input_envelope("你是哪种大模型", source="cli"),
            source="simple",
            channel="test",
        ),
        closed_input_event(source="simple", channel="test"),
    ]

    def fake_read_user_input_event(*, latest_output: str = "", **_kwargs):
        """记录 main loop 传给输入后端的最近输出，并返回预置事件。"""

        seen_latest_outputs.append(latest_output)
        return events.pop(0)

    monkeypatch.setattr(main, "read_user_input_event", fake_read_user_input_event)
    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        """simple CLI 新主路径会传 RuntimeEvent sink；旧 return 语义仍可兜底。"""

        assert on_runtime_event is not None
        return "我是一个测试回复"

    monkeypatch.setattr(main, "chat", fake_chat)
    monkeypatch.setattr(main, "finalize_session", lambda: None)
    monkeypatch.setattr(main, "print", lambda *_args, **_kwargs: None, raising=False)

    main.main_loop()

    assert seen_latest_outputs == ["", "我是一个测试回复"]


def test_main_loop_simple_cli_uses_command_registry_for_help(monkeypatch, capsys):
    """simple CLI fallback 和 Textual 共用同一个 command 执行层。

    simple CLI 没有 Textual 的 RuntimeEvent sink，所以 main.py 会把 CommandResult
    投影成 command.result 后再渲染到终端。这里不能让 `/help` 进入 chat，也不能写
    checkpoint/messages；它只是 debug/fallback adapter 的输出方式不同。
    """

    import main

    events = [
        submitted_input_event(
            build_user_input_envelope("/help", source="cli"),
            source="simple",
            channel="test",
        ),
        closed_input_event(source="simple", channel="test"),
    ]

    monkeypatch.setattr(
        main,
        "read_user_input_event",
        lambda **_kwargs: events.pop(0),
    )
    monkeypatch.setattr(
        main,
        "chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("/help 不应进入 chat")
        ),
    )
    monkeypatch.setattr(main, "finalize_session", lambda: None)

    main.main_loop()

    out = capsys.readouterr().out
    assert "可用命令" in out
    assert "/help" in out


def test_simple_backend_passes_runtime_event_sink_to_chat(monkeypatch, capsys):
    """simple CLI 应消费 RuntimeEvent，而不是依赖 core.py 无 sink print fallback。

    这个测试保护第四阶段边界：RuntimeEvent 是 Runtime -> UI 的用户可见输出主路径；
    simple CLI renderer 只负责终端投影，不写 checkpoint、conversation.messages 或
    Anthropic API messages，也不接收 runtime_observer/debug 日志。
    """

    import main
    from agent.display_events import assistant_delta

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("你"))
        on_runtime_event(assistant_delta("好"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    reply, latest = main._run_chat_for_backend("你好", backend="simple")
    captured = capsys.readouterr()

    assert reply == ""
    assert latest == "你好"
    assert captured.out == "你好\n"


def test_textual_runtime_turn_is_product_adapter_not_simple_cli(monkeypatch, capsys):
    """Textual 产品路径只投递 RuntimeEvent sink，不调用 simple CLI renderer。

    这是 TUI-first 边界回归：main.py 可以继续做 adapter dispatch，但 Textual
    主路径不能把 simple CLI fallback 的 print renderer 当作产品输出源，也不能把
    checkpoint、runtime_observer、conversation.messages、Anthropic API messages 或
    TaskState 语义混进 UI adapter。
    """

    import main
    from agent.display_events import assistant_delta

    events = []

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("TUI"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    reply, latest = main._run_textual_runtime_turn(
        "你好",
        on_runtime_event=events.append,
    )
    captured = capsys.readouterr()

    assert reply == ""
    assert latest == ""
    assert [event.text for event in events] == ["TUI"]
    assert captured.out == ""


def test_simple_cli_runtime_turn_is_fallback_adapter_without_legacy_callbacks(
    monkeypatch,
    capsys,
):
    """simple CLI fallback 通过 RuntimeEvent renderer 输出，不接旧 callback。

    simple CLI 是调试/兜底 adapter，不应反过来定义 Textual 产品能力。这个测试保护
    它只给 core.chat 传 on_runtime_event，不传 on_output_chunk/on_display_event；
    输入协议、checkpoint、runtime_observer 和状态机本体都不应进入这个输出边界。
    """

    import main
    from agent.display_events import assistant_delta

    def fake_chat(
        _user_input: str,
        *,
        on_runtime_event=None,
        on_output_chunk=None,
        on_display_event=None,
    ) -> str:
        assert on_runtime_event is not None
        assert on_output_chunk is None
        assert on_display_event is None
        on_runtime_event(assistant_delta("CLI"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    reply, latest = main._run_simple_cli_runtime_turn("你好")
    captured = capsys.readouterr()

    assert reply == ""
    assert latest == "CLI"
    assert captured.out == "CLI\n"


def test_simple_backend_renders_control_runtime_event(monkeypatch, capsys):
    """control/tool lifecycle 类 RuntimeEvent 在 simple CLI 也应直接可见。

    这里不把控制文案塞进模型消息或 checkpoint；测试只验证 I/O adapter 消费
    RuntimeEvent 后终端可见，避免回退到 stdout capture 或字符串过滤补丁。
    """

    import main
    from agent.display_events import control_message

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(control_message("等待用户确认"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    reply, latest = main._run_chat_for_backend("写文件", backend="simple")
    captured = capsys.readouterr()

    assert reply == ""
    assert latest == ""
    assert "等待用户确认" in captured.out


def test_simple_backend_does_not_repeat_streamed_final_reply(monkeypatch, capsys):
    """已 streaming 的 assistant.delta 不应再通过 final reply 打印第二遍。

    这是 simple CLI 的防重复回归：RuntimeEvent sink 已经输出正文时，旧 return-value
    兼容层只能更新 latest_output，不能让 main_loop 把同一段 assistant 文本再 print。
    """

    import main
    from agent.display_events import assistant_delta

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("你好"))
        return "你好"

    monkeypatch.setattr(main, "chat", fake_chat)

    reply, latest = main._run_chat_for_backend("你好", backend="simple")
    captured = capsys.readouterr()

    assert reply == ""
    assert latest == "你好"
    assert captured.out == "你好\n"


def test_textual_main_loop_captures_printed_chat_output_as_latest_output(monkeypatch):
    """Textual 下普通 assistant 流式 print 也应进入下一轮 output_panel。"""

    import main

    monkeypatch.setenv(main.INPUT_BACKEND_ENV, "textual")

    seen_latest_outputs = []
    events = [
        submitted_input_event(
            build_user_input_envelope("你是哪种大模型", source="tui"),
            source="tui",
            channel="test",
        ),
        cancelled_input_event(source="tui", channel="test"),
        closed_input_event(source="tui", channel="test"),
    ]

    def fake_read_user_input_event(*, latest_output: str = "", **_kwargs):
        """记录每一轮传给 textual backend 的 latest_output。"""

        seen_latest_outputs.append(latest_output)
        return events.pop(0)

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        """模拟 core.chat 普通 end_turn：正文 print，返回空串避免重复打印。"""

        assert on_runtime_event is not None
        print("我是流式测试回复")
        return ""

    monkeypatch.setattr(main, "read_user_input_event", fake_read_user_input_event)
    monkeypatch.setattr(main, "chat", fake_chat)
    monkeypatch.setattr(main, "load_checkpoint", lambda: False)
    monkeypatch.setattr(main, "handle_interrupt_without_checkpoint", lambda: False)
    monkeypatch.setattr(main, "finalize_session", lambda: None)

    main.main_loop()

    assert seen_latest_outputs == [
        "",
        "我是流式测试回复",
        "我是流式测试回复",
    ]


def test_textual_latest_output_filters_debug_observer_lines():
    """checkpoint/runtime 观测日志不应被塞进 TUI output_panel。"""

    import main

    captured = "\n".join([
        "[CHECKPOINT] saved (status=running)",
        "[RUNTIME_EVENT] event_type=debug",
        "用户可见回复",
    ])

    assert main._merge_chat_outputs("", captured) == "用户可见回复"


def test_textual_latest_output_filters_checkpoint_debug_resolution_prefixes():
    """TUI 只接收用户可见文本，不接收 runtime/checkpoint/debug 前缀日志。"""

    import main

    captured = "\n".join([
        "[CHECKPOINT] saved (status=running, source=test)",
        "[DEBUG] checkpoint payload would be noisy",
        "[RUNTIME_EVENT] event_type=loop.stop",
        "event_type=loop.stop event_source=runtime",
        "[INPUT_RESOLUTION] resolution_kind=runtime_user_input_answer",
        "[TRANSITION] from_state=awaiting_user_input target_state=running",
        "[ACTIONS] action_names=append_step_input,save_checkpoint",
        "真正用户可见文本",
        "[提示] 这行是用户可见文本，不应因为有中括号被误过滤",
    ])

    assert main._merge_chat_outputs("", captured) == (
        "真正用户可见文本\n"
        "[提示] 这行是用户可见文本，不应因为有中括号被误过滤"
    )


def test_textual_shell_input_handler_returns_printed_chat_output(monkeypatch):
    """常驻 Textual Shell 通过 main 桥接拿到普通 assistant 流式输出。"""

    import main

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        """模拟 core.chat：正文 print，返回空串。"""

        assert on_runtime_event is not None
        print("我是常驻 TUI 回复")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input("你好") == "我是常驻 TUI 回复"


def test_textual_shell_input_handler_forwards_output_chunks(monkeypatch):
    """deprecated on_output_chunk 兼容层仍可用，但不是 Textual 主路径。

    Textual Shell 新路径只传 on_runtime_event 给 core.chat；这个测试保护旧调用方显式
    传 on_output_chunk 时仍能通过 main.py 的 RuntimeEvent 兼容桥收到 assistant delta。
    兼容层不能扩大成新 UI 输出协议，也不写 checkpoint、runtime_observer、
    conversation.messages 或 Anthropic API messages。
    """

    import main
    from agent.display_events import assistant_delta

    seen_chunks = []

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("你"))
        on_runtime_event(assistant_delta("好"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    result = main._handle_textual_shell_input(
        "你好",
        on_output_chunk=seen_chunks.append,
    )

    assert seen_chunks == ["你", "好"]
    assert result == ""


def test_textual_shell_input_handler_forwards_display_events(monkeypatch):
    """deprecated on_display_event 兼容层仍可用，但不是 Textual 主路径。

    新 DisplayEvent 应先包装成 RuntimeEvent；这里验证旧调用方显式传
    on_display_event 时，仍通过 main.py 的 RuntimeEvent 兼容桥收到结构化 UI 投影，
    不把 debug/stdout 当作主出口。
    """

    import main
    from agent.display_events import DisplayEvent, runtime_display_event

    seen_events = []
    event = DisplayEvent(
        event_type="tool.awaiting_confirmation",
        title="需要确认工具调用",
        body="工具: write_file\n路径: demo.md",
    )

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(runtime_display_event(event))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    result = main._handle_textual_shell_input(
        "写文件",
        on_display_event=seen_events.append,
    )

    assert seen_events == [event]
    assert result == ""


def test_textual_shell_input_handler_forwards_runtime_events(monkeypatch):
    """main bridge 优先用 RuntimeEvent，不再让新输出依赖 stdout capture。"""

    import main
    from agent.display_events import assistant_delta, control_message

    seen_events = []

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("你"))
        on_runtime_event(assistant_delta("好"))
        on_runtime_event(control_message("等待确认"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    result = main._handle_textual_shell_input(
        "你好",
        on_runtime_event=seen_events.append,
    )

    assert [event.event_type for event in seen_events] == [
        "assistant.delta",
        "assistant.delta",
        "control.message",
    ]
    assert [event.text for event in seen_events] == ["你", "好", "等待确认"]
    assert result == ""


def test_textual_shell_input_handler_renders_runtime_events_without_stdout(monkeypatch):
    """传入 RuntimeEvent sink 后，新控制文案不需要经过 stdout capture。"""

    import main
    from agent.display_events import control_message

    seen_events = []

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(control_message("工具等待确认"))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input(
        "写文件",
        on_runtime_event=seen_events.append,
    ) == ""
    assert [event.text for event in seen_events] == ["工具等待确认"]


def test_textual_runtime_event_suppresses_duplicate_stdout_completion(monkeypatch):
    """RuntimeEvent 主路径已投递时，stdout capture 不能再返回同一语义。

    这是 Runtime -> UI 边界的回归保护：新输出已经由 on_runtime_event 进入 Textual，
    captured stdout 只允许作为没有事件时的旧代码兜底，不能再制造 final reply 覆盖
    或重复追加。测试不新增字符串过滤，只验证桥接职责收窄。
    """

    import main
    from agent.display_events import control_message

    seen_events = []

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(control_message("等待确认"))
        print("等待确认")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input(
        "写文件",
        on_runtime_event=seen_events.append,
    ) == ""
    assert [event.text for event in seen_events] == ["等待确认"]


def test_textual_runtime_event_ignores_unrelated_captured_stdout(monkeypatch):
    """RuntimeEvent 主路径已覆盖用户可见输出时，不再合并 captured stdout。

    这是第五阶段 stdout capture 收窄的关键回归：captured stdout 只兜底没有
    RuntimeEvent 的旧 print-era 路径。只要 RuntimeEvent 已投递到 Textual，main.py
    就不能把同轮 print 文案当 final completion 再塞回 conversation view；这里不把
    checkpoint、runtime_observer、conversation.messages、Anthropic API messages 或
    debug print 混进 UI 输出边界。
    """

    import main
    from agent.display_events import control_message

    seen_events = []

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(control_message("RuntimeEvent 主路径"))
        print("旧 stdout 文案不应进入 Textual latest_output")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input(
        "触发事件",
        on_runtime_event=seen_events.append,
    ) == ""
    assert [event.text for event in seen_events] == ["RuntimeEvent 主路径"]


def test_textual_runtime_event_sink_keeps_stdout_fallback_when_no_event(monkeypatch):
    """未迁移旧代码没有发 RuntimeEvent 时，stdout capture 仍作为兜底。"""

    import main

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        print("旧路径用户可见输出")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input(
        "旧路径",
        on_runtime_event=lambda _event: None,
    ) == "旧路径用户可见输出"


def test_textual_stdout_fallback_filters_debug_when_runtime_event_sink_has_no_event(
    monkeypatch,
):
    """有 RuntimeEvent sink 但本轮无事件时，stdout fallback 仍过滤内部观测日志。

    这是兼容层的边界测试：fallback 只服务旧 print-era 用户可见文案，不能把
    checkpoint/runtime_observer/debug terminal log 投进 TUI；同时不新增任何字符串前缀
    规则，只验证既有隔离仍然生效。
    """

    import main

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        print("[CHECKPOINT] saved (status=running)")
        print("[RUNTIME_EVENT] event_type=loop.stop")
        print("[INPUT_RESOLUTION] resolution_kind=test")
        print("旧路径用户可见文本")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input(
        "旧路径",
        on_runtime_event=lambda _event: None,
    ) == "旧路径用户可见文本"


def test_runtime_event_helper_still_forwards_legacy_callbacks():
    """RuntimeEvent 可集中转发到 deprecated 旧 callback，且不要求 stdout 参与。

    这是 main.py 的兼容桥回归：RuntimeEvent 仍是唯一输入，旧 output/display callback
    只作为临时转发目标存在。这里不能引入 checkpoint、runtime_observer、
    conversation.messages、Anthropic API messages 或新的输出协议。
    """

    import main
    from agent.display_events import DisplayEvent, assistant_delta, runtime_display_event

    chunks = []
    display_events = []
    event = DisplayEvent(
        event_type="tool.awaiting_confirmation",
        title="需要确认工具调用",
        body="工具: write_file",
    )

    streamed = main._forward_runtime_event_to_legacy_callbacks(
        assistant_delta("你"),
        on_output_chunk=chunks.append,
        on_display_event=display_events.append,
    )
    display_streamed = main._forward_runtime_event_to_legacy_callbacks(
        runtime_display_event(event),
        on_output_chunk=chunks.append,
        on_display_event=display_events.append,
    )

    assert chunks == ["你"]
    assert display_events == [event]
    assert streamed is True
    assert display_streamed is False


def test_textual_runtime_event_does_not_duplicate_into_legacy_callbacks(monkeypatch):
    """Textual 主路径提供 RuntimeEvent sink 时，不应再触发旧 callback。

    旧 callback 是 deprecated compatibility bridge；如果 on_runtime_event 已经存在，
    同一条 assistant.delta 或 DisplayEvent 不能再通过 on_output_chunk/on_display_event
    重复进入 UI。这个测试保护 RuntimeEvent 主路径优先级，不涉及状态机或 API messages。
    """

    import main
    from agent.display_events import DisplayEvent, assistant_delta, runtime_display_event

    events = []
    chunks = []
    display_events = []
    display_event = DisplayEvent(
        event_type="tool.awaiting_confirmation",
        title="需要确认工具调用",
        body="工具: write_file",
    )

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("你"))
        on_runtime_event(runtime_display_event(display_event))
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    _reply, latest = main._run_chat_for_backend(
        "写文件",
        backend="textual",
        on_runtime_event=events.append,
        on_output_chunk=chunks.append,
        on_display_event=display_events.append,
    )

    assert [event.event_type for event in events] == [
        "assistant.delta",
        "tool.confirmation_requested",
    ]
    assert chunks == []
    assert display_events == []
    assert latest == ""


def test_textual_shell_slash_command_uses_runtime_event(monkeypatch, capsys):
    """Textual slash command 主路径应走 command.result，而不是 stdout capture。

    这是 adapter 控制输入，不是模型 user message；识别后不应进入 chat，也不写
    conversation.messages/checkpoint。InputIntent metadata 只把 command_name/args
    传给 CommandRegistry，不能变成 RuntimeEvent 输入或复杂插件系统。
    """

    import main
    from agent import checkpoint
    from agent.state import create_agent_state

    class FakeRegistry:
        def count(self):
            return 2

        def get_warnings(self):
            return ["忽略了重复 skill"]

    monkeypatch.setattr(main, "reload_registry", lambda: FakeRegistry())
    monkeypatch.setattr(
        main,
        "chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recognized slash command 不应进入 chat")
        ),
    )
    state = create_agent_state(system_prompt="test")
    before_messages = list(state.conversation.messages)
    checkpoint_calls = {"save": 0}
    monkeypatch.setattr(main, "get_state", lambda: state)
    monkeypatch.setattr(
        checkpoint,
        "save_checkpoint",
        lambda *_args, **_kwargs: checkpoint_calls.__setitem__(
            "save",
            checkpoint_calls["save"] + 1,
        ),
    )

    events = []
    result = main._handle_textual_shell_input(
        "/reload_skills",
        on_runtime_event=events.append,
    )
    captured = capsys.readouterr()

    assert result == ""
    assert [event.event_type for event in events] == ["command.result"]
    assert "Skill 已重新加载" in events[0].text
    assert "忽略了重复 skill" in events[0].text
    assert "Skill 已重新加载" not in captured.out
    assert state.conversation.messages == before_messages
    assert checkpoint_calls == {"save": 0}


def test_handle_slash_command_rejects_invalid_args_without_reparsing(monkeypatch, capsys):
    """command handler 消费 InputIntent metadata，并结构化拒绝非法参数。

    `/reload_skills` 当前只支持无参数形式；带参数的 slash command 应由
    CommandRegistry 消费成 control error，不能继续掉入 chat/model。这里保留旧解析
    fallback，但新路径不能写 messages/checkpoint，不能混入 RuntimeEvent 输入或
    tool_result placeholder。
    """

    import main

    monkeypatch.setattr(
        main,
        "reload_registry",
        lambda: (_ for _ in ()).throw(
            AssertionError("带参数的 reload_skills 不应执行")
        ),
    )

    handled = main.handle_slash_command(
        "/reload_skills extra",
        command_name="reload_skills",
        command_args="extra",
    )

    assert handled is True
    out = capsys.readouterr().out
    assert "/reload_skills 不接受参数" in out


def test_textual_shell_help_status_and_clear_use_command_registry(monkeypatch):
    """Textual 产品路径通过 CommandRegistry 输出 command.result。

    这是 RuntimeEvent/InputIntent/CommandResult 三层边界测试：command 不进入
    conversation.messages，不写 checkpoint，不调用 chat；`/clear` 只暴露 UI 清屏信号，
    不 reset Runtime state。
    """

    import main
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {"question": "预算是多少？"}
    state.conversation.messages.append({"role": "user", "content": "历史仍保留"})

    monkeypatch.setattr(main, "get_state", lambda: state)
    monkeypatch.setattr(
        main,
        "chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("slash command 不应进入 chat")
        ),
    )

    events = []
    for command in ("/help", "/status", "/clear"):
        assert main._handle_textual_shell_input(command, on_runtime_event=events.append) == ""

    assert [event.event_type for event in events] == [
        "command.result",
        "command.result",
        "command.result",
    ]
    assert "/help" in events[0].text
    assert "awaiting_user_input" in events[1].text
    assert "预算是多少？" in events[1].text
    assert events[2].metadata["should_clear"] is True
    assert state.conversation.messages == [{"role": "user", "content": "历史仍保留"}]


def test_textual_request_user_reply_is_forwarded_to_runtime(monkeypatch):
    """request_user_input reply 不在 main.py 被当成新任务或 confirmation 消费。

    pending_user_input_request 的状态推进仍属于 core/chat/confirm_handlers；Textual
    adapter 只分类并把原始回复交给 Runtime，不写 checkpoint/messages，也不改变
    user_replied/step_input 或 tool_result placeholder 语义。
    """

    import main
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "是否选择高铁？",
        "why_needed": "继续当前 step",
    }
    calls = []

    def fake_run_chat_for_backend(user_input: str, **kwargs):
        calls.append((user_input, kwargs))
        return "ok", "ok"

    monkeypatch.setattr(main, "get_state", lambda: state)
    monkeypatch.setattr(main, "_run_chat_for_backend", fake_run_chat_for_backend)

    result = main._handle_textual_shell_input("yes")

    assert result == "ok"
    assert len(calls) == 1
    assert calls[0][0] == "yes"
    assert calls[0][1]["backend"] == "textual"


def test_textual_shell_slash_command_stdout_fallback_only_without_runtime_sink(
    monkeypatch,
    capsys,
):
    """slash command 的 stdout capture 只保留给没有 RuntimeEvent sink 的旧路径。

    CommandRegistry 已有 command.result 主路径；本测试只保护旧调用方仍能看到
    print fallback。这里不写 checkpoint、conversation.messages 或 Anthropic API
    messages；后续新增 slash command 应优先事件化。
    """

    import main

    class FakeRegistry:
        def count(self):
            return 1

        def get_warnings(self):
            return []

    monkeypatch.setattr(main, "reload_registry", lambda: FakeRegistry())

    result = main._handle_textual_shell_input("/reload_skills")
    captured = capsys.readouterr()

    assert "Skill 已重新加载" in result
    assert "Skill 已重新加载" not in captured.out


def test_textual_shell_unknown_slash_with_runtime_sink_returns_command_error(
    monkeypatch,
):
    """未知 slash command 由 CommandRegistry 消费，不再落入模型消息。

    这是 command 结构化后的边界：未知 command 仍是 UI/control 输入，不是用户给模型
    的 normal message；输出走 command.result RuntimeEvent，不写 checkpoint/messages。
    """

    import main

    def fake_chat(user_input: str, *, on_runtime_event=None) -> str:
        raise AssertionError(f"未知 command 不应进入 chat: {user_input}")

    monkeypatch.setattr(main, "chat", fake_chat)

    events = []
    result = main._handle_textual_shell_input(
        "/unknown_command",
        on_runtime_event=events.append,
    )

    assert result == ""
    assert [event.event_type for event in events] == ["command.result"]
    assert "未知命令 /unknown_command" in events[0].text


def test_pending_user_input_help_command_interrupts_current_pending(monkeypatch):
    """pending 状态下 slash command 当前允许打断业务等待。

    这里固化的是现有产品语义：InputIntent 在 pending_user_input_request 前先识别
    slash/control 输入，CommandRegistry 消费 `/help`，不会把它当 request_user_reply，
    也不会写 conversation.messages/checkpoint。若未来要禁止这种打断，需要单独产品
    决策，不能在 command handler 里偷偷读取 pending 状态改行为。
    """

    import main
    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = {"question": "预算是多少？"}
    before_messages = list(state.conversation.messages)
    monkeypatch.setattr(main, "get_state", lambda: state)
    monkeypatch.setattr(
        main,
        "chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("/help 不应作为 request_user_reply 进入 chat")
        ),
    )

    events = []
    result = main._handle_textual_shell_input("/help", on_runtime_event=events.append)

    assert result == ""
    assert [event.event_type for event in events] == ["command.result"]
    assert "/help" in events[0].text
    assert state.task.pending_user_input_request == {"question": "预算是多少？"}
    assert state.conversation.messages == before_messages


def test_textual_shell_input_handler_passes_confirmation_text_to_chat(monkeypatch):
    """TUI 输入 y 时，main bridge 只能原样交给 Runtime，不解释确认语义。

    这条同时保护本阶段收窄：Textual runtime turn 调用 core.chat 时只传
    RuntimeEvent sink，不再把旧 on_output_chunk 当作进入 Runtime 的主入口。
    """

    import main

    seen_calls = []

    def fake_chat(user_input: str, *, on_runtime_event=None) -> str:
        """记录 main.py 传给 core.chat 的原始文本。"""

        seen_calls.append((user_input, on_runtime_event is not None))
        return "继续执行"

    monkeypatch.setattr(main, "chat", fake_chat)

    chunks = []
    result = main._handle_textual_shell_input(
        "y",
        on_output_chunk=chunks.append,
    )

    assert seen_calls == [("y", True)]
    assert result == "继续执行"
    assert chunks == []


def test_textual_shell_input_handler_drops_stdout_when_chunks_streamed(monkeypatch):
    """streaming 已写入 TUI 时，stdout capture 不能再作为 completion 重复返回。"""

    import main

    seen_chunks = []

    from agent.display_events import assistant_delta

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        assert on_runtime_event is not None
        on_runtime_event(assistant_delta("你"))
        on_runtime_event(assistant_delta("好"))
        print("你好")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    result = main._handle_textual_shell_input(
        "你好",
        on_output_chunk=seen_chunks.append,
    )

    assert seen_chunks == ["你", "好"]
    assert result == ""


def test_textual_shell_input_handler_filters_debug_output(monkeypatch):
    """debug/checkpoint/runtime observer 文本不能进入 conversation view。"""

    import main

    def fake_chat(_user_input: str, *, on_runtime_event=None) -> str:
        """模拟 stdout 混有用户可见文本和内部观测日志。"""

        assert on_runtime_event is not None
        print("[CHECKPOINT] saved (status=running)")
        print("[RUNTIME_EVENT] event_type=assistant_text")
        print("用户可见回复")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input("你好") == "用户可见回复"


def test_run_textual_main_loop_uses_persistent_shell_and_finalizes(monkeypatch):
    """textual backend 入口应走常驻 Shell，不再每轮创建 one-shot App。"""

    import main
    import agent.input_backends.textual as textual_backend

    calls = []

    def fake_shell(*, chat_handler, prompt_text="你: "):
        """记录 main 传入的 chat_handler，避免启动真实 TUI。"""

        calls.append((chat_handler, prompt_text))

    finalized = []

    monkeypatch.setattr(textual_backend, "run_textual_io_shell", fake_shell)
    monkeypatch.setattr(main, "finalize_session", lambda: finalized.append(True))

    main.run_textual_main_loop()

    assert len(calls) == 1
    assert calls[0][0] is main._handle_textual_shell_input
    assert finalized == [True]
