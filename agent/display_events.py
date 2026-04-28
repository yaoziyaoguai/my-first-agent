"""User-visible display events for UI projections.

DisplayEvent 是 Runtime 向 UI adapter 投递“可展示控制信息”的最小边界。
它不进入 conversation.messages，也不参与 checkpoint；模型看不到这些事件。
这样可以把工具确认提示留在用户界面，同时避免把 debug/runtime observer 日志
误投到聊天视图。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


TOOL_INPUT_PREVIEW_LIMIT = 500
EVENT_ASSISTANT_DELTA = "assistant.delta"
EVENT_DISPLAY_EVENT = "display.event"
EVENT_CONTROL_MESSAGE = "control.message"
EVENT_TOOL_REQUESTED = "tool.requested"
EVENT_PLAN_CONFIRMATION_REQUESTED = "plan.confirmation_requested"
EVENT_USER_INPUT_REQUESTED = "user_input.requested"
EVENT_TOOL_CONFIRMATION_REQUESTED = "tool.confirmation_requested"
EVENT_TOOL_RESULT_VISIBLE = "tool.result_visible"
# P1：plan/step confirmation 阶段收到模糊文本后，Runtime 通过这条 RuntimeEvent
# 让用户在三个互斥选项里显式选择。它只是 Runtime → UI 投影，不写 messages、
# 不写 checkpoint，也不影响 tool_use_id 配对或 Anthropic API messages 投影。
# 详见 docs/P1_TOPIC_SWITCH_PLAN.md §4.4。
EVENT_FEEDBACK_INTENT_REQUESTED = "feedback.intent_requested"


@dataclass(slots=True, frozen=True)
class DisplayEvent:
    """TUI/CLI 可渲染的轻量显示事件。

    当前只落地 tool lifecycle 的最小子集；后续若扩展也只能承载用户可见控制信息。
    debug/checkpoint/runtime observer 日志不能放进 DisplayEvent；DisplayEvent 是 UI
    projection，不是 Runtime state。
    """

    event_type: str
    title: str
    body: str
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)


DisplayEventSink = Callable[[DisplayEvent], None]


@dataclass(slots=True, frozen=True)
class RuntimeEvent:
    """Runtime 到 UI adapter 的用户可见输出边界。

    这个事件只描述“这一刻 UI 可以投影什么”，不描述 Runtime 持久状态。
    因此它不能写入 checkpoint，不能追加到 conversation.messages，不能混进
    Anthropic API messages，也不能复用 runtime_observer 的 debug event。这样做
    是为了解决根因：用户可见输出过去散落在 stdout、assistant chunk callback、
    DisplayEvent callback 和 return value 里，TUI 只能靠 capture/猜测补丁拼回去。
    RuntimeEvent 先把这些用户可见投影收口到一个出口；旧 callback 只作为迁移期
    兼容层，后续不应继续扩张。
    """

    event_type: str
    text: str = ""
    display_event: DisplayEvent | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


RuntimeEventSink = Callable[[RuntimeEvent], None]


def assistant_delta(text: str) -> RuntimeEvent:
    """构造 assistant streaming delta；它是 UI 投影，不是对话历史。"""

    return RuntimeEvent(event_type=EVENT_ASSISTANT_DELTA, text=text)


def runtime_display_event(display_event: DisplayEvent) -> RuntimeEvent:
    """把已有 DisplayEvent 包装进统一 RuntimeEvent 出口。

    DisplayEvent 仍是工具/控制提示的结构化 UI payload；RuntimeEvent 是 Runtime 到
    UI 的统一投递边界。这里按 DisplayEvent 的业务类型映射成更稳定的 RuntimeEvent
    事件名，方便 Textual/CLI 不再只看到泛化的 display.event。这个映射只改变 UI
    projection，不改变 pending_tool、tool_result、checkpoint 或 Anthropic messages。
    """

    event_type = EVENT_DISPLAY_EVENT
    if display_event.event_type == "tool.awaiting_confirmation":
        event_type = EVENT_TOOL_CONFIRMATION_REQUESTED
    elif display_event.event_type in {
        "tool.completed",
        "tool.failed",
        "tool.rejected",
        "tool.user_rejected",
    }:
        event_type = EVENT_TOOL_RESULT_VISIBLE

    return RuntimeEvent(
        event_type=event_type,
        display_event=display_event,
        metadata={"display_event_type": display_event.event_type},
    )


def control_message(text: str, *, metadata: dict[str, Any] | None = None) -> RuntimeEvent:
    """构造用户可见控制文案；不要把 debug/checkpoint 日志塞进这里。"""

    return RuntimeEvent(
        event_type=EVENT_CONTROL_MESSAGE,
        text=text,
        metadata=dict(metadata or {}),
    )


def tool_requested(
    text: str = "🔧 正在规划工具调用...",
    *,
    metadata: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """构造工具调用开始规划的轻量生命周期提示。"""

    return RuntimeEvent(
        event_type=EVENT_TOOL_REQUESTED,
        text=text,
        metadata=dict(metadata or {}),
    )


def plan_confirmation_requested(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """构造计划确认提示事件。

    计划文本是用户确认前的 UI 投影，不是新的模型消息，也不应为了 TUI 展示重复写入
    conversation.messages。真正的 plan 状态仍在 TaskState/current_plan 和 checkpoint
    中维护；这个事件只替代旧 print-era 的“展示计划 + 询问 y/n”输出。
    """

    return RuntimeEvent(
        event_type=EVENT_PLAN_CONFIRMATION_REQUESTED,
        text=text,
        metadata=dict(metadata or {}),
    )


def _format_user_input_request(pending: dict[str, Any]) -> str:
    """把 pending_user_input_request 转成用户可读文本，保持状态与 UI 分离。"""

    lines = ["[需要你补充信息]"]
    if pending.get("question"):
        lines.append(f"  问题：{pending['question']}")
    if pending.get("why_needed"):
        lines.append(f"  原因：{pending['why_needed']}")
    options = pending.get("options") or []
    if options:
        lines.append("  可选项：")
        lines.extend(f"    - {option}" for option in options)
    return "\n".join(lines)


def user_input_requested(
    pending: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """构造执行期向用户补充信息的可见提示。

    pending_user_input_request 是 TaskState 里的等待事实；这个 helper 只把它投影成
    UI 文本。它不能清 pending、不能推进状态机、不能写 conversation.messages，也
    不能生成 Anthropic tool_result；这些仍由 transitions/tool_executor/response
    handlers 按原有协议负责。
    """

    payload = dict(metadata or {})
    payload.update({
        "awaiting_kind": pending.get("awaiting_kind"),
        "step_index": pending.get("step_index"),
    })
    return RuntimeEvent(
        event_type=EVENT_USER_INPUT_REQUESTED,
        text=_format_user_input_request(pending),
        metadata=payload,
    )


def feedback_intent_requested(
    pending: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """构造"模糊反馈 → 用户三选一"的 UI 投影事件。

    架构边界：
    - pending_user_input_request 是 TaskState 里的等待事实；本 helper 只把它
      投影成 UI 文本和结构化 payload，**不**清 pending、**不**推进状态机、
      **不**写 conversation.messages、**不**生成 Anthropic tool_result。
    - payload 必须显式暴露 `options=[3 项]`，让 Textual / CLI 都能渲染三选一
      （例如按钮、菜单或数字提示）。这样 UI adapter 不需要再去解析 text 字段
      才能拿到选项；同时也是测试可以验证"系统通过可观察出口要求用户做选择"
      的契约入口。
    - 不复用 `user_input_requested`：那个 helper 服务于 request_user_input
      元工具的"执行期求助"语义；本事件服务于"plan/step confirmation 阶段
      模糊反馈分流"，两者 awaiting_kind 不同、状态机出口不同，UI 渲染策略
      也可能不同（例如未来 Textual 可以为本事件渲染快捷按钮）。
    """

    payload = dict(metadata or {})
    options = pending.get("options") or []
    payload["options"] = list(options)
    payload["awaiting_kind"] = pending.get("awaiting_kind")
    payload["step_index"] = pending.get("step_index")
    return RuntimeEvent(
        event_type=EVENT_FEEDBACK_INTENT_REQUESTED,
        text=_format_user_input_request(pending),
        metadata=payload,
    )


def tool_result_visible(
    text: str,
    *,
    tool_name: str,
    metadata: dict[str, Any] | None = None,
) -> RuntimeEvent:
    """构造工具结果的用户可见摘要事件。

    工具完整结果仍通过 tool_result 进入模型协议；这里仅展示短摘要，避免 UI 用户只
    看到“执行完成”却不知道结果去向。它不改变 tool_use_id 配对、不写 checkpoint，
    也不替代 messages 里的 tool_result。
    """

    payload = dict(metadata or {})
    payload["tool"] = tool_name
    return RuntimeEvent(
        event_type=EVENT_TOOL_RESULT_VISIBLE,
        text=text,
        metadata=payload,
    )


def _compact_preview(text: str, limit: int = TOOL_INPUT_PREVIEW_LIMIT) -> str:
    """生成适合确认框展示的短预览，避免长文件内容刷满 TUI。"""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + f"\n...(已截断，原始长度 {len(normalized)} 字符)"


def build_tool_awaiting_confirmation_event(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
) -> DisplayEvent:
    """构造工具确认事件，优先展示文件路径和写入内容预览。

    这里不执行工具，也不判断用户是否同意；它只是把既有 pending_tool 状态投影成
    用户可读提示。确认语义仍由 confirm_handlers 处理 raw_text。
    """

    path = tool_input.get("path") or tool_input.get("file_path") or ""
    content = tool_input.get("content")

    lines = [f"工具: {tool_name}"]
    metadata: dict[str, Any] = {"tool": tool_name}
    if path:
        path_text = str(path)
        lines.append(f"路径: {path_text}")
        metadata["path"] = path_text

    if isinstance(content, str):
        preview = _compact_preview(content)
        lines.extend([
            f"内容预览: 前 {min(len(content), TOOL_INPUT_PREVIEW_LIMIT)} 字符",
            preview,
        ])
        metadata["content_length"] = len(content)
        metadata["content_preview"] = preview
    elif tool_input:
        preview = _compact_preview(str(tool_input), limit=300)
        lines.extend(["输入预览:", preview])
        metadata["input_preview"] = preview

    lines.append("是否执行？(y/n/输入反馈意见):")
    return DisplayEvent(
        event_type="tool.awaiting_confirmation",
        title="需要确认工具调用",
        body="\n".join(lines),
        severity="warning",
        metadata=metadata,
    )


def build_tool_status_event(
    *,
    event_type: str,
    tool_name: str,
    tool_input: dict[str, Any],
    status_text: str,
) -> DisplayEvent:
    """构造执行中/完成/失败等短工具生命周期提示。"""

    path = tool_input.get("path") or tool_input.get("file_path") or ""
    lines = [f"工具: {tool_name}"]
    metadata: dict[str, Any] = {"tool": tool_name}
    if path:
        path_text = str(path)
        lines.append(f"路径: {path_text}")
        metadata["path"] = path_text
    lines.append(status_text)
    return DisplayEvent(
        event_type=event_type,
        title="工具执行状态",
        body="\n".join(lines),
        metadata=metadata,
    )


def render_display_event(event: DisplayEvent) -> str:
    """把 DisplayEvent 渲染成 simple CLI / TUI 都能显示的短文本。"""

    return f"[{event.title}]\n{event.body}".strip()


def render_runtime_event_for_cli(event: RuntimeEvent) -> str:
    """把 RuntimeEvent 渲染成 simple CLI 可打印文本。

    这里是 RuntimeEvent 到终端的最后一层投影，不反向修改 Runtime state，也不把
    事件持久化。assistant.delta 返回纯文本，由调用方决定是否 `end=""`；DisplayEvent
    复用现有渲染；control/tool lifecycle 只显示明确的用户可见文案。checkpoint、
    runtime_observer debug event、conversation.messages 和 Anthropic messages 都不应
    经过这个 renderer。
    """

    if event.display_event is not None:
        return render_display_event(event.display_event)
    return event.text.strip() if event.event_type != EVENT_ASSISTANT_DELTA else event.text


def emit_display_event(
    sink: DisplayEventSink | None,
    event: DisplayEvent,
) -> None:
    """投递显示事件；没有 UI sink 时回退到 stdout。

    simple backend 仍依赖终端输出，所以这里保留 print fallback。Textual backend
    传入 sink 后不会再从 stdout 解析这类事件，避免 DisplayEvent 和 stdout capture
    双写。
    """

    if sink is not None:
        sink(event)
        return
    print(f"\n{render_display_event(event)}", flush=True)
