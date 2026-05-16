"""工具注册入口：导入工具模块以触发 @register_tool 装饰器注册。

本包是副作用导入层——import agent.tools 即完成所有内置工具的注册。
__all__ 仅列出公开的工具函数名，供外部显式引用。
"""

# 导入所有工具模块，触发装饰器注册
from agent.tools.file_ops import read_file as read_file, read_file_lines as read_file_lines  # noqa: F401
from agent.tools.write import write_file as write_file  # noqa: F401
from agent.tools.shell import run_shell as run_shell  # noqa: F401
from agent.tools.web import fetch_url as fetch_url  # noqa: F401
from agent.tools.edit import edit_file as edit_file  # noqa: F401
# Skill lifecycle 工具（install/load/update）不进入基础工具注册入口。
# 旧实现已隔离到 agent.legacy_skills；这些 wrapper 即便显式 import 也只能
# fail closed。正式 Skill loading/update 应在 agent/skill_system/ 后续阶段
# 重新设计，避免旧 prototype 污染本地 ToolSpec contract。
# calculate 这类低价值窄工具也不进入基础工具集；未来若需要计算能力，
# 应通过单独设计的 execution/sandbox seam，而不是在这里新增替代工具。
# 元工具（meta_tool=True，不污染对话上下文）
from agent.tools.meta import mark_step_complete as mark_step_complete  # noqa: F401
from agent.tools.meta import request_user_input as request_user_input  # noqa: F401

__all__ = [
    "edit_file",
    "fetch_url",
    "mark_step_complete",
    "read_file",
    "read_file_lines",
    "request_user_input",
    "run_shell",
    "write_file",
]
