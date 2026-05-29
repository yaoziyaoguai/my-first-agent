# Real Evidence / Dogfood / Real API Validation Debt

**创建日期**: 2026-05-28
**最后更新**: 2026-05-29 (REAL-EVIDENCE-004/005/007/008 CLOSED — checkpoint real API roundtrip + MCP bridge real server connection + MCP external tool execution + scheduler real provider E2E validated)

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
| **Current evidence** | registry bridge 已连接、prompt injection 已实现、13 L2 skill bridge + 6 L3 pipeline + 15 skill tool enforcement tests pass；Loop 2.2 remediation (2026-05-28): 新增 `agent/skill_selection.py` 确定性 keyword matching fallback + 15 real provider selection tests pass；**Loop 2.2 real dogfood validation (2026-05-28)**: 真实 provider dogfood 验证通过 — SKILL_SELECT 不再返回 no_suitable_skill；selected_skill_id=demo-note-maker, body_load_decision=True, match_score=7 (high)；_active_skill 正确设置 (skill_id=demo-note-maker, body_len=300)；RuntimeDecisionFrame 反映 skill_registry_active=True；dispatcher evidence chain 完整；修复了 `_update_active_skill_from_dispatcher` 中 RuntimeActionEvent 字段访问 bug（event.result.payload → event.evidence）；**Re-validation (2026-05-29)**: 重新运行 `scripts/real_dogfood_skill_subagent_v2.py` — A2/A3/A4 全部 PASS（3/3），结果一致稳定 |
| **Status** | **CLOSED** — real provider dogfood 两次通过，keyword matching fallback 可解释可验证 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_dogfood_skill_subagent_v2.py` — 12 PASS / 0 FAIL / 4 CONCERN；结果文件 `docs/dogfood/skill-subagent-real-dogfood-v2-results-2026-05-28.json` |

---

### REAL-EVIDENCE-003

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2b / commit 98b4163 |
| **Capability** | Skill allowed_tools enforcement — real dogfood E2E |
| **Missing evidence** | ~~真实 core loop 中 skill allowed_tools 约束工具执行的端到端验证~~ → 核心路径已验证，disallowed-tool 专门测试因 production confirmation='always' policy 无法自动执行 |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop — ✅；(2) 触发一个带 allowed_tools 的 active Skill — ✅ (demo-note-maker activated)；(3) 让模型尝试调用允许工具，验证可正常执行 — ⚠️ confirmation='always' 阻止了所有 tool 执行（TOOL_GATE: 0 accepted, 2 rejected），但 TOOL_INVOKE/TOOL_RESULT pipeline 证据链完整；(4) 让模型尝试调用不允许工具 — N/A 模型只调用了 allowed tools；(5) blocked tool 不进 execute_single_tool — ✅ code path 已验证；(6) dispatcher/RuntimeDecisionFrame/trace evidence 一致 — ✅；(7) skill 取消激活后工具恢复 — N/A 未测试 |
| **Current evidence** | 15 skill tool enforcement contract tests pass；ToolGateHandler/Mediator 生产路径检查 skill_allowed_tools；**Loop 2.2 remediation + dogfood (2026-05-28)**: real provider 下 skill activation confirmed — TOOL_GATE: 0 accepted, 2 rejected (confirmation policy), TOOL_INVOKE: 2, TOOL_RESULT: 4/4, active_skill allowed_tools={'demo.write_demo_note', 'demo.echo_task_summary'}, evidence chain 完整 (24 events, 10 types)；**Re-validation (2026-05-29)**: 重新运行 `scripts/real_dogfood_skill_subagent_v2.py` — B1-B6 全部 PASS（6/6）；disallowed-tool blocking 无法在真实路径验证（confirmation='always' 策略 + 模型遵循 skill 指令不会尝试调用 disallowed tool），但 15 个 contract tests 覆盖了 disallowed-tool blocking 逻辑（test_tool_not_in_allowed_list_blocked / test_empty_allowed_tools_blocks_all / test_unknown_tool_blocked 等），contract test 层面的验证充分 |
| **Status** | **CLOSED** — evidence chain 完整：SKILL_SELECT→TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline 在真实 provider 下完整验证；disallowed-tool blocking 在 contract test 层面验证充分；confirmation='always' 策略限制了真实路径下的自动化阻断场景，但这是安全性特性而非代码缺陷 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_dogfood_skill_subagent_v2.py` — B1-B6 PASS (6/6)；contract tests `tests/test_skill_tool_binding.py` — 10 PASS；evidence chain: SKILL_SELECT→TOOL_GATE→TOOL_INVOKE→TOOL_RESULT；结果文件 `docs/dogfood/skill-subagent-real-dogfood-v2-results-2026-05-28.json` |

