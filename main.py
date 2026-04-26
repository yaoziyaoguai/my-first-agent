"""程序入口：输入循环 + 调用 session 模块。"""
import os
import time
from collections.abc import Callable

from agent.core import chat
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


def handle_slash_command(user_input: str) -> bool:
    """处理 / 开头的系统命令。返回 True 表示已处理（不再走 chat）。"""
    cmd = user_input.strip()

    if cmd == "/reload_skills":
        registry = reload_registry()
        print(f"\n[系统] Skill 已重新加载，当前 {registry.count()} 个可用")
        for w in registry.get_warnings():
            print(f"  {w}")
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


def read_user_input_event(prompt_text: str = "你: ") -> UserInputEvent:
    """按环境变量选择输入后端并读取一轮 UserInputEvent。

    这是 main loop 和 User Input Layer 的薄适配：submitted 才会进入 chat；
    cancelled/closed 不会被伪造成空字符串。这里不解释输入语义，也不直接
    保存 checkpoint，保持 Runtime action 的职责边界。
    """

    backend = os.getenv(INPUT_BACKEND_ENV, "simple").strip().lower()
    if backend == "textual":
        from agent.input_backends.textual import read_user_input_event_tui

        return read_user_input_event_tui(prompt_text=prompt_text)

    if backend not in ("", "simple"):
        print(f"[系统] 未知输入后端 {backend!r}，已回退到 simple")

    return read_simple_user_input_event(prompt=prompt_text)


def main_loop():
    last_interrupt_time = 0

    while True:
        try:
            event = read_user_input_event()

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

            reply = chat(user_input)
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
    main_loop()
