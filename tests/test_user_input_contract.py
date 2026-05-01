"""UserInputEnvelope contract characterization tests。

本文件补齐 input boundary 的独立契约测试。v0.6.2 已经证明 paste burst /
multiline 是 TUI MVP 的最小实现目标：用户一次粘贴的多行编号列表必须作为
一个 user intent 被保留下来，而不是被 simple backend 拆成多轮，也不能在
input layer 被误判成菜单选择。

边界说明
--------
- `agent.user_input` 只描述输入事件/envelope，不修改 Runtime state、不保存
  checkpoint、不执行工具、不调用模型。
- 菜单/确认语义属于 input intent / confirmation handler / runtime 层；
  `1.` / `2.` 编号列表和单独 `1` 在 envelope 层都只是 raw text。
- 本轮仍不实现 Esc cancel 的 generation interruption，也不实现 user switch
  topic；这些需要 runtime lifecycle 设计，不能塞进 input contract 测试。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from agent.input_intents import classify_confirmation_response, classify_user_input
from agent.state import create_agent_state
from agent.user_input import (
    UserInputEvent,
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)


NUMBERED_PASTE = "\n".join(
    [
        "1. 北京出发",
        "2. 偏好高铁",
        "3. 高端酒店",
        "4. 先武汉后宜昌",
        "5. 自然风光和历史文化",
        "6. 预算 3500 元左右",
        "7. 单人出行",
        "8. 必须去黄鹤楼",
        "9. 出行日期：5 月 1 日到 5 月 3 日",
    ]
)


def test_numbered_multiline_paste_is_plain_multiline_input_contract() -> None:
    """编号列表粘贴在 input boundary 只是一段完整 multiline raw_text。

    这条测试保护 v0.6.2 TUI MVP 的核心语义：input layer 只保留用户一次提交
    的完整文本，不因为行首是 `1.` / `2.` 就把它当成菜单选择。后续 runtime
    可以按当前状态解释文本，但不能要求 backend 提前丢行、拆 turn 或塞选择字段。
    """

    envelope = build_user_input_envelope(NUMBERED_PASTE, source="cli")
    field_names = {field.name for field in fields(envelope)}

    assert envelope.raw_text == NUMBERED_PASTE
    assert envelope.normalized_text == NUMBERED_PASTE
    assert envelope.input_mode == "multiline"
    assert envelope.line_count == 9
    assert envelope.is_empty is False
    assert "selection" not in field_names
    assert "confirmation_response" not in field_names


def test_single_digit_input_stays_raw_text_until_confirmation_layer() -> None:
    """单独 `1` 在 envelope 层仍是普通 raw text，不是 backend 菜单决策。

    如果当前 Runtime 正处于确认状态，`classify_user_input` / confirm_handlers
    才能基于状态解释它；input backend 不能无上下文地把 `1` 当成 accept/reject。
    这避免 Ask User / Other free-text 被 backend 层绕过。
    """

    envelope = build_user_input_envelope("1", source="cli")

    assert envelope.raw_text == "1"
    assert envelope.normalized_text == "1"
    assert envelope.input_mode == "single_line"
    assert envelope.line_count == 1
    assert classify_confirmation_response(envelope.normalized_text) == "feedback"

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_plan_confirmation"
    intent = classify_user_input(envelope.raw_text, source="cli", state=state)

    assert intent.kind == "plan_confirmation"
    assert intent.metadata["confirmation_response"] == "feedback"


def test_user_input_envelope_is_frozen_input_boundary() -> None:
    """envelope 是输入快照，不能被 UI/display/runtime 后续随手 mutate。

    frozen dataclass 让 backend 收集到的 raw_text / line_count 成为稳定事实；
    后续如果 runtime 需要解释或转换，应该生成新的 decision/transition，而不是
    原地改 input event。
    """

    envelope = build_user_input_envelope("hello", source="cli")

    with pytest.raises(FrozenInstanceError):
        envelope.raw_text = "changed"  # type: ignore[misc]


def test_submitted_cancelled_closed_event_invariants() -> None:
    """submitted 必须携带 envelope；cancelled/closed 不能伪造成空文本提交。

    这条测试保护 Ask User / confirmation handler 边界：取消和关闭不是 free-text
    answer，也不应该进入 empty_user_input transition。Esc cancel 的完整 generation
    interruption 语义不在本轮实现，仍应由未来 runtime lifecycle 设计处理。
    """

    envelope = build_user_input_envelope("answer", source="tui")

    submitted = submitted_input_event(envelope, source="tui", channel="text_area_submit")
    cancelled = cancelled_input_event(source="tui", channel="escape_key")
    closed = closed_input_event(source="tui", channel="dialog_closed")

    assert submitted.event_type == "input.submitted"
    assert submitted.envelope is envelope
    assert cancelled.event_type == "input.cancelled"
    assert cancelled.envelope is None
    assert closed.event_type == "input.closed"
    assert closed.envelope is None

    with pytest.raises(ValueError, match="must carry"):
        UserInputEvent(
            event_type="input.submitted",
            event_source="tui",
            event_channel="text_area_submit",
        )

    with pytest.raises(ValueError, match="must not carry"):
        UserInputEvent(
            event_type="input.cancelled",
            event_source="tui",
            event_channel="escape_key",
            envelope=envelope,
        )
