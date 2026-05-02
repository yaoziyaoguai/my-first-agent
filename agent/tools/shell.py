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


def _normalize_shell_command(command: str) -> str:
    """对 shell 命令做最小规范化，把常见绕过形态归一回基础形态再跑黑名单。

    v0.2 RC P1-A 安全边界补丁：**不**做完整 shell parse / 不展开变量 /
    不处理子 shell。只做四件事：
    1. 删除两两相邻的空引号对（`r''m` / `r""m` 这类绕过）。这是最常见的
       手工拼接绕过，删掉空引号后等价于原命令。
    2. 删除非空白后接的反斜杠转义（`\\rm` → `rm`），仅针对单字符位置。
       不处理 shell 转义语义，仅消除最基础的字符串绕过。
    3. 把所有空白字符（`\\t`、`\\n`、`\\r`、连续空格）压成单个空格，
       让 `rm\\t-rf` / `rm\\n-rf` 等价于 `rm -rf`。
    4. 转成小写，让大小写绕过失效（`RM -RF` → `rm -rf`）。

    返回**规范化后**的命令字符串。这条函数**不**判定危险——它只把字符串
    变形成「让正则更容易命中」的形态。判定仍由 SHELL_BLACKLIST 完成。

    边界声明：这不是完整安全沙箱，更不是 shell parser。
    `$()` / `\\x72m` / `eval` / 多 shell 转义层叠的攻击仍可能绕过。
    完整方案在 v0.3 命令解析层做。
    """
    # 1. 空引号对（成对出现）
    #    `r''m` → `rm`，`a""b` → `ab`，但保留含字符的 `'foo'`。
    normalized = re.sub(r"''", "", command)
    normalized = re.sub(r'""', "", normalized)
    # 2. 单字符前反斜杠转义（`\r` `\m` 等），但保留路径分隔符 `/`。
    normalized = re.sub(r"\\([a-zA-Z])", r"\1", normalized)
    # 3. 空白压缩
    normalized = re.sub(r"\s+", " ", normalized).strip()
    # 4. 小写
    normalized = normalized.lower()
    return normalized


def check_shell_blacklist(command):
    """检查 shell 命令是否命中危险模式。

    v0.2 RC P1-A：先按原命令匹配；若未命中再按规范化后的命令匹配，
    抓住简单引号 / 反斜杠 / 空白 / 大小写绕过。任何一次命中即返回。
    """
    for pattern in SHELL_BLACKLIST:
        if re.search(pattern, command):
            return pattern
    normalized = _normalize_shell_command(command)
    if normalized and normalized != command:
        for pattern in SHELL_BLACKLIST:
            if re.search(pattern, normalized):
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
    capability="command_execution",
    risk_level="high",
    output_policy="bounded_text",
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
