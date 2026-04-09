import json
from pathlib import Path
from config import PROJECT_DIR, PROTECTED_EXTENSIONS, ALLOWED_TOOLS, ENABLE_REVIEW
from agent.logger import log_event


def is_protected_source_file(path):
    """已存在的项目源码文件不允许 Agent 修改"""
    try:
        file_path = Path(path).expanduser().resolve(strict=False)
        return (
            file_path.is_relative_to(PROJECT_DIR)
            and file_path.suffix.lower() in PROTECTED_EXTENSIONS
            and file_path.exists()
        )
    except Exception:
        return False


def needs_confirmation(tool_name, tool_input):
    """根据操作类型和路径判断是否需要人类确认"""

    if tool_name == "write_file":
        return True

    if tool_name in ("read_file", "read_file_lines"):
        file_path = Path(tool_input["path"]).resolve()
        if file_path.is_relative_to(PROJECT_DIR):
            return False
        else:
            return True

    if tool_name == "calculate":
        return False

    return True


def confirm_tool_call(tool_name, tool_input):
    """在工具执行前请求人类确认"""
    print(f"\n{'='*50}")
    print(f"⚠️  Agent 想要执行以下操作：")
    print(f"   工具: {tool_name}")
    print(f"   参数: {json.dumps(tool_input, ensure_ascii=False)}")
    print(f"{'='*50}")
    while True:
        choice = input("允许执行吗？(y/n): ").strip().lower()
        if choice in ("y", "n"):
            return choice == "y"
        print("请输入 y 或 n")
