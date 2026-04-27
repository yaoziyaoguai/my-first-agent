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

# ---------------------------------------------------------------------------
# Feedback 输入二次分类（plan/step confirmation 反馈分支专用）
# ---------------------------------------------------------------------------
# 这里**不是** InputIntent 状态机本体，也不是新的输入协议。它只是 confirm_handlers
# 在 awaiting_plan / awaiting_step 反馈分支上做的二次结构化分类：当基础 classifier
# 把输入归为 `feedback` 之后，再判断这条 feedback 究竟是“对当前 plan 的修订意见”
# 还是“用户其实在抛出一个新任务”。
#
# 架构边界刻意保持清晰：
#   - InputIntent 仍然只在 UI Adapter -> Runtime 边界做语义归一；
#   - RuntimeEvent 仍然只在 Runtime -> UI 边界投影输出；
#   - state.conversation.messages 仍然是 append-only 事件流；
#   - checkpoint schema、tool_use_id / tool_result placeholder、request_user_input
#     语义都不受影响；
#   - 这里产生的 `FeedbackIntent` 不会写入 messages、不会进 checkpoint、不会
#     变成 RuntimeEvent。confirm_handlers 才决定后续动作（继续 feedback 路径，
#     或发 control_message + 路由到 start_new_task_fn）。
#
# 设计原则刻意结构化、避免补丁式黑名单：
#   - **正向信号**：少而强的“新任务祈使前缀”集合（帮我 / 请帮 / 替我 / 另外 …）。
#     这是中文里开新任务最确定的句式标记，不会被反馈类语境占用。
#   - **结构性回退**：要求文本与当前 plan 的语义字符集合**零重叠**。这把
#     “帮我把这步改成 edit”这种仍在谈论 plan 的句子排除掉，无需维护反馈词表。
#   - 默认值保守地落在 "feedback_to_current_plan"，因此不会破坏既有反馈用例。
#
# 未来若要进一步引入 LLM judge / 三态分类（含 "unclear_user_input"），应当在
# 此函数之上加一层置信度评估，并通过独立的 RuntimeEvent + 用户确认 flow 表达，
# 而不是悄悄放宽这里的判定规则。
FeedbackIntent = Literal[
    "feedback_to_current_plan",
    "new_task_topic_switch",
]


_NEW_TASK_IMPERATIVE_PREFIXES = (
    "帮我",
    "请帮",
    "请帮我",
    "麻烦帮",
    "麻烦帮我",
    "替我",
    "给我",
    "另外",
    "另外帮我",
    "现在做",
    "现在改做",
    "新任务",
    "切换到",
    "换个任务",
    "换一个任务",
)


def classify_feedback_intent(
    text: str,
    *,
    plan: dict | None = None,
) -> FeedbackIntent:
    """对“被基础 classifier 判为 feedback 的输入”做结构化二次分类。

    返回 `"new_task_topic_switch"` 仅当**同时满足**：
      1. 文本以一个明确的“新任务祈使前缀”开头（`_NEW_TASK_IMPERATIVE_PREFIXES`）。
         这是少而强的正向信号，不依赖维护反馈关键词黑名单。
      2. 文本与当前 plan 的语义字符集合**零重叠**（结构性条件，由
         `_collect_plan_vocab` + `_shares_meaningful_chars` 给出）。

    其它任何情况（空白、只是反馈措辞、谈到 plan 词汇、带祈使语但仍涉及 plan
    范畴…）都返回 `"feedback_to_current_plan"`。这样既能识别“帮我写一首关于
    春天的诗”这种与原任务“分析文档”毫无关系的明显话题切换，又能保住
    “我想要更详细一点的分解 / 又改主意了 / 换成 edit 类型的”等历史反馈用例
    继续走 feedback 路径——避免一次启发式调整把 confirm_handlers 的反馈语义
    全部漂移。

    本函数是纯函数：只读 raw text 和 plan metadata；不修改 state，不写
    checkpoint / messages，不发 RuntimeEvent，不影响 tool_use_id / tool_result
    placeholder / request_user_input 语义。
    """

    normalized = (text or "").strip()
    if not normalized:
        return "feedback_to_current_plan"

    if not any(
        normalized.startswith(prefix) for prefix in _NEW_TASK_IMPERATIVE_PREFIXES
    ):
        return "feedback_to_current_plan"

    if plan:
        plan_vocab = _collect_plan_vocab(plan)
        if plan_vocab and _shares_meaningful_chars(normalized, plan_vocab):
            return "feedback_to_current_plan"

    return "new_task_topic_switch"


