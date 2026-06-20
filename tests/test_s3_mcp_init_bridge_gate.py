"""S3 audit fix (L2): MCP default-off 端到端 gate 测试（main.py init bridge 级）。

审计 L2：原 `test_mcp_default_off_not_exposed` 只断言到 `evaluate_activation` 决策层，
未端到端断言 `main.py:_init_mcp_bridge_if_enabled` 在 default-off 时**实际不运行 bridge**
（不注册 MCP 工具）。本测试补齐端到端 gate：

- default-off（`MY_FIRST_AGENT_MCP_ENABLE` 未设）→ early-return，`run_mcp_bridge` 不被调用；
- 显式 opt-in（=1）→ gate 放行，`run_mcp_bridge` 被调用。

不连真实 MCP endpoint（spy 掉 run_mcp_bridge），符合 `AGENTS.md` 安全边界。
"""
from __future__ import annotations

from types import SimpleNamespace

import main as main_mod


def test_init_mcp_bridge_default_off_does_not_run_bridge(monkeypatch):
    """default-off：契约 gate 关闭 → bridge 不运行（MCP 工具不暴露）。"""
    monkeypatch.delenv("MY_FIRST_AGENT_MCP_ENABLE", raising=False)

    import agent.mcp_bridge as mcp_bridge

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("default-off 时 run_mcp_bridge 不应被调用")

    monkeypatch.setattr(mcp_bridge, "run_mcp_bridge", _must_not_run)

    # 不抛异常即证明走了 early-return（未触达 run_mcp_bridge）。
    main_mod._init_mcp_bridge_if_enabled(session_id="s3-l2-default-off")


def test_init_mcp_bridge_opt_in_runs_bridge(monkeypatch):
    """显式 opt-in（=1）：gate 放行 → bridge 被调用（与 main.py 既有 opt-in 语义一致）。"""
    monkeypatch.setenv("MY_FIRST_AGENT_MCP_ENABLE", "1")

    import agent.mcp_bridge as mcp_bridge

    calls: list[bool] = []

    def _spy_run(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(
            mode="registration",
            servers_evaluated=0,
            servers_configured=0,
            tools_discovered=0,
            tools_blocked=0,
            tools_registered=0,
            overall_decision="none",
            errors=(),
        )

    monkeypatch.setattr(mcp_bridge, "run_mcp_bridge", _spy_run)
    monkeypatch.setattr(mcp_bridge, "set_mcp_bridge_result", lambda *a, **k: None)
    # lifecycle evidence dispatch 不是本测试关注点，置为 no-op，避免连真实 dispatcher。
    monkeypatch.setattr(
        main_mod, "_try_dispatch_mcp_bridge_lifecycle", lambda *a, **k: None
    )

    main_mod._init_mcp_bridge_if_enabled(session_id="s3-l2-opt-in")
    assert calls == [True], "opt-in 时 gate 应放行并调用 run_mcp_bridge"
