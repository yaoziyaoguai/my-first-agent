import json
from pathlib import Path
import re
from config import PROJECT_DIR, PROTECTED_EXTENSIONS
SENSITIVE_PATTERNS = {".env", ".env.local", ".env.production","id_rsa",".pem",".key"}
SENSITIVE_KEYWORDS = {"secret", "credential", "password", "token", "apikey"}

def is_sensitive_file(path):
    """检查文件是否为敏感文件，禁止 Agent 读取"""

    try:
        file_path = Path(path).expanduser().resolve(strict=False)
        name_lower = file_path.name.lower()
        
        # 文件名匹配
        if name_lower in SENSITIVE_PATTERNS:
            return True
        
        # .env 开头的文件
        if name_lower.startswith(".env"):
            return True
        
        # 文件名包含敏感关键词
        for keyword in SENSITIVE_KEYWORDS:
            if keyword in name_lower:
                return True
        
        return False
    except Exception:
        return False




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
        if is_sensitive_file(tool_input["path"]):
            return "block"  # 新增：返回 "block" 表示直接拦截
        file_path = Path(tool_input["path"]).resolve()
        if file_path.is_relative_to(PROJECT_DIR):
            return False
        else:
            return True

    if tool_name == "calculate":
        return False
    
    if tool_name == "run_shell":
        return True  # Shell 命令全部需要确认

    return True


def _extract_script_path(command):
    """尝试从命令中提取脚本文件路径"""
    patterns = [
        r"bash\s+(.+\.sh)",
        r"sh\s+(.+\.sh)",
        r"python\s+(.+\.py)",
        r"python3\s+(.+\.py)",
        r"\./(.+\.sh)",
    ]
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            return match.group(1).strip()
    return None




def _print_script_content(script_path):
    """打印脚本文件内容，供人工确认"""
    try:
        file_path = Path(script_path).expanduser().resolve(strict=False)

        if not file_path.exists():
            print(f"   [提示] 脚本文件不存在：{script_path}")
            return

        if not file_path.is_file():
            print(f"   [提示] 这是路径，不是普通文件：{script_path}")
            return

        content = file_path.read_text(encoding="utf-8", errors="replace")

        print(f"\n{'-'*50}")
        print(f"📄 即将执行的脚本文件内容：{file_path}")
        print(f"{'-'*50}")
        print(content)
        print(f"{'-'*50}")
    except Exception as e:
        print(f"   [提示] 读取脚本文件失败：{e}")



def confirm_tool_call(tool_name, tool_input):
    """在工具执行前请求人类确认"""
    print(f"\n{'='*50}")
    print("⚠️  Agent 想要执行以下操作：")
    print(f"   工具: {tool_name}")
    print(f"   参数: {json.dumps(tool_input, ensure_ascii=False)}")
    print(f"{'='*50}")


    # 只针对 run_shell：如果是执行脚本文件，就把脚本内容打印出来
    if tool_name == "run_shell":
        command = tool_input.get("command", "")
        if isinstance(command, str):
            script_path = _extract_script_path(command)
            if script_path:
                _print_script_content(script_path)


    while True:
        choice = input("允许执行吗？(y/n): ").strip().lower()
        if choice in ("y", "n"):
            return choice == "y"
        print("请输入 y 或 n")
