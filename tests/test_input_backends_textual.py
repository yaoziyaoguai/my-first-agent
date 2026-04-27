"""Textual backend 的 smoke test。

Textual backend 只是显式启用的 TUI v1 skeleton：它只做 I/O adapter，不碰
Runtime state，不保存 checkpoint，不判断 plan/tool/step。UserInputEvent 是
TUI/simple backend 和 main loop 的边界；cancelled/closed 不是空输入，不能进入
chat。
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading

import pytest

from agent.display_events import assistant_delta, control_message, runtime_display_event


def _require_textual():
    """Textual 是可选依赖；未安装时用 xfail 记录当前可观测风险。"""

    if importlib.util.find_spec("textual") is None:
        pytest.xfail(
            "当前环境未安装 optional textual 包，无法运行 headless TUI smoke。"
            "这暴露的风险是显式启用 MY_FIRST_AGENT_INPUT_BACKEND=textual 后才会"
            "发现依赖/构造问题；安装 textual 后应转为普通通过测试。"
        )


def test_textual_backend_app_class_can_be_built_when_dependency_exists():
    """安装 Textual 时，TUI App 类应可构造，并暴露预期 widget 标识。"""

    _require_textual()

    from agent.input_backends.textual import _build_textual_app_class

    app_cls = _build_textual_app_class()
    app = app_cls(prompt_text="你: ", latest_output="last answer")

    assert app.prompt_text == "你: "
    assert app.latest_output == "last answer"
    assert ".output-panel" in app.CSS
    assert ".input-panel" in app.CSS
    assert ".help-bar" in app.CSS

    bindings = {(key, action) for key, action, _description in app.BINDINGS}
    assert ("ctrl+s", "submit") in bindings
    assert ("escape", "cancel") in bindings
    assert ("ctrl+q", "close_input") in bindings
    assert ("ctrl+d", "close_input") not in bindings


def test_textual_backend_headless_smoke_exposes_real_widget_ids_and_classes():
    """用 Textual headless smoke 钉住 compose 产出的真实 widget 标识。"""

    _require_textual()

    from textual.widgets import Static, TextArea

    from agent.input_backends.textual import _build_textual_app_class

    async def run_smoke() -> None:
        """只验证 TUI I/O 外壳结构，不模拟复杂用户交互。"""

        app_cls = _build_textual_app_class()
        app = app_cls(prompt_text="你: ", latest_output="last answer")

        async with app.run_test():
            output_panel = app.query_one("#output-panel", Static)
            input_area = app.query_one("#input-area", TextArea)
            help_bar = app.query_one("#help-bar", Static)

            assert output_panel.id == "output-panel"
            assert "output-panel" in output_panel.classes
            assert output_panel.content == "last answer"
            assert input_area.id == "input-area"
            assert "input-panel" in input_area.classes
            assert help_bar.id == "help-bar"
            assert "help-bar" in help_bar.classes
            assert "你:" in help_bar.content
            assert "Ctrl+Q" in help_bar.content
            assert "Ctrl+D" not in help_bar.content

    asyncio.run(run_smoke())


def test_textual_backend_output_panel_uses_empty_output_placeholder():
    """没有最近输出时，output panel 不能把输入 prompt 当成输出。"""

    _require_textual()

    from textual.widgets import Static

    from agent.input_backends.textual import _build_textual_app_class

    async def run_smoke() -> None:
        """只确认最近输出为空时的展示文案，不扩展历史或渲染逻辑。"""

        app_cls = _build_textual_app_class()
        app = app_cls(prompt_text="你: ", latest_output="")

        async with app.run_test():
            output_panel = app.query_one("#output-panel", Static)

            assert output_panel.content != "你: "
            assert "暂无模型输出" in output_panel.content

    asyncio.run(run_smoke())


def test_textual_backend_submit_helper_preserves_raw_multiline_text():
    """不启动真实 UI 时，也要钉住 TextArea 文本到 submitted event 的边界。"""

    from agent.input_backends.textual import (
        _cancelled_textual_event,
        _closed_textual_event,
        _submitted_textual_event,
    )

    raw_text = "line1\n\nline3"
    submitted = _submitted_textual_event(raw_text)
    cancelled = _cancelled_textual_event()
    closed = _closed_textual_event()

    assert submitted.event_type == "input.submitted"
    assert submitted.event_source == "tui"
    assert submitted.event_channel == "text_area_submit"
    assert submitted.envelope is not None
    assert submitted.envelope.raw_text == raw_text
    assert submitted.envelope.input_mode == "multiline"

    assert cancelled.event_type == "input.cancelled"
    assert cancelled.envelope is None

    assert closed.event_type == "input.closed"
    assert closed.envelope is None


def test_textual_shell_headless_smoke_exposes_conversation_and_input_widgets():
    """常驻 Shell 应暴露滚动对话区、输入区和帮助栏。"""

    _require_textual()

    from textual.containers import VerticalScroll
    from textual.widgets import Static, TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """只验证常驻 I/O Shell 的结构，不触碰 Runtime。"""

        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda _text, on_runtime_event=None: "ok",
            prompt_text="你: ",
        )

        async with app.run_test():
            scroller = app.query_one("#conversation-scroll", VerticalScroll)
            conversation = app.query_one("#conversation-view", Static)
            input_area = app.query_one("#input-area", TextArea)
            help_bar = app.query_one("#help-bar", Static)

            assert scroller.id == "conversation-scroll"
            assert "output-panel" in scroller.classes
            assert conversation.id == "conversation-view"
            assert input_area.id == "input-area"
            assert "input-panel" in input_area.classes
            assert help_bar.id == "help-bar"
            assert "help-bar" in help_bar.classes
            assert "Enter 提交" in help_bar.content
            assert "Ctrl+Q 退出" in help_bar.content
            assert "Ctrl+D" not in help_bar.content

    asyncio.run(run_smoke())


def test_textual_shell_submit_shows_user_and_assistant_placeholder_immediately():
    """提交后先显示 You/Assistant 占位并清空输入，刷新后才调用 chat_handler。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """用直接方法调用验证核心行为，避免复杂 UI 自动化。"""

        app_cls = _build_textual_shell_app_class()
        call_order = []

        def fake_chat_handler(text: str, on_runtime_event=None) -> str:
            """记录模型调用发生在 You 消息之后。"""

            call_order.append(("chat", list(app.conversation_history)))
            return f"收到：{text}"

        app = app_cls(chat_handler=fake_chat_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("你好")

            event = app.submit_current_input()

            assert event is not None
            assert event.event_type == "input.submitted"
            assert input_area.text == ""
            assert app.return_value is None
            assert call_order == []
            assert app.conversation_history == [
                ("You", "你好"),
                ("Assistant", "正在思考..."),
            ]

            await pilot.pause()
            await pilot.pause()

            assert call_order == [
                ("chat", [
                    ("You", "你好"),
                    ("Assistant", "正在思考..."),
                ])
            ]
            assert app.conversation_history == [
                ("You", "你好"),
                ("Assistant", "收到：你好"),
            ]

    asyncio.run(run_smoke())


def test_textual_shell_preserves_user_message_when_chat_handler_fails():
    """chat_handler 抛错时，You 消息仍保留，只追加简短错误提示。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """错误提示不能包含 traceback 大段内容。"""

        def failing_handler(_text: str, on_runtime_event=None) -> str:
            raise RuntimeError("boom")

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=failing_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("会失败的问题")

            app.submit_current_input()
            assert app.conversation_history == [
                ("You", "会失败的问题"),
                ("Assistant", "正在思考..."),
            ]

            await pilot.pause()
            await pilot.pause()

            assert app.conversation_history[0] == ("You", "会失败的问题")
            assert app.conversation_history[1][0] == "Assistant"
            assert "处理输入时发生错误" in app.conversation_history[1][1]
            assert "Traceback" not in app.conversation_history[1][1]

    asyncio.run(run_smoke())


def test_textual_shell_appends_output_chunks_before_completion():
    """chunk 完成后即使 chat_handler 返回空串，Assistant 也不能消失。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """只断言最终 chunk 聚合结果，不写脆弱时间依赖。"""

        def streaming_handler(_text: str, on_runtime_event=None) -> str:
            assert on_runtime_event is not None
            on_runtime_event(assistant_delta("你"))
            on_runtime_event(assistant_delta("好"))
            return ""

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=streaming_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("打招呼")

            app.submit_current_input()
            await pilot.pause()
            await pilot.pause()

            assert app.conversation_history == [
                ("You", "打招呼"),
                ("Assistant", "你好"),
            ]

    asyncio.run(run_smoke())


def test_textual_shell_streaming_chunks_are_not_duplicated_by_final_reply():
    """chunk 聚合后 final reply 相同也不能重复或覆盖成异常内容。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """最终稳定内容应是一次完整回复。"""

        def streaming_handler(_text: str, on_runtime_event=None) -> str:
            assert on_runtime_event is not None
            on_runtime_event(assistant_delta("你"))
            on_runtime_event(assistant_delta("好"))
            return "你好"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=streaming_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("打招呼")

            app.submit_current_input()
            await pilot.pause()
            await pilot.pause()

            assert app.conversation_history == [
                ("You", "打招呼"),
                ("Assistant", "你好"),
            ]

    asyncio.run(run_smoke())


def test_textual_shell_streaming_chunks_with_different_final_reply_stay_single_message():
    """streaming + final reply 只能保留一条 Assistant 消息。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """chunk 聚合内容不能被 final reply 再追加一遍。"""

        def streaming_handler(_text: str, on_runtime_event=None) -> str:
            assert on_runtime_event is not None
            on_runtime_event(assistant_delta("已经完成"))
            on_runtime_event(assistant_delta("方案"))
            return "已经完成方案"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=streaming_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("做方案")

            app.submit_current_input()
            await pilot.pause()
            await pilot.pause()

            assistant_messages = [
                message for role, message in app.conversation_history
                if role == "Assistant"
            ]
            assert assistant_messages == ["已经完成方案"]
            assert assistant_messages[0] != "已经完成方案已经完成方案"

    asyncio.run(run_smoke())


def test_textual_shell_non_streaming_reply_replaces_placeholder():
    """没有 chunk 时，完整返回值仍作为非 streaming fallback 显示。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """占位应被完整回复替换。"""

        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda _text, on_runtime_event=None: "完整回复",
            prompt_text="你: ",
        )

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("问题")

            app.submit_current_input()
            await pilot.pause()
            await pilot.pause()

            assert app.conversation_history == [
                ("You", "问题"),
                ("Assistant", "完整回复"),
            ]

    asyncio.run(run_smoke())


def test_textual_shell_renders_display_event_as_tool_message():
    """DisplayEvent 应作为 Tool 消息显示，不混进 Assistant streaming 文本。"""

    _require_textual()

    from agent.display_events import DisplayEvent
    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda _text, on_runtime_event=None: "unused",
            prompt_text="你: ",
        )

        async with app.run_test():
            event = DisplayEvent(
                event_type="tool.awaiting_confirmation",
                title="需要确认工具调用",
                body="工具: write_file\n路径: demo.md\n是否执行？",
            )
            app.append_display_event(event)

            assert app.conversation_history == [
                (
                    "Tool",
                    "[需要确认工具调用]\n工具: write_file\n路径: demo.md\n是否执行？",
                )
            ]

    asyncio.run(run_smoke())


def test_textual_shell_renders_runtime_display_and_control_events():
    """RuntimeEvent 是 Textual 的统一入口，不再靠 display callback 猜接口。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.display_events import DisplayEvent
    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        event = DisplayEvent(
            event_type="tool.awaiting_confirmation",
            title="需要确认工具调用",
            body="工具: write_file\n路径: demo.md",
        )

        def handler(_text: str, on_runtime_event=None) -> str:
            assert on_runtime_event is not None
            on_runtime_event(runtime_display_event(event))
            on_runtime_event(control_message("等待确认"))
            return ""

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("写文件")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert ("Tool", "[需要确认工具调用]\n工具: write_file\n路径: demo.md") in (
                app.conversation_history
            )
            assert ("System", "等待确认") in app.conversation_history
            assert app.conversation_history[1] == ("Assistant", "[无输出]")

    asyncio.run(run_smoke())


def test_textual_shell_redraw_conversation_is_idempotent():
    """重复 redraw 不应让 conversation view 出现重复 transcript。"""

    _require_textual()

    from textual.widgets import Static

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """Static update 是替换内容，不是向 RichLog 继续 append。"""

        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda _text, on_runtime_event=None: "unused",
            prompt_text="你: ",
        )

        async with app.run_test():
            view = app.query_one("#conversation-view", Static)
            app.conversation_history = [
                ("You", "你好"),
                ("Assistant", "完整回复"),
            ]

            app._redraw_conversation()
            first_render = view.content
            app._redraw_conversation()

            assert view.content == first_render
            assert view.content.count("Assistant:") == 1
            assert view.content.count("完整回复") == 1

    asyncio.run(run_smoke())


