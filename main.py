"""程序入口：输入循环 + 调用 session 模块。"""
import contextlib
import io
import os
import time
from collections.abc import Callable

from agent.core import chat
from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    DisplayEvent,
    RuntimeEvent,
    command_result,
    render_runtime_event_for_cli,
)
from agent.input_backends.simple import (
    read_user_input_event as read_simple_user_input_event,
    read_user_input_text,
)
from agent.user_input import UserInputEvent
from agent.session import (
    init_session,
    try_resume_from_checkpoint,
    finalize_session,
    handle_interrupt_with_checkpoint,
    handle_interrupt_without_checkpoint,
    handle_double_interrupt,
)
from agent.checkpoint import load_checkpoint
from agent.skills.registry import reload_registry


CTRL_C_DOUBLE_PRESS_WINDOW = 1.0  # 秒
INPUT_BACKEND_ENV = "MY_FIRST_AGENT_INPUT_BACKEND"
DEBUG_OUTPUT_PREFIXES = (
    "[DEBUG]",
    "[CHECKPOINT]",
    "[RUNTIME_EVENT]",
    "[INPUT_RESOLUTION]",
    "[TRANSITION]",
    "[ACTIONS]",
    # 兼容早期/手写 observer 输出：即使没有 [RUNTIME_EVENT] 前缀，也不应把
    # event_type=... 这类内部观测字段投进 TUI conversation view。
    "event_type=",
)


def _selected_input_backend() -> str:
    """读取输入后端配置；main 只据此做 I/O 适配，不解释 Runtime 状态。"""

    return os.getenv(INPUT_BACKEND_ENV, "simple").strip().lower()


def _user_visible_stdout(captured_stdout: str) -> str:
    """从 chat 的 stdout 里提取可给 TUI 展示的轻量用户可见输出。

    这是 textual backend 的过渡桥接：RuntimeEvent 已是主路径，这里只兜住还没
    迁移的 print-era session/异常/旧调用方输出。这里只过滤明显的
    debug/checkpoint/runtime 观测日志，不解析模型语义，也不保存 checkpoint。

    这不是最终架构。长期应由 RuntimeEvent / DisplayEvent 把“用户可见输出”
    和“内部调试日志”从源头分开，而不是靠 stdout prefix 做后处理。当前保留
    这层，是为了在 print-era Runtime 尚未完全事件化前，保证 checkpoint/debug/
    runtime observer 日志不会进入 TUI conversation view。不要扩大
    DEBUG_OUTPUT_PREFIXES；新增用户可见输出应优先发 RuntimeEvent。
    """

    lines = []
    for line in captured_stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith(DEBUG_OUTPUT_PREFIXES):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _merge_chat_outputs(reply: str, captured_stdout: str) -> str:
    """合并 chat 返回值和 textual 捕获到的用户可见 stdout。

    这是兼容旧输出模型的 fallback：有些控制文案来自 return，有些正文仍来自
    print。这里不能把同一段 assistant 文本双写进 TUI；长期应由事件流明确区分
    assistant.delta / assistant.done / control.message。
    """

    visible_stdout = _user_visible_stdout(captured_stdout)
    reply_text = reply.strip()
    if reply_text and visible_stdout and reply_text not in visible_stdout:
        return f"{visible_stdout}\n{reply_text}"
    return reply_text or visible_stdout


def _forward_runtime_event_to_legacy_callbacks(
    event: RuntimeEvent,
    *,
    on_output_chunk: Callable[[str], None] | None,
    on_display_event: Callable[[DisplayEvent], None] | None,
) -> bool:
    """把 RuntimeEvent 转发给旧 callback，并返回是否产生 assistant streaming。

    这是 main.py 的兼容边界：Textual 主路径已经消费 RuntimeEvent；旧
    on_output_chunk/on_display_event 只服务未迁移的调用方和测试。这里不能继续扩展
    成新的输出协议，也不能把 checkpoint、runtime_observer、debug print、
    conversation.messages 或 Anthropic API messages 混进来。
    """

    if event.event_type == EVENT_ASSISTANT_DELTA:
        if on_output_chunk is not None:
            on_output_chunk(event.text)
        return True
    if event.display_event is not None and on_display_event is not None:
        on_display_event(event.display_event)
    return False