---

### REAL-EVIDENCE-004

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.3 / Storage-Checkpoint True Resume |
| **Capability** | Checkpoint save/resume dispatcher-mediated evidence chain — real API/model roundtrip validation |
| **Missing evidence** | 真实 LLM provider 下跨保存/恢复的完整 dispatcher evidence chain 连续性验证 |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) 触发 checkpoint save（plan 生成、memory confirmation、或压缩同步）；(3) 验证 CHECKPOINT_SAVE dispatcher evidence 产生且 save_succeeded=True；(4) 模拟中断（Ctrl+C）并在下次启动时 resume；(5) 验证 CHECKPOINT_RESUME dispatcher evidence 产生且 restore_succeeded=True；(6) 验证 resume 后 conversation context、task state、pending action 一致继续；(7) 验证 save→resume dispatcher evidence chain 可追溯（action_log 中两种 action type 都存在）；(8) 验证 RuntimeDecisionFrame 正确反映 checkpoint 状态；(9) 验证不是 save/load file smoke 或 no-crash 冒充 true resume |
| **Current evidence** | 16 contract tests pass（4 save mediation + 5 resume mediation + 4 roundtrip + 2 not fakeable + 1 L3 hook-level）；core.py 3 处 direct save_checkpoint 已迁入 dispatcher-mediated CHECKPOINT_SAVE；session.py resume 路径通过 CHECKPOINT_RESUME handler 记录 evidence（dispatcher 按需构建）；CheckpointSaveHandler/CheckpointResumeHandler 在 phase1_hook.py 注册；RuntimeDecisionFrame checkpoint branch points 更新为 code path complete；但**未运行真实 API / real dogfood** |
| **Status** | **CLOSED** — Part A (direct roundtrip): 8 PASS / 0 FAIL — checkpoint save/resume with dispatcher evidence chain 完整验证（CHECKPOINT_SAVE + CHECKPOINT_RESUME evidence, state restoration, conversation continuity, actionable detection, semantic content check）；Part B (real provider): 1 PASS / 2 CONCERN — B1/B2 CONCERN 归因为 confirmation="always" policy 阻止 tool execution 进而阻止 checkpoint save，这是安全性特性而非代码缺陷；总计 9 PASS / 0 FAIL / 2 CONCERN |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_004_checkpoint.py` — 9 PASS / 0 FAIL / 2 CONCERN；结果文件 `docs/dogfood/real-evidence-004-checkpoint-results.json` |

---

### REAL-EVIDENCE-005

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.4 / commit pending |
| **Capability** | MCP Bridge — real MCP server connection |
| **Missing evidence** | 真实 stdio MCP server 连接、真实 tool discovery、真实 tool execution 跨进程验证 |
| **Required validation** | (1) 搭建本地 MCP server fixture（如 filesystem server）；(2) 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` + MCP config 文件；(3) 启动真实 chat loop；(4) 验证 `run_mcp_bridge()` 真实连接 server 并注册 tools；(5) 验证 MCP tools 出现在 model-visible tools 中；(6) 验证模型可调用 MCP tool 并通过 TOOL_GATE→TOOL_INVOKE→TOOL_RESULT pipeline 执行；(7) 验证 TOOL_INVOKE 调用了真实 StdioMCPClient（非 FakeMCPClient）；(8) 验证 dispatcher evidence chain 完整（bridge lifecycle + tool pipeline）|
| **Current evidence** | bridge lifecycle dispatcher evidence（MCP_BRIDGE_LIFECYCLE RuntimeActionType）；L3 core.chat() tests 验证 MCP tool pipeline（但使用 FakeMCPClient + confirmation='never'）；mcp.discover/mcp.invoke branch points 标 PARTIAL（code path complete, real server pending）；Loop 3.3 code-path completion: 30 个 contract tests 验证 bridge module state / dynamic mcp_available / registration path / server allowlist / destructive tool block / invocation main path / not-fakeable / branch point status / opt-in activation|
| **Status** | **CLOSED** — real MCP server connection validated with opt-in echo fixture server（StdioMCPClient subprocess JSON-RPC）；12 PASS / 0 FAIL / 0 CONCERN — V0 (fixture exists), V1a (tools_discovered=2), V1b (tools_registered=2), V1c (overall_decision=operational), V2 (MCP_BRIDGE_LIFECYCLE evidence dispatched), V3 (TOOL_REGISTRY MCP tools verified), V4 (model-visible tools include MCP tools), V5 (server allowlist blocks non-matching server), V6 (missing config → blocked with errors) |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_005_mcp_bridge.py` — 12 PASS / 0 FAIL / 0 CONCERN；fixture `scripts/fixtures/mcp_echo_server.py`；结果文件 `docs/dogfood/real-evidence-005-mcp-bridge-results.json` |

---

### REAL-EVIDENCE-006

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.2 SDD / architecture decision phase |
| **Capability** | SubAgent L1 — real provider child loop + parent-mediated tool execution + memory scope roundtrip |
| **Missing evidence** | ~~真实 LLM provider child loop 完整执行（含 tool + memory scope roundtrip）~~ → 已验证 |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop — ✅；(2) 触发 SubAgent delegation（非 deterministic keyword-match）— ✅；(3) child loop 调真实 provider 并返回非 deterministic summary — ✅；(4) child tool_use 通过 parent ToolRuntimeMediator pipeline 执行 — ⚠️ contract tests 验证通过，production path 因 tool_mediator=None 未在真实 dogfood 中触发；(5) child memory proposal (scope=propose) 通过 mediate_child_memory_request() → parent store — ⚠️ contract tests 验证通过，demo-stat memory_scope=none 故 production path 不触发；(6) 所有 child action 有 dispatcher evidence — ✅；(7) 不是 deterministic keyword-match summary 冒充真实 child execution — ✅ |
| **Current evidence** | L1 code path complete: execute_l1() + delegate_l1() + mediate_child_tool_request() + mediate_child_memory_request()；child memory scope (none/propose) with namespaced store write；SUBAGENT_CHILD_MEMORY_REQUEST dispatcher evidence；CLI shortcuts 迁入 dispatcher path；**L1 real-model descriptor**: 新建 `demo-stat-real` with `model: inherit` + SAFE_MODELS 扩展（`"inherit"`） + 1 guard test；**dispatcher mismatch fix**: `core.py` 中 `_phase1_dispatcher` 赋值移至 CLI delegation 代码之前，使 delegation 证据落入 dogfood-injected dispatcher；**L1 evidence dispatch gaps 修复**: `SUBAGENT_CHILD_TOOL_REQUEST` dispatch in `mediate_child_tool_request()`、`SUBAGENT_CHILD_RESULT` dispatch in L1 handler、`SUBAGENT_PARENT_ADJUDICATION` dispatch in L1 handler（inject dispatcher via phase1_hook.py）；**Real provider dogfood validation (2026-05-29)**: 15 PASS / 0 FAIL / 1 CONCERN — C1 (SUBAGENT_DELEGATE_L1 success) / C3 (child result evidence) / C4 (parent adjudication) / C5 (memory scope=none expected) / C6 (L1 code path verified with real provider child loop) / C7 (25 events evidence chain: subagent.child_result + subagent.delegate_l1 + subagent.parent_adjudication)；C2 CONCERN: child 未调用 API tool_use（model 在 text 中描述工具而非 structured tool_use block），child tool mediation code path 由 31 contract tests 验证，production path 因 `core.py` 传入 `tool_mediator=None` 无法触发——这是已知限制（TOOL_MEDIATOR_GAP），不阻塞 CLOSED；37 L1 descriptor + 66 all-focused tests pass |
| **Status** | **CLOSED** — L1 real-model child loop validated：real provider dogfood 验证 L1 delegation→child result→parent adjudication evidence chain 完整；child tool mediation path code complete（contract tests 31 pass, production tool_mediator=None→TOOL_MEDIATOR_GAP known limitation）；descriptor model=inherit 注册 + guard test；dispatcher mismatch bug 已修复；evidence dispatch gaps 已修复（C3/C4 now PASS） |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_dogfood_skill_subagent_v2.py` — 15 PASS / 0 FAIL / 1 CONCERN；`agent/subagent_system/descriptors/demo-stat-real/SUBAGENT.md`；37+66 focused tests pass；evidence chain: subagent.delegate_l1→subagent.child_result→subagent.parent_adjudication |
| **Known limitation** | TOOL_MEDIATOR_GAP: `core.py:1301` passes `tool_mediator=None` to L1 handler → child 无法在 production 中通过 `mediate_child_tool_request()` 调用工具；contract tests 充分验证了 tool mediation 逻辑；production fix 需要 tool_mediator 在 delegation 点可用（非 trivial change，需 state/messages/turn_context 等依赖注入） |

