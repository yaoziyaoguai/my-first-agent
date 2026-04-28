"""v0.2 RC P1-C 工具负向断言：明确「不应通过」的边界。

本文件聚焦**负向**契约：哪些路径/内容/工具组合**绝不**能放行。同时
配套**正向**用例，证明 P1 加强没有误伤合法路径。

设计原则：
- 每个负向断言都对应一条 preflight / playbook 中明确登记的边界，不做
  发明性约束。
- 每个负向断言都搭配「正常路径不被误伤」的反向用例，避免 P1 收紧成
  过度防御。
- 不调用真实 LLM、不触发用户确认 prompt、不依赖外部环境。

边界：本文件**不**测 read_file / write_file 端到端 IO；那归 tools/ 自己
的测试。这里只验证 pre_write_check / SHELL_BLACKLIST / TOOL_REGISTRY
层面的契约。
"""
from __future__ import annotations

import pytest

from agent.security import is_protected_source_file, is_sensitive_file
from agent.tool_registry import TOOL_REGISTRY, is_meta_tool
from agent.tools.calc import calculate
from agent.tools.shell import check_shell_blacklist
from agent.tools.write import _check_dangerous_content, pre_write_check


# ---------------------------------------------------------------------------
# §1 写入受保护源码文件 → 必须拒
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "agent/core.py",
    "agent/state.py",
    "config.py",
    "main.py",
])
def test_write_protected_source_file_is_rejected(path):
    """v0.2 RC：受保护源码（已存在的 .py）写入必须被 pre_write_check 拒绝。"""
    assert is_protected_source_file(path)
    msg = pre_write_check("write_file", {"path": path, "content": "x"}, {})
    assert msg is not None and "拒绝" in msg, (
        f"受保护源码 {path} 应被拒写；当前 pre_write_check 返回 {msg!r}"
    )


# ---------------------------------------------------------------------------
# §2 写入 .pem / .key 内容（路径看似安全）→ P1-B 必须拒
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n",
    "-----BEGIN RSA PRIVATE KEY-----\nMIICXgIBAA...\n",
    "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNza...\n",
])
def test_write_private_key_content_is_rejected_even_with_safe_path(payload):
    """P1-B：私钥头出现在写入内容中，即使路径是 .txt / .md 也必须拒。

    这条阻止「扩展名看起来安全 → 内容是真密钥」的写入。
    """
    msg = pre_write_check(
        "write_file",
        {"path": "workspace/notes.txt", "content": payload},
        {},
    )
    assert msg is not None and "敏感密钥头" in msg


@pytest.mark.parametrize("payload", [
    ":(){ :|:& };:\n",
    "#!/bin/sh\nrm -rf /tmp/anything\n",
    "echo data > /dev/sda1\n",
    "mkfs.ext4 /dev/sdb\n",
])
def test_write_dangerous_shell_payload_is_rejected(payload):
    """P1-B：危险 shell payload 出现在写入内容中必须拒。"""
    msg = pre_write_check(
        "write_file",
        {"path": "workspace/script.txt", "content": payload},
        {},
    )
    assert msg is not None and "危险 shell payload" in msg


# ---------------------------------------------------------------------------
# §3 正向：普通安全内容仍可通过
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    "# 项目总结\n\n这是一段普通的中文笔记。\n",
    "Hello world\nLine 2\nLine 3\n",
    "name,value\nfoo,1\nbar,2\n",
    "",
    "console.log('safe')",
    # 注意：含 'rm' 子串但不是危险 payload，应放行
    "function rm_user(id) { return db.remove(id); }",
])
def test_write_safe_content_is_allowed(content):
    """P1-B：普通安全内容不能被误伤。"""
    msg = pre_write_check(
        "write_file",
        {"path": "workspace/safe.txt", "content": content},
        {},
    )
    # protected source 与同轮单写不会触发（path 是 workspace、context 空）
    assert msg is None, (
        f"P1-B 误伤了安全内容 {content!r}；返回 {msg!r}。"
        " 请检查 DANGEROUS_CONTENT_MARKERS / DANGEROUS_CONTENT_SUBSTRINGS"
        " 是否过于宽泛。"
    )


