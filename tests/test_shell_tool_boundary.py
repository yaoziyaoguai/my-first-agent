"""RunShell / Bash 边界 characterization tests.

本文件只锁当前 Tooling Foundation 的 shell 执行边界：`run_shell` 是
one-shot command 工具，不是 Bash alias、不是 persistent session，也不是
Python/dependency/sandbox 入口。这里不新增工具、不改生产实现；如果这些测试
暴露需要生产修复的安全缺口，应停止并单独开 slice。
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from config import PROJECT_DIR


def _load_builtin_tools() -> None:
    """显式加载基础工具注册入口，避免依赖测试顺序。"""

    importlib.import_module("agent.tools")


def test_run_shell_is_only_shell_like_builtin_and_no_bash_alias() -> None:
    """基础工具集当前只暴露 `run_shell`，不暴露 Bash alias。

    这保护的是工具选择面：Bash alias 会新增一个几乎等价的模型 Action，
    增加选择负担。未来若要改名或 alias，应先设计 Bash-like ToolSpec，
    而不是在 registry 里悄悄多注册一个工具名。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, execute_tool, get_tool_definitions
    from agent.tool_executor import _classify_tool_outcome

    visible_tools = {definition["name"] for definition in get_tool_definitions()}
    forbidden_aliases = {"bash", "shell", "run_bash", "python_exec", "run_python"}

    assert "run_shell" in visible_tools
    assert forbidden_aliases.isdisjoint(visible_tools)
    assert forbidden_aliases.isdisjoint(TOOL_REGISTRY)

    result = execute_tool("bash", {"command": "pwd"})
    assert result == "工具 'bash' 不在允许列表中"
    assert _classify_tool_outcome(result)[0] == "failed"


def test_run_shell_schema_is_one_shot_command_only() -> None:
    """`run_shell` schema 只表达一次性 command，不表达 session/env/cwd。

    cwd/env/stdin/session/dependency 安装都属于更复杂的 execution seam；
    现在不能通过 schema 暗示支持这些能力，否则未来 checkpoint、logging、
    confirmation 和 sandbox 都会被动背上未设计的状态语义。
    """

    _load_builtin_tools()

    from agent.tool_registry import TOOL_REGISTRY, get_tool_definitions

    registry_entry = TOOL_REGISTRY["run_shell"]
    definition = {
        definition["name"]: definition for definition in get_tool_definitions()
    }["run_shell"]

    assert registry_entry["parameters"].keys() == {"command"}
    assert definition["input_schema"]["properties"].keys() == {"command"}
    assert definition["input_schema"]["required"] == ["command"]
    assert registry_entry["confirmation"] == "always"


def test_run_shell_invokes_subprocess_with_project_root_cwd_and_timeout(monkeypatch) -> None:
    """shell 工具当前固定在 PROJECT_DIR 下执行，并使用硬 timeout。

    这是 cwd/timeout 边界的 characterization：它不是 sandbox，也不允许模型
    传入任意 cwd/env。测试只观察传给 subprocess 的参数，不运行真实命令。
    """

    import agent.tools.shell as shell_tool

    captured: dict[str, object] = {}

    def _fake_run(command: str, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(stdout="hello\n", stderr="warn\n", returncode=7)

    monkeypatch.setattr(shell_tool.subprocess, "run", _fake_run)

    result = shell_tool.run_shell("echo hello")

    assert captured == {
        "command": "echo hello",
        "shell": True,
        "capture_output": True,
        "text": True,
        "timeout": shell_tool.SHELL_TIMEOUT,
        "cwd": str(PROJECT_DIR),
    }
    assert result.startswith("[退出码: 7]")
    assert "[stdout]\nhello" in result
    assert "[stderr]\nwarn" in result


def test_run_shell_timeout_is_legacy_failure_string(monkeypatch) -> None:
    """timeout 当前仍是字符串 ToolResult，不是结构化 ToolResult。

    这条测试保护现状而不是认可最终设计：未来应迁移到 `{timed_out: true}`
    之类结构化结果，但迁移前不能让 timeout 变成 success。
    """

    import agent.tools.shell as shell_tool
    from agent.tool_executor import _classify_tool_outcome

    def _timeout_run(command: str, **kwargs):
        raise shell_tool.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(shell_tool.subprocess, "run", _timeout_run)

    result = shell_tool.run_shell("sleep 999")

    assert result == "执行超时：命令在 30 秒内未完成，已被终止。"
    assert _classify_tool_outcome(result)[0] == "failed"


def test_run_shell_rejects_dangerous_command_before_subprocess(monkeypatch) -> None:
    """危险命令必须在进入 subprocess 前被工具内部最后防线拒绝。

    confirmation 是 runtime/HITL 边界；shell 工具自身的 blacklist 是第二道防线。
    两者不能互相替代，也不能让危险命令先执行再报告失败。
    """

    import agent.tools.shell as shell_tool

    def _forbidden_run(*_args, **_kwargs):
        raise AssertionError("dangerous command reached subprocess")

    monkeypatch.setattr(shell_tool.subprocess, "run", _forbidden_run)

    result = shell_tool.run_shell("rm -rf /tmp/tooling-boundary")

    assert result.startswith("拒绝执行：命令匹配危险模式")


def test_run_shell_rejects_sensitive_file_argument_before_subprocess(monkeypatch) -> None:
    """shell 命令涉及敏感文件名时必须先拒绝，不读取敏感内容。

    测试只使用 `.env` 字符串作为路径名，不读取文件内容；它保护的是
    no-sensitive-read 边界在 shell 工具里的最小投影。
    """

    import agent.tools.shell as shell_tool

    def _forbidden_run(*_args, **_kwargs):
        raise AssertionError("sensitive command reached subprocess")

    monkeypatch.setattr(shell_tool.subprocess, "run", _forbidden_run)

    result = shell_tool.run_shell("cat .env")

    assert result == "拒绝执行：命令涉及敏感文件 '.env'，禁止访问。"


def test_run_shell_long_output_is_truncated(monkeypatch) -> None:
    """shell 输出预算当前在工具内本地实现。

    这说明项目已有 output budget 意识，但还没有统一 ToolResult output policy。
    本测试把现状钉住，避免后续重构悄悄移除截断。
    """

    import agent.tools.shell as shell_tool

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout="x" * 6000, stderr="", returncode=0)

    monkeypatch.setattr(shell_tool.subprocess, "run", _fake_run)

    result = shell_tool.run_shell("echo long-output")

    assert result.startswith("[退出码: 0]\n[stdout]")
    assert "输出过长，已截断" in result
    assert "共 6009 字符" in result
