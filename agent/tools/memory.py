"""Model-visible Memory v0 request-only tools.

这些工具只让模型表达“请求记住/查看/忘记”的意图。真正的长期记忆写入、
删除或更新必须经由 Runtime governance、用户确认和 memory.* evidence；
本模块不直接访问 MemoryStore。
"""

from __future__ import annotations

from agent.tool_registry import register_tool


@register_tool(
    name="MEMORY_REMEMBER_REQUEST",
    description=(
        "Request that the user approve saving a memory. "
        "This never commits memory directly."
    ),
    parameters={
        "content": {
            "type": "string",
            "description": "Memory candidate to ask the user to confirm.",
        },
    },
    confirmation="never",
    capability="memory_request",
    risk_level="low",
    output_policy="bounded_text",
)
def memory_remember_request(content: str) -> str:
    """Request-only stub; ToolRuntimeMediator owns the pending confirmation."""
    return "memory remember request submitted for user confirmation"


@register_tool(
    name="MEMORY_LIST",
    description="List user-visible saved memory without exposing hidden scratchpad.",
    parameters={},
    confirmation="never",
    capability="memory_request",
    risk_level="low",
    output_policy="bounded_text",
)
def memory_list() -> str:
    """Request-only stub; ToolRuntimeMediator renders records from MemoryRuntime."""
    return "memory list requested"


@register_tool(
    name="MEMORY_FORGET_REQUEST",
    description=(
        "Request that the user approve forgetting a saved memory. "
        "This never deletes memory directly."
    ),
    parameters={
        "record_id": {
            "type": "string",
            "description": "Memory record id or user-visible id prefix to forget.",
        },
    },
    confirmation="never",
    capability="memory_request",
    risk_level="low",
    output_policy="bounded_text",
)
def memory_forget_request(record_id: str) -> str:
    """Request-only stub; ToolRuntimeMediator owns user confirmation."""
    return "memory forget request submitted for user confirmation"