def test_check_dangerous_content_handles_non_string():
    """P1-B：_check_dangerous_content 对非字符串/空内容必须返回 None。"""
    assert _check_dangerous_content("") is None
    assert _check_dangerous_content(None) is None  # type: ignore[arg-type]
    assert _check_dangerous_content(123) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §4 危险 shell 命令片段（含 P1-A 规范化覆盖）→ 必须拒
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf /",
    "rm  -rf  /tmp",
    "sudo bash",
    "chmod 777 /etc/shadow",
    ":(){ :|:& };:",
    "echo data > /dev/sda1",
    # P1-A 规范化拦截
    "r''m -rf /",
    "RM -RF /",
    "rm\t-rf /tmp",
    "\\rm -rf /tmp",
])
def test_dangerous_shell_fragments_blocked(command):
    """v0.2 RC：所有危险命令片段（含 P0 + P1-A 修复项）必须被拦截。"""
    assert check_shell_blacklist(command) is not None, (
        f"危险命令 {command!r} 未被拦截；请检查 SHELL_BLACKLIST"
        " 与 _normalize_shell_command。"
    )


@pytest.mark.parametrize("command", [
    "ls -la",
    "cat README.md",
    "echo hello",
    "pwd",
    "grep -r 'foo' .",
    "wc -l README.md",
    "python -c 'print(1)'",
    "echo 'safe content' > workspace/notes.txt",
])
def test_safe_shell_commands_not_blocked(command):
    """v0.2 RC：常用只读命令与正常重定向不被误伤。"""
    assert check_shell_blacklist(command) is None, (
        f"P1-A 误伤了正常命令 {command!r}"
    )


# ---------------------------------------------------------------------------
# §5 工具注册一致性（P1-C 负向断言）
# ---------------------------------------------------------------------------

# 已知元工具白名单——v0.2 RC 范围内只有这两个
KNOWN_META_TOOLS = {"request_user_input", "mark_step_complete"}


def test_no_business_tool_is_meta_tool():
    """P1-C 负向断言：业务工具绝不能被误标 meta_tool=True。

    元工具的 tool_use 不进 conversation.messages、不产生 tool_result；
    如果 read_file / write_file 等业务工具被误标元工具，会在模型上下文中
    彻底消失，引发 silent failure。本测试钉死「只有这两个是元工具」。
    """
    actual_meta = {
        name for name, info in TOOL_REGISTRY.items()
        if info.get("meta_tool", False)
    }
    assert actual_meta == KNOWN_META_TOOLS, (
        f"meta_tool 集合漂移：期望 {KNOWN_META_TOOLS}，实际 {actual_meta}。"
        " 如果你新增了元工具，请同步更新 KNOWN_META_TOOLS 并审查是否真的"
        " 应该走元工具路径。"
    )


def test_is_meta_tool_consistency():
    """is_meta_tool() 与 TOOL_REGISTRY meta_tool 字段必须一致。"""
    for name, info in TOOL_REGISTRY.items():
        expected = bool(info.get("meta_tool", False))
        assert is_meta_tool(name) is expected, (
            f"工具 {name} meta_tool 字段 ({expected}) 与 is_meta_tool() 不一致"
        )


def test_all_tools_have_valid_confirmation_setting():
    """每个注册工具的 confirmation 必须是 'always' / 'never' 或 callable。"""
    for name, info in TOOL_REGISTRY.items():
        c = info.get("confirmation")
        assert c in ("always", "never") or callable(c), (
            f"工具 {name} 的 confirmation={c!r} 不在合法集合内"
        )


# ---------------------------------------------------------------------------
# §6 正常工具调用不被误伤
# ---------------------------------------------------------------------------

def test_calculate_safe_expression_works():
    """P1 加固后 calculate 不能受影响。"""
    assert calculate("2+3*4") == "14"


def test_non_sensitive_path_not_blocked():
    """普通路径不应被 is_sensitive_file 当成敏感。"""
    assert not is_sensitive_file("workspace/notes.txt")
    assert not is_sensitive_file("README.md")
    assert not is_sensitive_file("docs/guide.md")
