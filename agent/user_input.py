"""User Input Layer 的第一步：把终端输入建模成事件。

这个模块位于 CLI/TUI 输入后端和 Runtime 之间。它只描述“用户输入
发生了什么”，不负责解释输入语义，也不修改 Runtime state。

边界说明：
- 负责：保留 raw_text、标记输入模式、区分 submitted/cancelled/closed。
- 不负责：InputResolution、Transition、工具执行、checkpoint 保存。

这样分层的原因是：裸 input() 会把多行粘贴拆成多轮输入，而 Runtime
真正需要的是“这一轮用户意图”的完整输入事件。这里先建立稳定的数据
边界，后续再逐步把 Runtime 从裸 str 迁移到 envelope。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


InputMode = Literal["single_line", "multiline", "empty"]
InputEnvelopeSource = Literal["cli", "tui"]
InputEventType = Literal["input.submitted", "input.cancelled", "input.closed"]
InputEventSource = Literal["simple", "tui"]


@dataclass(frozen=True)
class UserInputEnvelope:
    """一次已提交文本输入的不可变快照。

    字段语义：
    - raw_text：用户提交的原始文本，必须完整保留，供 Runtime 继续处理。
    - normalized_text：第一阶段只做最小换行规范化，不能丢内容。
    - input_mode：输入形态，帮助日志和测试识别单行/多行/空输入。
    - source：输入来自 CLI fallback 还是 TUI。
    - line_count：提交文本的行数，用于观测，不替代 raw_text。
    - is_empty：strip 后是否为空，由 Runtime 的 empty guard 继续防御。

    这个对象只描述输入，不会修改 state，不会调用模型，不会执行工具，
    也不会写 messages/checkpoint。
    """

    raw_text: str
    normalized_text: str
    input_mode: InputMode
    source: InputEnvelopeSource
    line_count: int
    is_empty: bool


@dataclass(frozen=True)
class UserInputEvent:
    """输入后端产出的事件，供 main loop 分发给 Runtime。

    submitted 代表用户明确提交文本，必须携带 envelope；cancelled/closed
    代表输入会话被取消或关闭，不能伪造成空字符串，也不能携带 envelope。

    这个事件本身没有副作用：不修改 state、不调用模型、不执行工具、
    不写 messages/checkpoint。checkpoint 是否保存由 Runtime/main loop
    根据当前任务状态决定。
    """

    event_type: InputEventType
    event_source: InputEventSource
    event_channel: str
    envelope: UserInputEnvelope | None = None

    def __post_init__(self) -> None:
        """在对象边界处固定事件语义，避免取消/关闭被误当空输入。"""
        if self.event_type == "input.submitted":
            if self.envelope is None:
                raise ValueError("input.submitted must carry a UserInputEnvelope")
            return

        if self.envelope is not None:
            raise ValueError("input.cancelled/input.closed must not carry an envelope")


def build_user_input_envelope(
    raw_text: str,
    *,
    source: InputEnvelopeSource,
) -> UserInputEnvelope:
    """把后端读到的文本包装成 UserInputEnvelope。

    输入是后端读到的 raw_text；输出是无副作用的 envelope。这里不调用模型、
    不执行工具、不写 messages/checkpoint，只做最小换行规范化和元信息标记。

    第一阶段的 normalized_text 只统一 CRLF/CR 为 LF，避免丢失用户粘贴的
    编号列表、空行和大段说明。是否为空仍交给 Runtime empty guard 决定。
    """

    normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    is_empty = normalized_text.strip() == ""

    if is_empty:
        input_mode: InputMode = "empty"
    elif "\n" in normalized_text:
        input_mode = "multiline"
    else:
        input_mode = "single_line"

    line_count = 0 if normalized_text == "" else normalized_text.count("\n") + 1

    return UserInputEnvelope(
        raw_text=raw_text,
        normalized_text=normalized_text,
        input_mode=input_mode,
        source=source,
        line_count=line_count,
        is_empty=is_empty,
    )


def submitted_input_event(
    envelope: UserInputEnvelope,
    *,
    source: InputEventSource,
    channel: str,
) -> UserInputEvent:
    """创建文本提交事件。

    submitted 是唯一会进入 InputResolution 的输入事件，因此必须显式携带
    envelope。这个函数只构造事件，不触发 Runtime 行为。
    """

    return UserInputEvent(
        event_type="input.submitted",
        event_source=source,
        event_channel=channel,
        envelope=envelope,
    )


def cancelled_input_event(*, source: InputEventSource, channel: str) -> UserInputEvent:
    """创建输入取消事件。

    取消不是空输入，不能携带 envelope，也不应该进入 InputResolution。
    main loop 可以基于当前 Runtime 状态决定是否 checkpoint。
    """

    return UserInputEvent(
        event_type="input.cancelled",
        event_source=source,
        event_channel=channel,
    )


def closed_input_event(*, source: InputEventSource, channel: str) -> UserInputEvent:
    """创建输入关闭事件。

    closed 表示输入会话结束或 stdin/TUI 关闭。它不是用户提交空字符串，
    因此不能触发 empty_user_input transition。
    """

    return UserInputEvent(
        event_type="input.closed",
        event_source=source,
        event_channel=channel,
    )
