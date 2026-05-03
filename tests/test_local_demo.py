"""Local Agent Productization 切片测试。

中文学习边界：
- 这一组测试只跑 ``agent/local_demo.py`` 提供的 fake demo 闭环；
- 不允许进入 ``agent.core`` / ``agent.tool_executor`` / ``agent.checkpoint``；
- 不允许 import ``anthropic`` / ``requests`` / ``httpx`` / ``urllib`` / ``socket``；
- demo 写入路径必须在 ``workspace/demo/`` 或 ``tempfile.gettempdir()`` 下。
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from agent.local_demo import (
    DemoResult,
    FakeProvider,
    UnsafeDemoPathError,
    format_demo_result,
    resolve_demo_workspace,
    run_demo_cli,
    run_local_demo,
)


# ---------- happy path / fake provider ---------------------------------------


def test_run_local_demo_happy_path_writes_note_in_workspace(tmp_path):
    """快乐路径：fake provider 在显式 tmp_path 下完成一次完整闭环。"""

    result = run_local_demo("create a demo note about today's work", workspace=tmp_path)

    assert isinstance(result, DemoResult)
    assert result.provider == "fake"
    assert result.workspace == tmp_path.resolve()
    assert len(result.steps) == 1

    step = result.steps[0]
    assert step.action.tool_name == "demo.write_demo_note"
    assert step.envelope.status == "executed"

    note_path = Path(step.action.tool_input["path"])
    assert note_path.exists()
    body = note_path.read_text(encoding="utf-8")
    assert "task: create a demo note about today's work" in body
    assert "provider: fake" in body

    assert result.final_answer.startswith("wrote demo note to ")


def test_run_local_demo_default_provider_is_fake(tmp_path):
    """显式不传 provider 时默认仍然是 FakeProvider。"""

    result = run_local_demo("hello", workspace=tmp_path)
    assert result.provider == FakeProvider.name == "fake"


def test_run_local_demo_does_not_require_api_key(tmp_path, monkeypatch):
    """无 ANTHROPIC_API_KEY 时也必须跑通；demo 不应依赖任何 secret env。"""

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = run_local_demo("ensure no api key", workspace=tmp_path)
    assert result.steps[0].envelope.status == "executed"


# ---------- dependency boundary ---------------------------------------------


_FORBIDDEN_IMPORT_TOKENS = (
    "anthropic",
    "openai",
    "requests",
    "httpx",
    "urllib",
    "socket",
    "agent.core",
    "agent.tool_executor",
    "agent.checkpoint",
    "agent.mcp",
)


def test_local_demo_module_has_no_forbidden_imports():
    """守住边界：local_demo 不应 import runtime brain / 网络 / 真实 provider。

    只扫描以 ``import`` / ``from`` 开头的真实导入语句，避免把 docstring 中
    解释边界的文字误判为依赖。
    """

    import_lines = []
    for raw in Path("agent/local_demo.py").read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            import_lines.append(stripped)
    joined = "\n".join(import_lines)
    for token in _FORBIDDEN_IMPORT_TOKENS:
        assert token not in joined, (
            f"agent/local_demo.py must not import {token!r}; got:\n{joined}"
        )


def test_main_demo_subcommand_is_thin_adapter():
    """``main.py`` 中 demo 分支只允许做 argv 转发，不能塞业务逻辑。"""

    text = Path("main.py").read_text(encoding="utf-8")
    assert "from agent.local_demo import run_demo_cli" in text
    assert 'if argv and argv[0] == "demo":' in text


def test_no_network_modules_loaded_after_demo(tmp_path):
    """子进程跑完 demo 后 sys.modules 不应包含网络 / 真实 provider 模块。

    这里用 subprocess 隔离，因为 pytest 主进程可能因为其他测试已经加载了
    httpx / anthropic，会污染同进程断言。子进程只 import ``agent.local_demo``
    并跑一次 demo，结束后打印 sys.modules 里是否出现禁用模块。
    """

    import json
    import subprocess
    import textwrap

    code = textwrap.dedent(
        f"""
        import sys
        from agent.local_demo import run_local_demo
        run_local_demo("network boundary subprocess", workspace=r"{tmp_path}")
        forbidden = ("anthropic", "openai", "requests", "httpx", "urllib3")
        loaded = sorted(m for m in forbidden if m in sys.modules)
        import json
        print(json.dumps(loaded))
        """
    )
    out = subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    loaded = json.loads(out.decode("utf-8").strip())
    assert loaded == [], f"local demo must not load network modules; got {loaded}"


# ---------- path safety ------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "sessions/demo",
        "runs/demo",
        "memory/demo",
        "skills/demo",
        ".env",
        "agent_log.jsonl",
        "/etc/demo",
    ],
)
def test_run_local_demo_rejects_unsafe_workspace(bad_path):
    """workspace 落在敏感目录或项目外时必须直接拒绝，不能静默写入。"""

    with pytest.raises(UnsafeDemoPathError):
        run_local_demo("unsafe", workspace=bad_path)


def test_resolve_demo_workspace_default_is_under_workspace_demo():
    """默认 workspace 必须落在 repo 内 ``workspace/demo/``。"""

    safe = resolve_demo_workspace()
    repo_demo_root = (Path(__file__).resolve().parent.parent / "workspace" / "demo").resolve()
    assert safe.is_relative_to(repo_demo_root)


# ---------- redaction & trace summary ---------------------------------------


def test_trace_summary_redacts_secret_in_task(tmp_path):
    """task 里偶然出现 sk- token 时，渲染出的 trace summary 必须脱敏。"""

    secret_task = "explore sk-ABCDEFGHIJKLMNOP token usage"
    result = run_local_demo(secret_task, workspace=tmp_path)
    rendered = format_demo_result(result)

    assert "sk-ABCDEFGHIJKLMNOP" not in rendered
    assert "[REDACTED]" in rendered
    assert "Trace summary" in rendered
    assert "demo.complete" in rendered


def test_format_demo_result_lists_each_step_and_final(tmp_path):
    """presenter 必须把 task / provider / step / final / trace / inspect 都打出来。"""

    result = run_local_demo("demo render", workspace=tmp_path)
    rendered = format_demo_result(result)

    for needle in (
        "[Local Agent Demo] provider=fake",
        "Task : demo render",
        "Step 1 demo.write_demo_note -> ok",
        "Final: wrote demo note to ",
        "Trace summary",
        "Inspect: open ",
    ):
        assert needle in rendered, f"missing line in demo output: {needle!r}"


# ---------- CLI thin adapter -------------------------------------------------


def test_run_demo_cli_writes_artifact_and_returns_zero(tmp_path, capsys, monkeypatch):
    """CLI 入口在 tmp workspace 下应返回 0 并产生 note 文件。"""

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = run_demo_cli(["create a CLI demo note", "--workspace", str(tmp_path)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "[Local Agent Demo] provider=fake" in captured.out
    note = tmp_path / "note.md"
    assert note.exists()


def test_run_demo_cli_rejects_unsafe_workspace(capsys):
    """CLI 不能让用户绕开 path safety。"""

    rc = run_demo_cli(["task", "--workspace", "sessions/demo"])
    captured = capsys.readouterr()

    assert rc == 2
    assert "Error" in captured.out


def test_run_demo_cli_help_returns_zero(capsys):
    rc = run_demo_cli(["--help"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Usage:" in captured.out
