"""S3-G03: MCP governed tool source 受控接入验收（AC-2 / S3_REFERENCE_TASK §3）。

证明 MCP 作为**受控 governed tool source**（非完整 MCP 生态）：

- (a) MCP 经 S3-G02 统一契约声明（`MCP_CAPABILITY`），default-off + 显式 opt-in；
- (b) fake/fixture MCP tool 经 governed policy gate 注册进**同一** TOOL_REGISTRY，
      带 governed 属性（capability="mcp_tool" / confirmation="always"），并产生
      registration-time mcp evidence；
- (c) default-off → 不暴露（契约 gate 无 opt-in 即拒绝）；
- (d) allowlist 外的 MCP server/tool 被拒 + 产生 blocked evidence；
- (e) fake-first：dry_run 路径用 FakeMCPClient，不构造 StdioMCPClient（无真实 endpoint）。

MCP 工具经 governed path 的**调用期** evidence（TOOL_GATE/INVOKE/RESULT 经 mediator）
已由 `tests/runtime_integration/test_mcp_real_external_flight.py::
TestMCPInvocationMainPath::test_mcp_tool_goes_through_gate_invoke_result` 证明；本文件
聚焦 S3 的 capability 声明 + 受控接入（registration/policy/default-off/allowlist/
fake-first）验收。不连真实 MCP endpoint（`AGENTS.md` 安全边界）。
"""
from __future__ import annotations

import pytest

from agent.extension_capability import evaluate_activation
from agent.mcp import FakeMCPClient, MCPCallResult, register_mcp_tools
from agent.mcp_models import (
    MCPServerConfig,
    MCPToolDescriptor,
    mcp_registry_tool_name,
)
from agent.tool_registry import TOOL_REGISTRY


def _make_fake_mcp_source(
    *, server_name: str, tool_name: str, description: str, result_content: str
):
    """构造一个 fake/fixture MCP tool source（FakeMCPClient，无真实 endpoint）。"""
    server = MCPServerConfig(
        name=server_name, transport="stdio", command="fake-cmd", enabled=True
    )
    descriptor = MCPToolDescriptor(
        server_name=server_name,
        name=tool_name,
        description=description,
        input_schema={},
    )
    call_result = MCPCallResult(content=result_content, is_error=False)
    client = FakeMCPClient(
        tools_by_server={server_name: [descriptor]},
        results_by_call={(server_name, tool_name): call_result},
    )
    return server, descriptor, client


@pytest.fixture
def capture_mcp_evidence(monkeypatch):
    """捕获 mcp_audit 经 record_evidence 写入的 MCP evidence。"""
    calls: list[dict] = []

    def _fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return kwargs

    # _mcp_evidence 调用的是 mcp_audit 命名空间内绑定的 record_evidence
    monkeypatch.setattr("agent.mcp_audit.record_evidence", _fake_record_evidence)
    return calls


# ---- (a) capability 声明 ----


def test_mcp_capability_declared_via_unified_contract():
    """MCP 经 S3-G02 统一契约声明，五要素齐全 + default-off。"""
    from agent.mcp_capability import MCP_CAPABILITY

    assert MCP_CAPABILITY.kind == "mcp"
    assert MCP_CAPABILITY.is_default_off() is True
    # 与 main.py 既有的 default-off env 同名（行为保持）
    assert MCP_CAPABILITY.enable_env == "MY_FIRST_AGENT_MCP_ENABLE"
    # risk / verification / evidence 均声明
    assert MCP_CAPABILITY.risk is not None and MCP_CAPABILITY.risk.level in (
        "low", "medium", "high"
    )
    assert MCP_CAPABILITY.verification is not None and MCP_CAPABILITY.verification.spec
    assert MCP_CAPABILITY.evidence is not None
    assert MCP_CAPABILITY.evidence.subsystem == "mcp"


# ---- (b) fake tool 经 governed policy gate 注册 + evidence ----


def test_fake_mcp_tool_registered_through_governed_path_with_evidence(capture_mcp_evidence):
    """allowlisted fake MCP tool 进入同一 TOOL_REGISTRY，带 governed 属性 + mcp evidence。"""
    server, descriptor, client = _make_fake_mcp_source(
        server_name="s3-g03-demo",
        tool_name="repo_doc_reader",
        description="Read fixture repo doc via governed MCP source.",
        result_content="fixture: gap FIXTURE-GAP-1 evidence satisfied",
    )
    registry_name = mcp_registry_tool_name(server.name, descriptor.name)

    registered = register_mcp_tools(
        [server], client, server_allowlist=frozenset({server.name}), dry_run=True
    )
    # 注册成功（进入同一 TOOL_REGISTRY）
    assert registry_name in registered
    assert registry_name in TOOL_REGISTRY
    entry = TOOL_REGISTRY[registry_name]
    # governed 属性：capability=mcp_tool / confirmation=always（与既有契约一致）
    assert entry["capability"] == "mcp_tool"
    assert entry["confirmation"] == "always"
    # registration-time mcp evidence 已记录
    mcp_events = [c for c in capture_mcp_evidence if c.get("subsystem") == "mcp"]
    assert mcp_events, "MCP 注册应产生 subsystem=mcp evidence"


# ---- (c) default-off → 不暴露 ----


def test_mcp_default_off_not_exposed():
    """default-off：契约 gate 无 opt-in → 不允许激活（bridge 不运行 → 不暴露 MCP 工具）。"""
    from agent.mcp_capability import MCP_CAPABILITY

    denied = evaluate_activation(MCP_CAPABILITY, env={})
    assert denied.allowed is False
    assert denied.state == "disabled"
    # opt-in 语义：显式启用值才允许（与 main.py 既有 gate 同语义）
    enabled = evaluate_activation(
        MCP_CAPABILITY, env={"MY_FIRST_AGENT_MCP_ENABLE": "1"}
    )
    assert enabled.allowed is True


# ---- (d) allowlist 外被拒 + blocked evidence ----


def test_out_of_allowlist_mcp_server_rejected_with_blocked_evidence(capture_mcp_evidence):
    """server 不在 allowlist → 工具不注册 + 产生 blocked evidence（deny-default）。"""
    server, descriptor, client = _make_fake_mcp_source(
        server_name="s3-g03-blocked",
        tool_name="leaky_tool",
        description="Should be rejected by allowlist.",
        result_content="must-not-register",
    )
    registry_name = mcp_registry_tool_name(server.name, descriptor.name)

    # allowlist 不含该 server（deny-default：空 allowlist = 全拒）
    registered = register_mcp_tools(
        [server], client, server_allowlist=frozenset({"other-server"}), dry_run=True
    )
    assert registry_name not in registered
    assert registry_name not in TOOL_REGISTRY
    # blocked evidence：allowlist 外的 server 产生 subsystem=mcp 且含 blocked 的证据
    blocked = []
    for c in capture_mcp_evidence:
        if c.get("subsystem") != "mcp":
            continue
        haystack = " ".join(
            str(c.get(k, "")) for k in ("status", "operation", "reason_code")
        ).lower()
        if "blocked" in haystack:
            blocked.append(c)
    assert blocked, "allowlist 外的 MCP server 应产生 blocked evidence"


# ---- (e) fake-first：无真实 endpoint ----


def test_no_real_endpoint_on_dry_run_path():
    """dry_run=True → FakeMCPClient；不构造 StdioMCPClient（无真实 endpoint 连接）。"""
    from agent.mcp_bridge import _create_mcp_client

    client = _create_mcp_client(dry_run=True)
    assert isinstance(client, FakeMCPClient)
