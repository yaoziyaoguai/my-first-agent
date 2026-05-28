# Real Evidence / Dogfood / Real API Validation Debt

**创建日期**: 2026-05-28
**最后更新**: 2026-05-28 (Loop 3.3 SDD — REAL-EVIDENCE-007 登记)

---

## 为什么存在

当前项目很多子系统已经通过 L2（contract tests via `dispatcher.route()`）和 L3（contract
tests via `dispatcher.route_from_runtime_loop()`）验证，但缺少真实 CLI / real core loop
/ real API / real dogfood 的端到端验证。

## 为什么不阻塞当前 loop

当前阶段优先完成 unified runtime path 和 subsystem main-path integration。把真实验证需求
集中收敛到本文档，避免每个 loop 被手工 dogfood 打断节奏。

## 不能 overclaim

缺少真实 dogfood 验证的能力**不能**标为 READY 或 COMPLETED，只能标为 PARTIAL 或
"code path complete, real validation pending"。在 PROJECT_STATUS 中对应行必须明确引用
本文档 ID。

## 后续处理原则

- 所有审计文档（`docs/audits/`）、dogfood 报告（`docs/dogfood/`）中出现的真实 API
  测试、真实 dogfood、real E2E、外部服务验证，都统一登记到本文档
- 最后集中处理（一个专门的 validation convergence loop），而非零散逐个验证
- 新的 capability loop 完成后，如果缺真实 dogfood，登记到本文档而不是把它写成
  loop 本身的 blocker

---

## Debt Items

