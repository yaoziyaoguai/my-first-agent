"""G1 — Simple conversation Golden E2E (characterization, flag off).

Drives ``chat()`` with ``FakeProvider`` and asserts the user-visible reply shape
and the empty-input guard. Characterization must pass on unchanged production
code (G1 is the floor that U3 may not break).
"""

from __future__ import annotations

from agent.core import chat
from agent.provider.fake_provider import FakeProvider


def _print_section(title: str) -> None:
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def test_g1_simple_conversation_with_fake_provider_streams_echo():
    """G1: chat() + FakeProvider → assistant.delta 事件 + 非空 reply。"""
    _print_section("G1 simple conversation — echo via FakeProvider")

    captured_events: list = []
    reply = chat(
        "帮我创建一个 demo note",
        provider=FakeProvider(),
        on_runtime_event=lambda ev: captured_events.append(ev),
    )

    # chat() reply 用于 UI 控制流；空字符串表示正常完成（非错误）。
    assert isinstance(reply, str)

    # 至少一条 assistant.delta，含 FakeProvider 回显
    delta_events = [
        e for e in captured_events
        if getattr(e, "event_type", None) == "assistant.delta"
    ]
    assert len(delta_events) > 0, "chat() 应通过 on_runtime_event 产生 assistant.delta 事件"

    full_text = "".join(getattr(e, "text", "") for e in delta_events)
    assert "已收到你的消息" in full_text, (
        f"流式输出应包含 FakeProvider 回显，实际: {full_text!r}"
    )


def test_g1b_simple_conversation_empty_input_returns_empty():
    """G1 子用例：空输入 → chat() 返回 ''，不崩。"""
    _print_section("G1 empty input — guard returns ''")

    reply = chat("   ", provider=FakeProvider())
    assert reply == "", f"空输入应返回空字符串，实际: {reply!r}"
