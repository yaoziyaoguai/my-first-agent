"""工具注册入口：导入工具模块以触发 @register_tool 装饰器注册。

本包是副作用导入层——import agent.tools 即完成所有内置工具的注册。
__all__ 仅列出公开的工具函数名，供外部显式引用。
"""

# 导入所有工具模块，触发装饰器注册
# _confirmable_noop: 内部 confirmable no-op 工具——仅用于 ToolRegistry gate
# confirmation_required branch behavior 验证。
# 与 _safe_noop 同等安全（zero-arg, no shell, no file write, no external process,
# no network），唯一区别是 confirmation="always"。
# 以下划线开头，模型不可见；ToolGateHandler 通过 allowlist 放行后走
# 正常 needs_tool_confirmation → gate_disposition="confirmation_required"。
from agent.tools.confirmable_noop import _confirmable_noop as _confirmable_noop  # noqa: F401

# Skill lifecycle 工具（install/load/update）不进入基础工具注册入口。
# agent/tools/skill.py 保留为 disabled legacy wrapper（fail-closed 兼容
# 边界，不 import 任何旧 skill 实现）。正式 Skill loading/update 由
# agent/skill_system/ 负责。
# calculate 这类低价值窄工具也不进入基础工具集；未来若需要计算能力，
# 应通过单独设计的 execution/sandbox seam，而不是在这里新增替代工具。
# Demo 工具（安全、确定性、fake-only——First Usable Task MVP）
from agent.tools.demo import demo_echo_task_summary as demo_echo_task_summary  # noqa: F401
from agent.tools.demo import demo_write_demo_note as demo_write_demo_note  # noqa: F401
from agent.tools.edit import edit_file as edit_file  # noqa: F401
from agent.tools.file_ops import read_file as read_file  # noqa: F401
from agent.tools.file_ops import read_file_lines as read_file_lines

# Memory v0 request-only tools：模型可见，但不能 direct commit。
from agent.tools.memory import memory_forget_request as memory_forget_request  # noqa: F401
from agent.tools.memory import memory_list as memory_list  # noqa: F401
from agent.tools.memory import memory_remember_request as memory_remember_request  # noqa: F401

# 元工具（meta_tool=True，不污染对话上下文）
from agent.tools.meta import mark_step_complete as mark_step_complete  # noqa: F401
from agent.tools.meta import request_user_input as request_user_input  # noqa: F401

# _safe_noop: 内部 safe no-op 工具——仅用于 ToolRegistry gate branch behavior 验证。
# 以下划线开头，模型不可见（get_model_visible_tools 的 `_` prefix filter 排除），
# 但 ToolGateHandler 通过最小 allowlist 可在 TOOL_REGISTRY 中查到它。
# 它不代表放开所有 `_` 前缀工具——其他 `_` 前缀工具仍被 gate blocked。
from agent.tools.safe_noop import _safe_noop as _safe_noop  # noqa: F401
from agent.tools.shell import run_shell as run_shell  # noqa: F401
from agent.tools.web import fetch_url as fetch_url  # noqa: F401
from agent.tools.write import write_file as write_file  # noqa: F401

__all__ = [
    "demo_echo_task_summary",
    "demo_write_demo_note",
    "edit_file",
    "fetch_url",
    "mark_step_complete",
    "memory_forget_request",
    "memory_list",
    "memory_remember_request",
    "read_file",
    "read_file_lines",
    "request_user_input",
    "run_shell",
    "write_file",
]