def test_textual_shell_long_plan_prompt_scrolls_to_confirmation_question():
    """长计划输出后，确认问题必须保留并自动滚到可见位置。"""

    _require_textual()

    from textual.containers import VerticalScroll
    from textual.widgets import Static, TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """复现真实 TUI 中长计划撑满视口后看不到 y/n 提示的问题。"""

        plan_text = "\n".join([
            "📋 任务规划：为用户制定武汉+宜昌三天两夜旅游行程规划",
            *[
                f"{index}. 这是一段较长的计划说明，用来撑满 conversation view。"
                for index in range(1, 80)
            ],
            "按此计划执行吗？(y/n/输入修改意见):",
        ])

        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda _text, on_runtime_event=None: plan_text,
            prompt_text="你: ",
        )

        async with app.run_test(size=(80, 20)) as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("帮我规划武汉宜昌三天游")

            await pilot.press("enter")
            for _ in range(5):
                await pilot.pause()

            view = app.query_one("#conversation-view", Static)
            scroller = app.query_one("#conversation-scroll", VerticalScroll)

            assert app.conversation_history[-1] == ("Assistant", plan_text)
            assert "按此计划执行吗？" in str(view.content)
            assert scroller.max_scroll_y > 0
            assert scroller.scroll_y == scroller.max_scroll_y

    asyncio.run(run_smoke())


