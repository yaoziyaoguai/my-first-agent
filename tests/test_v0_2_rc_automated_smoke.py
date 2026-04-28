"""v0.2 RC 可自动化部分的 smoke 测试。

本文件覆盖 `docs/V0_2_MANUAL_SMOKE_PLAYBOOK.md` 中**不需要人眼判断
交互体验**的部分。它**不**调用真实 LLM、**不**触发用户交互、**不**
依赖外部环境（API key、网络、远端 skill）。

设计原则：
1. 不大改 runtime；只用现有公开入口（tools、checkpoint、security）做端到端
   行为校验。
2. 不伪造通过：真正必须人类观察的项（CLI 渲染顺序 / 文案可读性 / Ctrl+C
   恢复体验）**留在** manual playbook 里，本文件不假装覆盖。
3. 失败信息必须能直接对应到 playbook 第几节，方便排错时回到 playbook。

覆盖范围：
- §3.3  checkpoint 损坏字段过滤（_filter_to_declared_fields）
- §4.3  工具失败不污染 task.last_error 路径（直接调 read_file 不存在路径）
- §5.1  read_file / read_file_lines / write_file / calculate 工具基本可用
- §5.2  M6 安全：sensitive 文件 block、受保护源码写拒绝、
        shell 黑名单（含 P0 修复后的 .pem/.key、fork bomb、>/dev/sd）
- §5.3  CLI 输出契约：调用工具不会在 stdout 输出裸 dict / protocol dump
- §5.4  运行产物 .gitignore 覆盖

不在本文件覆盖（必须人眼）：
- §1   完整任务流的 CLI 可读性
- §2   实际 RuntimeEvent 投影正确性（已由 test_runtime_event_boundaries 守护）
- §3.1/§3.2 真实 Ctrl+C 中断后的复现体验（自动化只能验字段，不能验渲染）
- §4.1/§4.2 模型连续 max_tokens / no_progress 的真实文案
- §6   LLM Processing live smoke（已由 LLM 子线测试覆盖）
"""
from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from agent.security import is_protected_source_file, is_sensitive_file
from agent.tools.calc import calculate
from agent.tools.file_ops import read_file, read_file_lines
from agent.tools.shell import check_shell_blacklist
from agent.tools.write import pre_write_check

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# §5.1 工具基本可用
# ---------------------------------------------------------------------------

def test_smoke_read_file_returns_readme_content():
    """playbook §5.1：read_file 读取 README.md 必须成功。"""
    out = read_file("README.md")
    assert "my-first-agent" in out, (
        "read_file('README.md') 没有返回预期内容；"
        " 请按 playbook §5.1 手动重跑确认。"
    )


def test_smoke_read_file_lines_returns_specific_range():
    """playbook §5.1：read_file_lines 必须能读取指定范围。"""
    out = read_file_lines("README.md", 1, 5)
    assert isinstance(out, str) and len(out) > 0


def test_smoke_calculate_basic():
    """playbook §5.1：calculate 必须能算 (13*17)+1。"""
    assert calculate("(13*17)+1") == "222"


def test_smoke_read_nonexistent_file_returns_readable_error_not_crash():
    """playbook §4.3：工具失败必须返回可读字符串，不抛异常。"""
    out = read_file("/tmp/definitely_does_not_exist_v0_2_smoke_xyz.txt")
    assert isinstance(out, str)
    assert "不存在" in out or "错误" in out or "error" in out.lower()


# ---------------------------------------------------------------------------
# §5.2 M6 安全现状（含 P0 已修复项）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    ".env",
    "~/.env",
    "/tmp/api.key",          # P0 已修复
    "/tmp/server.pem",       # P0 已修复
    "/tmp/notes_password.txt",
])
def test_smoke_security_sensitive_file_blocked(path):
    """playbook §5.2：敏感文件 / 密钥扩展名必须被识别为 sensitive。"""
    assert is_sensitive_file(path), f"playbook §5.2: {path} 必须被 block"


def test_smoke_security_protected_source_blocks_write():
    """playbook §5.2：受保护源码（已存在的 .py）必须拒写。"""
    assert is_protected_source_file("agent/core.py")
    msg = pre_write_check("write_file", {"path": "agent/core.py"}, {})
    assert msg is not None and "拒绝" in msg


