"""Anthropic protocol debug helpers.

这些 helper 只服务本地排查，默认关闭。它们不能成为普通 CLI 输出协议，也不
写 checkpoint / messages / runtime state。
"""

from __future__ import annotations

import os
from typing import Any


DEBUG_PROTOCOL = False


def _protocol_dump_enabled() -> bool:
    """协议 dump 开关：普通 CLI 永远不打印，仅排查时开。"""

    if not DEBUG_PROTOCOL:
        return False
    return os.getenv("MY_FIRST_AGENT_PROTOCOL_DUMP", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _truncate(s: str, n: int = 200) -> str:
    if len(s) <= n:
        return s
    return s[:n] + f"...(共 {len(s)} 字，截 {n})"


def _summarize_content(content: Any) -> str:
    """把一条 message 的 content 压成一行人类可读的描述。"""

    if isinstance(content, str):
        return f"text: {_truncate(content, 150)!r}"
    if not isinstance(content, list):
        return f"<未知形态 {type(content).__name__}>"
    parts = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(f"<非 dict 块 {type(block).__name__}>")
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(f"text {_truncate(block.get('text',''), 120)!r}")
        elif btype == "tool_use":
            parts.append(
                f"tool_use(id={block.get('id')}, "
                f"name={block.get('name')}, "
                f"input={_truncate(str(block.get('input')), 120)})"
            )
        elif btype == "tool_result":
            content_text = block.get("content", "")
            if not isinstance(content_text, str):
                content_text = str(content_text)
            parts.append(
                f"tool_result(tool_use_id={block.get('tool_use_id')}, "
                f"content={_truncate(content_text, 120)!r})"
            )
        else:
            parts.append(f"{btype}(...)")
    return " | ".join(parts)


def _debug_print_request(system_prompt: str, messages: list, tools: list) -> None:
    if not _protocol_dump_enabled():
        return
    print("\n" + "=" * 12 + " REQUEST → Anthropic " + "=" * 12)
    print("system: " + _truncate(system_prompt, 200))
    print(f"tools:  {[t['name'] for t in tools]}")
    print(f"messages ({len(messages)} 条):")
    for i, msg in enumerate(messages):
        role = msg.get("role")
        summary = _summarize_content(msg.get("content"))
        print(f"  [{i}] role={role}")
        print(f"       {summary}")
    print("=" * 45 + "\n")


def _debug_print_response(response: Any) -> None:
    if not _protocol_dump_enabled():
        return
    print("\n" + "=" * 12 + " RESPONSE ← Anthropic " + "=" * 11)
    print(f"stop_reason: {response.stop_reason}")
    print("content blocks:")
    for i, block in enumerate(response.content):
        btype = getattr(block, "type", "?")
        if btype == "text":
            print(f"  [{i}] text: {_truncate(block.text, 150)!r}")
        elif btype == "tool_use":
            print(
                f"  [{i}] tool_use: {block.name}"
                f"(id={block.id}, input={_truncate(str(block.input), 150)})"
            )
        else:
            print(f"  [{i}] {btype}: ...")
    usage = getattr(response, "usage", None)
    if usage is not None:
        print(
            f"usage: input_tokens={usage.input_tokens}, "
            f"output_tokens={usage.output_tokens}"
            + (
                f", cache_read={getattr(usage, 'cache_read_input_tokens', 0)}, "
                f"cache_create={getattr(usage, 'cache_creation_input_tokens', 0)}"
                if hasattr(usage, "cache_read_input_tokens") else ""
            )
        )
    print("=" * 45 + "\n")