_PLAN_VOCAB_STOP_CHARS = set(
    "的了和与及或者啊呢吗呀哦嗯，。、；：？！\"'“”‘’()（）《》<>「」 \t\n\r"
)


def _collect_plan_vocab(plan: dict) -> set[str]:
    """收集 plan 中的语义字符集合，供 feedback 二次分类做结构性重叠判断。

    这里只读取 `plan.goal` / `step.title` / `step.description` 的 unicode 字符。
    它不解析 plan_schema、不依赖 planner 内部结构；plan 字段缺失或类型异常都按
    “没有词表”处理，绝不抛错——这是 UI 输入边界上的辅助函数，必须对脏数据保守。
    停用词集合排除了助词、标点和空白，避免“的/了”这种几乎必中的字符把所有
    输入都误判为反馈。
    """

    chars: set[str] = set()
    goal = plan.get("goal") if isinstance(plan, dict) else None
    if isinstance(goal, str):
        chars.update(goal)
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            for key in ("title", "description"):
                value = step.get(key)
                if isinstance(value, str):
                    chars.update(value)
    return {ch for ch in chars if ch not in _PLAN_VOCAB_STOP_CHARS}


def _shares_meaningful_chars(text: str, plan_chars: set[str]) -> bool:
    """文本是否与 plan 词表存在“非停用词”级别的字符重叠。

    用字符级而非分词级做重叠是有意为之：避免引入分词依赖，同时对中文长 goal
    依然有信号。这里只做只读判断，不会改变 state、checkpoint 或任何模型协议。
    """

    text_chars = {ch for ch in text if ch not in _PLAN_VOCAB_STOP_CHARS}
    return bool(text_chars & plan_chars)


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


def parse_slash_command(text: str) -> dict[str, Any]:
    """解析 UI/control slash command 的轻量 metadata。

    slash command 是 UI Adapter -> Runtime 的控制输入，不是用户给模型的自然语言
    消息。这个 helper 只做字符串解析，不执行命令，不写 checkpoint，不写
    conversation.messages，不触发 RuntimeEvent，也不读取或修改 TaskState。它解决的是
    main.py 和测试里反复 `startswith("/")` / `split()` 的散落判断；真正命令执行在
    CommandRegistry，且不能反向把 CommandResult、checkpoint 或用户可见输出混进
    输入分类层。
    """

    normalized = text.strip()
    command_token, _, args = normalized.partition(" ")
    command_name = command_token[1:] if command_token.startswith("/") else command_token
    return {
        "command": command_token,
        "command_name": command_name,
        "command_args": args.strip(),
        "is_exit_command": command_token in {"/exit"},
    }


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

    分类优先级刻意贴近 adapter 边界：cancel/eof/empty/exit/slash 先在 UI 层识别。
    这固化的是当前产品语义：pending_user_input_request、pending_tool 或 plan
    confirmation 期间，slash command 仍可作为 UI/control 输入打断，而不会进入模型
    messages。plan/step/tool/request_user_input 的具体状态推进仍交给 core.chat() 按
    TaskState 分派。

    后续如果引入更正式的 InputEnvelope/UserAction，也应沿用这个“只分类、不持久化”
    的边界，不能把 Textual 产品主路径和 simple CLI fallback 的协议混在一起，也不能
    改变 tool_use_id 配对或 tool_result placeholder 语义。
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
            parse_slash_command(normalized),
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
