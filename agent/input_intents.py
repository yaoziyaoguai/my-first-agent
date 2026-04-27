"""UI 输入语义分类层。

这个模块位于 UI adapter 和 Runtime/Core 之间，负责把 raw text 或输入后端事件
归一成轻量 InputIntent。本阶段只做分类，不改变业务执行。

============================================================
本轮（slash command 整体下线）边界变化说明 —— 中文学习型注释
============================================================
- 原本的 `slash_command` InputIntent kind、`parse_slash_command` 解析器、
  `_EXIT_INPUTS` 中收录的 `/exit` 字面串，以及 c252695 引入的 `FeedbackIntent`
  浅层启发式（`_NEW_TASK_IMPERATIVE_PREFIXES` / `_PLAN_VOCAB_STOP_CHARS` /
  `_collect_plan_vocab` / `_shares_meaningful_chars` / `classify_feedback_intent`）
  全部已下线。
- 下线 `slash_command`：本阶段 slash command 属于"UI / 命令层"高阶能力，会让
  Runtime/InputIntent 主线被 CommandRegistry/CommandResult 间接耦合；为了保护
  RuntimeEvent / InputIntent / CommandResult / checkpoint / messages /
  context_builder._project_to_api / tool_use_id / tool_result placeholder /
  request_user_input 这一组主线边界的清晰度，本轮把整个能力移除。后续如需补回，
  必须通过普通方式（自然语言归一 InputIntent、明确 RuntimeEvent 用户确认流、
  状态机转移、UI 菜单/参数等），而不是再恢复 `/xxx` 字符串协议。
- 下线 `FeedbackIntent` 启发式：c252695 引入的"新任务祈使前缀 + plan 词表零字符
  重叠"双门槛属于浅层关键词/字符启发式（imperative phrases + no-overlap），
  不允许靠这些猜测用户意图。后续应通过明确 RuntimeEvent 让用户主动选择
  "继续当前任务 / 切换为新任务 / 取消"，或在 confirm_handlers 状态机层做正式
  转移，而不是在分类器里悄悄放宽规则。
- 唯一保留：bare `exit` / `quit` 字面串仍然识别为 `exit` kind，由 main.py 的
  非 slash 输入循环负责 finalize_session。这是 UI 退出语义，不是 slash 协议。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


InputIntentKind = Literal[
    "normal_message",
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
# slash command 整体下线后，退出输入仅保留 bare 字面串；不再识别 `/exit`。
_EXIT_INPUTS = {"quit", "exit"}


@dataclass(frozen=True, slots=True)
class InputIntent:
    """UI Adapter -> Runtime 的输入语义归一结果。

    InputIntent 是输入边界，不是 RuntimeEvent；RuntimeEvent 的方向是 Runtime -> UI
    用户可见输出。这里的对象不进入 conversation.messages，不写 checkpoint，不改变
    Anthropic API messages，也不替代 TaskState 状态机本体。它只帮助 Textual 产品
    主路径和 simple CLI fallback 在进入 Runtime 前少靠散落字符串猜测。

    metadata 只放分类辅助信息，例如 confirmation_response 或 slash command 名称/参数。
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

    分类优先级刻意贴近 adapter 边界：cancel/eof/empty/exit 先在 UI 层识别。
    plan/step/tool/request_user_input 的具体状态推进仍交给 core.chat() 按
    TaskState 分派。

    后续如果引入更正式的 InputEnvelope/UserAction，也应沿用这个"只分类、不持久化"
    的边界，不能把 Textual 产品主路径和 simple CLI fallback 的协议混在一起，也不能
    改变 tool_use_id 配对或 tool_result placeholder 语义。

    本轮（slash command 整体下线）：以 `/` 起头的输入不再被特殊识别，会按普通
    自然语言进入下游分类（confirmation / normal_message 等）。如果将来需要让
    用户表达"切换任务 / 取消 generation"等控制语义，必须通过明确 RuntimeEvent
    确认流、状态机转移或 UI 操作来表达，不能再恢复 `/xxx` 字符串协议。
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
