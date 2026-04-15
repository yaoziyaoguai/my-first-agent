# 导入所有工具模块，触发装饰器注册
from agent.tools.calc import calculate as calculate  # noqa: F401
from agent.tools.file_ops import read_file as read_file, read_file_lines as read_file_lines  # noqa: F401
from agent.tools.write import write_file as write_file  # noqa: F401
from agent.tools.shell import run_shell as run_shell  # noqa: F401
from agent.tools.web import fetch_url as fetch_url  # noqa: F401
from agent.tools.edit import edit_file as edit_file  # noqa: F401