def test_textual_shell_plan_confirmation_prompt_releases_next_submit():
    """计划确认提示完成后，下一次输入 y 必须还能提交到 handler。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """TUI 不理解 y，只验证 raw_text 第二次仍进入 main/runtime handler。"""

        calls = []

        def fake_handler(text: str, on_runtime_event=None) -> str:
            calls.append(text)
            if len(calls) == 1:
                return "📋 任务规划...\n按此计划执行吗？(y/n/输入修改意见):"
            return "继续执行"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=fake_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("帮我规划武汉宜昌三天游")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert calls == ["帮我规划武汉宜昌三天游"]
            assert app.is_generating is False
            assert input_area.text == ""
            assert app.conversation_history[-1] == (
                "Assistant",
                "📋 任务规划...\n按此计划执行吗？(y/n/输入修改意见):",
            )

            input_area.load_text("y")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert calls == ["帮我规划武汉宜昌三天游", "y"]
            assert input_area.text == ""
            assert app.is_generating is False

    asyncio.run(run_smoke())


def test_textual_shell_streaming_plan_prompt_releases_next_submit():
    """流式计划确认提示结束后，TUI 也必须恢复可输入。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """覆盖 output.chunk 完成后 return 空串的确认场景。"""

        calls = []

        def fake_handler(text: str, on_runtime_event=None) -> str:
            calls.append(text)
            if len(calls) == 1:
                assert on_runtime_event is not None
                on_runtime_event(assistant_delta("📋 任务规划..."))
                on_runtime_event(assistant_delta("\n按此计划执行吗？(y/n/输入修改意见):"))
                return ""
            return "已确认"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=fake_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("帮我规划武汉宜昌三天游")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert calls == ["帮我规划武汉宜昌三天游"]
            assert app.is_generating is False
            assert app.conversation_history[-1] == (
                "Assistant",
                "📋 任务规划...\n按此计划执行吗？(y/n/输入修改意见):",
            )

            input_area.load_text("y")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert calls == ["帮我规划武汉宜昌三天游", "y"]
            assert app.is_generating is False

    asyncio.run(run_smoke())


