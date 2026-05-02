"""File tool safety parity characterization tests.

本文件只描述当前 read/write/edit/fetch 工具的安全边界，不修 production。
目标是让 Tooling Foundation 先看清 FileRead / FileMutation / NetworkFetch
各自的 guard 分布，避免未来引入 apply_patch、MCP resource 或 SourceAdapter
时把安全策略散落到 core.py 或 display 层。
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from config import PROJECT_DIR


def _load_builtin_tools() -> None:
    """触发工具注册，保证 confirmation 查询来自真实 registry。"""

    importlib.import_module("agent.tools")


def _agent_imports(path: Path) -> set[str]:
    """用 AST 收集 agent.* imports，避免把注释误判成依赖。"""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names if alias.name.startswith("agent"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agent":
                imports.update(f"agent.{alias.name}" for alias in node.names)
            elif node.module.startswith("agent."):
                imports.add(node.module)
    return imports


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


def test_edit_file_rejects_project_escape_like_write_file() -> None:
    """edit_file 是 FileMutation，必须和 write_file 共享项目根边界。

    这是 MCP 前 cleanup 的 security characterization：read_file 对项目外路径是
    “需要确认”，但 write/edit 这种 mutation 必须 hard block。这个判断属于工具
    safety seam，不属于 runtime、confirmation handler 或 display；否则未来 MCP
    resource/file adapter 会绕过本地项目根边界。
    """

    from agent.tools.edit import pre_edit_check
    from agent.tools.write import pre_write_check

    assert "受保护源码文件" in pre_edit_check(
        "edit_file",
        {"path": "agent/core.py"},
        {},
    )

    assert pre_edit_check(
        "edit_file",
        {"path": "workspace/tooling-foundation-edit.txt"},
        {},
    ) is None
    assert "项目目录之外" in pre_edit_check(
        "edit_file",
        {"path": "/tmp/tooling-foundation-edit.txt"},
        {},
    )
    assert "项目目录之外" in pre_write_check(
        "write_file",
        {"path": "/tmp/tooling-foundation-write.txt", "content": "x"},
        {},
    )


def test_read_write_edit_project_root_parity_keeps_read_as_confirmation_only() -> None:
    """read/write/edit 对项目外路径的策略不同但必须一致可审计。

    read_file 是 FileRead，项目外普通路径可以交给 HITL confirmation；write/edit
    是 FileMutation，项目外路径必须在工具 safety 层拒绝。此测试让差异显式化，
    避免后续把 edit_file 当成 read_file 一样只靠确认，或把 read_file 误改成硬拒。
    """

    _load_builtin_tools()

    from agent.tool_registry import needs_tool_confirmation
    from agent.tools.edit import pre_edit_check
    from agent.tools.write import pre_write_check

    outside_path = "/tmp/tooling-foundation-project-root-parity.txt"

    assert needs_tool_confirmation("read_file", {"path": outside_path}) is True
    assert needs_tool_confirmation("read_file_lines", {
        "path": outside_path,
        "start_line": 1,
        "end_line": 1,
    }) is True
    assert "项目目录之外" in pre_write_check(
        "write_file",
        {"path": outside_path, "content": "x"},
        {},
    )
    assert "项目目录之外" in pre_edit_check(
        "edit_file",
        {"path": outside_path},
        {},
    )


def test_shared_path_safety_covers_relative_absolute_and_parent_escape_paths() -> None:
    """共享 path-safety helper 必须覆盖常见 project-root 绕过形态。

    这个测试直接验证 FileMutation 的底层 seam，而不是只测 edit/write 的表面
    文案：相对路径、绝对项目内路径应放行；`..` 和项目父目录绝对路径应拒绝。
    它保护的是 path boundary 算法，不涉及 runtime confirmation 或文件内容读取。
    """

    from agent.tools.path_safety import is_path_inside_project

    assert is_path_inside_project("workspace/tooling-foundation-edit.txt") is True
    assert is_path_inside_project(
        str(PROJECT_DIR / "workspace" / "tooling-foundation-absolute.txt")
    ) is True
    assert is_path_inside_project("../tooling-foundation-parent-escape.txt") is False
    assert is_path_inside_project(
        str(PROJECT_DIR.parent / "tooling-foundation-outside.txt")
    ) is False


def test_edit_file_rejects_parent_directory_escape_before_file_io() -> None:
    """edit_file 必须在 pre-check 阶段拒绝 `..` 逃逸路径。

    这里不创建也不读取项目外文件；只调用 pre_edit_check，确保 edit_file 在进入
    文件 IO 前复用共享 project-root safety。这样未来重构 edit implementation 时，
    不会绕过工具 safety seam 直接读写项目外路径。
    """

    from agent.tools.edit import pre_edit_check

    assert "项目目录之外" in pre_edit_check(
        "edit_file",
        {"path": "../tooling-foundation-parent-escape.txt"},
        {},
    )


def test_file_mutation_tools_share_path_safety_without_importing_each_other() -> None:
    """write/edit 共享 path_safety seam，但不互相依赖。

    这条架构测试比字符串 grep 更稳：FileMutation 工具都应该依赖
    `agent.tools.path_safety`，而不是让 edit.py import write.py 的私有函数或把
    file_ops.py 的 read confirmation 策略混入 mutation hard-block 逻辑。
    """

    write_imports = _agent_imports(PROJECT_DIR / "agent" / "tools" / "write.py")
    edit_imports = _agent_imports(PROJECT_DIR / "agent" / "tools" / "edit.py")

    assert "agent.tools.path_safety" in write_imports
    assert "agent.tools.path_safety" in edit_imports
    assert "agent.tools.edit" not in write_imports
    assert "agent.tools.write" not in edit_imports
    assert "agent.tools.file_ops" not in write_imports
    assert "agent.tools.file_ops" not in edit_imports


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
