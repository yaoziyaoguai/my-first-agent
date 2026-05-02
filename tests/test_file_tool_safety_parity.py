"""File tool safety parity characterization tests.

本文件只描述当前 read/write/edit/fetch 工具的安全边界，不修 production。
目标是让 Tooling Foundation 先看清 FileRead / FileMutation / NetworkFetch
各自的 guard 分布，避免未来引入 apply_patch、MCP resource 或 SourceAdapter
时把安全策略散落到 core.py 或 display 层。
"""

from __future__ import annotations

import importlib
from pathlib import Path


def _load_builtin_tools() -> None:
    """触发工具注册，保证 confirmation 查询来自真实 registry。"""

    importlib.import_module("agent.tools")


def test_read_file_tools_share_sensitive_and_project_confirmation_policy() -> None:
    """read_file/read_file_lines 共享同一类读取确认策略。

    敏感文件直接 block；项目内普通文件免确认；项目外普通路径需要确认。
    测试只检查路径策略，不读取 `.env` 或项目外文件内容。
    """

    _load_builtin_tools()

    from agent.tool_registry import needs_tool_confirmation

    for tool_name in ("read_file", "read_file_lines"):
        assert needs_tool_confirmation(tool_name, {"path": ".env"}) == "block"
        assert needs_tool_confirmation(tool_name, {"path": "README.md"}) is False
        assert needs_tool_confirmation(
            tool_name,
            {"path": "/tmp/tooling-foundation-outside.txt"},
        ) is True


def test_write_file_rejects_project_escape_protected_source_and_dangerous_content() -> None:
    """write_file 是高风险 FileMutation，必须有多层 pre_execute guard。

    这里锁住当前顺序：受保护源码拒绝、项目外路径拒绝、明显危险内容拒绝。
    这些 guard 属于工具 safety seam，不应搬到 display，也不能由 core.py 特判。
    """

    from agent.tools.write import pre_write_check

    assert "受保护源码文件" in pre_write_check(
        "write_file",
        {"path": "agent/core.py", "content": "x"},
        {},
    )
    assert "项目目录之外" in pre_write_check(
        "write_file",
        {"path": "/tmp/tooling-foundation-write.txt", "content": "x"},
        {},
    )
    assert "敏感密钥头" in pre_write_check(
        "write_file",
        {
            "path": "workspace/key-notes.txt",
            "content": "-----BEGIN PRIVATE KEY-----\nsecret\n",
        },
        {},
    )


def test_write_and_edit_share_same_round_single_mutation_guard() -> None:
    """write_file/edit_file 当前共享“同一轮只允许一次写操作”的语义。

    这保护 runtime/tooling 的 mutation 节流边界：一次模型响应不应连续写多个文件
    来绕过用户 review。后续 apply_patch/edit_patch 也必须复用这个 seam。
    """

    from agent.tools.edit import pre_edit_check
    from agent.tools.write import pre_write_check

    context = {"write_file_seen": True}

    assert "同一轮" in pre_write_check(
        "write_file",
        {"path": "workspace/a.txt", "content": "x"},
        context,
    )
    assert "同一轮" in pre_edit_check(
        "edit_file",
        {"path": "workspace/a.txt"},
        context,
    )


def test_edit_file_currently_only_has_protected_source_and_round_guards() -> None:
    """edit_file 的项目边界现状是 characterization，不是最终认可。

    当前 edit_file pre-check 会拒绝受保护源码和同轮重复写，但没有像 write_file
    一样做 project root guard。测试把这个 production gap 明确暴露出来；如果要修，
    应单独开安全修复 slice，而不是混进 tests-only characterization。
    """

    from agent.tools.edit import pre_edit_check

    assert "受保护源码文件" in pre_edit_check(
        "edit_file",
        {"path": "agent/core.py"},
        {},
    )
    assert pre_edit_check(
        "edit_file",
        {"path": "/tmp/tooling-foundation-edit.txt"},
        {},
    ) is None


def test_fetch_url_is_network_tool_with_confirmation_and_url_only_schema() -> None:
    """fetch_url 是当前 base registry 里的临时网络读取工具。

    它不是 file read，也不是 MCP；当前必须 always confirm，schema 也只能暴露 URL。
    长期是否转为 MCP/external adapter 是后续决策，不在本 slice 实现。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, needs_tool_confirmation

    entry = TOOL_REGISTRY["fetch_url"]

    assert entry["parameters"].keys() == {"url"}
    assert needs_tool_confirmation("fetch_url", {"url": "https://example.com"}) is True


def test_file_tool_safety_tests_do_not_depend_on_real_session_artifacts() -> None:
    """file safety 测试不能读取真实 sessions/runs 或 agent_log.jsonl。

    这条测试是边界提醒：Tooling Foundation 只验证工具策略，不把真实运行产物、
    session state 或日志内容纳入测试输入，避免泄漏和不可复现。
    """

    forbidden_roots = {Path("sessions"), Path("runs"), Path("agent_log.jsonl")}

    assert all(path.parts[0] in {"sessions", "runs"} or path.name == "agent_log.jsonl"
               for path in forbidden_roots)
