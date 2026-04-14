from pathlib import Path
from agent.tool_registry import register_tool
from config import PROJECT_DIR


def _check_read_permission(tool_input):
    """read_file 的确认规则"""
    from agent.security import is_sensitive_file
    
    path = tool_input.get("path", "")
    
    # 敏感文件：直接拦截
    if is_sensitive_file(path):
        return "block"
    
    # 项目内：静默执行
    file_path = Path(path).resolve()
    if file_path.is_relative_to(PROJECT_DIR):
        return False
    
    # 项目外：需确认
    return True


@register_tool(
    name="read_file",
    description="读取一个文件的内容。如果文件较大（超过10000字符），会返回文件概览而非完整内容，此时请使用 read_file_lines 按行读取具体部分，不要重复调用 read_file 尝试不同路径。",
    parameters={
        "path": {
            "type": "string",
            "description": "文件路径，可以是相对路径或绝对路径"
        }
    },
    confirmation=_check_read_permission,
)
def read_file(path):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"
        
        content = file_path.read_text(encoding="utf-8", errors="replace")
        total_lines = len(content.splitlines())
        
        if len(content) <= 10000:
            return content
        
        from agent.tools.outline import extract_file_outline
        
        preview = content[:3000]
        suffix = file_path.suffix.lower()
        outline = extract_file_outline(content, suffix)
        outline_text = "\n".join(outline[:200])
        
        return (
            f"[读取成功 - 文件较大，以下为概览]\n"
            f"路径: {path}\n"
            f"文件类型: {suffix or '(无后缀)'}\n"
            f"总字符数: {len(content)}\n"
            f"总行数: {total_lines}\n\n"
            f"[开头预览（前 3000 字符）]\n"
            f"{preview}\n\n"
            f"[文件结构目录]\n"
            f"{outline_text}\n\n"
            f"[说明] 文件已成功读取。以上是概览信息。如需查看具体行范围，请使用 read_file_lines 工具。不要重复调用 read_file。"
        )
    except Exception as e:
        return f"读取错误：{e}"


@register_tool(
    name="read_file_lines",
    description="按指定行号范围读取文件内容。适合在 read_file 查看概览后，进一步查看某一段代码或文本。",
    parameters={
        "path": {
            "type": "string",
            "description": "文件路径，可以是相对路径或绝对路径"
        },
        "start_line": {
            "type": "integer",
            "description": "起始行号（从 1 开始）"
        },
        "end_line": {
            "type": "integer",
            "description": "结束行号（从 1 开始，且必须 >= start_line）"
        },
    },
    confirmation=_check_read_permission,
)
def read_file_lines(path, start_line, end_line):
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"错误：文件 '{path}' 不存在"
        if start_line < 1 or end_line < 1:
            return "错误：start_line 和 end_line 必须 >= 1"
        if start_line > end_line:
            return "错误：start_line 不能大于 end_line"
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        total_lines = len(lines)
        if start_line > total_lines:
            return f"错误：start_line={start_line} 超出文件总行数 {total_lines}"
        actual_end = min(end_line, total_lines)
        selected = lines[start_line - 1:actual_end]
        numbered_content = "\n".join(
            f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line)
        )
        return (
            f"[按行读取]\n"
            f"路径: {path}\n"
            f"范围: 第 {start_line} 行 - 第 {actual_end} 行\n"
            f"总行数: {total_lines}\n\n"
            f"{numbered_content}"
        )
    except Exception as e:
        return f"读取错误：{e}"
