"""S3-G03: MCP governed tool source 的 capability 声明（经 S3-G02 统一契约）。

把 MCP 作为**受控 governed tool source**（非完整 MCP 生态）用统一 extension capability
契约声明，使 MCP 与 SubAgent / Skill 共享同一接入形状（metadata / enable-disable /
risk / verification / evidence）。

事实基线（graphify + 代码核验，2026-06-19）：

- MCP 工具经 `register_mcp_tools`（`agent/mcp.py:161`）注册进**同一** `TOOL_REGISTRY`，
  执行期走与内置工具相同的 `ToolRuntimeMediator` / `tool_executor` 路径（**非** harness-only，
  **不**绕过 dispatcher/mediator）。
- 两层 policy gate（`evaluate_server_policy` / `evaluate_tool_policy`，`agent/mcp_policy.py`）+
  registration-time evidence（`agent/mcp_audit.emit_mcp_*` → `record_evidence(subsystem="mcp")`）。
- default-off gate 原在 `main.py:_init_mcp_bridge_if_enabled` 手写 env 判定（opt-in 值
  `1/true/yes/on`）；本模块把该判定对齐到统一契约 `evaluate_activation(MCP_CAPABILITY)`，
  语义完全一致（行为保持），让 MCP 激活决策流经与 Skill/SubAgent 同一的契约评估器。
- allowlist deny-default（`mcp_policy.py`：空 allowlist = 全拒）。
- fake-first：`dry_run=True` → `FakeMCPClient`（`agent/mcp_bridge._create_mcp_client`），
  不构造 `StdioMCPClient`，**不连真实 MCP endpoint**（`AGENTS.md` 安全边界）。

S3 不做完整 MCP 生态（多 server 编排 / 动态发现生态化留 S4/Sn）。
"""
from __future__ import annotations

from agent.extension_capability import (
    ExtensionCapability,
    ExtensionEvidenceDescriptor,
    ExtensionRisk,
    ExtensionVerification,
)

MCP_CAPABILITY = ExtensionCapability(
    kind="mcp",
    id="mcp",
    name="MCP governed tool source",
    description=(
        "受控 MCP tool source：MCP 工具经 governed tool path（dispatcher/mediator + "
        "两层 policy gate + evidence）接入同一 TOOL_REGISTRY；default-off + server "
        "allowlist（deny-default）；fake-first / dry-run，不连真实 endpoint。"
    ),
    default_state="disabled",
    enable_env="MY_FIRST_AGENT_MCP_ENABLE",
    risk=ExtensionRisk(
        level="high",
        summary=(
            "MCP 引入外部工具来源（即便 fake/fixture 也是外部边界）；每次调用必须经 "
            "policy gate + evidence，且 default-off + allowlist 可禁用。"
        ),
        mitigations=(
            "default-off + 显式 opt-in",
            "server allowlist（deny-default）",
            "两层 policy gate（server + tool）",
            "registration-time evidence（subsystem=mcp）",
            "fake-first / dry_run（不连真实 endpoint）",
        ),
    ),
    verification=ExtensionVerification(
        spec=(
            "fake/fixture MCP tool 经 governed path 注册并产生 evidence；default-off "
            "时不暴露；allowlist 外的 server/tool 被拒；dry_run 路径不连真实 endpoint"
        ),
        acceptance_refs=(
            "S3-G03",
            "tests/test_s3_mcp_governed_tool_source.py",
            "S3_REFERENCE_TASK.md §3/§5",
        ),
    ),
    evidence=ExtensionEvidenceDescriptor(
        subsystem="mcp",
        shape=(
            "mcp_audit events（server_discovered / server_blocked / tools_listed / "
            "tool_registered / tool_blocked）+ 调用期 governed tool evidence（经 mediator）"
        ),
    ),
)
"""MCP 受控 tool source 的统一 capability 声明（AC-2 / AC-4）。"""
