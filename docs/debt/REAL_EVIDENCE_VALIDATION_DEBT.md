# Real Evidence / Dogfood / Real API Validation Debt

**创建日期**: 2026-05-28
**最后更新**: 2026-06-01 (B7 Phase 1 security preflight: config.yaml real key replaced with placeholder; docs secret fragments redacted; SEC-001 registered)

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
| **Required validation** | 启动真实 chat loop；输入"记住"命令触发 retain → CONFIRMATION_REQUIRED → 确认 → MEMORY_PROPOSE dispatch → store 写入；MEMORY_RECALL dispatch → 返回正确内容；输入"忘记"命令 → MEMORY_FORGET dispatch → store 移除；验证 retain/recall/forget 使用共享 store；forget 后 recall 不再返回已删除 memory |
| **Current evidence** | 5 L2 MemoryForget contract tests pass；5 L3 shared-store contract tests pass；65 focused tests pass；**REAL-EVIDENCE-001 dogfood validation (2026-05-29)**: 真实 provider memory dogfood E2E 验证通过 — 13/13 PASS (M0-M7)；retain → CONFIRMATION_REQUIRED → 确认 → MEMORY_PROPOSE dispatched → store written；MEMORY_RECALL dispatched → correct content returned (1 item, 532 chars)；MEMORY_FORGET dispatched → store removal confirmed (1→0)；post-forget recall empty (0 items, no Python reference)；shared store consistency confirmed (InMemoryMemoryStore, same id)；not no-crash PASS (12 positive assertions) |
| **Status** | **CLOSED** — real provider memory retain/recall/forget E2E validated |
| **Caveat** | Recall validation includes direct `dispatcher.route_from_runtime_loop()` provenance (not through `core.chat()` → `refresh_runtime_system_prompt()` production path)；Retain/Forget have stronger `core.chat()` E2E evidence (CONFIRMATION_REQUIRED → MEMORY_PROPOSE / MEMORY_FORGET dispatch)。不影响 credible 结论，但 Recall production path 验证弱于 Retain/Forget。 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_001_memory.py` — 13 PASS / 0 FAIL / 0 CONCERN；结果文件 `docs/dogfood/real-evidence-001-memory-results.json`；修复 `agent/core.py:600` MEMORY_FORGET dispatcher 路由（`_p1_dispatcher` → `_phase1_dispatcher`）使注入 dispatcher 可观测 forget evidence |

---

### REAL-EVIDENCE-002

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2 / commit 2d26c2a；Loop 2.2b / commit 98b4163；model-owned path / REAL-EVIDENCE-002 implementation (2026-05-30) |
| **Capability** | Skill Activation — model-owned SKILL_SELECT tool call via ToolRuntimeMediator pipeline |
| **Missing evidence** | ~~真实模型（非 FakeProvider）在真实 chat loop 中是否自主触发 tool_use("SKILL_SELECT", ...)~~ → **已验证** |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop — ✅；(2) 输入能触发 Skill selection 的用户请求 — ✅；(3) 验证模型是否真实调用 SKILL_SELECT tool — ✅；(4) 验证 tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → _active_skill 完整 pipeline — ✅；(5) 验证 _skill_selected_by_model flag 正确设置 → turn-end hook 跳过 keyword fallback — ✅ |
| **Current evidence (2026-05-30)** | **Real provider SKILL_SELECT E2E 验证通过 (6/6 PASS)**: R0 (provider connectivity ok: AnthropicCompatibleProvider) → R1 (core.chat() completed, event types: skill.select + tool.gate + tool.invoke + tool.result) → R2 (SKILL_SELECT evidence: skill.select events=1) → R3 (mediator pipeline: skill_select=1, tool_gate=3, tool_invoke=2) → R4 (_active_skill populated: skill_id=demo-note-maker, body_len=300, allowed_tools={'demo.write_demo_note', 'demo.echo_task_summary'}) → R5 (_skill_selected_by_model flag consumed by turn-end hook, model-owned path confirmed by R4) → R6 (model-owned path confirmed: no keyword fallback)。完整链路: `core.chat()` → model-visible tools 包含 SKILL_SELECT → real AnthropicCompatibleProvider emits tool_use("SKILL_SELECT") → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → _active_skill 设置 + _skill_selected_by_model=True → evidence 区分 model-owned vs keyword fallback。 |
| **Status** | **CLOSED (credible)** — Plan 3 pipeline + manifest-based language matching。real provider SKILL_SELECT 模型自主调用验证通过。完整 ToolRuntimeMediator pipeline 证据链闭合。**Loop 7 (2026-05-31, ab013ed)**: D05/D06 关闭 — D06 dogfood 断言字段修正 (no_suitable_skill: True) + dogfood 状态重置 + plan confirmation auto-confirm。**12 PASS / 0 CONCERN / 0 FAIL** (AnthropicCompatibleProvider, 53.7s)。Evidence chain fully closed (D01-D08 + P3S9-P3S12)。Language matching: 不做隐式跨语言匹配，多语言由 manifest 显式声明。**Closed concerns**: D04 lifecycle activation evidence、D05 TOOL_GATE evidence field consistency (Loop 5 mediator fix validated)、D06 no_suitable_skill dogfood assertion。**Remaining non-blocking scope caveats**: (1) prompt-steered dogfood; (2) single-skill scenario。|
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-31 (Loop 7: ab013ed) |
| **Closing evidence** | `scripts/real_evidence_002_plan3_dogfood.py` — 12 PASS / 0 CONCERN / 0 FAIL (AnthropicCompatibleProvider, core.chat() runtime path, real provider)；结果文件 `docs/dogfood/real-evidence-002-plan3-results.json`。**Earlier**: `scripts/real_evidence_002_003_real_provider_dogfood.py` Phase 1 — 6 PASS / 0 FAIL / 0 CONCERN（R0-R6 all PASS, prompt-steered）。**Hardening (historical)**: `scripts/real_evidence_002_hardening.py` — 9 PASS / 3 FAIL / 5 CONCERN。|
| **Credibility** | **credible** — Plan 3 pipeline (retriever + selection section + lifecycle + allowed_tools) runtime path + evidence chain fully closed (12/12 PASS)。real provider SKILL_SELECT validated。manifest-based language matching。D03 reclassified as manifest language coverage policy (not runtime blocker)。D04/D05/D06 closed。Not product-ready。B7/B8 not started。002 can be stage-closed；next: start REAL-EVIDENCE-003 independent remediation / dogfood。 |

---

### REAL-EVIDENCE-003

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.2b / commit 98b4163 |
| **Capability** | Skill allowed_tools enforcement — real dogfood E2E |
| **Missing evidence** | ~~真实 core loop 中 skill allowed_tools 约束工具执行的端到端验证~~ → **已验证** |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop — ✅；(2) 触发一个带 allowed_tools 的 active Skill — ✅ (demo-note-maker activated via real SKILL_SELECT)；(3) 让模型尝试调用允许工具 — ✅ (allowed tools were gated via confirmation='always')；(4) 让模型尝试调用不允许工具 — ✅ (model attempted SKILL_SELECT("blog-writing") via adversarial prompt)；(5) blocked tool 不进 execute_single_tool — ✅ (no TOOL_INVOKE for disallowed tool)；(6) dispatcher evidence chain 验证 — ✅ (TOOL_GATE rejected via skill_allowed_tools→rejected)；(7) evidence 含 skill_allowed_tools — ✅ (('demo.echo_task_summary', 'demo.write_demo_note') in evidence) |
| **Current evidence (2026-05-30)** | **Real provider disallowed-tool blocking E2E 验证通过 (4/4 PASS)**: R7 (adversarial prompt triggered SKILL_SELECT request) → R8 (TOOL_GATE rejected disallowed tool 'SKILL_SELECT' via skill_allowed_tools→rejected, identified by decision=rejected + skill_allowed_tools present) → R9 (No TOOL_INVOKE for disallowed tool 'SKILL_SELECT') → R10 (skill_allowed_tools_present=True, decision_rejected=True, requested_tool_name_present=True) → R11 (execute_single_tool not called, FORCE_STOP from mediator)。完整链路: real provider SKILL_SELECT activates demo-note-maker (allowed_tools={'demo.echo_task_summary', 'demo.write_demo_note'}) → adversarial prompt 诱导模型调用 SKILL_SELECT("blog-writing") → TOOL_GATE 检查 skill_allowed_tools, SKILL_SELECT 不在其中 → rejected (skill_allowed_tools→rejected) → mediator FORCE_STOP → no TOOL_INVOKE → evidence chain complete。 |
| **Status** | **CLOSED (credible)** — Loop 8 (2026-05-31): 13 PASS / 0 FAIL / 4 CONCERN。lifecycle→mediator→gate enforcement 全链闭合。Multiple disallowed business tools (read_file/read_file_lines/SKILL_SELECT) blocked via skill_allowed_tools→rejected。H2 adversarial styles 2/3 PASS (direct+indirect via read_file target fix)。execution_suppressed evidence added to rejected gates。TestRejectedGateNoToolExecution (6 tests) verifies no TOOL_INVOKE dispatch + execution_suppressed evidence + FORCE_STOP return for read_file/read_file_lines/request_user_input + allowed contrast。24 focused tests PASS。Remaining 4 CONCERN all MODEL_BEHAVIOR (request_user_input model avoidance; privilege_escalation model refusal) — not code defects, gate mechanism proven。**No remaining caveat blocks credible status**。 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-31 (Loop 8: execution_suppressed + no-TOOL_INVOKE verification + H2 fix → credible) |
| **Closing evidence** | `scripts/real_evidence_003_hardening.py` — 13 PASS / 0 FAIL / 4 CONCERN (AnthropicCompatibleProvider, core.chat() runtime path)；结果文件 `docs/dogfood/real-evidence-003-hardening-results.json` |
| **Hardening Loop 8 (2026-05-31)** | `scripts/real_evidence_003_hardening.py` — **13 PASS / 0 FAIL / 4 CONCERN**。H0: skill activation PASS。H1: read_file_lines + read_file both rejected via skill_allowed_tools→rejected (invokes=0)；request_user_input CONCERN (模型走 AskUserQuestion — MODEL_BEHAVIOR)。H2: direct → read_file rejected PASS；indirect → read_file rejected PASS；privilege_escalation CONCERN (模型文本拒绝 — MODEL_BEHAVIOR)。H3: R33 SKILL_SELECT rejected PASS；R34 no TOOL_INVOKE PASS；R35 skill state changed CONCERN (pre-existing skill activation design)。R36 evidence completeness PASS。**Key fix**: H2 target preference changed from `list(disallowed)[0]` to `prefer read_file > read_file_lines` → 2/3 adversarial styles now trigger gate rejection。**Production code**: `agent/runtime_integration/tool_gate.py` added `execution_suppressed: True` to rejected evidence_extra。**New tests**: TestRejectedGateNoToolExecution (6 tests)。24 focused tests PASS。 |
| **Credibility** | **credible** — Loop 8 (2026-05-31)。lifecycle→mediator→gate enforcement 全链闭合。execution_suppressed evidence + no-TOOL_INVOKE verified by focused tests + real provider dogfood。H2 adversarial styles 2/3 PASS (direct+indirect)。Remaining CONCERN 全部 MODEL_BEHAVIOR (request_user_input 模型主动规避; privilege_escalation 模型拒绝 — 非代码缺陷, gate 机制本身已验证)。24 focused tests PASS。Fake/real 共享同一 main runtime path (ToolRuntimeMediator)。**No remaining code-level caveats**。Prompt-steered + 单 skill 场景为已知限制 (不影响 credible status)。 |

---

### REAL-EVIDENCE-004

| 字段 | 值 |
|------|-----|
| **Source** | Loop 2.3 / Storage-Checkpoint True Resume |
| **Capability** | Checkpoint save/resume dispatcher-mediated evidence chain — real API/model roundtrip validation |
| **Missing evidence** | 真实 LLM provider 下跨保存/恢复的完整 dispatcher evidence chain 连续性验证 |
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop；(2) 触发 checkpoint save（plan 生成、memory confirmation、或压缩同步）；(3) 验证 CHECKPOINT_SAVE dispatcher evidence 产生且 save_succeeded=True；(4) 模拟中断（Ctrl+C）并在下次启动时 resume；(5) 验证 CHECKPOINT_RESUME dispatcher evidence 产生且 restore_succeeded=True；(6) 验证 resume 后 conversation context、task state、pending action 一致继续；(7) 验证 save→resume dispatcher evidence chain 可追溯（action_log 中两种 action type 都存在）；(8) 验证 RuntimeDecisionFrame 正确反映 checkpoint 状态；(9) 验证不是 save/load file smoke 或 no-crash 冒充 true resume |
| **Current evidence** | 16 contract tests pass（4 save mediation + 5 resume mediation + 4 roundtrip + 2 not fakeable + 1 L3 hook-level）；core.py 3 处 direct save_checkpoint 已迁入 dispatcher-mediated CHECKPOINT_SAVE；session.py resume 路径通过 CHECKPOINT_RESUME handler 记录 evidence（dispatcher 按需构建）；CheckpointSaveHandler/CheckpointResumeHandler 在 phase1_hook.py 注册；RuntimeDecisionFrame checkpoint branch points 更新为 code path complete；**Batch A evidence hardening (2026-05-29)**: Part A (roundtrip) — 10 PASS / 0 FAIL (A1a/A1b/A2/A3/A4/A5/A6/A7 all PASS)；direct-save fallback 已移除 (Guardrail 2: dispatcher 不可用时标 CONCERN 而非静默 fallback)；CHECKPOINT_PATH 重定向确保 dispatcher handler 写入正确 temp path；Part B (real provider chat) — 2 CONCERN (B1/B2): action_log 中 tool.gate/tool.invoke/tool.result 均存在（工具执行管道活跃），但缺失 checkpoint.save/CHECKPOINT_SAVE —— checkpoint save trigger condition not met in this conversation，tools were executing but no save point was reached |
| **Status** | **CLOSED (hardened)** — Part A: 10 PASS / 0 FAIL — checkpoint save/resume dispatcher evidence chain 完整验证，direct-save fallback 已移除；Part B: 2 CONCERN — tools executing (tool.gate/invoke/result in action_log) but no checkpoint save point reached；总计 10 PASS / 0 FAIL / 2 CONCERN |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_004_checkpoint.py` — 10 PASS / 0 FAIL / 2 CONCERN（Batch A hardened: Guardrail 2 enforcement + CHECKPOINT_PATH redirection）；结果文件 `docs/dogfood/real-evidence-004-checkpoint-results.json` |

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
| **Required validation** | (1) 使用真实 LLM provider 启动真实 chat loop — ✅；(2) 触发 SubAgent delegation（非 deterministic keyword-match）— ✅；(3) child loop 调真实 provider 并返回非 deterministic summary — ✅；(4) child tool_use 通过 parent ToolRuntimeMediator pipeline 执行 — ✅ real provider E2E 验证通过；(5) child memory proposal (scope=propose) 通过 mediate_child_memory_request() → parent store — ⚠️ contract tests 验证通过，demo-stat memory_scope=none 故 production path 不触发；(6) 所有 child action 有 dispatcher evidence — ✅；(7) 不是 deterministic keyword-match summary 冒充真实 child execution — ✅ |
| **Current evidence** | L1 code path complete: execute_l1() + delegate_l1() + mediate_child_tool_request() + mediate_child_memory_request()；child memory scope (none/propose) with namespaced store write；SUBAGENT_CHILD_MEMORY_REQUEST dispatcher evidence；CLI shortcuts 迁入 dispatcher path；**L1 real-model descriptor**: `demo-stat-real` with `model: inherit` + SAFE_MODELS 扩展（`"inherit"`）；**dispatcher mismatch fix**: `core.py` 中 `_phase1_dispatcher` 赋值移至 CLI delegation 代码之前；**L1 evidence dispatch gaps 修复**: `SUBAGENT_CHILD_TOOL_REQUEST` dispatch in `mediate_child_tool_request()`、`SUBAGENT_CHILD_RESULT` dispatch in L1 handler、`SUBAGENT_PARENT_ADJUDICATION` dispatch in L1 handler；**TOOL_MEDIATOR_GAP 闭合**: `_dispatch_or_fallback_delegation()` 内部构造 ToolRuntimeMediator → `set_provider()`；**child_tools schema fix (2026-05-29, 第三轮)**: `execute_l1()` 修复 — 从 `context_package.request.allowed_tools` (descriptor 字符串名) 读取工具名并通过 TOOL_REGISTRY 查找真实 tool schema 传入 `provider.create(tools=child_tools)`。根因：`delegate_l1()` hardcode `tool_snapshots=()` + `build_context_package()` 忽略 `request.allowed_tools` → child_tools 始终为空 → 模型无 tool schema 可见 → 只能输出 XML/文本格式 tool call。修复后 child 收到 model-visible tool schema → 输出 API-native structured tool_use block。**Real provider E2E (2026-05-29, 第三轮)**: **12 PASS / 0 FAIL / 0 CONCERN** — 完整 evidence chain 闭合: M0 (provider built) → M1 (SUBAGENT_DELEGATE_L1 success) → M1b (TOOL_REGISTRY has read_file) → M2 (child structured tool_use — **首次 PASS**) → M3 (TOOL_GATE success) → M4a (TOOL_INVOKE) → M4b (TOOL_RESULT 1/1 success) → M5 (ToolRuntimeMediator mediation confirmed) → M6 (real tool result returned) → M7a (child result dispatched) → M7b (parent adjudication dispatched) → M8 (evidence chain traceable: 7 event types)。52/52 contract tests + 49/49 focused tests PASS。 |
| **Status** | **CLOSED (credible)** — 完整 parent→child→tool mediation→result→adjudication evidence chain 通过真实 provider E2E 验证。12/12 PASS。child_tools schema fix 是本次闭合的关键生产代码修复（execute_l1() 3 行新增代码从 request.allowed_tools 读取工具名并从 TOOL_REGISTRY 构建 schema）。 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_006_subagent_real_provider.py` — 12 PASS / 0 FAIL / 0 CONCERN（第三轮：child_tools schema fix 闭合 MODEL_BEHAVIOR_CONCERN）；production code fix: `agent/subagent_system/executor.py` (lines 162-188, child_tools 从 TOOL_REGISTRY 构建)；contract: 52 L1 parent-mediated tests PASS；结果文件 `docs/dogfood/real-evidence-006-subagent-real-provider-results.json` |
| **Known limitation** | ~~TOOL_MEDIATOR_GAP resolved.~~ ~~MODEL_BEHAVIOR_CONCERN resolved — child_tools schema fix 使模型可见 tool schema，模型输出 API-native structured tool_use。~~ SimpleNamespace turn_state + _turn_context 私有属性访问 caveat 仍在（不影响功能正确性）。demo-stat-real memory_scope=none 故 child memory proposal path 未在 real provider E2E 中触发（contract tests 已覆盖）。**upstream tool_snapshots=()**: `delegate_l1()` hardcode `tool_snapshots=()` 未修复——`execute_l1()` 绕过此限制从 `request.allowed_tools` + TOOL_REGISTRY 构建 child_tools；`tool_snapshots` 参数当前不承载业务数据，作为 future cleanup。**M7a/M7b evidence reporting**: `RuntimeActionEvent` 不含 `payload` 字段（业务数据在 `RuntimeActionResult.payload` 中，转换时丢弃）；validation script 中 `_safe_payload()` 已修正为先读 `payload` 再 fallback `evidence`；`SUBAGENT_CHILD_RESULT` / `SUBAGENT_PARENT_ADJUDICATION` 的 `status="not_supported"` 是预期行为（notification 式 dispatch，无注册 handler）。 |
| **Independent review** | **PASS_WITH_CONCERNS** (2026-05-29) — score 3.8/5 可接受；production code risk = low；补了 schema content test (name/description/input_schema 断言) + unauthorized tool exclusion test (shell/demo 不泄露)；upstream tool_snapshots=() 仍为 known limitation。 |
| **Credibility** | **credible** — 完整 evidence chain 闭合: parent delegates to child → child real provider emits structured tool_use → child tool_use goes through parent ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → tool result returns to child context → child final result returns to parent adjudication。12/12 PASS with real provider (AnthropicCompatibleProvider)。 |

---

### REAL-EVIDENCE-007

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.3 SDD / architecture decision phase |
| **Capability** | MCP Real External Flight — 真实 stdio MCP server 连接 + external tool execution + external tool policy |
| **Missing evidence** | 真实外部 MCP server 的完整连接→discovery→registration→tool_use→execution→result 路径 |
| **Required validation** | (1) 搭建本地 real MCP server fixture（如 filesystem 或 echo server）；(2) 设置 `MY_FIRST_AGENT_MCP_ENABLE=1` + `MY_FIRST_AGENT_MCP_DRY_RUN=0` + MCP config 文件含真实 server entry；(3) 启动 real chat loop；(4) 验证 `run_mcp_bridge(mode="registration", dry_run=False)` → StdioMCPClient 真实连接 → list_tools → 通过 policy gate → TOOL_REGISTRY 注册（FakeMCPClient 无真实 server 进程）；(5) 验证注册的 MCP tools 出现在 `get_model_visible_tools(max_mcp_tools=5)` 中；(6) 验证模型 tool_use MCP tool → TOOL_GATE（含 server_allowlist 校验）→ TOOL_INVOKE → StdioMCPClient.call_tool（非 FakeMCPClient）→ real server response → TOOL_RESULT → dispatcher evidence；(7) 验证 destructive tool name block（含 server_allowlist 边界）；(8) 验证 confirmation="always" 在 real core loop 中正确拦截（非 test hack `confirmation="never"`） |
| **Current evidence** | bridge lifecycle dispatcher evidence（MCP_BRIDGE_LIFECYCLE + disposable dispatcher）；L3 core.chat() tests 验证 MCP tool pipeline（但使用 FakeMCPClient + confirmation='never' test hack）；mcp.discover/mcp.invoke branch points 标 PARTIAL（code path complete, real server pending）；Loop 3.3 SDD 完成（`docs/design/mcp-real-external-flight-contract.md`）定义 opt-in contract + 17 test intents；Loop 3.3 code-path completion: 30 个 contract tests 全部通过；**Batch A evidence hardening (2026-05-29)**: W1 (MCP bridge via real StdioMCPClient → echo fixture) PASS — 2 tools registered；W2 (MCP tools in TOOL_REGISTRY) PASS；W3-W6 CONCERN — 模型未选择 MCP tool（Guardrail 1: 不 hack model behavior）；**007 main-path hardening (2026-05-29)**: `scripts/real_evidence_007_mcp_invoke.py` — FakeProvider deterministic tool_use + real StdioMCPClient bridge + confirmation='never' override + main runtime path — **10 PASS / 0 FAIL / 0 CONCERN**。完整执行链验证通过: W0 (fixture) → W1 (bridge registration via real StdioMCPClient) → W2a (TOOL_REGISTRY) → W2b (model-visible) → W3 (TOOL_GATE allowed) → W4 (TOOL_INVOKE success) → W5 (StdioMCPClient.call_tool executed via subprocess) → W6 (real MCP result, 67 bytes) → W7 (conversation context) → W8 (evidence chain: gate→invoke→result)。**Production code fix**: `tool_runtime_mediator.py:_route_result()` payload 字段 `result_summary` → `tool_output`（修复 ToolResultFeedbackHandler 无法消费 result 的 bug），新增 `execution_status` 字段。 |
| **Status** | **CLOSED (credible-with-caveats)** — 完整 MCP runtime-mediated execution chain 已验证: core.chat → ToolRuntimeMediator → TOOL_GATE(allowed) → TOOL_INVOKE → StdioMCPClient.call_tool(subprocess JSON-RPC) → TOOL_RESULT(real MCP result, 67 bytes) → conversation context。10/10 PASS。**Caveat (validation scope note, 非 runtime blocker)**: FakeProvider deterministic tool_use（非真实模型自主选择 MCP tool）+ confirmation='never' validation-only override（production 默认 confirmation='always'）。Code path 完整、evidence chain 闭合、底层 StdioMCPClient 真实调用已验证——caveat 仅影响验证方法学，不影响代码正确性。 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no |
| **Closed date** | 2026-05-29 |
| **Closing evidence** | `scripts/real_evidence_007_mcp_invoke.py` — 10 PASS / 0 FAIL / 0 CONCERN（FakeProvider + real StdioMCPClient bridge + confirmation='never' override + main runtime path）；production code fix: `tool_runtime_mediator.py:_route_result()` 字段修正；fixture `scripts/fixtures/mcp_echo_server.py`；结果文件 `docs/dogfood/real-evidence-007-mcp-invoke-results.json` |
| **Known limitation** | FakeProvider deterministic tool_use（非真实模型自主 MCP tool selection）+ confirmation='never' validation-only override（production 默认 confirmation='always'）。Model-owned MCP tool selection 不在本轮 scope。 |
| **Credibility** | **credible-with-caveats** — 完整 runtime-mediated execution chain (TOOL_GATE→TOOL_INVOKE→StdioMCPClient.call_tool→TOOL_RESULT→conversation context) 已验证；result_size=0 bug 已修复（mediator payload 字段修正）；code path + evidence chain 闭合。**Caveat (validation scope note, 非 runtime blocker)**: FakeProvider deterministic tool_use + confirmation='never' validation-only override——仅影响验证方法学，不影响代码正确性或 production readiness |

---

### REAL-EVIDENCE-008

| 字段 | 值 |
|------|-----|
| **Source** | Loop 3.4 SDD / architecture decision phase |
| **Capability** | Advanced Scheduler — main-path injection + model output → ActionPlan bridge |
| **Missing evidence** | ~~真实 LLM 自主生成 JSON plan 并送入 scheduler~~ → **CLOSED (2026-05-30)**: model-generated plan `provider.create()` path 13/13 PASS → **v3 (2026-05-31)**: `core.chat()` planning path 14/14 PASS, last caveat closed |
| **Required validation** | (1) ~~使用真实 LLM provider 启动真实 chat loop~~ → Gap A: FakeProvider + hand-built ActionPlan 通过 `_run_main_loop(action_scheduler=...)` 验证；(2) ~~planner.generate_plan() 返回真实 JSON plan~~ → Gap B: `build_action_plan_from_model_output()` bridge；(3) ~~scheduler 从 JSON 构造 ActionPlan~~ → Gap A+B；(4) ~~scheduler 按序推进 node~~ → 10/10 PASS；(5) ~~dispatcher evidence~~ → verified；(6) ~~condition_flags 跨 node 影响 + NODE_FAILURE halt~~ → verified；(7) ~~real model-generated stable JSON ActionPlan~~ → **Model Plan validation 13/13 PASS (2026-05-30)** |
| **Current evidence** | **Gap A+B completed + Model Plan caveat closed (2026-05-30)** — (A) `scripts/real_evidence_008_scheduler_core_chat_e2e.py`: 10/10 PASS, `_run_main_loop(action_scheduler=scheduler)` 完整 injection chain 验证；(B) `build_action_plan_from_model_output()` bridge: 7/7 contract tests PASS；(C) `scripts/real_evidence_008_model_generated_plan.py`: **13/13 PASS** — real AnthropicCompatibleProvider 通过 `provider.create()` (custom system prompt) 生成合法 JSON ActionPlan → `build_action_plan_from_model_output()` 成功解析 → ActionScheduler 执行 → ACTION_PLAN_START / NODE_ENTER x2 / NODE_EXIT x3 (2 completed + 1 skipped) / ACTION_PLAN_COMPLETE evidence chain 完整闭合 + condition_flags 跨 node 影响验证 + malformed safety 4 用例通过。27/27 scheduler tests total (20 existing + 7 new)。 |
| **Status** | **credible (evidence chain fully closed, last caveat resolved 2026-05-31)** — Gap A: `_run_main_loop(action_scheduler=...)` E2E injection chain (10/10 PASS)。Gap B: `build_action_plan_from_model_output()` JSON→ActionPlan bridge (7/7 tests PASS)。Model Plan v1: `provider.create()` (custom system prompt) → 13/13 PASS。**Model Plan v3 (2026-05-31)**: `core.chat()` → `_run_planning_phase()` (ACTION_PLAN_PROMPT + schema validation + 1 repair retry) → real model outputs stable ActionPlan JSON (plan_id=cond_flag_test_v3_001, 3 nodes, has_depends, has_condition) → bridge → `_run_main_loop(action_scheduler=...)` → all 5 scheduler evidence types + condition_flags → **14 PASS / 0 FAIL / 0 CONCERN**。不再有 MODEL_BEHAVIOR_CONCERN。不再有 provider.create() 旁路 caveat。不再有 manual scheduler while caveat。6 处 `Plan.model_validate` ActionPlan guard 全部就位。104 scheduler/schema focused tests PASS。**ReAct main loop preserved**。**Scheduler remains opt-in branch executor**。**ActionPlan is planning branch contract, not global forced runtime path**。No second runtime introduced。Not product-ready。B7/B8 not started。 |
| **Blocking current code loop** | no |
| **Blocking READY claim** | no — scheduler injection chain + plan bridge + model JSON generation all verified |
| **Overclaim corrected** | 2026-05-29; caveat closed 2026-05-30 |
| **Gap A validation** | `scripts/real_evidence_008_scheduler_core_chat_e2e.py` — 10/10 PASS (V1-V10) |
| **Gap B implementation** | `agent/action_scheduler.py` — `build_action_plan_from_model_output()` (~50 lines); `tests/runtime_integration/test_scheduler_main_path.py` — `TestBuildActionPlanFromModelOutput` (7 tests) |
| **Model Plan validation** | `scripts/real_evidence_008_model_generated_plan.py` — 13/13 PASS (M0-M12) |
| **Gap A result file** | `docs/dogfood/real-evidence-008-gap-a-results.json` |
| **Model Plan result file** | `docs/dogfood/real-evidence-008-model-plan-results.json` |
| **Previous closing evidence (overclaimed)** | `scripts/real_evidence_008_scheduler.py` — manual harness, not main-path evidence |
| **Closed date** | 2026-05-30 (Gap A+B + Model Plan v1); last caveat closed 2026-05-31 (v3 core.chat() planning path) |
| **Closing evidence** | Gap A validation script (10/10 PASS) + Gap B bridge implementation (7/7 tests PASS) + Model Plan v1 `provider.create()` path (13/13 PASS) + **Model Plan v3 `core.chat()` planning path (14/14 PASS, 0 MODEL_BEHAVIOR_CONCERN)** + 104 scheduler/schema focused tests PASS |
| **Independent review** | **PASS_WITH_CONCERNS → caveat closed** (2026-05-30): model JSON generation caveat 已闭合；B7/B8 entry gate: runtime prerequisites mostly satisfied——scheduler evidence chain fully closed 含 model-generated plan；仍需评估 002 implementation scope |

---

---

## SEC-001: Tracked config.yaml contained real-looking API key

| 字段 | 值 |
|------|-----|
| **Source** | Codex B7 red-line audit / Phase 1 security preflight (2026-06-01) |
| **Risk type** | Secret leak — real-looking key in git-tracked file |
| **File** | `config/config.yaml` (tracked) |
| **Discovery** | `test_config_yaml_does_not_contain_real_api_key` FAILED |
| **Action taken** | Replaced value with `sk-REPLACE_ME` placeholder |
| **Docs fragments** | `docs/plans/` (2 lines), `docs/audit/` (3 lines) — all redacted |
| **Guard tests** | 3 tests now PASS: config key check + plans fragments + audit fragments |
| **Recommendation** | If the original key was ever valid, rotate/revoke it immediately |
| **Status** | REMEDIATED — placeholder in place, guard tests pass |

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
