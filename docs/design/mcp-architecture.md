# MCP System Architecture

**日期**: 2026-05-27
**状态**: L0 文档化 — 架构 seam 已建立，真实连接未验证
**对应 Loop**: Loop 10 (P2)

---

## 1. 概述

MCP (Model Context Protocol) 系统为 First Agent 提供外部工具集成能力。当前阶段只建立了完整的架构 seam（config → policy → sanitize → audit → register），不启动真实 server、不联网、不读取 `.env`。

### 设计原则

- **默认禁用**：所有 MCP server 默认 `enabled: false`，必须显式 opt-in
- **多层安全**：server policy → tool policy → sanitizer → adversarial scan 四层隔离
- **audit 全覆盖**：6 类审计事件覆盖 MCP 完整生命周期
- **不污染 core runtime**：MCP 系统不导入 core.py / loop.py / tool_executor.py / checkpoint.py

---

## 2. 模块架构

```
agent/mcp_models.py      — 纯数据模型（MCPServerConfig, MCPToolDescriptor, MCPClient protocol）
agent/mcp.py              — client seam（MCPCallResult, FakeMCPClient, register_mcp_tools）
agent/mcp_policy.py       — 安全策略 gate（server/tool 策略评估，4 层隔离模型）
agent/mcp_sanitizer.py    — 文本清洗（对抗性模式扫描，description 脱敏）
agent/mcp_audit.py        — 审计事件发射（6 类 MCP 生命周期事件）
agent/mcp_bridge.py       — 编排适配器（config → discovery → registration 的 thin adapter）
agent/mcp_stdio.py        — stdio transport（最小 JSON-RPC stdio 实现，仅用于本地验证）
```

### 依赖方向

```
mcp_models         ← 零依赖（纯 dataclass + protocol）
    ↑
mcp_sanitizer      ← 只依赖标准库
    ↑
mcp_policy         ← 依赖 mcp_models, mcp_sanitizer, tool_registry（只读 TOOL_REGISTRY）
    ↑
mcp_audit          ← 依赖 runtime_observer（日志写入）
    ↑
mcp_stdio          ← 依赖 mcp_models, mcp.py(MCPCallResult)
    ↑
mcp.py             ← 依赖 mcp_models, mcp_policy（懒导入）, mcp_audit（懒导入）, tool_registry
    ↑
mcp_bridge         ← 依赖 mcp.py, mcp_models, mcp_policy, mcp_stdio
```

**关键边界**：MCP 系统不导入 `agent/core.py`、`agent/loop.py`、`agent/tool_executor.py`、`agent/checkpoint.py`。

---

## 3. 四层安全隔离

来自 `agent/mcp_policy.py`，MCP tool descriptor 进入系统前经过四层隔离：

| 层 | 名称 | 内容 |
|----|------|------|
| 第 1 层 | raw descriptor | MCP server 返回的原始 MCPToolDescriptor |
| 第 2 层 | internal spec | 经过 policy 校验和 risk 赋值后的内部 ToolSpec |
| 第 3 层 | model-visible projection | 脱敏后的 Anthropic tool schema（截断 + [MCP:server] 前缀） |
| 第 4 层 | audit-safe summary | 审计和 health check 可用的短摘要 |

### 安全威胁模型

- **Implicit Tool Poisoning (MCP-ITP)**：攻击者在 tool description 中嵌入对抗性指令
- **Tool Shadowing**：恶意 server 注册与内置工具同名的 tool
- **Rug Pull**：server 先提供合法 schema，运行时改变 schema

### 防御层次

1. server/tool allowlist（mcp_policy.py）
2. 对抗性模式扫描（mcp_sanitizer.py）
3. description 脱敏 + [MCP:server] 来源标记
4. destructive tool 名称匹配拒绝
5. 所有 MCP tool 默认 confirmation="always"、risk_level="high"
6. 结构化审计（mcp_audit.py）

---

## 4. Bridge 编排

`agent/mcp_bridge.py` 的 `run_mcp_bridge()` 是 MCP 从 config → discovery → registration 的唯一受控入口。

### 三种模式

| 模式 | 行为 |
|------|------|
| `disabled` | 不做任何 MCP 操作（默认） |
| `discovery` | 只做 server policy readiness 评估，不连接 server、不 list_tools、不注册 |
| `registration` | 完整链路：config → server policy → list_tools → tool policy → registration + audit |

### Bridge 不负责

- policy 评估 → mcp_policy
- descriptor 清洗 → mcp_sanitizer
- 审计事件 → mcp_audit
- 工具注册 → mcp.py register_mcp_tools
- bridge 只做编排，不承载具体逻辑

---

## 5. Transport 层

### FakeMCPClient（`agent/mcp.py`）

测试用 in-memory client，不启动进程、不联网。通过 `tools_by_server` / `results_by_call` dict 配置 scripted 行为。

### StdioMCPClient（`agent/mcp_stdio.py`）

最小 stdio JSON-RPC transport，用于本地 fixture 验证：
- `shell=False`，command/args 来自显式 config
- `env` 只使用 config 中的显式 mapping，不继承真实环境变量
- 每次请求启动短生命周期子进程
- 不参与 runtime/checkpoint/TUI

---

## 6. 审计覆盖

6 类 MCP 审计事件（`agent/mcp_audit.py`）：

| 事件 | 触发时机 |
|------|---------|
| `mcp_server_discovered` | server 被发现且通过策略检查 |
| `mcp_server_blocked` | server 被策略拒绝 |
| `mcp_tools_listed` | server 的工具列表已获取 |
| `mcp_tool_registered` | tool 通过策略检查并注册 |
| `mcp_tool_blocked` | tool 被策略拒绝（含原因） |
| `mcp_tool_call` | tool 被实际调用（通过 tool_executor 审计通道） |

所有事件通过 `runtime_observer.log_event()` 写入 `agent_log.jsonl`，不创建新存储。

---

## 7. 已知限制

| 限制 | 影响 | 路线 |
|------|------|------|
| 无真实 MCP server 连接验证 | 所有 MCP 测试使用 FakeMCPClient，真实 stdio/HTTP/SSE 连接未经端到端验证 | 需要真实 MCP server fixture 环境 |
| dry_run 模式硬编码 | `_create_mcp_client(dry_run=True)` 始终使用 FakeMCPClient | dry_run=False 需用户显式配置 |
| MCP tool 调用未经真实 LLM 验证 | tool selection 行为在 fake 和 real 下可能不同 | 需真实 API dogfood |
| stdio 进程管理不处理长期运行 | 每次请求启动短生命周期进程 | 后续需支持 persistent server session |
| HTTP/SSE transport 未实现 | 只实现了 stdio transport | 后续按需添加 |

---

## 8. 未来迁移路线

1. **真实 stdio 连接验证**：搭建本地 MCP server fixture（如 filesystem server），端到端验证 config → discovery → tool call 完整链路
2. **HTTP/SSE transport**：实现 MCPClient protocol 的 HTTP/SSE transport
3. **persistent server session**：支持长期运行的 MCP server 进程
4. **tool_allowlist 细化**：从 destructive 全拒绝 → 逐 tool allowlist
5. **语义安全评估**：超越 regex 的对抗性内容检测

---

## 9. 参考

- MCP 协议规范：https://modelcontextprotocol.io/
- MCP-ITP 安全背景：arXiv:2601.07395
- 项目能力边界：`docs/CAPABILITY_BOUNDARIES.md`
- SubAgent 边界架构：`docs/design/subagent-boundary-architecture.md`
- Skill 系统架构：`docs/design/skill-system-architecture.md`
