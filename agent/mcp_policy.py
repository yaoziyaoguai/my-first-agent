"""MCP 安全策略与 descriptor 隔离层。

中文学习边界：
- 本模块是 MCP 的安全策略 gate：在 MCP tool 进入本地 registry 之前，评估 server
  安全性、校验 tool descriptor 不包含有害内容、生成脱敏后的 model-visible projection。
- 它只做策略评估，不做 server 启动、tool 执行、http/stdio transport。
- 它不 import agent/core.py / agent/tool_executor.py / agent/checkpoint.py，
  保持对 Runtime 主循环的零依赖。
- MCP tool descriptor 来自不可信外部 server，必须经过以下四层隔离才能进入系统：

  第 1 层 — raw descriptor：MCP server 返回的原始 MCPToolDescriptor
  第 2 层 — internal spec：经过 policy 校验和 risk 赋值后的内部 ToolSpec
  第 3 层 — model-visible projection：脱敏后的 Anthropic tool schema（description 截断、
      adversarial 模式过滤、server 来源标记）
  第 4 层 — audit-safe summary：审计和 health check 可用的短摘要

安全背景：
- 隐式 Tool Poisoning (MCP-ITP, arXiv:2601.07395) 攻击成功率 84.2%，检测率仅 0.3%。
  攻击者注册一个看起来无害的工具，在描述中嵌入对抗性指令影响 agent 对**其他**工具
  的调用行为 —— 被污染的 tool 从未被调用，整个攻击活在 description 层。
- Tool Shadowing：恶意 server 注册与内置工具同名的 tool，拦截本应发给内置工具的调用。
- Rug Pull：server 先提供合法的 tool schema，runtime 改变 schema 引入恶意参数。
- 这些攻击的根本原因是 MCP 协议本身缺少对 server capability 的密码学证明。

本模块的策略：
- 所有 MCP tool description 被视为不可信外部输入
- 注册前必须经过 adversarial pattern 扫描
- description 截断到安全长度
- 所有 MCP tool 的 model-visible description 必须带 [MCP:server_name] 前缀
- 所有 MCP tool 默认 confirmation="always"、risk_level="high"
- server 必须显式 allowlisted
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence, Literal
import re

from agent.mcp_models import MCPServerConfig, MCPToolDescriptor
from agent.mcp_sanitizer import (
    scan_adversarial_patterns,
    sanitize_description,
)
from agent.tool_registry import TOOL_REGISTRY


# ============================================================================
# 安全常量（policy 层，非 sanitizer 层）
# ============================================================================

# MCP server name 最大长度
MAX_SERVER_NAME_CHARS = 64

# MCP tool name 最大长度
MAX_MCP_TOOL_NAME_CHARS = 128

# 默认允许的本地 transport（当前阶段只允许 stdio）
ALLOWED_TRANSPORTS_DEFAULT: frozenset[str] = frozenset({"stdio"})

# 默认为 destructive 的 MCP tool 命名模式 —— 在首次真实试飞阶段，
# 任何匹配这些模式的 MCP tool 都会被 blocked，即使通过了其他 policy 检查。
# 这是 defense-in-depth：sanitizer 检查描述文本，这里检查工具语义（名称）。
# 真实试飞阶段过后，可通过 tool_allowlist 逐工具放行。
DEFAULT_DESTRUCTIVE_TOOL_PATTERNS: frozenset[str] = frozenset({
    "write_file",
    "edit_file",
    "create_directory",
    "move_file",
    "delete_file",
    "remove_file",
    "rename",
    "execute_command",
    "run_shell",
    "run_command",
})


# ============================================================================
# 策略评估结果
# ============================================================================

MCPPolicyDecision = Literal["allowed", "blocked", "dry_run_only"]


@dataclass(frozen=True, slots=True)
class ServerPolicyResult:
    """单个 MCP server 的策略评估结果。"""

    server_name: str
    decision: MCPPolicyDecision
    reason: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolPolicyResult:
    """单个 MCP tool descriptor 的策略评估结果。"""

    server_name: str
    tool_name: str
    decision: MCPPolicyDecision
    reason: str = ""
    assigned_risk: str = "high"
    sanitized_description: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MCPPolicyReport:
    """一次 MCP policy 评估的完整报告。"""

    servers_evaluated: int
    tools_evaluated: int
    servers_blocked: int
    tools_blocked: int
    server_results: tuple[ServerPolicyResult, ...] = ()
    tool_results: tuple[ToolPolicyResult, ...] = ()
    overall_decision: MCPPolicyDecision = "blocked"


# ============================================================================
# Server 策略评估
# ============================================================================


def evaluate_server_policy(
    server: MCPServerConfig,
    *,
    server_allowlist: frozenset[str] | None = None,
    allowed_transports: frozenset[str] | None = None,
    dry_run: bool = True,
) -> ServerPolicyResult:
    """评估单个 MCP server 配置的安全性。

    参数:
        server: 要评估的 server 配置
        server_allowlist: 允许的 server name 集合；None 表示全部拒绝
        allowed_transports: 允许的 transport 类型；默认只允许 stdio
        dry_run: True 时，server 可以通过策略检查但标记为 dry_run_only
    """
    transports = (
        allowed_transports if allowed_transports is not None
        else ALLOWED_TRANSPORTS_DEFAULT
    )
    allowlist = server_allowlist or frozenset()

    # 1. server 必须在 allowlist 中
    if server.name not in allowlist:
        return ServerPolicyResult(
            server_name=server.name,
            decision="blocked",
            reason=(
                f"MCP server '{server.name}' 不在允许列表中。"
                "当前阶段所有外部 MCP server 默认禁用，必须显式 allowlist。"
            ),
        )

    # 2. transport 必须在允许集合中
    if server.transport not in transports:
        return ServerPolicyResult(
            server_name=server.name,
            decision="blocked",
            reason=(
                f"MCP server '{server.name}' transport '{server.transport}' "
                f"不在允许列表中。当前允许: {sorted(transports)}"
            ),
        )

    # 3. stdio transport 必须有 command
    if server.transport == "stdio" and not server.command:
        return ServerPolicyResult(
            server_name=server.name,
            decision="blocked",
            reason=(
                f"MCP server '{server.name}' 使用 stdio transport 但未提供 command。"
            ),
        )

    # 4. server name 安全检查
    if len(server.name) > MAX_SERVER_NAME_CHARS:
        return ServerPolicyResult(
            server_name=server.name,
            decision="blocked",
            reason=f"Server name 过长（>{MAX_SERVER_NAME_CHARS} 字符）",
        )

    if not re.match(r"^[A-Za-z0-9_-]+$", server.name):
        return ServerPolicyResult(
            server_name=server.name,
            decision="blocked",
            reason=(
                f"Server name '{server.name}' 包含非法字符。"
                "只允许字母、数字、下划线和连字符。"
            ),
        )

    warnings: list[str] = []
    if dry_run:
        warnings.append("dry_run 模式：server 可通过策略检查但不会执行真实工具调用")

    decision: MCPPolicyDecision = "dry_run_only" if dry_run else "allowed"
    return ServerPolicyResult(
        server_name=server.name,
        decision=decision,
        warnings=tuple(warnings),
    )


# ============================================================================
# Tool Descriptor 安全评估与脱敏
# ============================================================================
#
# descriptor 的文本清洗和对抗性扫描逻辑已提取到 agent/mcp_sanitizer.py。
# 本模块通过 scan_adversarial_patterns / sanitize_description 调用它们。
# 这保持了 policy decision 层（本模块）和文本清洗层（mcp_sanitizer）的分离。


def _detect_name_collision(server_name: str, tool_name: str) -> str | None:
    """检测 MCP tool 是否与内置工具命名冲突。

    返回 None 表示无冲突；返回冲突描述字符串表示检测到冲突。
    """
    # 用 mcp_registry_tool_name 生成的完整名检查
    from agent.mcp_models import mcp_registry_tool_name

    full_name = mcp_registry_tool_name(server_name, tool_name)
    if full_name in TOOL_REGISTRY:
        return f"MCP tool '{full_name}' 与已注册工具命名冲突"

    # 同时检查原始 tool_name 是否与内置工具同名（即使是不同 server）
    if tool_name in TOOL_REGISTRY:
        return (
            f"MCP tool '{tool_name}' (server={server_name}) 原始名称与内置工具冲突。"
            "MCP tool 不应使用与内置工具相同的原始名称，即使最终 registry name 不同。"
        )

    return None


def evaluate_tool_policy(
    server: MCPServerConfig,
    descriptor: MCPToolDescriptor,
    *,
    server_decision: MCPPolicyDecision = "dry_run_only",
) -> ToolPolicyResult:
    """评估单个 MCP tool descriptor 的安全性并生成脱敏后的描述。

    对 descriptor 执行：
    1. 对抗性指令扫描
    2. 描述脱敏（截断 + 来源标记）
    3. 名称冲突检测
    4. 风险等级赋值
    5. tool name 长度检查

    返回 ToolPolicyResult 包含决策和脱敏后的描述。
    """
    warnings: list[str] = []
    reasons: list[str] = []

    # 1. tool name 安全检查
    if not descriptor.name or not descriptor.name.strip():
        return ToolPolicyResult(
            server_name=server.name,
            tool_name=descriptor.name,
            decision="blocked",
            reason="MCP tool name 为空",
            assigned_risk="high",
        )

    if len(descriptor.name) > MAX_MCP_TOOL_NAME_CHARS:
        return ToolPolicyResult(
            server_name=server.name,
            tool_name=descriptor.name,
            decision="blocked",
            reason=f"MCP tool name 过长（>{MAX_MCP_TOOL_NAME_CHARS} 字符）",
            assigned_risk="high",
        )

    # 1.5. destructive tool 名称检测 ——
    # 在首次真实试飞阶段，写操作类 MCP tool 默认 blocked。
    # 这是 defense-in-depth：sanitizer 检查描述，这里检查工具语义。
    if descriptor.name in DEFAULT_DESTRUCTIVE_TOOL_PATTERNS:
        return ToolPolicyResult(
            server_name=server.name,
            tool_name=descriptor.name,
            decision="blocked",
            reason=(
                f"MCP tool '{descriptor.name}' 匹配 destructive 命名模式，"
                "当前试飞阶段默认 blocked。如需启用，请显式加入 tool_allowlist。"
            ),
            assigned_risk="high",
        )

    # 2. 名称冲突检测
    collision = _detect_name_collision(server.name, descriptor.name)
    if collision:
        return ToolPolicyResult(
            server_name=server.name,
            tool_name=descriptor.name,
            decision="blocked",
            reason=collision,
            assigned_risk="high",
        )

    # 3. 对抗性指令扫描（委托给 mcp_sanitizer）
    adversarial_hits = scan_adversarial_patterns(descriptor.description)
    if adversarial_hits:
        reasons.append(
            f"tool description 包含可疑对抗性指令: {'; '.join(adversarial_hits)}"
        )

    # 4. 描述脱敏（委托给 mcp_sanitizer）
    sanitized_desc = sanitize_description(
        descriptor.description, server_name=server.name
    )

    # 5. server 级别决策传递
    if server_decision == "blocked":
        return ToolPolicyResult(
            server_name=server.name,
            tool_name=descriptor.name,
            decision="blocked",
            reason=f"server '{server.name}' 策略拒绝",
            assigned_risk="high",
            sanitized_description=sanitized_desc,
            warnings=tuple(warnings),
        )

    # 6. 对抗性内容 → 标记为 blocked
    if adversarial_hits:
        return ToolPolicyResult(
            server_name=server.name,
            tool_name=descriptor.name,
            decision="blocked",
            reason="; ".join(reasons),
            assigned_risk="high",
            sanitized_description=sanitized_desc,
            warnings=tuple(warnings),
        )

    # 7. 风险等级赋值 —— 所有 MCP tool 默认 high，server 可以提供 metadata 但不作为唯一依据
    # 当前阶段基于 MCP 协议缺少 capability attestation 的事实，所有外部工具默认 high risk
    assigned_risk = "high"

    # 8. dry_run 模式
    tool_decision: MCPPolicyDecision = (
        "dry_run_only" if server_decision == "dry_run_only" else "allowed"
    )

    return ToolPolicyResult(
        server_name=server.name,
        tool_name=descriptor.name,
        decision=tool_decision,
        assigned_risk=assigned_risk,
        sanitized_description=sanitized_desc,
        warnings=tuple(warnings),
    )


# ============================================================================
# 批量评估
# ============================================================================


def evaluate_mcp_policy(
    servers: Sequence[MCPServerConfig],
    descriptors_by_server: Mapping[str, Sequence[MCPToolDescriptor]],
    *,
    server_allowlist: frozenset[str] | None = None,
    dry_run: bool = True,
) -> MCPPolicyReport:
    """对一组 MCP servers 和 tools 做完整的策略评估。

    保持只读：不修改 registry、不启动 server、不注册工具。
    调用方根据返回的 MCPPolicyReport 决定是否进一步注册。
    """
    all_server_results: list[ServerPolicyResult] = []
    all_tool_results: list[ToolPolicyResult] = []

    # 先评估每个 server
    server_decisions: dict[str, MCPPolicyDecision] = {}
    for server in servers:
        result = evaluate_server_policy(
            server,
            server_allowlist=server_allowlist,
            dry_run=dry_run,
        )
        all_server_results.append(result)
        server_decisions[server.name] = result.decision

    # 再评估每个 tool
    for server in servers:
        descriptors = descriptors_by_server.get(server.name, ())
        for descriptor in descriptors:
            tool_result = evaluate_tool_policy(
                server,
                descriptor,
                server_decision=server_decisions.get(server.name, "blocked"),
            )
            all_tool_results.append(tool_result)

    servers_blocked = sum(1 for r in all_server_results if r.decision == "blocked")
    tools_blocked = sum(1 for r in all_tool_results if r.decision == "blocked")

    overall: MCPPolicyDecision = "blocked"
    if all(r.decision != "blocked" for r in all_server_results):
        if all(r.decision == "allowed" for r in all_tool_results):
            overall = "allowed"
        elif any(r.decision in ("allowed", "dry_run_only") for r in all_tool_results):
            overall = "dry_run_only"

    return MCPPolicyReport(
        servers_evaluated=len(servers),
        tools_evaluated=len(all_tool_results),
        servers_blocked=servers_blocked,
        tools_blocked=tools_blocked,
        server_results=tuple(all_server_results),
        tool_results=tuple(all_tool_results),
        overall_decision=overall,
    )