@pytest.mark.parametrize("command", [
    "rm -rf /",
    "sudo apt-get install x",
    ":(){ :|:& };:",          # P0 已修复
    "echo data > /dev/sda1",  # P0 已修复
    "chmod 777 /etc/passwd",
])
def test_smoke_security_shell_blacklist_blocks_dangerous(command):
    """playbook §5.2：危险命令必须被 SHELL_BLACKLIST 拦截（含 P0 修复项）。"""
    assert check_shell_blacklist(command) is not None, (
        f"playbook §5.2: {command!r} 必须被拦截"
    )


@pytest.mark.parametrize("command", [
    "ls -la",
    "cat README.md",
    "pwd",
    "echo hello",
])
def test_smoke_security_safe_shell_not_blacklisted(command):
    """playbook §5.2：常用只读命令不应被误伤。"""
    assert check_shell_blacklist(command) is None


# ---------------------------------------------------------------------------
# §3.3 checkpoint 损坏字段过滤（自动化）
# ---------------------------------------------------------------------------

def test_smoke_corrupted_checkpoint_unknown_fields_dropped(monkeypatch, tmp_path):
    """playbook §3.3：手改 checkpoint 加未知字段，加载不 crash 且字段被丢弃。"""
    from agent import checkpoint as ck
    from agent.state import create_agent_state

    fake_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(ck, "CHECKPOINT_PATH", fake_path)

    fake_path.write_text(json.dumps({
        "task": {
            "status": "idle",
            "__totally_unknown_field__": "should-be-dropped",
        },
        "memory": {"__also_unknown__": "drop-me"},
        "conversation": {"messages": []},
        "__top_level_garbage__": True,
    }), encoding="utf-8")

    state = create_agent_state(system_prompt="test")
    ok = ck.load_checkpoint_to_state(state)
    assert ok
    assert not hasattr(state.task, "__totally_unknown_field__")
    assert not hasattr(state.memory, "__also_unknown__")


# ---------------------------------------------------------------------------
# §5.3 CLI 输出契约：工具调用不会污染 stdout
# ---------------------------------------------------------------------------

def test_smoke_calculate_does_not_print_to_stdout():
    """playbook §5.3：calculate 不应在 stdout 写裸 dict / 调试信息。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        calculate("1+1")
    assert buf.getvalue() == "", (
        f"calculate 不应该 print 任何东西，实际输出：{buf.getvalue()!r}"
    )


def test_smoke_read_file_does_not_print_to_stdout():
    """playbook §5.3：read_file 不应在 stdout 写裸 dict / 调试信息。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        read_file("README.md")
    assert buf.getvalue() == "", (
        f"read_file 不应该 print 任何东西，实际输出：{buf.getvalue()!r}"
    )


# ---------------------------------------------------------------------------
# §5.4 运行产物 .gitignore 覆盖
# ---------------------------------------------------------------------------

GITIGNORE_REQUIRED_PATTERNS = [
    ".env",
    "memory/",
    "summary.md",
    "runs/",
    "state.json",
]


@pytest.mark.parametrize("pattern", GITIGNORE_REQUIRED_PATTERNS)
def test_smoke_gitignore_covers_runtime_artifacts(pattern):
    """playbook §5.4：本地运行产物必须被 .gitignore 覆盖。

    注意：checkpoint.json 是通过 `memory/` 目录覆盖的，不是单独 pattern；
    实际是否生效由 `test_smoke_runtime_artifacts_not_tracked_by_git` 二次
    校验。
    """
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert pattern in gi, (
        f".gitignore 缺少 {pattern!r}；本地运行产物可能误入 git。"
    )


def test_smoke_runtime_artifacts_not_tracked_by_git():
    """playbook §5.4：跑过 smoke 后这些产物不会出现在 git status。

    用 `git check-ignore` 验证 .gitignore 是真实生效的；如果 pattern 写错或
    被前置规则覆盖，本测试会立刻失败。
    """
    candidate_paths = [
        ".env",
        "memory/checkpoint.json",
        "summary.md",
        "runs/foo.log",
        "state.json",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *candidate_paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # check-ignore 退出码 0 = 全部被 ignore；1 = 部分未被 ignore
    if result.returncode != 0:
        ignored = set(result.stdout.split())
        missing = [p for p in candidate_paths if p not in ignored]
        pytest.fail(
            f"以下路径未被 .gitignore 覆盖：{missing}；请检查 .gitignore"
        )
