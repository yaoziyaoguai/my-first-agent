"""Tool output policy characterization tests.

当前项目还没有集中式 ToolResult/output policy；read、shell、fetch 等工具各自
实现输出预算。本文件只锁这些现状，避免未来迁移结构化 ToolResult 前，输出形状
或截断策略悄悄漂移。
"""

from __future__ import annotations

from types import SimpleNamespace


def test_read_file_lines_result_shape_keeps_range_and_line_numbers(tmp_path) -> None:
    """按行读取的输出形状是当前大文件导航 contract。

    read_file 大文件概览会提示使用 read_file_lines，因此 line range、总行数和
    行号前缀必须稳定；这保护模型后续定位文件片段的能力。
    """

    from agent.tools.file_ops import read_file_lines

    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    result = read_file_lines(str(target), 2, 3)

    assert "[按行读取]" in result
    assert "范围: 第 2 行 - 第 3 行" in result
    assert "总行数: 4" in result
    assert "2: beta" in result
    assert "3: gamma" in result


def test_run_shell_no_output_result_shape_is_explicit(monkeypatch) -> None:
    """shell 无输出也要返回显式 observation，而不是空 tool_result。

    空字符串会让模型难以判断工具是否真的执行；当前 contract 用 `(无输出)`
    占位。未来结构化 ToolResult 也应保留“执行过但无输出”的语义。
    """

    import agent.tools.shell as shell_tool

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(shell_tool.subprocess, "run", _fake_run)

    result = shell_tool.run_shell("true")

    assert result == "[退出码: 0]\n(无输出)"


def test_fetch_url_large_content_uses_workspace_artifact_with_preview(
    tmp_path,
    monkeypatch,
) -> None:
    """fetch_url 大输出当前会写 workspace artifact 并返回预览。

    这不是最终 Blob/Artifact 设计；它只是现有 output budget 的本地实现。
    测试用 tmp cwd 和 fake httpx，不联网，也不写真实 workspace。
    """

    import agent.tools.web as web_tool

    class _FakeResponse:
        text = f"<html><body><p>{'x' * 11000}</p></body></html>"

        def raise_for_status(self) -> None:
            return None

    def _fake_get(*_args, **_kwargs):
        return _FakeResponse()

    monkeypatch.setattr(web_tool.httpx, "get", _fake_get)
    monkeypatch.chdir(tmp_path)

    result = web_tool.fetch_url("https://example.com/large")

    assert "[读取成功 - 内容较长，已保存到本地]" in result
    assert "本地文件: workspace/fetched_" in result
    saved_line = next(line for line in result.splitlines() if line.startswith("本地文件: "))
    saved_path = tmp_path / saved_line.removeprefix("本地文件: ")
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == "x" * 11000


def test_fetch_url_timeout_is_failure_like_output(monkeypatch) -> None:
    """网络读取 timeout 必须保持 failure-like，不得误判 success。

    fetch_url 属于当前临时网络工具；timeout 结果仍是字符串前缀。未来若迁移
    MCP/external adapter，应映射到同一 ToolResult failure contract。
    """

    import agent.tools.web as web_tool
    from agent.tool_executor import _classify_tool_outcome

    def _timeout_get(*_args, **_kwargs):
        raise web_tool.httpx.TimeoutException("timeout")

    monkeypatch.setattr(web_tool.httpx, "get", _timeout_get)

    result = web_tool.fetch_url("https://example.com/timeout")

    assert result.startswith("读取超时：")
    assert _classify_tool_outcome(result)[0] == "failed"