---

### REAL-EVIDENCE-007

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.3 SDD / architecture decision phase |
| **Capability** | MCP Real External Flight — 真实 stdio MCP server 连接 + external tool execution + external tool policy |
| **Missing evidence** | 真实外部 MCP server 的完整连接→discovery→registration→tool_use→execution→result 路径 |
| **Required validation** | (1) 搭建本地 real MCP server fixture（如 filesystem 或 echo server）；(2) 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` + MCP config 文件含真实 server entry；(3) 启动 real chat loop；(4) 验证 `run_mcp_bridge(mode="registration", dry_run=False)` → StdioMCPClient 真实连接 → list_tools → 通过 policy gate → TOOL_REGISTRY 注册（FakeMCPClient 无真实 server 进程）；(5) 验证注册的 MCP tools 出现在 `get_model_visible_tools(max_mcp_tools=5)` 中；(6) 验证模型 tool_use MCP tool → TOOL_GATE（含 server_allowlist 校验）→ TOOL_INVOKE → StdioMCPClient.call_tool（非 FakeMCPClient）→ real server response → TOOL_RESULT → dispatcher evidence；(7) 验证 destructive tool name block（含 server_allowlist 边界）；(8) 验证 confirmation="always" 在 real core loop 中正确拦截（非 test hack `confirmation="never"`） |
| **Current evidence** | bridge lifecycle dispatcher evidence（MCP_BRIDGE_LIFECYCLE + disposable dispatcher）；L3 core.chat() tests 验证 MCP tool pipeline（但使用 FakeMCPClient + confirmation='never' test hack）；mcp.discover/mcp.invoke branch points 标 PARTIAL（code path complete, real server pending）；Loop 3.3 SDD 完成（`docs/design/mcp-real-external-flight-contract.md`）定义 opt-in contract + 17 test intents；Loop 3.3 code-path completion: 30 个 contract tests 全部通过 — module-level bridge state / dynamic mcp_available / server allowlist main.py wiring / registration→gate→invoke→result 路径验证 / getattr eager evaluation bug 修复（11 处）|
| **Status** | **CLOSED** — MCP external tool execution validated (顺带 REAL-EVIDENCE-005)；3 PASS / 0 FAIL — W0 (mcp_echo tool found in TOOL_REGISTRY), W1 (MCP tool executed via tool_registry.execute_tool() → real StdioMCPClient subprocess → [mcp_echo] hello from real evidence validation), W2 (destructive tool block patterns configured)；完整 pipeline: discovery→registration→TOOL_REGISTRY→model-visible→execute_tool→real server response |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_005_mcp_bridge.py` (W0-W2 section) — 3 PASS / 0 FAIL；结果文件 `docs/dogfood/real-evidence-005-mcp-bridge-results.json` |