def _run_chat_for_backend(
    user_input: str,
    *,
    backend: str,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
) -> tuple[str, str]:
    """执行 chat，并返回应打印文本和应进入 latest_output 的文本。

    simple backend 保持原有行为：chat 内部流式输出照常打到终端，main 只打印
    reply。textual backend 优先消费 RuntimeEvent；旧 on_output_chunk/on_display_event
    仅作为迁移期兼容。

    关键边界：streaming chunk 已经进入 TUI 后，final return / stdout capture
    不能再作为第二条 Assistant 正文追加，否则长任务结束时会重复显示最后一条
    assistant 消息。这里切断的是输出写入路径，不改变 Runtime 状态推进。
    """

    if backend == "textual":
        captured = io.StringIO()
        runtime_event_outputs: list[str] = []
        emitted_runtime_event = False
        streamed_any_chunk = False

        def forward_output_chunk(chunk: str) -> None:
            """旧 output_chunk callback 的兼容桥。

            Textual 新路径应走 RuntimeEvent；这层只保证尚未迁移的测试或调用方仍能
            避免 stdout/final return 双写。不要在这里继续新增事件类型或字符串过滤。
            """

            nonlocal streamed_any_chunk
            streamed_any_chunk = True
            if on_output_chunk is not None:
                on_output_chunk(chunk)

        def forward_runtime_event(event: RuntimeEvent) -> None:
            """记录并转发 RuntimeEvent，替代 stdout-era 输出猜测。

            main.py 只做 I/O 适配：它不解释 Runtime 状态，不写 checkpoint，也不把
            runtime_observer debug event 混进 TUI。这里保留旧 callback 转发，是为了
            让未迁移的调用方继续工作；新 Textual Shell 会直接传 on_runtime_event。
            一旦本轮已经有 RuntimeEvent，stdout capture 就只能作为无事件旧路径的
            兜底，不能再把同一条用户可见语义作为 completion 返回给 Textual。
            """

            nonlocal emitted_runtime_event, streamed_any_chunk
            emitted_runtime_event = True
            streamed_any_chunk = (
                _forward_runtime_event_to_legacy_callbacks(
                    event,
                    on_output_chunk=on_output_chunk,
                    on_display_event=on_display_event,
                )
                or streamed_any_chunk
            )

            if on_runtime_event is not None:
                on_runtime_event(event)
                return

            if on_output_chunk is None and on_display_event is None:
                rendered = render_runtime_event_for_cli(event)
                if rendered:
                    runtime_event_outputs.append(rendered)

        with contextlib.redirect_stdout(captured):
            if on_runtime_event is not None:
                reply = chat(user_input, on_runtime_event=forward_runtime_event)
            elif on_display_event is None:
                reply = chat(user_input, on_output_chunk=forward_output_chunk)
            else:
                reply = chat(
                    user_input,
                    on_output_chunk=forward_output_chunk,
                    on_display_event=on_display_event,
                )
        if emitted_runtime_event and runtime_event_outputs:
            latest_output = _merge_chat_outputs(
                reply,
                "".join(runtime_event_outputs),
            )
            return reply, latest_output
        if emitted_runtime_event and on_runtime_event is not None:
            # Textual 主路径已经通过 on_runtime_event 实时追加了用户可见内容。这里不再
            # 合并 captured stdout，避免旧 print-era 文案把同一语义作为 final reply
            # 再盖到 Assistant 占位上。若本轮完全没有 RuntimeEvent，后面的 stdout
            # fallback 仍会兜住尚未迁移的 session/异常旧输出。
            return reply, reply.strip()
        if streamed_any_chunk:
            # 已经通过 output.chunk 进入 conversation view，stdout capture 只保留
            # 非 assistant 的控制型返回；避免同一 assistant 文本再走 completion。
            return reply, reply.strip()
        latest_output = _merge_chat_outputs(reply, captured.getvalue())
        return reply, latest_output

    reply = chat(user_input)
    return reply, reply.strip()


def _handle_textual_shell_input(
    user_input: str,
    on_output_chunk: Callable[[str], None] | None = None,
    on_display_event: Callable[[DisplayEvent], None] | None = None,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
) -> str:
    """处理常驻 Textual Shell 提交的文本，并返回用户可见输出。

    这里是 main.py 的 I/O 桥接层：TUI 不 import Runtime state，也不
    save_checkpoint；main 负责复用现有 slash/chat 流程，再把可展示文本交还给
    conversation view。stdout capture 仍保留，是为了兜住尚未迁移的 print-era
    session/异常/旧调用方文案；已经事件化的 assistant.delta、plan confirmation、
    slash command、request_user_input、DisplayEvent 和工具 lifecycle 不应再依赖
    这层 capture。
    """

    text = user_input.strip()
    if not text:
        return ""

    if text.lower() == "quit":
        return "[系统] 常驻 TUI 请按 Ctrl+Q 退出并保存会话。"

    if text.startswith("/"):
        if on_runtime_event is not None:
            handled = handle_slash_command(text, on_runtime_event=on_runtime_event)
            if handled:
                return ""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            handled = handle_slash_command(text)
        if handled:
            return _user_visible_stdout(captured.getvalue())

    _reply, latest_output = _run_chat_for_backend(
        text,
        backend="textual",
        on_output_chunk=on_output_chunk,
        on_display_event=on_display_event,
        on_runtime_event=on_runtime_event,
    )
    return latest_output


