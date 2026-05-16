"""my-first-agent Runtime 核心包。

本包是 agent loop、confirmation、state、tools、memory 的运行时实现。
公开 API 仅包含稳定、可外部依赖的符号；内部 helper / 实验性模块不在此导出。
"""

# state 工厂（所有外部入口构造 state 的统一入口）
from agent.state import create_agent_state, TaskState, MemoryState

# checkpoint（持久化控制面）
from agent.checkpoint import (
    CheckpointTruncationConfig,
    save_checkpoint,
    load_checkpoint,
    load_checkpoint_to_state,
    clear_checkpoint,
    get_checkpoint_truncation_config,
    reset_checkpoint_truncation_config,
    set_checkpoint_truncation_config,
)

# tool registry（工具注册与查询）
from agent.tool_registry import (
    ToolVisibilityConfig,
    register_tool,
    execute_tool,
    get_model_visible_tools,
    get_tool_definitions,
    get_tool_specs,
    get_model_visible_tool_limits,
    needs_tool_confirmation,
    reset_model_visible_tool_limits,
    set_model_visible_tool_limits,
)

# confirmation（用户确认接口）
from agent.confirm_handlers import ConfirmationContext

__all__ = [
    "ConfirmationContext",
    "CheckpointTruncationConfig",
    "MemoryState",
    "TaskState",
    "ToolVisibilityConfig",
    "clear_checkpoint",
    "create_agent_state",
    "execute_tool",
    "get_checkpoint_truncation_config",
    "get_model_visible_tools",
    "get_tool_definitions",
    "get_model_visible_tool_limits",
    "get_tool_specs",
    "load_checkpoint",
    "load_checkpoint_to_state",
    "needs_tool_confirmation",
    "register_tool",
    "reset_checkpoint_truncation_config",
    "reset_model_visible_tool_limits",
    "save_checkpoint",
    "set_checkpoint_truncation_config",
    "set_model_visible_tool_limits",
]
