from pathlib import Path
from agent.tool_registry import register_tool
from agent.security import is_protected_source_file
from agent.checks import run_linter
from config import ENABLE_REVIEW


def pre_write_check(tool_name, tool_input, context):
    """写文件前的检查"""
    path = tool_input.get("path", "")
    
    # 源码保护
    if is_protected_source_file(path):
        return f"拒绝执行：'{path}' 属于受保护源码文件（.py），不允许 Agent 修改"
    
    # 同一轮只允许一次 write_file
    if context and context.get("write_file_seen"):
        return "拒绝执行：同一轮响应中只允许执行一个 write_file，请先等待用户确认后再继续下一个文件。"
    
    return None  # 放行


def post_write_check(tool_name, tool_input, result):
    """写文件后的处理"""
    # 写入失败的不做后续处理
    if result.startswith("拒绝") or result.startswith("写入错误"):
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
            result += "\n\n[系统指令] 文件已写入。请停止当前操作，向用户报告本次操作的结果。不要询问用户是否继续，不要自行继续创建更多文件。"
        else:
            result += "\n\n[系统指令] 文件已写入。请停止当前操作，将结果报告给用户，并询问用户是否继续下一步。不要自行继续创建更多文件。"
    
    return result


@register_tool(
    name="write_file",
    description="将内容写入文件。如果文件已存在会被覆盖（会自动备份原文件）。如果目录不存在会自动创建。",
    parameters={
        "path": {
            "type": "string",
            "description": "要写入的文件路径"
        },
        "content": {
            "type": "string",
            "description": "要写入的文件内容"
        },
    },
    confirmation="always",
    pre_execute=pre_write_check,
    post_execute=post_write_check,
)
def write_file(path, content):
    try:
        file_path = Path(path)
        backup_path = None
        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            backup_path.write_text(
                file_path.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8"
            )
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        msg = f"成功写入 '{path}'"
        if backup_path:
            msg += f"（原文件已备份到 '{backup_path}'）"
        return msg
    except Exception as e:
        return f"写入错误：{e}"