# Loop 3.3 — Real MCP External Flight Contract (SDD)

**日期**: 2026-05-28
**状态**: architecture decision complete / implementation pending
**依赖**: Loop 2.4 (MCP Main-Path Readiness — code path complete)
**当前事实源**: `docs/PROJECT_STATUS.md`, `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
**历史背景**: 2026-05-28 redteam addendum 曾把 real external MCP flight 列为缺口；该旧审计不再作为当前架构 source of truth。

---

## 1. 问题定义

Loop 2.4 让 MCP bridge lifecycle 通过 disposable dispatcher 产生 evidence, 并将 `mcp.discover`/`mcp.invoke` branch points 从 DEFERRED 推到 PARTIAL。但 MCP 仍然：

1. **未连接真实外部 MCP server** — `run_mcp_bridge()` 默认 `dry_run=True`, 始终使用 FakeMCPClient
2. **Bridge 是 standalone startup 操作** — 在 `main.py` 中一次性运行, 不在 `core.chat()` main runtime path 中
3. **真实 StdioMCPClient 路径从未在 main runtime 中验证** — 只有直接单元测试
4. **无 sandbox** — 没有对真实 MCP server 进程的资源隔离
5. **opt-in 机制不完整** — `MY_FIRST_AGENT_MCP_DRY_RUN=0` 可以关闭 dry_run, 但从未在 main runtime 中验证

本 Loop 目标：让 MCP 从 "bridge lifecycle evidence / readiness" 推进到 opt-in real external MCP flight through main runtime, 复用统一 Tool pipeline, 不引入第二条 runtime flow。

---

## 2. Real MCP External Flight 定义

**Real MCP External Flight** = 通过 main runtime path (`core.chat()`) 完成以下闭环：

```
session startup (main.py)
  → opt-in check (MY_FIRST_AGENT_MCP_ENABLE=1 + MY_FIRST_AGENT_MCP_DRY_RUN=0)
  → run_mcp_bridge(mode="registration", dry_run=False)
  → StdioMCPClient 连接真实外部 MCP server
  → server policy gate → tool discovery → tool policy gate
  → register_mcp_tools() → TOOL_REGISTRY (MCP_BRIDGE_LIFECYCLE evidence)
  → 用户输入进入 core.chat()
  → model 通过 get_model_visible_tools(max_mcp_tools=5) 看到 MCP tools
  → model tool_use (mcp__<server>__<tool>)
  → handle_tool_use_response → ToolRuntimeMediator.mediate()
  → TOOL_GATE → TOOL_INVOKE → execute_single_tool
  → _call_mcp_tool closure → StdioMCPClient.call_tool()
  → 真实外部 MCP server 执行 → result
  → TOOL_RESULT → append_tool_result → model context
