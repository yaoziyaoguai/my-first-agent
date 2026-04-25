"""程序入口：输入循环 + 调用 session 模块。"""
import time
from collections.abc import Callable

from agent.core import chat
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

# 多行输入协议
MULTI_START = "/multi"        # 显式进入多行收集
MULTI_DONE = "/done"          # 提交多行
MULTI_CANCEL = "/cancel"      # 取消多行（read_user_input 返回 None）
PASTE_FENCE = "```"           # 三引号围栏，再次 ``` 结束（无 cancel）


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


def _collect_multiline(
    *,
    reader: Callable[[str], str],
    writer: Callable[[str], None],
    done_token: str,
    cancel_token: str | None,
    hint: str,
    continuation_prompt: str = "... ",
) -> str | None:
    """收集多行输入直到 done_token。

    - 命中 cancel_token（仅 /multi 模式有此 token）→ 返回 None
    - 命中 done_token → 返回各行 "\\n".join 拼接
    - reader 抛 EOFError（stdin 关闭）→ 视同 done，提交已有行
    """
    writer(f"[多行模式] {hint}")
    lines: list[str] = []
    while True:
        try:
            line = reader(continuation_prompt)
        except EOFError:
            # stdin 关闭：把已收集的内容当作 done 提交，不丢数据
            return "\n".join(lines)

        stripped = line.strip()
        if stripped == done_token:
            return "\n".join(lines)
        if cancel_token is not None and stripped == cancel_token:
            return None
        lines.append(line)


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
    - `\`\`\`` 起头 → 进入粘贴围栏模式，再次单独一行 `\`\`\`` 结束（无 cancel 路径，
      若需中断请用 Ctrl+C 让 main_loop 走 KeyboardInterrupt 分支）
    - 其它 → 普通单行，原样返回（与历史行为一致）

    reader / writer 通过参数注入，方便单元测试用 fake 替换 input / print。
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


def main_loop():
    last_interrupt_time = 0

    while True:
        try:
            raw = read_user_input()

            # /cancel 取消多行：跳过本轮，不进入 chat
            if raw is None:
                continue

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
