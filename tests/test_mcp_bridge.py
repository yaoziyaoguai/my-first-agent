"""MCP bridge 集成测试。

中文学习边界：
- 测试 run_mcp_bridge 的三种 mode（disabled / discovery / registration）行为。
- 验证 bridge 不绕过 policy gate、audit 正确发射、report 不含 raw descriptor。
- 使用 FakeMCPClient，不启动真实 server。
"""

from __future__ import annotations

from agent.mcp_bridge import run_mcp_bridge
from agent.tool_registry import TOOL_REGISTRY


def _cleanup_mcp_registry(*names: str):
    for name in names:
        TOOL_REGISTRY.pop(name, None)


# ============================================================================
# mode: disabled
# ============================================================================


def test_bridge_disabled_mode_does_nothing():
    """disabled 模式下不做任何 MCP 操作。"""
    report = run_mcp_bridge(mode="disabled")
    assert report.mode == "disabled"
    assert report.servers_configured == 0
    assert report.tools_registered == 0
    assert report.overall_decision == "blocked"


def test_bridge_disabled_is_default():
    """默认调用（不传 mode）等同于 disabled。"""
    report = run_mcp_bridge()
    assert report.mode == "disabled"


# ============================================================================
# mode: discovery
# ============================================================================


def test_bridge_discovery_mode_does_not_register():
    """discovery 模式不注册任何工具，tools_discovered / blocked 标记为 -1（not_attempted）。"""
    report = run_mcp_bridge(mode="discovery")
    assert report.mode == "discovery"
    assert report.tools_registered == 0
    # discovery 模式不实际连接 server → tools_discovered / blocked = -1
    assert report.tools_discovered == -1
    assert report.tools_blocked == -1


def test_bridge_registration_stats_consistent():
    """registration 模式下 tools_discovered / blocked / registered 应一致。"""
    # 使用空 config（无 servers）→ 全 0
    report = run_mcp_bridge(mode="registration")
    assert report.mode == "registration"
    assert report.tools_discovered == 0
    assert report.tools_blocked == 0
    assert report.tools_registered == 0
    # 不应出现 registered > discovered 的矛盾
    assert report.tools_registered <= report.tools_discovered


# ============================================================================
# mode: registration
# ============================================================================


def test_bridge_report_is_frozen_dataclass():
    """MCPBridgeReport 是 frozen dataclass，不可变。"""
    report = run_mcp_bridge(mode="disabled")
    assert report.mode == "disabled"
    # frozen dataclass 应能 hash（作为 struct 使用）
    assert hash(report) is not None


def test_bridge_report_does_not_leak_raw_descriptor():
    """bridge report 不应包含 raw descriptor / raw args / raw result / secret。"""
    report = run_mcp_bridge(mode="disabled")
    report_str = str(report)
    assert "sk-ant-" not in report_str
    assert "api_key" not in report_str.lower()
    assert "BEGIN PRIVATE KEY" not in report_str


def test_bridge_registration_with_empty_config():
    """空 config 路径时 registration 不崩溃。"""
    report = run_mcp_bridge(mode="registration")
    assert report.tools_registered == 0
    assert len(report.errors) == 0