```

**不是** real external flight 的情况：
- `dry_run=True` + FakeMCPClient
- 直接 `register_mcp_tools()` 调用（不经过 bridge）
- 直接 `StdioMCPClient.call_tool()` 调用（不经过 Tool pipeline）
- no-crash 但 tool 未实际执行
- bridge lifecycle evidence 但 tools_registered=0

---

## 3. Opt-In Activation 机制

### 3.1 环境变量契约

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `MY_FIRST_AGENT_MCP_ENABLE` | (unset) | `1`/`true`/`yes` 才启用 MCP bridge |
| `MY_FIRST_AGENT_MCP_DRY_RUN` | `1` | `0`/`false`/`no` 才使用真实 StdioMCPClient |
| `MY_FIRST_AGENT_MCP_MODE` | `registration` | bridge 模式：disabled/discovery/registration |
| `MY_FIRST_AGENT_MCP_CONFIG` | (unset) | MCP server 配置 JSON 文件路径 |

### 3.2 安全默认

- 未设置 `MY_FIRST_AGENT_MCP_ENABLE` → MCP bridge 不运行 → 零 MCP tools 注册 → 零外部连接
- 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` 但 `MY_FIRST_AGENT_MCP_DRY_RUN` 默认 `1` → FakeMCPClient → 零外部连接
- 只有同时设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` 才会连接真实外部 MCP server
- `MY_FIRST_AGENT_MCP_DRY_RUN=0` 是显式 opt-in, 不接受默认值

### 3.3 不读取的文件

- `.env` — 不作为 MCP config 来源
- `config/config.yaml` — 不作为 MCP config 来源
- `~/.claude.json` / `~/.claude/` — 不作为 MCP config 来源
- MCP config 只能通过 `MY_FIRST_AGENT_MCP_CONFIG` 环境变量指定的 JSON 文件加载

---

## 4. Sandbox / Allowlist / Read-Only Tool 边界

### 4.1 Server Allowlist

- `server_allowlist` 必须显式指定, 不接受空集合
- 未在 allowlist 中的 server → `evaluate_server_policy()` 返回 `blocked`
- allowlist 通过 `MY_FIRST_AGENT_MCP_SERVER_ALLOWLIST` 环境变量传入（逗号分隔的 server name 列表）

### 4.2 Transport 限制

- 当前阶段**只允许 stdio transport**
- HTTP/SSE transport 被 `evaluate_server_policy()` 拒绝
- 未来如需 SSE, 需要新的 architecture decision

### 4.3 Destructive Tool 拒绝

`DEFAULT_DESTRUCTIVE_TOOL_PATTERNS` (mcp_policy.py) 中定义的工具名模式默认 blocked：
- `write_file`, `edit_file`, `create_directory`, `move_file`, `delete_file`, `remove_file`, `rename`, `execute_command`, `run_shell`, `run_command`

这些工具即使在 allowlist 中也会被 `evaluate_tool_policy()` block。

### 4.4 进程隔离

- StdioMCPClient 通过 subprocess 启动外部 MCP server
- `timeout_seconds=10` 防止 server 挂起
- server 进程在 client 生命周期内管理, bridge 退出后不保留
- **不实现**容器/VM 级别 sandbox（超出当前阶段范围）

### 4.5 Confirmation

- 所有 MCP tools 注册时 `confirmation="always"` + `risk_level="high"`
- 每次 MCP tool 调用需要用户显式确认（y/n）
- 确认发生在 TOOL_GATE 阶段（`needs_tool_confirmation()` 返回 True → `gate_disposition="confirmation_required"`）

---

## 5. MCP Server Config 来源

### 5.1 Config 文件格式

JSON 文件, 由 `MY_FIRST_AGENT_MCP_CONFIG` 环境变量指定路径：

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/mcp-test"],
      "enabled": true
    }
  }
}
```

### 5.2 安全约束

- 不读取 home 目录下的 config
- 不读取 `.env` 中的 MCP 配置
- `_reject_sensitive_config_path()` 拒绝 `.env` / `agent_log.jsonl` / `sessions` / `runs` 路径
- config 文件中不包含 API key / secret

---

## 6. 复用统一 Tool Pipeline

### 6.1 当前已验证路径（Loop 2.4）

MCP tool invocation 已复用统一 Tool pipeline：

```
model tool_use (mcp__<server>__<tool>)
  → response_handlers.handle_tool_use_response()
  → ToolRuntimeMediator.mediate(block)
  → _route_gate() → TOOL_GATE → ToolGateHandler.handle()
  → gate_disposition="allowed"/"rejected"/"confirmation_required"
  → _route_invoke() → TOOL_INVOKE
  → execute_single_tool(block, ...)
  → _call_mcp_tool closure → client.call_tool(server, tool_name, tool_input)
  → _route_result() → TOOL_RESULT
```

### 6.2 Loop 3.3 新增内容

唯一的区别是 `_call_mcp_tool` closure 中的 `client` 是 `StdioMCPClient`（而非 `FakeMCPClient`）。Tool pipeline 本身不变。这意味着：

- **不需要新增 RuntimeActionType** — TOOL_GATE / TOOL_INVOKE / TOOL_RESULT 已足够
- **不需要新增 handler** — ToolGateHandler / ToolInvokeHandler / ToolResultFeedbackHandler 已注册
- **不需要修改 ToolRuntimeMediator** — `mediate()` 不关心 tool 是 MCP 还是内置
- **不需要修改 execute_single_tool** — 它只调用已注册的 tool function（closure 内包含 MCP client）

