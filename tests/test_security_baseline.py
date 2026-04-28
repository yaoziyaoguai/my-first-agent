"""安全机制基线回归测试（v0.2 M5/M6 preflight）。

本文件是 `docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md` §3 / §4 / §5 中
「已识别但本轮不修复」的最小回归保护：把当前安全机制的**已实现行为**
钉死，防止未来在做 M5 / M6 最小补丁或更大重构时悄悄退化。

不在本文件覆盖：
- M6 候选最小修复（is_sensitive_file 内容前缀扫描、shell 命令规范化、项目
  外路径标签）。这些缺口已在 preflight 文档登记，**实现时**再补对应测试。
- 工具行为本身（read_file / write_file 端到端）。归 tools/ 自己的测试。
"""

from __future__ import annotations

import pytest

from agent.security import (
    SENSITIVE_KEYWORDS,
    SENSITIVE_PATTERNS,
    is_protected_source_file,
    is_sensitive_file,
)
from agent.tools.shell import (
    READONLY_COMMANDS,
    SHELL_BLACKLIST,
    check_shell_blacklist,
)


# ---------------------------------------------------------------------------
# §1 sensitive 文件名匹配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    ".env",
    ".env.local",
    ".env.production",
    "config/.env",
    "/tmp/id_rsa",
    "/tmp/my_secret_notes.txt",
    "/tmp/credentials.json",
    "/tmp/password_list.csv",
    "/tmp/api_token.txt",
    "/tmp/myapikey.conf",
])
def test_sensitive_files_are_blocked(path):
    """文件名命中 SENSITIVE_PATTERNS / 关键词 / `.env` 前缀 → 必须 block。

    这条 invariant 是 read_file / read_file_lines 的 `_check_read_permission`
    依赖项；任何对 SENSITIVE_PATTERNS 或 SENSITIVE_KEYWORDS 的修改都会让
    本测试失败，提醒维护者评估是否要同步更新 preflight 文档。

    已知缺口（preflight 文档 §3 已登记）：`.pem` / `.key` 等扩展名当前
    走不到 block，因为 `is_sensitive_file` 用的是 `name == ".pem"` 整名
    匹配，而非扩展名匹配。修复时请在 preflight 文档迁出该缺口并把对应
    用例加回本 parametrize。
    """
    assert is_sensitive_file(path), (
        f"敏感路径 {path!r} 未被 is_sensitive_file 识别；"
        " 请检查 SENSITIVE_PATTERNS / SENSITIVE_KEYWORDS 是否被改弱。"
    )


@pytest.mark.parametrize("path", [
    "README.md",
    "agent/state.py",
    "/tmp/notes.txt",
    "tests/test_main_loop.py",
])
def test_non_sensitive_files_are_not_blocked(path):
    """普通文件名不应被 is_sensitive_file 误伤为敏感。"""
    assert not is_sensitive_file(path)


def test_sensitive_pattern_constants_have_expected_baseline():
    """SENSITIVE_PATTERNS / KEYWORDS 改动需先更新 preflight 文档。

    本测试钉死最小集合；任何**移除**这里的项都会 red。新增项不会 red
    （`>=` 比较），鼓励维护者按需扩展。
    """
    expected_patterns_subset = {".env", ".env.local", "id_rsa", ".pem", ".key"}
    expected_keywords_subset = {"secret", "credential", "password", "token", "apikey"}

    assert expected_patterns_subset <= set(SENSITIVE_PATTERNS), (
        "SENSITIVE_PATTERNS 缺失基线项；请同步更新"
        " docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md §2.1"
    )
    assert expected_keywords_subset <= set(SENSITIVE_KEYWORDS), (
        "SENSITIVE_KEYWORDS 缺失基线项；请同步更新"
        " docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md §2.1"
    )


# ---------------------------------------------------------------------------
# §2 protected source file
# ---------------------------------------------------------------------------

def test_existing_project_python_file_is_protected():
    """项目内已存在的 .py 文件必须被 is_protected_source_file 识别。"""
    # 仓库内任意肯定存在的 .py 文件。
    assert is_protected_source_file("agent/state.py")
    assert is_protected_source_file("config.py")


