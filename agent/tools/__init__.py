# 导入所有工具模块，触发装饰器注册
from agent.tools.file_ops import read_file as read_file, read_file_lines as read_file_lines  # noqa: F401
from agent.tools.write import write_file as write_file  # noqa: F401
from agent.tools.shell import run_shell as run_shell  # noqa: F401
from agent.tools.web import fetch_url as fetch_url  # noqa: F401
from agent.tools.edit import edit_file as edit_file  # noqa: F401
from agent.tools.install_skill import install_skill as install_skill  # noqa: F401
# Skill lifecycle 工具（load/update）暂不进入基础工具注册入口。
# 当前 Stage 2.5 只打牢 Tooling Foundation；正式 Skill loading/update
# 应在后续 Skill System 阶段重新设计，避免过早污染本地 ToolSpec contract。
# calculate 这类低价值窄工具也不进入基础工具集；未来若需要计算能力，
# 应通过单独设计的 execution/sandbox seam，而不是在这里新增替代工具。
# 元工具（meta_tool=True，不污染对话上下文）
from agent.tools.meta import mark_step_complete as mark_step_complete  # noqa: F401
from agent.tools.meta import request_user_input as request_user_input  # noqa: F401
