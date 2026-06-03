import json
import re
from pathlib import Path

from config import PROJECT_DIR, PROTECTED_EXTENSIONS

SENSITIVE_PATTERNS = {".env", ".env.local", ".env.production","id_rsa",".pem",".key"}
SENSITIVE_KEYWORDS = {"secret", "credential", "password", "token", "apikey"}
# v0.2 RC P0 安全边界补丁：除「整名匹配」之外，再按扩展名识别敏感文件。
# 例如 `server.pem` / `api.key` 这类真实密钥文件，原先 `name in SENSITIVE_PATTERNS`
# 不会命中（因为 name 是 "server.pem" 而不是 ".pem"）。这里**补一个最小集合**，
# 不引入沙箱，不改变 confirmation 路径，仅修复扩展名识别盲区。
SENSITIVE_SUFFIXES = {".pem", ".key"}
# F-001 P0 修复（2026-06-04）：
# config.yaml / config.yml 是 v1 项目配置入口，包含真实 provider api_key。
# 之前 is_sensitive_file 不识别这两个文件名，导致 read_file("config/config.yaml")
# 通过 TOOL_GATE 检查，文件内容进入 tool_result 并持久化到 sessions/。
# 这里补两个最小集合：
#   - CONFIG_FILE_NAMES：精确匹配主流配置文件基名
#   - CONFIG_DIR_SENSITIVE_SUFFIXES：config/（含子目录）下匹配常见密钥文件扩展名
CONFIG_FILE_NAMES = {"config.yaml", "config.yml", "config.toml", "config.json"}
CONFIG_DIR_SENSITIVE_SUFFIXES = {".yaml", ".yml", ".toml", ".json"}


def is_sensitive_file(path):
    """检查文件是否为敏感文件，禁止 Agent 读取"""

    try:
        file_path = Path(path).expanduser().resolve(strict=False)
        name_lower = file_path.name.lower()
        suffix_lower = file_path.suffix.lower()

        # 文件名匹配
        if name_lower in SENSITIVE_PATTERNS:
            return True

        # v0.2 RC P0：扩展名匹配（.pem / .key 等真实密钥文件）
        if suffix_lower in SENSITIVE_SUFFIXES:
            return True

        # .env 开头的文件
        if name_lower.startswith(".env"):
            return True

        # F-001 P0 修复：config.yaml / config.yml 等配置文件识别
        if name_lower in CONFIG_FILE_NAMES:
            return True
        # config*.yaml / config*.yml 等带前缀变体（如 config.production.yaml）
        if name_lower.startswith("config") and suffix_lower in CONFIG_DIR_SENSITIVE_SUFFIXES:
            return True
        # 双扩展名备份文件：config.yaml.bak / config.yml.backup 等
        # stem 为 "config.yaml" 时 stem 的 suffix 是 ".yaml"
        stem = file_path.stem.lower()  # e.g. "config.yaml" from "config.yaml.bak"
        stem_suffix = Path(stem).suffix.lower() if "." in stem else ""
        if name_lower.startswith("config") and stem_suffix in CONFIG_DIR_SENSITIVE_SUFFIXES:
            return True
        # config/ 目录下任意 yaml/yml/toml/json 文件（如 config/production.yaml）
        if suffix_lower in CONFIG_DIR_SENSITIVE_SUFFIXES:
            # 检查路径中是否包含 config/ 或 configs/ 目录
            parts = file_path.parts
            for _i, part in enumerate(parts):
                if part.lower() in ("config", "configs"):
                    # 该目录下的 .yaml/.yml/.toml/.json 视为配置/密钥文件
                    return True

        # 文件名包含敏感关键词
        return any(keyword in name_lower for keyword in SENSITIVE_KEYWORDS)
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
        return not file_path.is_relative_to(PROJECT_DIR)

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
        choice = input("允许执行吗？(y/n/输入反馈意见): ").strip()
        if choice.lower() == "y":
            return True
        elif choice.lower() == "n":
            return False
        elif len(choice) > 1:
            # 用户输入了反馈意见
            return choice  # 返回字符串
        print("请输入 y、n 或反馈意见")