def test_nonexistent_or_outside_project_path_is_not_protected():
    """不存在的文件 / 项目外路径不应被识别为受保护源码。

    write_file 的 protected source 检查只针对「已存在 + 项目内 + 受保护
    扩展名」三者同时满足，避免误伤新建文件或项目外脚本。
    """
    assert not is_protected_source_file("agent/this_does_not_exist.py")
    assert not is_protected_source_file("/tmp/test_outside_project.py")
    # 非保护扩展名（即使在项目内、即使存在）也不算受保护源码。
    assert not is_protected_source_file("README.md")


# ---------------------------------------------------------------------------
# §3 shell 黑名单
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf /",
    "rm -rf ~",
    "rm --recursive /tmp",
    "sudo apt-get install evil",
    "mkfs.ext4 /dev/sda1",
    "shutdown now",
    "reboot",
    "poweroff",
    "dd if=/dev/zero of=/dev/sda",
    "chmod 777 /etc/passwd",
    "chown root:root file",
    "passwd root",
    "kill -9 1",
])
def test_dangerous_shell_commands_are_blacklisted(command):
    """SHELL_BLACKLIST 必须拦截所有典型危险命令。

    任何对正则的「优化」或「简化」都可能放过这些命令；本测试是回归网。
    新增危险模式时，加一条参数即可。

    已知缺口（preflight 文档 §3 已登记）：
    - fork bomb `:(){ :|:& };:` 正则当前匹配失败（特殊字符 `\\b` 边界问题）
    - `echo data > /dev/sda1` 当前匹配失败（`\\b>` 在 `>` 前无 word
      boundary）
    修复后把这些用例加回本 parametrize 并从 preflight 文档迁出。
    """
    matched = check_shell_blacklist(command)
    assert matched is not None, (
        f"命令 {command!r} 未被 SHELL_BLACKLIST 拦截；"
        " 请检查 agent/tools/shell.py::SHELL_BLACKLIST 是否被改弱。"
    )


@pytest.mark.parametrize("command", [
    "ls -la",
    "cat README.md",
    "grep -r 'foo' .",
    "find . -name '*.py'",
    "echo hello",
    "pwd",
    "wc -l README.md",
])
def test_safe_shell_commands_are_not_blacklisted(command):
    """只读 / 无害命令不应被黑名单误伤。"""
    assert check_shell_blacklist(command) is None


def test_readonly_commands_baseline_set():
    """READONLY_COMMANDS 改动同样要先更新 preflight 文档。"""
    expected_subset = {"ls", "cat", "find", "grep", "wc", "head", "tail", "pwd"}
    assert expected_subset <= READONLY_COMMANDS, (
        "READONLY_COMMANDS 缺失基线项；请同步更新"
        " docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md §2.2"
    )


# ---------------------------------------------------------------------------
# §4 SHELL_BLACKLIST 已知缺口（preflight 文档 §3 表格第 2 行登记）
# ---------------------------------------------------------------------------

def test_known_gap_simple_quoted_rm_can_currently_bypass_blacklist():
    """已知缺口：简单引号转义可绕过黑名单（preflight 文档 §3 第 2 行登记）。

    例如 `r''m -rf /` 在 shell 中等价于 `rm -rf /`，但当前正则
    `\\brm\\s+(-...)` 不会命中。本测试**故意**断言「当前确实绕过」，
    用于：
    1. 让维护者意识到这不是被遗忘的盲区，是已登记的缺口。
    2. 当 M6 最小补丁完成（命令规范化后再跑黑名单）时，本测试会 red，
       提醒同步翻转断言并把缺口从 preflight 文档迁出。

    修复时请把本测试改为 `assert check_shell_blacklist(...) is not None`，
    并在 commit message 引用 docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md §3。
    """
    assert SHELL_BLACKLIST  # sanity
    bypass_command = "r''m -rf /tmp/anything"
    # 当前实现确实让这条命令通过——这是 preflight 登记的已知缺口。
    assert check_shell_blacklist(bypass_command) is None, (
        "如果本断言反向 red，说明 SHELL_BLACKLIST 已经被强化（例如先做命令"
        " 规范化再匹配）。请把本测试翻转为 assert is not None，并在"
        " docs/V0_2_TOOLING_AND_SECURITY_PREFLIGHT.md §3 把对应缺口迁出。"
    )