### REAL-EVIDENCE-001

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.1 / commit 480da7e |
| **Capability** | Explicit Memory Main-Path Completion |
| **Missing evidence** | real core loop dogfood E2E |
| **Required validation** | 启动真实 chat loop；输入 `/forget` 或"忘记"命令；验证 dispatcher-mediated MEMORY_FORGET path；验证 retain/recall/forget 使用共享 store；验证用户可见结果与 durable evidence 一致 |
| **Current evidence** | 5 L2 MemoryForget contract tests pass；5 L3 shared-store contract tests pass；65 focused tests pass |
| **Status** | pending real dogfood |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-002

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2 / commit 2d26c2a；Loop 2.2b / commit 98b4163 |
| **Capability** | Skill Activation — real model SKILL_SELECT tool call |
| **Missing evidence** | 真实模型（非 FakeProvider）在真实 chat loop 中是否触发 SKILL_SELECT tool call |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) 输入能触发 Skill selection 的用户请求；(3) 验证模型是否真实调用 SKILL_SELECT tool；(4) 验证 SkillRegistry / dispatcher / RuntimeDecisionFrame 有对应 evidence；(5) 验证 `_active_skill` 被设置并进入后续 runtime path（system prompt 包含 [Active Skill Instructions]） |
| **Current evidence** | registry bridge 已连接、prompt injection 已实现、13 L2 skill bridge tests pass + 6 L3 pipeline tests pass；allowed_tools enforcement code path 已完成（15 contract tests pass）；但**未运行真实模型 SKILL_SELECT** |
| **Status** | pending real API / real model validation |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-003

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2b / commit 98b4163 |
| **Capability** | Skill allowed_tools enforcement — real dogfood E2E |
| **Missing evidence** | 真实 core loop 中 skill allowed_tools 约束工具执行的端到端验证 |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) 触发一个带 allowed_tools 的 active Skill；(3) 让模型尝试调用允许工具，验证可正常执行；(4) 让模型尝试调用不允许工具，验证在执行前被 ToolGateHandler block（gate_disposition="rejected"）；(5) 验证 blocked tool 不进入 execute_single_tool（tool_execution_log status="blocked_by_policy"）；(6) 验证 dispatcher / RuntimeDecisionFrame / trace evidence 与用户可见结果一致；(7) 验证 skill 取消激活后工具恢复正常 |
| **Current evidence** | 15 skill tool enforcement contract tests pass（6 ToolGate + 6 Mediator + 3 NotFakeable）；ToolGateHandler 在生产路径中检查 skill_allowed_tools → rejected；ToolRuntimeMediator 传递 skill_allowed_tools；blocked 工具返回 FORCE_STOP 不进 execute_single_tool；但**未运行真实 API / real dogfood** |
| **Status** | pending real API / real dogfood validation |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-004

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.3 / Storage-Checkpoint True Resume |
| **Capability** | Checkpoint save/resume dispatcher-mediated evidence chain — real API/model roundtrip validation |
| **Missing evidence** | 真实 LLM provider 下跨保存/恢复的完整 dispatcher evidence chain 连续性验证 |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) 触发 checkpoint save（plan 生成、memory confirmation、或压缩同步）；(3) 验证 CHECKPOINT_SAVE dispatcher evidence 产生且 save_succeeded=True；(4) 模拟中断（Ctrl+C）并在下次启动时 resume；(5) 验证 CHECKPOINT_RESUME dispatcher evidence 产生且 restore_succeeded=True；(6) 验证 resume 后 conversation context、task state、pending action 一致继续；(7) 验证 save→resume dispatcher evidence chain 可追溯（action_log 中两种 action type 都存在）；(8) 验证 RuntimeDecisionFrame 正确反映 checkpoint 状态；(9) 验证不是 save/load file smoke 或 no-crash 冒充 true resume |
| **Current evidence** | 16 contract tests pass（4 save mediation + 5 resume mediation + 4 roundtrip + 2 not fakeable + 1 L3 hook-level）；core.py 3 处 direct save_checkpoint 已迁入 dispatcher-mediated CHECKPOINT_SAVE；session.py resume 路径通过 CHECKPOINT_RESUME handler 记录 evidence（dispatcher 按需构建）；CheckpointSaveHandler/CheckpointResumeHandler 在 phase1_hook.py 注册；RuntimeDecisionFrame checkpoint branch points 更新为 code path complete；但**未运行真实 API / real dogfood** |
| **Status** | pending real API / real dogfood roundtrip validation |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-005

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.4 / commit pending |
| **Capability** | MCP Bridge — real MCP server connection |
| **Missing evidence** | 真实 stdio MCP server 连接、真实 tool discovery、真实 tool execution 跨进程验证 |
| **Required validation** | (1) 搭建本地 MCP server fixture（如 filesystem server）；(2) 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` + MCP config 文件；(3) 启动真实 chat loop；(4) 验证 `run_mcp_bridge()` 真实连接 server 并注册 tools；(5) 验证 MCP tools 出现在 model-visible tools 中；(6) 验证模型可调用 MCP tool 并通过 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline 执行；(7) 验证 TOOL_INVOKE 调用了真实 StdioMCPClient（非 FakeMCPClient）；(8) 验证 dispatcher evidence chain 完整（bridge lifecycle + tool pipeline）|
| **Current evidence** | bridge lifecycle dispatcher evidence（MCP_BRIDGE_LIFECYCLE RuntimeActionType）；L3 core.chat() tests 验证 MCP tool pipeline（但使用 FakeMCPClient + confirmation='never'）；mcp.discover/mcp.invoke branch points 标 PARTIAL（code path complete, real server pending）|
| **Status** | pending real MCP server connection |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-006

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.2 SDD / architecture decision phase |
| **Capability** | SubAgent L1 — real provider child loop + parent-mediated tool execution + memory scope roundtrip |
| **Missing evidence** | 真实 LLM provider child loop 完整执行（含 tool + memory scope roundtrip） |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) 触发 SubAgent delegation（非 deterministic keyword-match）；(3) child loop 调真实 provider 并返回非 deterministic summary；(4) child tool_use 通过 parent ToolRuntimeMediator pipeline 执行；(5) child memory proposal (scope=propose) 通过 mediate_child_memory_request() → parent store；(6) 所有 child action 有 dispatcher evidence；(7) 不是 deterministic keyword-match summary 冒充真实 child execution |
| **Current evidence** | L1 code path complete: execute_l1() + delegate_l1() + mediate_child_tool_request() + mediate_child_memory_request()；child memory scope (none/propose) with namespaced store write；SUBAGENT_CHILD_MEMORY_REQUEST dispatcher evidence；CLI shortcuts 迁入 dispatcher path；Loop 3.2b TDD tests (24 pass, 11 new for memory scope) |
| **Status** | code path complete, real provider dogfood pending |
| **Blocking current code loop** | no |
| **Blocking READY claim** | yes |

---

### REAL-EVIDENCE-007

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.3 SDD / architecture decision phase |
| **Capability** | MCP Real External Flight — 真实 stdio MCP server 连接 + external tool execution + external tool policy |
| **Missing evidence** | 真实外部 MCP server 的完整连接→discovery→registration→tool_use→execution→result 路径 |
| **Required validation** | (1) 搭建本地 real MCP server fixture（如 filesystem 或 echo server）；(2) 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` + MCP config 文件含真实 server entry；(3) 启动 real chat loop；(4) 验证 `run_mcp_bridge(mode="registration", dry_run=False)` → StdioMCPClient 真实连接 → list_tools → 通过 policy gate → TOOL_REGISTRY 注册（FakeMCPClient 无真实 server 进程）；(5) 验证注册的 MCP tools 出现在 `get_model_visible_tools(max_mcp_tools=5)` 中；(6) 验证模型 tool_use MCP tool → TOOL_GATE（含 server_allowlist 校验）→ TOOL_INVOKE → StdioMCPClient.call_tool（非 FakeMCPClient）→ real server response → TOOL_RESULT → dispatcher evidence；(7) 验证 destructive tool name block（含 server_allowlist 边界）；(8) 验证 confirmation="always" 在 real core loop 中正确拦截（非 test hack `confirmation="never"`） |
| **Current evidence** | bridge lifecycle dispatcher evidence（MCP_BRIDGE_LIFECYCLE + disposable dispatcher）；L3 core.chat() tests 验证 MCP tool pipeline（但使用 FakeMCPClient + confirmation='never' test hack）；mcp.discover/mcp.invoke branch points 标 PARTIAL（code path complete, real server pending）；Loop 3.3 SDD 完成（`docs/design/mcp-real-external-flight-contract.md`）定义 opt-in contract + 17 test intents |
| **Status** | pending real MCP server connection + real external tool execution |
| **Blocking current code loop** | no — SDD/architecture decision 阶段不要求 real server |
| **Blocking READY claim** | yes |

---

## 登记模板

新 debt item 按以下格式追加：

```markdown
### REAL-EVIDENCE-NNN

| 字段 | 值 |
|------|-----|
| **Source** | Loop X.Y / commit <hash> |
| **Capability** | <capability name> |
| **Missing evidence** | <简要描述缺什么> |
| **Required validation** | <具体验证步骤> |
| **Current evidence** | <已有测试/dogfood/contract 证据> |
| **Status** | pending real dogfood / pending real API / pending external service |
| **Blocking current code loop** | yes / no |
| **Blocking READY claim** | yes / no |
```
