from pathlib import Path
from agent.tool_registry import register_tool
from agent.security import is_protected_source_file
from agent.checks import run_linter
from agent.tools.path_safety import is_path_inside_project, project_boundary_rejection
from config import ENABLE_REVIEW

# v0.2 RC P1-B 安全边界补丁：写入内容的危险前缀/payload 扫描。
#
# 目标：阻止「文件扩展名看起来安全（.txt / .md / .log 等），但内容
# 明显是密钥 / fork bomb / 块设备覆盖 payload」的写入。
#
# 边界：这**不**是病毒扫描器，也**不**做语义分析。只匹配少量、明确、
# 几乎不会出现在正常文档中的危险标志串。误伤面：用户如果真的想写一份
# 「关于 PEM 私钥格式的文档」会被拒——这种情况让用户改 confirmation 流程
# 或更换 wording 即可，比静默写入真实密钥更安全。
DANGEROUS_CONTENT_MARKERS = [
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----",
]
# 危险 shell payload 的最小子串集合。这里**不**用正则，避免与
# SHELL_BLACKLIST 形成两套规则；只匹配字面、稳定的攻击 payload。
DANGEROUS_CONTENT_SUBSTRINGS = [
    ":(){ :|:& };:",   # fork bomb 字面
    "rm -rf /",        # 典型破坏命令
    "rm -rf ~",
    "> /dev/sda",
    "> /dev/sdb",
    ">/dev/sda",
    ">/dev/sdb",
    "mkfs.ext4 /dev/",
]


def _check_dangerous_content(content: str) -> str | None:
    """扫描写入内容中明显的危险 payload。命中返回拒绝原因，否则 None。"""
    if not isinstance(content, str) or not content:
        return None
    for marker in DANGEROUS_CONTENT_MARKERS:
        if marker in content:
            return (
                f"拒绝执行：写入内容包含敏感密钥头 '{marker[:30]}...'，"
                "禁止把私钥/密钥写入文件。"
            )
    for sub in DANGEROUS_CONTENT_SUBSTRINGS:
        if sub in content:
            return (
                f"拒绝执行：写入内容包含危险 shell payload '{sub}'，"
                "禁止写入此类内容。"
            )
    return None


def pre_write_check(tool_name, tool_input, context):
    """写文件前的检查"""
    path = tool_input.get("path", "")
    content = tool_input.get("content", "")

    # 源码保护
    if is_protected_source_file(path):
        return f"拒绝执行：'{path}' 属于受保护源码文件（.py），不允许 Agent 修改"

    # v0.2 RC：项目外路径硬拦截。
    # 顺序：在 protected source（更具体的拒绝原因）之后、内容扫描之前。
    if not is_path_inside_project(path):
        return project_boundary_rejection(
            path,
            action="向项目外路径写入文件",
            manual_action="在项目外写文件",
        )

    # v0.2 RC P1-B：内容级危险 payload 扫描。
    danger = _check_dangerous_content(content)
    if danger:
        return danger

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
    capability="file_write",
    risk_level="high",
    output_policy="bounded_text",
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
