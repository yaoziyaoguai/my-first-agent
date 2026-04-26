"""只读模型输出解析层。

本模块把 LLM 输出归类成 Runtime Event，但不执行任何 runtime action：
不修改 state、不调用模型、不执行工具、不写 messages、不写 checkpoint。
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
    event_type: str
    event_source: str
    event_payload: dict[str, Any]


def resolve_tool_use_block(block: Any) -> RuntimeEvent:
    """把单个 tool_use block 解析成 RuntimeEvent，不执行工具。"""
    tool_name = getattr(block, "name", "")
    tool_input = getattr(block, "input", {}) or {}
    tool_use_id = getattr(block, "id", "")

    payload = {
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }

    if tool_name == "request_user_input":
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

    return RuntimeEvent(
        event_type=EVENT_MODEL_USED_BUSINESS_TOOL,
        event_source=EVENT_SOURCE_MODEL,
        event_payload=payload,
    )


def resolve_end_turn_output(
    text_content: str,
    no_progress_count: int,
) -> RuntimeEvent | None:
    """解析 end_turn 文本求助 / no_progress，不决定暂停或推进。"""
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
    """把 max_tokens stop_reason 解析成 RuntimeEvent。"""
    return RuntimeEvent(
        event_type=EVENT_MODEL_HIT_MAX_TOKENS,
        event_source=EVENT_SOURCE_MODEL,
        event_payload={},
    )
