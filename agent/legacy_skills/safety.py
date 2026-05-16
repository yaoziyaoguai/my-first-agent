# agent/skills/safety.py
"""Skill 安全扫描模块。

在 Parser 和 Registry 之间做拦截：
- prompt injection 模式 → 拒绝加载
- scripts 里的危险命令 → 只警告，不拒绝
"""

import re
from pathlib import Path


# ========== 检测规则 ==========

# Prompt injection 模式（中英文）
# 匹配到就是 "rejected"
PROMPT_INJECTION_PATTERNS = [
    (r"ignore\s+(the\s+)?(previous|above|prior|all)", "指令劫持（英文）"),
    (r"disregard\s+(the\s+)?(previous|above|rules|instructions?)", "指令劫持（英文）"),
    (r"忽略(之前|上面|前面|所有)", "指令劫持（中文）"),
    (r"不要?(参考|理会)(之前|上面|前面)", "指令劫持（中文）"),
    (r"from\s+now\s+on\s+you\s+are", "身份欺骗"),
    (r"(pretend|act)\s+(as|to\s+be)\s+(?!a\s+user)", "身份欺骗"),
    (r"从现在起你是", "身份欺骗"),
    (r"system\s*prompt", "试图操纵 system prompt"),
    (r"api[_\s-]?key", "提及 API key（可能数据外泄）"),
    (r"环境变量.*(token|key|secret|密钥)", "试图读取密钥"),
]

# 危险 shell 命令模式
# 匹配到是 "warning"
DANGEROUS_SCRIPT_PATTERNS = [
    (r"rm\s+-rf\s+/", "递归删除根目录"),
    (r"curl\s+[^\|]+\|\s*(sh|bash)", "curl 管道执行（远程代码执行）"),
    (r"wget\s+[^\|]+\|\s*(sh|bash)", "wget 管道执行"),
    (r":(){ ?:\|:& ?};:", "fork bomb"),
    (r"dd\s+if=/dev/(zero|random)", "磁盘覆写"),
    (r"chmod\s+777", "过度开放权限"),
    (r"sudo\s+(rm|dd|mkfs)", "sudo 配合危险命令"),
]


# ========== 主函数 ==========

def check_skill_safety(skill_dir: Path, skill_data: dict) -> dict:
    skill_dir = Path(skill_dir)
    skill_name = skill_data["name"]   # ← 赋值给变量
    issues = []
    
    # 1. 扫描 SKILL.md body
    issues.extend(_check_prompt_injection(
        skill_data["body"], 
        location=f"{skill_name}/SKILL.md"   # ← 加 f
    ))
    
    # 2. 扫描 references/
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        for ref_file in references_dir.glob("*.md"):
            try:
                content = ref_file.read_text(encoding="utf-8")
                issues.extend(_check_prompt_injection(
                    content,
                    location=f"{skill_name}/references/{ref_file.name}"   # ← 加 f
                ))
            except Exception:
                pass
    
    # 3. 扫描 scripts/
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for script_file in scripts_dir.rglob("*"):
            if script_file.is_file():
                try:
                    content = script_file.read_text(encoding="utf-8", errors="ignore")
                    issues.extend(_check_dangerous_scripts(
                        content,
                        location=f"{skill_name}/scripts/{script_file.name}"   # ← 加 f
                    ))
                except Exception:
                    pass
    
    level = _compute_level(issues)
    return {"level": level, "issues": issues}

# ========== 辅助函数 ==========

def _check_prompt_injection(text: str, location: str) -> list:
    """扫描一段文本是否有 prompt injection 模式。"""
    issues = []
    text_lower = text.lower()  # 正则匹配用小写（中文不受影响）
    
    for pattern, reason in PROMPT_INJECTION_PATTERNS:
        for match in re.finditer(pattern, text_lower, re.IGNORECASE):
            # 用原始文本里对应位置的内容作为 matched_text
            matched_text = text[match.start():match.end()]
            issues.append({
                "type": "prompt_injection",
                "severity": "rejected",
                "location": location,
                "matched_text": matched_text,
                "reason": reason,
            })
    
    return issues


def _check_dangerous_scripts(text: str, location: str) -> list:
    """扫描 script 文件里的危险命令模式。"""
    issues = []
    
    for pattern, reason in DANGEROUS_SCRIPT_PATTERNS:
        for match in re.finditer(pattern, text):
            matched_text = text[match.start():match.end()]
            issues.append({
                "type": "dangerous_script",
                "severity": "warning",
                "location": location,
                "matched_text": matched_text,
                "reason": reason,
            })
    
    return issues


def _compute_level(issues: list) -> str:
    """根据所有 issue 的 severity 合成整体等级。"""
    if any(issue["severity"] == "rejected" for issue in issues):
        return "rejected"
    if any(issue["severity"] == "warning" for issue in issues):
        return "warning"
    return "safe"
