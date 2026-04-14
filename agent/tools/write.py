from pathlib import Path
from agent.tool_registry import register_tool
from agent.security import is_protected_source_file


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
)
def write_file(path, content):
    try:
        if is_protected_source_file(path):
            return f"拒绝写入：'{path}' 属于受保护源码文件（.py），不允许 Agent 修改"
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
