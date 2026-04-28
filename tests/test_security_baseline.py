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
    # v0.2 RC P0 安全边界补丁：扩展名识别真实密钥文件。
    # 这些 case 在 P0 之前会失败，因为旧的 is_sensitive_file 只看完整文件名。
    "/tmp/server.pem",
    "/tmp/api.key",
    "secrets/private.pem",
    "secrets/api.KEY",  # 大小写不敏感
])
def test_sensitive_files_are_blocked(path):
    """文件名命中 SENSITIVE_PATTERNS / 关键词 / `.env` 前缀 / 敏感扩展名 → block。

    这条 invariant 是 read_file / read_file_lines 的 `_check_read_permission`
    依赖项；任何对 SENSITIVE_PATTERNS / SENSITIVE_KEYWORDS / SENSITIVE_SUFFIXES
    的修改都会让本测试失败，提醒维护者评估是否要同步更新 preflight 文档。

    v0.2 RC P0 已修复：`.pem` / `.key` 扩展名识别。
    """
    assert is_sensitive_file(path), (
        f"敏感路径 {path!r} 未被 is_sensitive_file 识别；"
        " 请检查 SENSITIVE_PATTERNS / SENSITIVE_KEYWORDS / SENSITIVE_SUFFIXES"
        " 是否被改弱。"
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
    # v0.2 RC P0 安全边界补丁：fork bomb 字面匹配。
    ":(){ :|:& };:",
    ":() { :|:& };:",
    # v0.2 RC P0 安全边界补丁：>/dev/sd 重定向。
    "echo data > /dev/sda1",
    "cat foo >/dev/sdb",
])
def test_dangerous_shell_commands_are_blacklisted(command):
    """SHELL_BLACKLIST 必须拦截所有典型危险命令。

    任何对正则的「优化」或「简化」都可能放过这些命令；本测试是回归网。
    新增危险模式时，加一条参数即可。

    v0.2 RC P0 已修复：fork bomb 与 `> /dev/sd` 的 word boundary 失效问题。
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
# §4 SHELL_BLACKLIST 命令规范化（v0.2 RC P1-A）
# ---------------------------------------------------------------------------

def test_simple_quoted_rm_now_blocked_after_p1_normalization():
    """v0.2 RC P1-A 已修复：简单引号绕过 `r''m -rf /` 现在被规范化后命中。

    历史：preflight §3 把这条记为「已知缺口」，旧测试 `test_known_gap_*`
    断言 `is None`。P1-A 加入 `_normalize_shell_command` 后，规范化能去掉
    成对空引号，让正则真的命中 `rm -rf /`。

    如果未来重构去掉了规范化，本测试会立刻 red，提醒在 preflight 文档
    把缺口写回去。
    """
    assert SHELL_BLACKLIST  # sanity
    bypass_command = "r''m -rf /tmp/anything"
    assert check_shell_blacklist(bypass_command) is not None, (
        "P1-A 命令规范化预期能拦截 `r''m -rf /...`；"
        " 如果意外放过，请检查 _normalize_shell_command 是否被简化或移除。"
    )


@pytest.mark.parametrize("command", [
    'r""m -rf /tmp/x',           # 双引号绕过
    "\\rm -rf /tmp/x",           # 反斜杠转义
    "rm\t-rf /tmp/x",            # tab
    "rm  \t  -rf /tmp/x",        # 多空白
    "RM -RF /tmp/x",             # 大小写
    "rm\n-rf /tmp/x",            # 换行
    "su''do apt install evil",   # sudo 引号绕过
])
def test_normalized_bypass_forms_are_blocked(command):
    """P1-A：常见绕过形态在规范化后必须命中。"""
    assert check_shell_blacklist(command) is not None, (
        f"P1-A 期望规范化拦截 {command!r}，实际放过；请检查"
        " _normalize_shell_command 与 check_shell_blacklist。"
    )


@pytest.mark.parametrize("command", [
    "echo 'hello world'",         # 含字符的引号不能被破坏
    "ls -la",
    "cat README.md",
    "grep -r 'foo bar' .",
    "echo \"safe content\" > workspace/notes.txt",
])
def test_p1_normalization_does_not_break_safe_commands(command):
    """P1-A：规范化不能误伤正常命令（含引号字符串、重定向到普通路径）。"""
    assert check_shell_blacklist(command) is None, (
        f"P1-A 误伤了正常命令 {command!r}；请收紧 _normalize_shell_command。"
    )
