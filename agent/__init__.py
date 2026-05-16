"""my-first-agent Runtime 核心包。

本包是 agent loop、confirmation、state、tools、memory 的运行时实现。
公开 API 仅包含稳定、可外部依赖的符号；内部 helper / 实验性模块不在此导出。
"""

# state 工厂（所有外部入口构造 state 的统一入口）
from agent.state import create_agent_state, TaskState, MemoryState

# checkpoint（持久化控制面）
from agent.checkpoint import (
    save_checkpoint,
    load_checkpoint,
    load_checkpoint_to_state,
    clear_checkpoint,
)

# tool registry（工具注册与查询）
from agent.tool_registry import (
    register_tool,
    execute_tool,
    get_model_visible_tools,
    get_tool_definitions,
    get_tool_specs,
    needs_tool_confirmation,
)

# confirmation（用户确认接口）
from agent.confirm_handlers import ConfirmationContext

__all__ = [
    "ConfirmationContext",
    "MemoryState",
    "TaskState",
    "clear_checkpoint",
    "create_agent_state",
    "execute_tool",
    "get_model_visible_tools",
    "get_tool_definitions",
    "get_tool_specs",
    "load_checkpoint",
    "load_checkpoint_to_state",
    "needs_tool_confirmation",
    "register_tool",
    "save_checkpoint",
]
