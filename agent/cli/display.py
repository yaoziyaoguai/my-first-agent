"""CLI display and deprecated callback bridge.

学习型说明：
本模块只把 RuntimeEvent 投影到 CLI/TUI 兼容输出，不反向修改 Runtime state、
不保存 checkpoint、不追加 conversation.messages。旧 callback 桥仍保留，
但它不是新功能入口。
"""

from __future__ import annotations

from collections.abc import Callable

from agent.display_events import (
    EVENT_ASSISTANT_DELTA,
    DisplayEvent,
    RuntimeEvent,
    render_runtime_event_for_cli,
)


DEBUG_OUTPUT_PREFIXES = (
    "[DEBUG]",
    "[CHECKPOINT]",
    "[RUNTIME_EVENT]",
    "[INPUT_RESOLUTION]",
    "[TRANSITION]",
    "[ACTIONS]",
    "event_type=",
)


def _user_visible_stdout(captured_stdout: str) -> str:
    """从 chat stdout 中提取可展示文本，过滤内部 debug/checkpoint 输出。"""

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
    """合并 chat 返回值和兼容 stdout，避免同一 assistant 文本双写。"""

    visible_stdout = _user_visible_stdout(captured_stdout)
    reply_text = reply.strip()
    if reply_text and visible_stdout and reply_text not in visible_stdout:
        return f"{visible_stdout}\n{reply_text}"
    return reply_text or visible_stdout


def _textual_stdout_fallback_output(reply: str, captured_stdout: str) -> str:
    """Textual 旧 stdout capture fallback；RuntimeEvent 仍是主路径。"""

    return _merge_chat_outputs(reply, captured_stdout)


def _forward_runtime_event_to_legacy_callbacks(
    event: RuntimeEvent,
    *,
    on_output_chunk: Callable[[str], None] | None,
    on_display_event: Callable[[DisplayEvent], None] | None,
) -> bool:
    """把 RuntimeEvent 转发给旧 callback，并返回是否产生 assistant streaming。"""

    if event.event_type == EVENT_ASSISTANT_DELTA:
        if on_output_chunk is not None:
            on_output_chunk(event.text)
        return True
    if event.display_event is not None and on_display_event is not None:
        on_display_event(event.display_event)
    return False


def _render_runtime_event_for_simple_cli(event: RuntimeEvent) -> bool:
    """把 RuntimeEvent 投影到 simple CLI，并返回是否输出 assistant delta。"""

    rendered = render_runtime_event_for_cli(event)
    if not rendered:
        return False

    if event.event_type == EVENT_ASSISTANT_DELTA:
        print(rendered, end="", flush=True)
        return True

    print(f"\n{rendered}", flush=True)
    return False