### 6.3 不创建第二条路径

以下路径严格禁止，因为它们会绕过 Tool pipeline：

```
# 禁止：直接 bridge → call_tool（绕过 TOOL_GATE/INVOKE/RESULT）
client.call_tool(server, tool_name, tool_input)

# 禁止：直接 register_mcp_tools() 不通过 bridge（绕过 policy gate + audit）
register_mcp_tools(servers, client)

# 禁止：core.chat() 中直接调 MCP bridge（会在每 turn 重新注册）
```

---

## 7. Dispatcher / RuntimeDecisionFrame Evidence

### 7.1 Bridge Lifecycle Evidence

现有 `MCP_BRIDGE_LIFECYCLE` RuntimeActionType 已覆盖。Loop 3.3 需确保：
- `dry_run=False` 时 `tools_registered > 0` → handler 返回 `context.success`
- `dry_run=True` 时 `tools_registered` 可为 0（FakeMCPClient 无真实 tools）
- evidence 中包含 `dry_run` 字段, 可区分真实 vs fake

### 7.2 RuntimeDecisionFrame

`mcp.discover` 和 `mcp.invoke` branch points 在 Loop 2.4 中已从 DEFERRED→PARTIAL。Loop 3.3 不改变其 status（仍为 PARTIAL, 因为 real MCP server 连接是 opt-in, 不是默认路径）。

`build_decision_frame_from_chat_params()` 中 `mcp_available` 字段：
- Loop 2.4: 始终 `mcp_available=False`
- Loop 3.3 implementation: 应检查 `MY_FIRST_AGENT_MCP_ENABLE` + TOOL_REGISTRY 中是否有 `capability="mcp_tool"` 的条目
- 如果 bridge 已注册 MCP tools, `mcp_available=True`

### 7.3 不新增 Branch Point

MCP discovery/registration 不需要新的 RuntimeDecisionFrame branch point——现有 `mcp.discover` / `mcp.invoke` 已覆盖。`MCP_BRIDGE_LIFECYCLE` evidence 类型已在 schema 中定义。

---

## 8. Code Path Complete 判定标准

Loop 3.3 code path complete 需满足：

1. `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` 时 StdioMCPClient 连接真实 MCP server
2. server policy gate + tool policy gate 对真实 server 生效
3. 真实 MCP tools 注册到 TOOL_REGISTRY（`capability="mcp_tool"`）
4. 模型可见 MCP tools（通过 `get_model_visible_tools(max_mcp_tools=5)`）
5. 模型调用 MCP tool → ToolRuntimeMediator → TOOL_GATE/INVOKE/RESULT 完整 pipeline
6. real MCP tool 结果进入 model context（`append_tool_result` → `_project_to_api`）
7. MCP_BRIDGE_LIFECYCLE dispatcher evidence 包含 `dry_run=False` + `tools_registered > 0`
8. MCP tool invocation 的 TOOL_GATE/INVOKE/RESULT evidence 有 `real_core_loop_runtime_e2e` provenance

**不要求**：
- 默认路径下 MCP 激活（必须 opt-in）
- 多 server 同时连接
- HTTP/SSE transport
- 生产级 sandbox（容器/VM）

---

## 9. Real Evidence Debt

Loop 3.3 implementation 完成后必须登记：

### REAL-EVIDENCE-007: Real MCP Server Connection Verification

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.3 |
| **Capability** | Real MCP External Flight — 真实外部 MCP server 通过 main runtime path 的完整闭环 |
| **Missing evidence** | 真实外部 MCP server (如 filesystem server) 的 main runtime path E2E 验证 |
| **Required validation** | (1) 搭建本地 MCP server fixture；(2) 设置 MY_FIRST_AGENT_MCP_ENABLE=1 + DRY_RUN=0；(3) 启动真实 chat loop；(4) 验证 StdioMCPClient 真实连接并注册 tools；(5) 模型调用 MCP tool → ToolRuntimeMediator → 真实 server 执行；(6) 验证 dispatcher evidence chain 完整；(7) 验证 MCP tool result 进入模型上下文 |
| **Current evidence** | (待 implementation 完成后填写) |
| **Status** | pending real MCP server connection |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

