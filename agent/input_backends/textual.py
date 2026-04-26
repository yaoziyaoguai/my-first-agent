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

from collections.abc import Callable
from typing import Any

from agent.user_input import (
    UserInputEvent,
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)

EMPTY_OUTPUT_PLACEHOLDER = "暂无模型输出。请在下方输入你的问题。"
ASSISTANT_THINKING_PLACEHOLDER = "正在思考..."


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
            ("ctrl+q", "close_input", "退出"),
        ]

        def __init__(self, *, prompt_text: str, latest_output: str = "") -> None:
            super().__init__()
            self.prompt_text = prompt_text
            self.latest_output = latest_output

        def compose(self) -> ComposeResult:
            output_text = self.latest_output or EMPTY_OUTPUT_PLACEHOLDER
            with Vertical():
                yield Static(output_text, id="output-panel", classes="output-panel")
                yield TextArea("", id="input-area", classes="input-panel")
                yield Static(
                    f"{self.prompt_text}Enter 换行 | Ctrl+S/Ctrl+Enter/F10 提交 | Esc 取消 | Ctrl+Q 退出",
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
            # Ctrl+Q 是当前真实验收可用的退出键；关闭语义仍交给 main/session。
            self.exit(_closed_textual_event(channel="ctrl_q"))

    return LightweightInputApp


def _build_textual_shell_app_class() -> type[Any]:
    """懒加载并创建常驻 Textual I/O Shell。

    one-shot TUI 每次提交都会 app.exit，main 再调用 chat，随后重新创建 App，
    所以真实终端里会出现“闪退闪回”。常驻 Shell 把 App 生命周期提升到整个
    会话：TUI 只负责显示 conversation view、收集输入、调用外部 I/O 回调。

    这个 Shell 仍然不是 Runtime：它不 import Runtime state，不保存
    checkpoint，不判断 plan/tool/step。传入的 chat_handler 是 main.py 提供的
    I/O 桥接函数，负责调用现有 chat 流程并返回用户可见文本。
    """

    try:
        from textual.app import App, ComposeResult
        from textual.containers import Vertical, VerticalScroll
        from textual.widgets import Static, TextArea
    except ImportError as exc:
        raise ImportError(
            "Textual backend requires the optional 'textual' package. "
            "Install it before setting MY_FIRST_AGENT_INPUT_BACKEND=textual."
        ) from exc

    class ChatTextArea(TextArea):
        """聊天输入框：Enter 发送，组合 Enter 尽量保留为换行。

        TextArea 聚焦时会先消费 Enter，所以按键语义要放在输入框子类里处理。
        Shift/Ctrl+Enter 是否能到达程序取决于终端；能识别时插入换行，不能识别
        时用户仍可用粘贴多行或后续终端能力补强。
        """

        def _on_key(self, event: Any) -> None:
            if event.key == "enter":
                event.prevent_default()
                event.stop()
                self.app.action_submit()
                return

            if event.key in {"shift+enter", "ctrl+enter"}:
                event.prevent_default()
                event.stop()
                self.insert("\n")

    class PersistentInputShell(App[None]):
        """常驻极简对话框：上方历史，下方输入。

        conversation_history 是 TUI adapter 内部的轻量显示缓存，不是 Runtime
        state，也不会写入 checkpoint。它只保存用户可见的 You/Assistant 文本，
        debug/checkpoint/runtime observer 日志由 main.py 在进入这里前过滤。
        """

        CSS = """
        Screen {
            layout: vertical;
        }

        .output-panel {
            height: 1fr;
            min-height: 10;
            padding: 1 2;
            background: $surface;
            color: $text;
            border: round $primary;
            overflow-y: auto;
        }

        .input-panel {
            height: 8;
            min-height: 5;
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
            ("f10", "submit", "提交"),
            ("escape", "cancel", "取消"),
            ("ctrl+q", "close_input", "退出"),
            ("ctrl+s", "submit", "备用提交"),
        ]

        def __init__(
            self,
            *,
            chat_handler: Callable[..., str],
            prompt_text: str = "你: ",
        ) -> None:
            super().__init__()
            self.chat_handler = chat_handler
            self.prompt_text = prompt_text
            self.conversation_history: list[tuple[str, str]] = []
            self.cancelled_events: list[UserInputEvent] = []
            self.is_generating = False

        def compose(self) -> ComposeResult:
            with Vertical():
                with VerticalScroll(id="conversation-scroll", classes="output-panel"):
                    yield Static(
                        EMPTY_OUTPUT_PLACEHOLDER,
                        id="conversation-view",
                    )
                yield ChatTextArea("", id="input-area", classes="input-panel")
                yield Static(
                    f"{self.prompt_text}Enter 提交 | Shift+Enter/Ctrl+Enter 换行 | F10 备用提交 | Esc 清空 | Ctrl+Q 退出",
                    id="help-bar",
                    classes="help-bar",
                )

        def on_mount(self) -> None:
            self.query_one("#input-area", TextArea).focus()

        def append_message(self, role: str, text: str) -> None:
            """向 conversation view 追加用户可见消息。

            这里不做 Markdown、streaming 或 tool log，只用清晰前缀区分说话方。
            """

            clean_text = text.strip()
            if not clean_text:
                return
            self.conversation_history.append((role, clean_text))
            self._redraw_conversation()

        def _input_area(self) -> Any:
            return self.query_one("#input-area", TextArea)

        def _redraw_conversation(self) -> None:
            """重绘 RichLog；用于占位替换和 chunk 追加后保持显示一致。"""

            view = self.query_one("#conversation-view", Static)
            if not self.conversation_history:
                view.update(EMPTY_OUTPUT_PLACEHOLDER)
                return
            transcript = "\n\n".join(
                f"{role}:\n{message}"
                for role, message in self.conversation_history
            )
            view.update(transcript)
            scroller = self.query_one("#conversation-scroll", VerticalScroll)
            # 长计划输出后必须自动停在最新内容，让用户能看到 y/n 确认提示。
            scroller.call_after_refresh(scroller.scroll_end, animate=False)

        def _replace_assistant_placeholder(self, message_index: int, text: str) -> None:
            """把 Assistant 占位替换成最终回复并重绘 conversation view。"""

            clean_text = text.strip()
            if not clean_text:
                return

            self.conversation_history[message_index] = ("Assistant", clean_text)
            self._redraw_conversation()

        def _append_assistant_chunk(self, message_index: int, chunk: str) -> None:
            """追加一个 output.chunk 到当前 Assistant 消息。

            这是 model-level streaming 的 TUI 接入口。core.chat 通过 callback 把
            用户可见 delta 传进来；debug/checkpoint 日志不会走这个 callback。
            """

            if not chunk:
                return

            role, current_text = self.conversation_history[message_index]
            if role != "Assistant":
                return

            if current_text == ASSISTANT_THINKING_PLACEHOLDER:
                next_text = chunk
            else:
                next_text = f"{current_text}{chunk}"
            self.conversation_history[message_index] = ("Assistant", next_text)
            self._redraw_conversation()

        def _complete_assistant_response(
            self,
            message_index: int,
            assistant_output: str,
        ) -> None:
            """完成本轮 Assistant 消息，避免 completion 覆盖流式内容。

            output.chunk 到达后，conversation_history 已经保存聚合文本。此时
            chat_handler 的返回值只是非 streaming fallback 或控制文案；如果当前
            Assistant 已经不是“正在思考...”，就说明已有 chunk，completion 不能
            再覆盖它，否则真实 TUI 会出现流式内容结束后消失或重复的问题。
            """

            try:
                role, current_text = self.conversation_history[message_index]
                if role != "Assistant":
                    return

                if current_text != ASSISTANT_THINKING_PLACEHOLDER:
                    # 已有 chunk 聚合结果，保持它；相同 final reply 也不重复追加。
                    return

                clean_output = assistant_output.strip()
                if clean_output:
                    self._replace_assistant_placeholder(message_index, clean_output)
                    return

                self._replace_assistant_placeholder(message_index, "[无输出]")
            finally:
                # Runtime 等待 y/n、补充信息或下一句话时，TUI 必须回到可输入态。
                # 这个释放动作放在 UI thread，避免 worker thread 改状态后焦点没有
                # 回到 TextArea，导致真实终端里 Enter 不再提交。
                self.is_generating = False
                self._input_area().focus()

        def _append_assistant_response(self, raw_text: str, message_index: int) -> None:
            """在界面刷新后调用 chat_handler，并追加 Assistant 回复。

            submit_current_input 会先写入 You 消息并清空输入框，然后用
            worker thread 调用这个方法。chunk 通过 call_from_thread 回到 UI，
            所以 RichLog 能在模型生成过程中持续刷新；即使 chat_handler 报错，
            You 消息也已经保留。
            """

            def on_output_chunk(chunk: str) -> None:
                """从 Runtime 线程安全地把模型 delta 投递回 Textual UI。"""

                self.call_from_thread(
                    self._append_assistant_chunk,
                    message_index,
                    chunk,
                )

            try:
                assistant_output = self.chat_handler(
                    raw_text,
                    on_output_chunk=on_output_chunk,
                )
            except Exception as exc:  # pragma: no cover - 真实终端兜底
                # traceback 不进入 conversation view，只给用户一个短提示。
                assistant_output = f"[系统] 处理输入时发生错误：{exc}"

            self.call_from_thread(
                self._complete_assistant_response,
                message_index,
                assistant_output,
            )

        def submit_current_input(self) -> UserInputEvent | None:
            """提交当前 TextArea 内容，但不退出 App。

            Enter 在聊天式 UI 中更符合“发送”；多行输入用 Shift+Enter 或
            Ctrl+Enter。不同终端对组合键支持不完全一致，所以 F10 保留为稳定
            备用提交键，Ctrl+S 仅作为备用 binding，不在帮助文案主推。
            """

            text_area = self._input_area()
            raw_text = text_area.text
            event = _submitted_textual_event(raw_text)
            if event.envelope is None or event.envelope.is_empty:
                text_area.clear()
                return None

            self.append_message("You", event.envelope.raw_text)
            text_area.clear()
            self.append_message("Assistant", ASSISTANT_THINKING_PLACEHOLDER)
            assistant_index = len(self.conversation_history) - 1
            self.is_generating = True
            self.run_worker(
                lambda: self._append_assistant_response(
                    event.envelope.raw_text,
                    assistant_index,
                ),
                thread=True,
            )
            return event

        def insert_newline(self) -> None:
            """插入换行；用于终端能识别 Shift/Ctrl+Enter 的场景。"""

            self._input_area().insert("\n")

        def cancel_current_input(self) -> UserInputEvent:
            """Esc 只取消当前编辑内容，不伪造成 input.submitted。"""

            self._input_area().clear()
            event = _cancelled_textual_event()
            self.cancelled_events.append(event)
            return event

        def action_submit(self) -> None:
            self.submit_current_input()

        def action_cancel(self) -> None:
            self.cancel_current_input()

        def action_close_input(self) -> None:
            self.exit()

    return PersistentInputShell


def run_textual_io_shell(
    *,
    chat_handler: Callable[[str], str],
    prompt_text: str = "你: ",
) -> None:
    """运行常驻 Textual I/O Shell。

    调用方传入 chat_handler 完成 Runtime 调度；本函数只启动 TUI I/O Shell。
    """

    app_cls = _build_textual_shell_app_class()
    app = app_cls(chat_handler=chat_handler, prompt_text=prompt_text)
    app.run()


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
