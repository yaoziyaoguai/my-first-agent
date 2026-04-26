"""只读模型输出解析层：把 LLM 输出翻译成 RuntimeEvent。

这个模块处在 Model Output -> Event 的边界上。模型可能返回结构化 tool_use、
普通 assistant 文本、end_turn 无进展或 max_tokens；Runtime 先把这些输出归类成
`RuntimeEvent`，让它们可观测、可测试，后续才可能再接入 Transition 层。

重要边界：
- 这里只解析模型输出，不修改 state；
- 不写 conversation.messages；
- 不保存 checkpoint；
- 不执行工具，也不判断工具是否应该执行；
- 不决定是否暂停、是否推进 step、是否结束任务。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EVENT_MODEL_REQUESTED_USER_INPUT = "model.requested_user_input"
EVENT_MODEL_TEXT_REQUESTED_USER_INPUT = "model.text_requested_user_input"
EVENT_MODEL_COMPLETED_STEP = "model.completed_step"
EVENT_MODEL_USED_BUSINESS_TOOL = "model.used_business_tool"
EVENT_MODEL_HIT_MAX_TOKENS = "model.hit_max_tokens"
EVENT_RUNTIME_NO_PROGRESS = "runtime.no_progress"

EVENT_SOURCE_MODEL = "model"
EVENT_SOURCE_RUNTIME = "runtime"

TEXT_USER_INPUT_PATTERNS = (
    "?",
    "？",
    "请告诉我",
    "请提供",
    "请说明",
    "请回复",
    "请补充",
    "麻烦您",
    "您能否",
    "请确认",
)


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """模型输出或 runtime 观察结果对应的事件。

    - event_type：事件类型，使用 `source.action_object` 风格，例如
      `model.requested_user_input`。
    - event_source：事件来源主体，例如 `model` / `runtime`。它回答“谁产生了
      这个事件”，不是“通过哪个通道看到它”。
    - event_payload：后续 handler / transition 可能需要的最小上下文。这里不应
      放无限制的大对象；尤其要避免把完整用户输入、完整工具参数或敏感内容塞进
      观测日志。
    """

    event_type: str
    event_source: str
    event_payload: dict[str, Any]


def resolve_tool_use_block(block: Any) -> RuntimeEvent:
    """把单个 tool_use block 解析成 RuntimeEvent，不执行工具。

    tool_use 是模型最清晰的结构化协议输出：
    - request_user_input：模型正式请求用户补充信息；
    - mark_step_complete：模型声明当前 step 完成的候选信号，是否达标由 runtime
      其他层判断；
    - 其他工具：普通业务工具调用。

    本函数只做分类和最小 payload 投影，不调用工具、不改 state、不写 messages。
    """
    tool_name = getattr(block, "name", "")
    tool_input = getattr(block, "input", {}) or {}
    tool_use_id = getattr(block, "id", "")

    payload = {
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }

    if tool_name == "request_user_input":
        # 结构化协议事件：模型通过 meta tool 明确表达“需要用户输入”。
        payload.update({
            "question": tool_input.get("question", ""),
            "why_needed": tool_input.get("why_needed", ""),
            "options": tool_input.get("options") or [],
            "context": tool_input.get("context", ""),
        })
        return RuntimeEvent(
            event_type=EVENT_MODEL_REQUESTED_USER_INPUT,
            event_source=EVENT_SOURCE_MODEL,
            event_payload=payload,
        )

    if tool_name == "mark_step_complete":
        # 候选完成事件：这里只记录模型声明，分数是否足够由 task_runtime 判定。
        payload.update({
            "completion_score": tool_input.get("completion_score"),
            "summary": tool_input.get("summary", ""),
            "outstanding": tool_input.get("outstanding", ""),
        })
        return RuntimeEvent(
            event_type=EVENT_MODEL_COMPLETED_STEP,
            event_source=EVENT_SOURCE_MODEL,
            event_payload=payload,
        )

    # 普通业务工具：事件可见化后仍交给既有 tool_executor 路径执行。
    return RuntimeEvent(
        event_type=EVENT_MODEL_USED_BUSINESS_TOOL,
        event_source=EVENT_SOURCE_MODEL,
        event_payload=payload,
    )


def resolve_end_turn_output(
    text_content: str,
    no_progress_count: int,
) -> RuntimeEvent | None:
    """解析 end_turn 文本求助 / no_progress，不决定暂停或推进。

    end_turn 没有 tool_use 结构，所以这里做的是 guardrail 式归类：
    - 文本像是在问用户：记为 `model.text_requested_user_input`。这是协议外兜底，
      用来捕获模型没有调用 request_user_input、却直接用普通文本提问的情况。
    - 连续无进展达到阈值：记为 `runtime.no_progress`。这是 runtime 观察事件，
      不是模型主动表达的事件。

    当前优先级是“文本求助优先于 no_progress”。如果同一轮文本已经像阻塞性问题，
    runtime 先保留模型问了什么；真正是否切到 awaiting_user_input 仍由
    response handler 决定。
    """
    if text_content and any(pattern in text_content for pattern in TEXT_USER_INPUT_PATTERNS):
        return RuntimeEvent(
            event_type=EVENT_MODEL_TEXT_REQUESTED_USER_INPUT,
            event_source=EVENT_SOURCE_MODEL,
            event_payload={"text": text_content},
        )

    if no_progress_count >= 2:
        return RuntimeEvent(
            event_type=EVENT_RUNTIME_NO_PROGRESS,
            event_source=EVENT_SOURCE_RUNTIME,
            event_payload={
                "text": text_content,
                "no_progress_count": no_progress_count,
            },
        )

    return None


def resolve_max_tokens_output() -> RuntimeEvent:
    """把 max_tokens stop_reason 解析成 RuntimeEvent。

    max_tokens 表示模型本轮输出被长度限制截断。这里仅把它记录成事件，方便观测
    和测试；是否重试、停止或改变恢复策略仍由 handler / runtime 其他层决定。
    """
    return RuntimeEvent(
        event_type=EVENT_MODEL_HIT_MAX_TOKENS,
        event_source=EVENT_SOURCE_MODEL,
        event_payload={},
    )
