"""Textual 轻量 I/O Shell 后端。

这个模块实现的是输入/输出适配层，不是 Runtime。它用 output_panel 展示
最近提示，用 TextArea 接收多行输入，然后只返回 UserInputEvent。

明确不负责：
- 不 import Runtime state；
- 不调用 InputResolution/Transition；
- 不执行工具；
- 不保存 checkpoint；
- 不判断 plan/tool/step。

Textual 是可选依赖。模块本身可以导入；只有真正构造/运行 TUI 时才懒加载
textual 包，避免未安装依赖时破坏 simple fallback 和 CI。
"""

from __future__ import annotations

from typing import Any

from agent.user_input import (
    UserInputEvent,
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)


def _submitted_textual_event(raw_text: str) -> UserInputEvent:
    """把 TextArea 文本转换成提交事件。

    这个 helper 让多行 raw_text 完整保留的语义可以脱离真实 TUI 自动化测试。
    """

    envelope = build_user_input_envelope(raw_text, source="tui")
    return submitted_input_event(
        envelope,
        source="tui",
        channel="text_area_submit",
    )


def _cancelled_textual_event(channel: str = "escape_key") -> UserInputEvent:
    """创建 TUI 取消事件；取消不是空文本提交。"""

    return cancelled_input_event(source="tui", channel=channel)


def _closed_textual_event(channel: str = "dialog_closed") -> UserInputEvent:
    """创建 TUI 关闭事件；关闭不会进入 InputResolution。"""

    return closed_input_event(source="tui", channel=channel)


def _build_textual_app_class() -> type[Any]:
    """懒加载并创建 Textual App 类。

    函数只在用户显式选择 textual backend 或测试 Textual 集成时调用。这样
    simple backend 不需要安装 Textual。快捷键都是 TUI 事件，不代表 Runtime
    决策；Runtime 是否 checkpoint 仍由 main loop 决定。
    """

    try:
        from textual.app import App, ComposeResult
        from textual.containers import Vertical
        from textual.widgets import Static, TextArea
    except ImportError as exc:
        raise ImportError(
            "Textual backend requires the optional 'textual' package. "
            "Install it before setting MY_FIRST_AGENT_INPUT_BACKEND=textual."
        ) from exc

    class LightweightInputApp(App[UserInputEvent]):
        """一轮输入用的轻量 TUI 对话框。

        App 生命周期只覆盖“展示最近输出 -> 收集输入 -> 返回事件”这一轮。
        它不持有 Runtime state，也不会触发 checkpoint。
        """

        CSS = """
        Screen {
            layout: vertical;
        }

        .output-panel {
            height: 35%;
            min-height: 5;
            padding: 1 2;
            background: $surface;
            color: $text;
            border: round $primary;
        }

        .input-panel {
            height: 1fr;
            min-height: 8;
            border: round $secondary;
        }

        .help-bar {
            height: 1;
            color: $text-muted;
            background: $panel;
        }
        """

        ESCAPE_TO_MINIMIZE = False
        BINDINGS = [
            ("ctrl+s", "submit", "提交"),
            ("ctrl+enter", "submit", "提交"),
            ("f10", "submit", "提交"),
            ("escape", "cancel", "取消"),
            ("ctrl+d", "close_input", "关闭"),
        ]

        def __init__(self, *, prompt_text: str, latest_output: str = "") -> None:
            super().__init__()
            self.prompt_text = prompt_text
            self.latest_output = latest_output

        def compose(self) -> ComposeResult:
            output_text = self.latest_output or self.prompt_text
            with Vertical():
                yield Static(output_text, id="output-panel", classes="output-panel")
                yield TextArea("", id="input-area", classes="input-panel")
                yield Static(
                    "Enter 换行 | Ctrl+S/Ctrl+Enter/F10 提交 | Esc 取消 | Ctrl+D 关闭",
                    id="help-bar",
                    classes="help-bar",
                )

        def on_mount(self) -> None:
            self.query_one("#input-area", TextArea).focus()

        def action_submit(self) -> None:
            # 提交键只是生成 input.submitted 事件；是否进入 Runtime 由 main 决定。
            text_area = self.query_one("#input-area", TextArea)
            self.exit(_submitted_textual_event(text_area.text))

        def action_cancel(self) -> None:
            # Esc 取消当前输入，不伪造成空字符串。
            self.exit(_cancelled_textual_event())

        def action_close_input(self) -> None:
            # Ctrl+D 表示输入会话关闭，由 main 决定退出或 checkpoint。
            self.exit(_closed_textual_event(channel="ctrl_d"))

    return LightweightInputApp


def read_user_input_event_tui(
    *,
    prompt_text: str = "你: ",
    latest_output: str = "",
) -> UserInputEvent:
    """运行一轮 Textual I/O Shell 并返回 UserInputEvent。

    只有 input.submitted 会携带 envelope；窗口关闭或 Textual 无返回值时，
    统一映射为 input.closed，避免把关闭误当作空输入。
    """

    app_cls = _build_textual_app_class()
    app = app_cls(prompt_text=prompt_text, latest_output=latest_output)
    result = app.run()
    if result is None:
        return _closed_textual_event()
    return result
