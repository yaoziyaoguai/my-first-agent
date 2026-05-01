"""simple 输入后端：把旧 input()/multi 协议包装成 UserInputEvent。

这个后端是 Lightweight TUI I/O Shell 的 fallback。它保留历史 CLI 行为，
但输出不再是裸 str/None，而是 input.submitted/input.cancelled/input.closed
事件。

边界说明
--------
- 负责：读取 stdin、收集 /multi 或围栏多行、**把 stdin 缓冲里同一次粘贴
  的 paste burst 余行 drain 进同一次返回**、包装 UserInputEvent。
- 不负责：InputResolution、Transition、工具执行、checkpoint 保存、
  解释 "1." / "2." 这类编号是不是菜单选择（属 InputResolution / runtime）、
  Esc cancel 模型生成（属 Stage 1 cancel_token + Stage 2 TUI Esc 集成，
  本轮 v0.6.2 MVP 不做）。

为什么 v0.6.2 MVP 要在这里做 paste burst drain
----------------------------------------------
v0.5.x 之前 main.read_user_input → read_user_input_text 普通分支只调用
``first = reader(prompt)`` 一次，丢弃 stdin 缓冲里同一次粘贴的余行。
真实交互场景：用户从浏览器复制一段「9 行编号旅游需求」粘贴进 CLI，
终端把整段送入 stdin，input() 只 return 第一行 "1. 北京出发"，剩余 8 行
变成下一轮甚至下下轮 input()，被 runtime 误当成 9 个独立 user intent，
触发 plan/confirmation 循环混乱。

v0.6.2 MVP 在 simple backend 普通分支末尾用 ``select.select`` 在零超时
下探测 stdin 是否仍有就绪数据：
- 探测就绪 → 继续 reader() drain 进同一段；
- 探测不就绪 → 立即 return（避免对真实交互单行输入造成阻塞）。

这样既解 paste burst（XFAIL-3），又不破坏单行交互 UX，也不需要引入
prompt_toolkit / bracketed paste 依赖。

未来扩展点
----------
- xterm bracketed paste 序列（``ESC [ 200 ~`` / ``ESC [ 201 ~``）显式包裹
  粘贴块，能 100% 区分粘贴 vs 键入；目前未启用，因为需要协调终端 raw
  模式与现有 input() 兼容性。
- prompt_toolkit / textual: 在 textual backend 已可用（不在本 fallback
  范围）。
- 其他平台 stdin（如 Windows pipes）``select`` 不支持时，本模块保守降级
  为「不 drain」，仍保 v0.5.x 单行行为，不会阻塞或崩溃。
"""

from __future__ import annotations

import builtins
import select
import sys
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


def _stdin_has_pending_data() -> bool:
    """零超时探测真实 stdin 是否还有就绪行可读（用于 paste burst drain）。

    返回 True 表示 stdin 缓冲里还有未消费的字节（典型情形 = 用户刚粘贴
    了一段多行文本，终端把整段一次性送进 stdin）；返回 False 表示当前
    没有就绪数据（典型情形 = 用户敲完一行后正在等下一次按键）。

    保守降级：``select.select`` 在 Windows / 非文件描述符 stdin /
    pytest capsys 等场景可能抛 ``OSError`` / ``ValueError``——一律视为
    「不就绪」，让 paste burst drain 退化为不 drain。这样最坏情况只是
    回到 v0.5.x 行为（粘贴块被拆 turn），绝不会阻塞或崩溃。
    """

    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0.0)
        return bool(ready)
    except (OSError, ValueError):
        return False


def _drain_paste_burst_lines(
    reader: Callable[[str], str],
    *,
    is_real_interactive_input: bool,
) -> list[str]:
    """把 paste burst 的余行从 reader 里拉出来。

    两种 drain 策略：

    - ``is_real_interactive_input=True``（reader 是 builtins.input 且
      stdin 是真实 tty）：用 ``_stdin_has_pending_data`` 探测，仅当 stdin
      缓冲已就绪时才继续 ``reader("")``，否则立即 break——避免对真实交互
      场景下"用户只输了一行"的情形造成阻塞 input()。

    - ``is_real_interactive_input=False``（测试注入的 fake reader，或
      非 tty stdin）：用 ``try/EOFError`` 循环 drain。fake reader 通常
      在队列耗尽时抛 EOFError，循环自然退出；测试场景一次性给出 paste
      burst 的所有行，会被一次性拼回。

    本函数只做无副作用的 stdin pull：不调用模型、不修改 runtime state、
    不写 checkpoint。runtime 层后续是否把多行视为同一 user intent，由
    InputResolution / Transition 决定，本层只负责"不要把同一次粘贴拆
    成两次 read"这一 IO 边界。

    捕获的「队列耗尽」异常族
    ----------------------
    drain 循环对 ``EOFError`` / ``KeyboardInterrupt`` / ``IndexError`` /
    ``StopIteration`` 都视作"没有更多余行"而 break：不同测试 fake reader
    的耗尽信号不一致（test_main_input.py 抛 EOFError、
    test_input_backends_simple.py 抛 IndexError），生产 ``input()`` 抛
    EOFError，迭代器风格抛 StopIteration。这是 IO 边界的容错，不是吞异常
    隐藏 bug——首行已经成功 read 并返回，drain 本身不能因 reader 耗尽而
    阻断已经合法的 user input。
    """

    extra: list[str] = []

    if is_real_interactive_input:
        while _stdin_has_pending_data():
            try:
                extra.append(reader(""))
            except (EOFError, KeyboardInterrupt, IndexError, StopIteration):
                break
        return extra

    while True:
        try:
            extra.append(reader(""))
        except (EOFError, KeyboardInterrupt, IndexError, StopIteration):
            break
    return extra


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

    Paste burst 处理（v0.6.2 MVP，解 XFAIL-3）
    -----------------------------------------
    普通分支（既非 /multi 也非 ``` 围栏）在拿到首行后，会调用
    ``_drain_paste_burst_lines`` 把 stdin 缓冲里同一次粘贴的余行一并
    pull 进同一段，最后用 ``"\\n".join`` 拼回返回，让 InputResolution
    收到完整粘贴块而不是被拆成 N 个 user intent。

    交互单行场景（reader 是 builtins.input、stdin 是 tty、用户只输了
    一行）会通过 ``_stdin_has_pending_data`` 立即返回 False 而 short-circuit，
    不会阻塞下一次 input()，保留 v0.5.x 单行 UX。
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

    is_real_interactive_input = reader is builtins.input and sys.stdin.isatty()
    extra = _drain_paste_burst_lines(
        reader, is_real_interactive_input=is_real_interactive_input
    )
    if extra:
        return "\n".join([first, *extra])
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
