"""simple 输入后端：把旧 input()/multi 协议包装成 UserInputEvent。

这个后端是 Lightweight TUI I/O Shell 的 fallback。它保留历史 CLI 行为，
但输出不再是裸 str/None，而是 input.submitted/input.cancelled/input.closed
事件。

边界说明：
- 负责：读取 stdin、收集 /multi 或围栏多行、包装 UserInputEvent。
- 不负责：InputResolution、Transition、工具执行、checkpoint 保存。

这样做可以让 main loop 先切到事件模型，同时不强制所有环境立刻安装
或启用 Textual。
"""

from __future__ import annotations

from collections.abc import Callable

from agent.user_input import (
    UserInputEvent,
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)


MULTI_START = "/multi"
MULTI_DONE = "/done"
MULTI_CANCEL = "/cancel"
PASTE_FENCE = "```"


def _collect_multiline(
    *,
    reader: Callable[[str], str],
    writer: Callable[[str], None],
    done_token: str,
    cancel_token: str | None,
    hint: str,
    continuation_prompt: str = "... ",
) -> str | None:
    """收集显式多行文本，直到 done/cancel/EOF。

    这里延续旧 main.read_user_input 的协议：EOF 发生在多行收集中时，把
    已收集内容当作提交，避免 stdin 关闭吞掉用户已经输入的文本。
    """

    writer(f"[多行模式] {hint}")
    lines: list[str] = []
    while True:
        try:
            line = reader(continuation_prompt)
        except EOFError:
            return "\n".join(lines)

        stripped = line.strip()
        if stripped == done_token:
            return "\n".join(lines)
        if cancel_token is not None and stripped == cancel_token:
            return None
        lines.append(line)


def read_user_input_text(
    prompt: str = "你: ",
    *,
    reader: Callable[[str], str] = input,
    writer: Callable[[str], None] = print,
) -> str | None:
    """兼容旧 main.read_user_input 的文本读取函数。

    返回 str 表示用户提交文本；返回 None 表示 /multi 中用户显式取消。
    这个函数仍可能把首行 KeyboardInterrupt/EOFError 交给调用方，事件
    包装由 read_user_input_event 负责。
    """

    first = reader(prompt)
    stripped = first.strip()

    if stripped == MULTI_START:
        return _collect_multiline(
            reader=reader,
            writer=writer,
            done_token=MULTI_DONE,
            cancel_token=MULTI_CANCEL,
            hint=(
                f"输入多行内容；单独一行 {MULTI_DONE} 提交，"
                f"{MULTI_CANCEL} 取消"
            ),
        )

    if stripped == PASTE_FENCE:
        return _collect_multiline(
            reader=reader,
            writer=writer,
            done_token=PASTE_FENCE,
            cancel_token=None,
            hint=f"粘贴模式；单独一行 {PASTE_FENCE} 结束（Ctrl+C 中断）",
        )

    return first


def read_user_input_event(
    prompt: str = "你: ",
    *,
    reader: Callable[[str], str] = input,
    writer: Callable[[str], None] = print,
) -> UserInputEvent:
    """读取一次输入并包装成 UserInputEvent。

    普通文本和空文本都会成为 input.submitted，交给 Runtime 的 empty guard
    判断是否推进；KeyboardInterrupt/EOFError 分别成为 cancelled/closed，
    不会被伪造成空字符串。
    """

    try:
        raw_text = read_user_input_text(prompt=prompt, reader=reader, writer=writer)
    except KeyboardInterrupt:
        return cancelled_input_event(source="simple", channel="keyboard_interrupt")
    except EOFError:
        return closed_input_event(source="simple", channel="eof")

    if raw_text is None:
        return cancelled_input_event(source="simple", channel="multi_cancel")

    envelope = build_user_input_envelope(raw_text, source="cli")
    return submitted_input_event(envelope, source="simple", channel="stdin")