def test_textual_shell_busy_does_not_swallow_confirmation_input():
    """计划提示已显示但 worker 还没结束时，Enter 也不能吞掉 y。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """复现 output.chunk 可见但 is_generating 仍为 True 的窗口期。"""

        calls = []
        first_handler_entered = threading.Event()

        def fake_handler(text: str, on_runtime_event=None) -> str:
            calls.append(text)
            if len(calls) == 1:
                assert on_runtime_event is not None
                on_runtime_event(assistant_delta("📋 任务规划..."))
                on_runtime_event(assistant_delta("\n按此计划执行吗？(y/n/输入修改意见):"))
                first_handler_entered.set()
                threading.Event().wait(timeout=0.3)
                return ""
            return "已确认，继续执行"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=fake_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("帮我规划武汉宜昌三天游")
            await pilot.press("enter")

            assert first_handler_entered.wait(timeout=2)
            await pilot.pause()
            assert app.is_generating is True
            assert app.conversation_history[-1] == (
                "Assistant",
                "📋 任务规划...\n按此计划执行吗？(y/n/输入修改意见):",
            )

            input_area.load_text("y")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()

            assert calls == ["帮我规划武汉宜昌三天游", "y"]
            assert app.is_generating in (False, True)
            assert input_area.text == ""
            assert ("You", "y") in app.conversation_history
            assert app.conversation_history[-1] == ("Assistant", "已确认，继续执行")

    asyncio.run(run_smoke())


def test_textual_shell_request_user_input_prompt_releases_next_submit():
    """request_user_input 类提示后，用户补充信息仍能继续提交。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """TUI 只提交 raw_text，不判断补充信息语义。"""

        calls = []

        def fake_handler(text: str, on_runtime_event=None) -> str:
            calls.append(text)
            if len(calls) == 1:
                return "请补充预算、人数、出发城市"
            return "收到补充信息"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=fake_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("做旅行计划")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert app.is_generating is False

            input_area.load_text("预算 3000，两人，从北京出发")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert calls == ["做旅行计划", "预算 3000，两人，从北京出发"]
            assert app.is_generating is False

    asyncio.run(run_smoke())


