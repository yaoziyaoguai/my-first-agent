import re
import subprocess
from pathlib import Path
from agent.tool_registry import register_tool
from agent.security import is_sensitive_file, _extract_script_path
from config import PROJECT_DIR

SHELL_BLACKLIST = [
    r"\brm\s+(-[a-zA-Z]*f|-[a-zA-Z]*r|--force|--recursive)",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bdd\s+",
    # v0.2 RC P0 安全边界补丁：fork bomb 字面匹配。
    # 原来的 `\b:(){ :\|:& };:` 永不命中——`:` / `(` / `{` 都不是 word 字符，
    # `\b` 在这些位置不成立，正则恒不匹配。这里改为允许 `:()`、`{` / `}`
    # 周围有任意空白，并去掉 `\b`，**不**引入命令规范化（那是 P1 范围）。
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    # v0.2 RC P0 安全边界补丁：覆盖块设备的重定向命令拦截。
    # 原来的 `\b>\s*/dev/sd` 永不命中——`>` 之前根本不可能有 word boundary。
    # 这里去掉前导 `\b`，让 `echo data > /dev/sda1` 这种命令真的被拦截。
    r">\s*/dev/sd",
    r"\bchmod\s+777",
    r"\bchown\b",
    r"\bpasswd\b",
    r"\bkill\s+-9",
]

# 只读命令白名单——这些命令不会修改系统状态
READONLY_COMMANDS = {
    "ls", "cat", "find", "grep", "wc", "head", 
    "tail", "pwd", "which", "echo", "tree", "file",
    "ruff", "python -c",
}

def _check_shell_confirmation(tool_input):
    """shell 命令的智能确认规则"""
    command = tool_input.get("command", "").strip()
    first_word = command.split()[0] if command.split() else ""
    
    # 只读命令：静默执行
    if first_word in READONLY_COMMANDS:
        return False
    
    # 其他命令：需要确认
    return True



SHELL_TIMEOUT = 30


def check_shell_blacklist(command):
    for pattern in SHELL_BLACKLIST:
        if re.search(pattern, command):
            return pattern
    return None


@register_tool(
    name="run_shell",
    description="在项目目录下执行一条 Shell 命令。仅在用户明确要求执行命令时使用。不要主动执行命令来探索文件系统——使用 read_file 代替。危险命令（如 rm -rf、sudo）会被自动拦截。",
    parameters={
        "command": {
            "type": "string",
            "description": "要执行的 Shell 命令"
        },
    },
    confirmation="always",
)
def run_shell(command):
    blocked_pattern = check_shell_blacklist(command)
    if blocked_pattern:
        return f"拒绝执行：命令匹配危险模式 '{blocked_pattern}'，禁止运行。"

    # 敏感文件保护
    words = command.split()
    for word in words:
        if is_sensitive_file(word):
            return f"拒绝执行：命令涉及敏感文件 '{word}'，禁止访问。"

    # 脚本内容检查
    script_path = _extract_script_path(command)
    if script_path:
        script_file = Path(script_path)
        if not script_file.exists():
            script_file = PROJECT_DIR / script_path
        if script_file.exists():
            try:
                script_content = script_file.read_text(encoding="utf-8", errors="replace")
                blocked_pattern = check_shell_blacklist(script_content)
                if blocked_pattern:
                    return f"拒绝执行：脚本文件 '{script_path}' 内容匹配危险模式 '{blocked_pattern}'，禁止运行。"
            except Exception:
                pass

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT,
            cwd=str(PROJECT_DIR),
        )
        output = ""
        if result.stdout:
            output += f"[stdout]\n{result.stdout}"
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if not output.strip():
            output = "(无输出)"
        if len(output) > 5000:
            output = output[:5000] + f"\n\n...(输出过长，已截断，共 {len(output)} 字符)"
        return f"[退出码: {result.returncode}]\n{output}"
    except subprocess.TimeoutExpired:
        return f"执行超时：命令在 {SHELL_TIMEOUT} 秒内未完成，已被终止。"
    except Exception as e:
        return f"执行错误：{e}"