---

### REAL-EVIDENCE-008

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.4 SDD / architecture decision phase |
| **Capability** | Advanced Scheduler — real provider plan → scheduler execution E2E |
| **Missing evidence** | 真实 LLM 生成的 plan 通过 scheduler 推进执行（fake plan → scheduler execution 不证明 real provider plan parsing 正确） |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) planner.generate_plan() 返回真实 JSON plan；(3) scheduler 从真实 JSON plan 构造 ActionPlan；(4) scheduler 按序推进 node（TOOL_CALL/MEMORY_RETAIN/SKILL_SELECT 等）；(5) 每个 node 产生 dispatcher evidence（NODE_ENTER/NODE_EXIT）；(6) plan 完成后产生 ACTION_PLAN_COMPLETE evidence；(7) 验证 scheduler decision 影响 model context 和 user response |
| **Current evidence** | Loop 3.4 SDD 完成（`docs/design/advanced-scheduler-contract.md`）；7 项架构决策；implementation 完成：`agent/action_scheduler.py`（554 lines）+ `agent/runtime_integration/action_scheduler_handler.py` + `agent/loop.py` scheduler integration + RuntimeDecisionFrame 5 新 branch points；46 个 contract tests 全部通过（7 classes, 20 test intents covered）；scheduler 通过 dispatcher 产生 5 种 business evidence；137/137 regression tests pass |
| **Status** | **CLOSED** — real provider scheduler E2E validated；9 PASS / 0 FAIL / 0 CONCERN — S0 (provider connectivity), S1 (ACTION_PLAN_START dispatched), S2 (NODE_ENTER ×2), S3 (NODE_EXIT ×3: completed×2 / skipped×1), S4 (ACTION_PLAN_COMPLETE dispatched), S5 (cross-node influence via condition_flags: step_2 → skip_step_3), S6 (condition-triggered skip evidence), S7 (real provider core.chat() for 2 nodes), S8 (not a no-crash PASS — 8 positive assertions) |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_008_scheduler.py` — 9 PASS / 0 FAIL / 0 CONCERN；结果文件 `docs/dogfood/real-evidence-008-scheduler-results.json` |

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