def test_textual_shell_error_path_releases_next_submit():
    """handler 抛错后也不能永久卡住下一次输入。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """错误提示显示后，下一次 submit 仍进入 handler。"""

        calls = []

        def fake_handler(text: str, on_runtime_event=None) -> str:
            calls.append(text)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return "恢复正常"

        app_cls = _build_textual_shell_app_class()
        app = app_cls(chat_handler=fake_handler, prompt_text="你: ")

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("会失败")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert app.is_generating is False
            assert app.conversation_history[-1][0] == "Assistant"
            assert "处理输入时发生错误" in app.conversation_history[-1][1]

            input_area.load_text("再试一次")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

            assert calls == ["会失败", "再试一次"]
            assert app.is_generating is False
            assert app.conversation_history[-1] == ("Assistant", "恢复正常")

    asyncio.run(run_smoke())


def test_textual_shell_enter_submits_and_modifier_enter_inserts_newline():
    """Enter 发送；Shift/Ctrl+Enter 在 headless 下可模拟为换行。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """Textual headless 能模拟这些按键；真实终端仍需人工验收。"""

        seen_inputs = []
        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda text, on_runtime_event=None: (
                seen_inputs.append(text) or "assistant"
            ),
            prompt_text="你: ",
        )

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)

            input_area.load_text("hello")
            await pilot.press("enter")
            await pilot.pause()
            assert seen_inputs == ["hello"]
            assert input_area.text == ""
            await pilot.pause()

            input_area.load_text("line")
            await pilot.press("shift+enter")
            assert "\n" in input_area.text

            input_area.clear()
            input_area.load_text("line")
            await pilot.press("ctrl+enter")
            assert "\n" in input_area.text

    asyncio.run(run_smoke())


