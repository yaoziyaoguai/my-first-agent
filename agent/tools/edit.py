from pathlib import Path

from agent.tool_registry import register_tool
from agent.security import is_protected_source_file
from agent.checks import run_linter
from agent.tools.path_safety import is_path_inside_project, project_boundary_rejection
from config import ENABLE_REVIEW


def pre_edit_check(tool_name, tool_input, context):
    """编辑文件前的检查，复用 FileMutation 的项目根 safety seam。"""
    path = tool_input.get("path", "")

    # 源码保护
    if is_protected_source_file(path):
        return f"拒绝执行：'{path}' 属于受保护源码文件（.py），不允许 Agent 修改"

    # edit_file 与 write_file 都是文件 mutation，必须共享项目根硬边界。
    if not is_path_inside_project(path):
        return project_boundary_rejection(
            path,
            action="编辑项目外路径文件",
            manual_action="在项目外编辑文件",
        )

    # 同一轮只允许一次文件写操作
    if context and context.get("write_file_seen"):
        return "拒绝执行：同一轮响应中只允许执行一次文件写操作，请先等待用户确认后再继续。"

    return None


def post_edit_check(tool_name, tool_input, result):
    """编辑文件后的处理"""
    # 失败场景直接返回
    if (
        result.startswith("拒绝")
        or result.startswith("编辑错误")
        or result.startswith("文件不存在")
        or result.startswith("未找到")
        or result.startswith("匹配到多处")
    ):
        return result

    # linter 检查
    linter_result = run_linter(tool_input["path"])

    if linter_result and "发现以下问题" in linter_result:
        result += f"\n\n{linter_result}"
        result += "\n\n[系统指令] 请根据以上 linter 反馈修复代码，然后重新写入文件。"
    else:
        if linter_result:
            result += f"\n\n{linter_result}"
        if ENABLE_REVIEW:
            result += "\n\n[系统指令] 文件已编辑。请停止当前操作，向用户报告本次操作的结果。不要询问用户是否继续，不要自行继续创建更多文件。"
        else:
            result += "\n\n[系统指令] 文件已编辑。请停止当前操作，将结果报告给用户，并询问用户是否继续下一步。不要自行继续创建更多文件。"

    return result


@register_tool(
    name="edit_file",
    description="在已有文件中，将指定旧内容替换为新内容。要求旧内容在文件中必须唯一出现，否则拒绝执行。",
    parameters={
        "path": {
            "type": "string",
            "description": "要编辑的文件路径"
        },
        "old": {
            "type": "string",
            "description": "要被替换的原始内容，必须在文件中唯一出现"
        },
        "new": {
            "type": "string",
            "description": "替换后的新内容"
        },
    },
    confirmation="always",
    pre_execute=pre_edit_check,
    post_execute=post_edit_check,
    capability="file_write",
    risk_level="high",
    output_policy="bounded_text",
)
def edit_file(path, old, new):
    try:
        file_path = Path(path)

        if not file_path.exists():
            return f"文件不存在：'{path}'"

        content = file_path.read_text(encoding="utf-8", errors="replace")

        if old not in content:
            return "未找到要替换的目标内容"

        match_count = content.count(old)
        if match_count > 1:
            return f"匹配到多处相同内容（共 {match_count} 处），无法确定替换位置，请提供更精确的 old 内容"

        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        backup_path.write_text(content, encoding="utf-8")

        updated_content = content.replace(old, new, 1)
        file_path.write_text(updated_content, encoding="utf-8")

        return f"成功编辑 '{path}'（原文件已备份到 '{backup_path}'）"

    except Exception as e:
        return f"编辑错误：{e}"