def run_textual_main_loop() -> None:
    """运行常驻 Textual backend。

    one-shot TUI 的闪退闪回来自“提交即 app.exit，再由 main 重建 App”。这里改成
    一个常驻 I/O Shell：Textual 只显示/收集 I/O，Runtime 仍通过 main 调用
    chat()，checkpoint 仍由既有 Runtime/session 逻辑负责。
    """

    from agent.input_backends.textual import run_textual_io_shell

    run_textual_io_shell(chat_handler=_handle_textual_shell_input)
    finalize_session()


def handle_slash_command(
    user_input: str,
    *,
    on_runtime_event: Callable[[RuntimeEvent], None] | None = None,
) -> bool:
    """处理 / 开头的本地系统命令。

    slash command 是 main.py 的 I/O 控制命令，不是模型消息，不写
    conversation.messages，也不影响 checkpoint。新 Textual 路径通过
    command.result RuntimeEvent 展示结果；没有 sink 的 simple CLI 仍打印。stdout
    capture 只作为旧调用方兜底，不能继续扩展成新的输出协议。
    """
    cmd = user_input.strip()

    if cmd == "/reload_skills":
        registry = reload_registry()
        lines = [f"[系统] Skill 已重新加载，当前 {registry.count()} 个可用"]
        lines.extend(f"  {warning}" for warning in registry.get_warnings())
        event = command_result("\n".join(lines), command=cmd)
        if on_runtime_event is not None:
            on_runtime_event(event)
        else:
            print(f"\n{render_runtime_event_for_cli(event)}")
        return True

    return False


def read_user_input(
    prompt: str = "你: ",
    *,
    reader: Callable[[str], str] = input,
    writer: Callable[[str], None] = print,
) -> str | None:
    """读取一次完整的用户输入。返回：
    - str：要交给 chat 的原始内容（调用方自行 strip + 过滤空串）
    - None：用户在 /multi 模式下 /cancel，调用方应跳过本轮、不调 chat

    输入分支：
    - `/multi` 起头 → 进入显式多行模式，单独一行 `/done` 提交、`/cancel` 取消
    - ``` 起头 → 进入粘贴围栏模式，再次单独一行 ``` 结束（无 cancel 路径，
      若需中断请用 Ctrl+C 让 main_loop 走 KeyboardInterrupt 分支）
    - 其它 → 普通单行，原样返回（与历史行为一致）

    reader / writer 通过参数注入，方便单元测试用 fake 替换 input / print。
    """
    return read_user_input_text(prompt=prompt, reader=reader, writer=writer)


def read_user_input_event(
    prompt_text: str = "你: ",
    *,
    latest_output: str = "",
) -> UserInputEvent:
    """按环境变量选择输入后端并读取一轮 UserInputEvent。

    这是 main loop 和 User Input Layer 的薄适配：submitted 才会进入 chat；
    cancelled/closed 不会被伪造成空字符串。这里不解释输入语义，也不直接
    保存 checkpoint，保持 Runtime action 的职责边界。

    latest_output 只给 textual backend 展示上一轮用户可见输出；simple backend
    仍保持原来的终端 prompt 行为。
    """

    backend = _selected_input_backend()
    if backend == "textual":
        from agent.input_backends.textual import read_user_input_event_tui

        return read_user_input_event_tui(
            prompt_text=prompt_text,
            latest_output=latest_output,
        )

    if backend not in ("", "simple"):
        print(f"[系统] 未知输入后端 {backend!r}，已回退到 simple")

    return read_simple_user_input_event(prompt=prompt_text)


def main_loop():
    last_interrupt_time = 0
    latest_output = ""

    while True:
        try:
            backend = _selected_input_backend()
            event = read_user_input_event(latest_output=latest_output)

            # cancelled 复用现有 Ctrl+C interrupt 流程；它不是空输入。
            if event.event_type == "input.cancelled":
                raise KeyboardInterrupt

            # closed 表示输入会话结束/EOF，不进入 chat，也不触发 empty guard。
            if event.event_type == "input.closed":
                finalize_session()
                break

            if event.envelope is None:
                continue

            raw = event.envelope.raw_text
            user_input = raw.strip()

            # 空输入过滤
            if not user_input:
                continue

            if user_input.lower() == "quit":
                finalize_session()
                break

            if handle_slash_command(user_input):
                continue

            reply, new_latest_output = _run_chat_for_backend(
                user_input,
                backend=backend,
            )
            if new_latest_output:
                latest_output = new_latest_output
            if reply:
                print(reply)

        except KeyboardInterrupt:
            now = time.time()

            if now - last_interrupt_time < CTRL_C_DOUBLE_PRESS_WINDOW:
                handle_double_interrupt()
                break

            last_interrupt_time = now

            if load_checkpoint():
                should_exit = handle_interrupt_with_checkpoint()
            else:
                should_exit = handle_interrupt_without_checkpoint()

            if should_exit:
                break


if __name__ == "__main__":
    init_session()
    try_resume_from_checkpoint()
    if _selected_input_backend() == "textual":
        run_textual_main_loop()
    else:
        main_loop()