## 10. 只能标 PARTIAL

Loop 3.3 implementation 完成后：

- MCP 整体仍是 **PARTIAL**
- `mcp.discover` / `mcp.invoke` branch points 保持 **PARTIAL**
- 原因：
  - 真实外部 MCP server 连接是 opt-in, 不是默认路径
  - 需要真实 MCP server fixture 验证 → REAL-EVIDENCE-007
  - sandbox 是进程级 timeout, 不是容器/VM 级隔离
  - HTTP/SSE transport 未实现
- 不标 READY, 不标 COMPLETED

---

## 11. TDD / Test Intent

### 11.1 安全契约测试

| # | 测试意图 | 验证方式 |
|---|---------|---------|
| T1 | 未设置 MY_FIRST_AGENT_MCP_ENABLE → bridge 不运行 | `_init_mcp_bridge_if_enabled()` 返回 early |
| T2 | MY_FIRST_AGENT_MCP_DRY_RUN=1 (默认) → FakeMCPClient | `_create_mcp_client(dry_run=True)` 返回 FakeMCPClient |
| T3 | MY_FIRST_AGENT_MCP_DRY_RUN=0 → StdioMCPClient | `_create_mcp_client(dry_run=False)` 返回 StdioMCPClient |
| T4 | server 不在 allowlist → blocked | `evaluate_server_policy()` 返回 blocked |
| T5 | destructive tool name → blocked | `evaluate_tool_policy()` 返回 blocked |
| T6 | HTTP transport → blocked | `evaluate_server_policy()` 返回 blocked |

### 11.2 Main Runtime Path 测试

| # | 测试意图 | 验证方式 |
|---|---------|---------|
| T7 | 真实 MCP tool 注册到 TOOL_REGISTRY | `register_mcp_tools(servers, StdioMCPClient(...))` → TOOL_REGISTRY 中有 `mcp__*` entry |
| T8 | MCP tool capability="mcp_tool" | 注册后 `TOOL_REGISTRY[name]["capability"] == "mcp_tool"` |
| T9 | MCP tool 对模型可见 | `get_model_visible_tools(max_mcp_tools=5)` 包含 mcp__* tools |
| T10 | MCP tool 走 ToolRuntimeMediator pipeline | core.chat() with FakeProvider + 已注册 MCP tool → TOOL_GATE→TOOL_INVOKE→TOOL_RESULT evidence |
| T11 | MCP_BRIDGE_LIFECYCLE evidence 含 dry_run 和 registered count | dispatcher evidence payload |
| T12 | mcp_available 在 decision frame 中正确反映 | `build_decision_frame_from_chat_params()` 中 mcp_available=True 当 MCP tools 已注册 |

### 11.3 Not-Fakeable 防护测试

| # | 测试意图 | 验证方式 |
|---|---------|---------|
| T13 | 不是只 print 了事 | 有 dispatcher evidence（MCP_BRIDGE_LIFECYCLE + TOOL_GATE/INVOKE/RESULT） |
| T14 | dry_run=True 不等于完成 | tools_registered 为 0 时 MCPBridgeLifecycleHandler 返回 failed |
| T15 | no-crash 不等于 PASS | MCP tool result 进入 model context（非空、非 error） |
| T16 | 不是 direct call | MCP tool invocation 必须通过 ToolRuntimeMediator.mediate()（检查 TOOL_GATE evidence） |
| T17 | 不是 standalone bridge | MCP tool 必须在 core.chat() 路径中被调用 |

---

## 12. 推荐 Implementation Slice

如果 SDD 批准, implementation 分为两个 phase：

### Phase A: 本地 Fixture 验证（安全, 可 auto-run）