def test_textual_shell_cancel_clears_input_without_submitting():
    """Esc 取消当前编辑，不生成 submitted，也不调用 chat_handler。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """取消是输入事件，不是空文本提交。"""

        seen_inputs = []
        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda text, on_runtime_event=None: (
                seen_inputs.append(text) or "unused"
            )
        )

        async with app.run_test() as pilot:
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("draft")

            await pilot.press("escape")

            assert input_area.text == ""
            assert seen_inputs == []
            assert app.cancelled_events[-1].event_type == "input.cancelled"
            assert app.cancelled_events[-1].envelope is None

    asyncio.run(run_smoke())


def test_textual_shell_ctrl_q_close_does_not_submit_draft():
    """Ctrl+Q 绑定的 close action 只能退出 Shell，不能误提交草稿。"""

    _require_textual()

    from textual.widgets import TextArea

    from agent.input_backends.textual import _build_textual_shell_app_class

    async def run_smoke() -> None:
        """直接调用 action_close_input 保护 Ctrl+Q binding 的核心语义。"""

        seen_inputs = []
        app_cls = _build_textual_shell_app_class()
        app = app_cls(
            chat_handler=lambda text, on_runtime_event=None: (
                seen_inputs.append(text) or "unused"
            )
        )

        async with app.run_test():
            input_area = app.query_one("#input-area", TextArea)
            input_area.load_text("这是一段尚未提交的草稿")

            app.action_close_input()

            assert seen_inputs == []
            assert app.conversation_history == []

    asyncio.run(run_smoke())


@pytest.mark.xfail(
    reason=(
        "当前 Esc 只属于 Textual 输入编辑边界；core/chat 还没有 cancel_token、"
        "模型 stream abort 或 generation.cancelled RuntimeEvent。删除条件："
        "RuntimeEvent 先定义生成生命周期，main/core 能把 cancel_token 传到模型流，"
        "Textual 再把 Esc 从编辑取消升级为生成取消。"
    ),
    strict=True,
)
def test_textual_shell_escape_can_cancel_running_generation():
    """生成阶段 Esc 应停止继续 append chunk，并标记 Assistant 已中断。

    这是 cancellation 设计债的严格 xfail，不是待补一行代码的 UI bug。当前
    Textual 的 Esc 只在输入后端边界产生 input.cancelled/清空草稿；生成取消需要
    RuntimeEvent 输出生命周期、core cancel_token、模型 stream abort 和 main.py
    adapter 协作。测试不能把 RuntimeEvent、InputIntent、checkpoint、
    conversation.messages、TaskState 或 simple CLI fallback 混成一个临时补丁。
    """

    raise AssertionError("generation.cancelled 尚未接入 cancel_token")
