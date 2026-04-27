"""UI 输入语义分类层。

这个模块位于 UI adapter 和 Runtime/Core 之间，负责把 raw text 或输入后端事件
归一成轻量 InputIntent。它解决的是旧 CLI 时代把 slash、quit、confirmation、
request_user_input 回复都散落成字符串判断的问题；本阶段只做分类，不改变业务执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


InputIntentKind = Literal[
    "normal_message",
    "slash_command",
    "plan_confirmation",
    "step_confirmation",
    "tool_confirmation",
    "request_user_reply",
    "empty",
    "exit",
    "cancel",
    "eof",
    "unknown",
]
ConfirmationResponse = Literal["accept", "reject", "feedback"]

_ACCEPT_CONFIRMATIONS = {
    "y",
    "yes",
    "ok",
    "okay",
    "好",
    "好的",
    "是",
    "是的",
    "确认",
    "行",
    "可以",
}
_REJECT_CONFIRMATIONS = {"n", "no", "不", "不要", "否", "取消"}
_EXIT_INPUTS = {"quit", "exit", "/exit"}


@dataclass(frozen=True, slots=True)
class InputIntent:
    """UI Adapter -> Runtime 的输入语义归一结果。

    InputIntent 是输入边界，不是 RuntimeEvent；RuntimeEvent 的方向是 Runtime -> UI
    用户可见输出。这里的对象不进入 conversation.messages，不写 checkpoint，不改变
    Anthropic API messages，也不替代 TaskState 状态机本体。它只帮助 Textual 产品
    主路径和 simple CLI fallback 在进入 Runtime 前少靠散落字符串猜测。

    metadata 只放分类辅助信息，例如 confirmation_response 或 slash command 名称。
    它不能承载 runtime_observer、debug print、terminal observer log，也不能变成新的
    持久化 schema。
    """

    kind: InputIntentKind
    raw_text: str
    normalized_text: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


def classify_confirmation_response(text: str) -> ConfirmationResponse:
    """把确认输入归一成 accept/reject/feedback。

    这是 UI Adapter -> Runtime 输入边界上的只读分类 helper，用来让 adapter 和
    confirm_handlers 共享同一套 yes/no/中文确认词表。它解决的是旧 CLI 时代
    plan/step/tool confirmation 各自散落字符串判断的根因；真正的状态推进仍在
    confirm_handlers。

    本函数不能修改 state，不能写 checkpoint 或 conversation.messages，不能触发
    RuntimeEvent，不能改变 Anthropic API messages，也不能影响 tool_use_id 配对或
    tool_result placeholder。普通文本和空文本都归为 feedback，交给状态推进层按当前
    awaiting 状态处理。
    """

    normalized = text.strip().lower()
    if normalized in _ACCEPT_CONFIRMATIONS:
        return "accept"
    if normalized in _REJECT_CONFIRMATIONS:
        return "reject"
    return "feedback"


def classify_user_input(
    raw_text: str | None,
    *,
    source: str,
    state: Any | None = None,
    event_type: str = "input.submitted",
) -> InputIntent:
    """把 UI/backend 输入分类为轻量 InputIntent。

    这个函数只读取 raw_text、event_type 和 state.task 的 pending/awaiting 字段，
    不修改 Runtime state，不触发 RuntimeEvent，不调用模型，不执行工具，不写
    checkpoint，也不把分类结果写进 conversation.messages 或 Anthropic API messages。

    分类优先级刻意贴近 adapter 边界：cancel/eof/empty/exit/slash 先在 UI 层识别；
    plan/step/tool/request_user_input 的具体执行仍交给 core.chat() 按 TaskState 分派。
    后续如果引入更正式的 InputEnvelope/UserAction，也应沿用这个“只分类、不持久化”
    的边界，不能把 Textual 产品主路径和 simple CLI fallback 的协议混在一起。
    """

    if event_type == "input.cancelled":
        return InputIntent("cancel", "", "", source, {"event_type": event_type})
    if event_type == "input.closed" or raw_text is None:
        return InputIntent("eof", "", "", source, {"event_type": event_type})

    normalized = raw_text.strip()
    lowered = normalized.lower()

    if not normalized:
        return InputIntent("empty", raw_text, normalized, source)
    if lowered in _EXIT_INPUTS:
        return InputIntent("exit", raw_text, normalized, source)
    if normalized.startswith("/"):
        return InputIntent(
            "slash_command",
            raw_text,
            normalized,
            source,
            {"command": normalized.split(maxsplit=1)[0]},
        )

    task = getattr(state, "task", None)
    status = getattr(task, "status", None)

    if status == "awaiting_tool_confirmation" and getattr(task, "pending_tool", None):
        return InputIntent(
            "tool_confirmation",
            raw_text,
            normalized,
            source,
            {"confirmation_response": classify_confirmation_response(normalized)},
        )

    if status == "awaiting_user_input":
        pending = getattr(task, "pending_user_input_request", None)
        awaiting_kind = "request_user_input" if pending else "collect_input"
        return InputIntent(
            "request_user_reply",
            raw_text,
            normalized,
            source,
            {"awaiting_kind": awaiting_kind},
        )

    if status == "awaiting_plan_confirmation":
        return InputIntent(
            "plan_confirmation",
            raw_text,
            normalized,
            source,
            {"confirmation_response": classify_confirmation_response(normalized)},
        )

    if status == "awaiting_step_confirmation":
        return InputIntent(
            "step_confirmation",
            raw_text,
            normalized,
            source,
            {"confirmation_response": classify_confirmation_response(normalized)},
        )

    return InputIntent("normal_message", raw_text, normalized, source)