1. 创建 `tests/fixtures/mcp_config.json` — 本地 MCP server fixture 配置
2. 创建或复用本地 MCP server fixture（如 filesystem server 或 echo server）
3. 实现 T1-T6（安全契约）+ T7-T12（main runtime path）+ T13-T17（not-fakeable）
4. 所有测试使用本地 fixture, 不连接外部服务
5. 更新 PROJECT_STATUS / PROGRESS_LEDGER

### Phase B: 真实外部 MCP Server 验证（需用户 opt-in, 不可 auto-run）

1. 用户提供真实 MCP server config（不 commit）
2. 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0`
3. 启动真实 chat loop, 验证完整闭环
4. 登记 REAL-EVIDENCE-007
5. 更新 dogfood report

**本轮建议**: 只完成 SDD + Phase A 的 test intent 定义，不直接实现。Phase A implementation 在下一轮 `/auto-run` 中执行。

---

## 13. Out of Scope

- 真实外部 MCP server 连接（需 Phase B opt-in）
- HTTP/SSE transport 实现
- 多 server 并发连接
- 容器/VM 级 sandbox
- MCP server 动态发现（startup 一次性注册保持）
- MCP tool 结果的结构化迁移（保持现有 legacy string contract）
- MCP config UI/CLI 管理

---

## 14. 对现有代码的预期改动

### 不需要改动的文件

- `agent/tool_runtime_mediator.py` — 已支持 MCP tool 通过 mediate() 执行
- `agent/runtime_integration/tool_gate.py` — 已支持 TOOL_GATE
- `agent/runtime_integration/tool_invoke.py` — 已支持 TOOL_INVOKE
- `agent/runtime_integration/tool_result_feedback.py` — 已支持 TOOL_RESULT
- `agent/runtime_integration/schema.py` — 不需要新增 RuntimeActionType
- `agent/runtime_integration/phase1_hook.py` — handler 注册已完整
- `agent/tool_registry.py` — MCP tool 注册/可见性逻辑已完整
- `agent/mcp_policy.py` — server/tool policy gate 已完整
- `agent/mcp_sanitizer.py` — 对抗性扫描/脱敏已完整
- `agent/mcp_audit.py` — 审计事件已完整
- `agent/runtime_decision_frame.py` — mcp.discover/mcp.invoke branch points 已 PARTIAL

### 可能需要小改动的文件

- `main.py` — `_init_mcp_bridge_if_enabled()` 可能需要传递 `server_allowlist` 环境变量
- `agent/mcp_bridge.py` — `run_mcp_bridge()` 可能需要接受 `server_allowlist` 参数
- `agent/runtime_decision_frame.py` — `build_decision_frame_from_chat_params()` 中的 `mcp_available` 逻辑

### 需要新增的文件

- `docs/design/mcp-real-external-flight-contract.md` — 本文件（SDD）
- `tests/runtime_integration/test_mcp_real_external_flight.py` — contract tests（T1-T17）

---

## 15. 架构决策记录

| 决策 | 结论 | 理由 |
|------|------|------|
| MCP discovery 是否进入 core.chat()? | 否 — 保持 startup 一次性注册 | 避免每 turn 重复注册, 保持 bridge 作为 session-startup 操作 |
| 是否需要新 RuntimeActionType? | 否 | TOOL_GATE/INVOKE/RESULT 已足够表达 MCP tool invocation |
| 是否需要新 handler? | 否 | ToolGateHandler/ToolInvokeHandler/ToolResultFeedbackHandler 已覆盖 |
| 是否需要修改 ToolRuntimeMediator? | 否 | `mediate()` 不关心 tool 来源 |
| opt-in 是否通过 `config/config.yaml`? | 否 — 使用环境变量 | 避免 config.yaml 复杂化, 保持 MCP opt-in 显式 |
| sandbox 级别? | 进程级 timeout + subprocess | 容器/VM 级 sandbox 超出当前阶段 |
| HTTP/SSE transport? | 不在 Loop 3.3 scope | 需新的 architecture decision |
