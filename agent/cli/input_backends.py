"""CLI input backend selection.

学习型说明：
这里是 main loop 的输入 adapter，不解释 Runtime 状态、不保存 checkpoint、
不写 conversation messages。submitted/cancelled/closed 的语义交给
UserInputEvent 和上层 Runtime 分派处理。
"""

from __future__ import annotations

import os
from collections.abc import Callable

from agent.input_backends.simple import (
    read_user_input_event as read_simple_user_input_event,
)
from agent.input_backends.simple import (
    read_user_input_text,
)
from agent.user_input import UserInputEvent

INPUT_BACKEND_ENV = "MY_FIRST_AGENT_INPUT_BACKEND"


def _selected_input_backend() -> str:
    """读取输入后端配置；CLI adapter 不解释 Runtime 状态。"""

    return os.getenv(INPUT_BACKEND_ENV, "simple").strip().lower()


def read_user_input(
    prompt: str = "你: ",
    *,
    reader: Callable[[str], str] = input,
    writer: Callable[[str], None] = print,
) -> str | None:
    """读取一次完整的用户输入，保留 simple backend 历史行为。"""

    return read_user_input_text(prompt=prompt, reader=reader, writer=writer)


def read_user_input_event(
    prompt_text: str = "你: ",
    *,
    latest_output: str = "",
) -> UserInputEvent:
    """按环境变量选择输入后端并读取一轮 UserInputEvent。"""

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
