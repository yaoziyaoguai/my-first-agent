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
    monkeypatch.setattr(main, "chat", lambda _user_input: "我是一个测试回复")
    monkeypatch.setattr(main, "finalize_session", lambda: None)
    monkeypatch.setattr(main, "print", lambda *_args, **_kwargs: None, raising=False)

    main.main_loop()

    assert seen_latest_outputs == ["", "我是一个测试回复"]


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

    def fake_chat(_user_input: str, *, on_output_chunk=None) -> str:
        """模拟 core.chat 普通 end_turn：正文 print，返回空串避免重复打印。"""

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

    def fake_chat(_user_input: str, *, on_output_chunk=None) -> str:
        """模拟 core.chat：正文 print，返回空串。"""

        print("我是常驻 TUI 回复")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    assert main._handle_textual_shell_input("你好") == "我是常驻 TUI 回复"


def test_textual_shell_input_handler_forwards_output_chunks(monkeypatch):
    """main bridge 应把 on_output_chunk 透传给 core.chat。"""

    import main

    seen_chunks = []

    def fake_chat(_user_input: str, *, on_output_chunk=None) -> str:
        assert on_output_chunk is not None
        on_output_chunk("你")
        on_output_chunk("好")
        return ""

    monkeypatch.setattr(main, "chat", fake_chat)

    result = main._handle_textual_shell_input(
        "你好",
        on_output_chunk=seen_chunks.append,
    )

    assert seen_chunks == ["你", "好"]
    assert result == ""


def test_textual_shell_input_handler_passes_confirmation_text_to_chat(monkeypatch):
    """TUI 输入 y 时，main bridge 只能原样交给 Runtime，不解释确认语义。"""

    import main

    seen_calls = []

    def fake_chat(user_input: str, *, on_output_chunk=None) -> str:
        """记录 main.py 传给 core.chat 的原始文本。"""

        seen_calls.append((user_input, on_output_chunk is not None))
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

    def fake_chat(_user_input: str, *, on_output_chunk=None) -> str:
        assert on_output_chunk is not None
        on_output_chunk("你")
        on_output_chunk("好")
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

    def fake_chat(_user_input: str, *, on_output_chunk=None) -> str:
        """模拟 stdout 混有用户可见文本和内部观测日志。"""

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
