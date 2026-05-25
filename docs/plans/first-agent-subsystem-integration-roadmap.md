# First Agent Subsystem / Intervention Point Integration Roadmap

Date: 2026-05-24
Status: active
Based on: repository evidence as of commit 748513c

## A. 当前架构心智模型

First Agent 只有一条统一主流程：

```
query/event
  → core.chat()
  → _run_main_loop()
  → model call → classify → dispatch
  → turn-end hook → _try_phase1_turn_end_runtime_action()
  → RuntimeActionDispatcher.route_from_runtime_loop()
  → handler (gate/invoke/result/retain/recall)
  → return to runtime loop
```

核心约束：
- 子系统只是主流程上的有限介入点（branch point / hook）
- 子系统可能写入状态（retain），也可能从子系统召回内容进入主流程（recall）
- ToolGate / ToolInvoke / ToolResult 是 Tool lifecycle stages / pipeline phases，不是三个独立子系统
- MCP 是 adapter boundary，不是新 runtime
- Memory 可以写入（retain），也可以 recall into context
- 其他子系统/介入点必须从仓库证据中发现，不凭空编造

## B. Subsystem / Intervention Point Discovery

基于仓库 `agent/`、`tests/`、`docs/specs/`、`docs/implementation-notes/` 的实际证据：

| Area | Repository evidence | Existing docs/specs/tests | Current maturity | Notes |
|---|---|---|---|---|
| **Tool Pipeline** | `agent/runtime_integration/tool_gate.py`, `tool_invoke.py`, `tool_result_feedback.py`, `agent/tool_registry.py`, `agent/tool_executor.py` | `docs/specs/tool-pipeline-l3-completion/`, `docs/specs/tool-branch-confirmation-required/`, `docs/specs/tool-invoke-branch-behavior/`, `docs/specs/tool-result-feedback-branch-behavior/`, `docs/specs/tool-gate-not-found-l3/`, `docs/specs/tool-request-l3/` | L3 完整闭环 | TOOL_GATE→TOOL_REQUEST→TOOL_INVOKE→TOOL_RESULT 四阶段全部 L3 verified；four dispositions: allowed✅, confirmation_required✅, not_found✅, blocked ❌(L3 gap) |
| **MCP** | `agent/mcp.py`, `agent/mcp_models.py`, `agent/mcp_policy.py`, `agent/mcp_bridge.py`, `agent/runtime_integration/mcp_tool_orchestrator.py` | `docs/specs/mcp-runtime-integration/`, `docs/specs/mcp-l3-real-core-loop/` | L3 Tool Pipeline adapter boundary | MCP 是 Tool Pipeline 的 adapter boundary，不是独立 runtime；confirmation="never" 工具经 Tool Pipeline（TOOL_GATE→TOOL_INVOKE→TOOL_RESULT）走通完整管线；confirmation="always" 工具在 gate 被正确拦截；MCP L3 证据归入 Tool lifecycle integration |
| **Memory (retain)** | `agent/runtime_integration/memory_retain.py`, `agent/memory.py`, `agent/memory_runtime.py`, `agent/memory_policy.py`, `agent/memory_store.py` | `docs/specs/memory-retain-branch-behavior/`, `docs/specs/memory-propose-l3/` | L3 完整闭环 | MEMORY_TURN_END_PROPOSAL + MEMORY_PROPOSE 双 action L3 verified；confirmation → queue → turn-end dispatch → store.write() 完整 evidence chain |
| **Memory (recall)** | `agent/runtime_integration/memory_recall.py`, `agent/memory.py`, `agent/memory_suggestions.py` | `docs/specs/memory-recall-branch-behavior/` | L3 完整闭环（双路径，AD 裁决不统一） | MEMORY_RECALL AD (`docs/design/MEMORY_RECALL_DUAL_PATH_AD.md`) 裁决：Path A（pre-loop prompt injection via `snapshot_for_prompt()` → `build_system_prompt()`）与 Path B（turn-end dispatcher evidence）服务于不同目的、不同生命周期点，不统一。Path A 直接注入 system prompt 影响模型行为（用户可见"已加载 X 条相关记忆"）；Path B 通过 dispatcher 收集 L3 evidence。两者互补，不竞争。 | 已闭环 (commit e18595b + AD)；双路径统一为 unnecessary——AD 裁决当前架构正确 |
| **Memory (consolidation)** | `agent/memory_consolidation.py`, `agent/memory_consolidation_engine.py`, `agent/memory_consolidation_llm.py`, `agent/memory_extraction.py` | `docs/specs/memory-consolidation-l3/`, `docs/rfc/MEMORY_CANONICAL_RFC.md` | L3 dispatch path verified | MEMORY_CONSOLIDATE RuntimeActionType L3 verified via loop.py turn-end hook → route_from_runtime_loop → catalog adapter；real LLM consolidation（consolidation_llm.py）需要真实 LLM/private data，仍 deferred |
| **Checkpoint** | `agent/checkpoint.py`, `agent/runtime_integration/checkpoint_summary.py` | `docs/specs/checkpoint-save-resume-l3/`, `docs/CHECKPOINT_RESUME_SEMANTICS.md` | L3 完整闭环 | CHECKPOINT_SAFE_SUMMARY 经 turn-end hook → dispatcher → handler L3 verified |
| **Skill System** | `agent/skill_system/` (15 files), `skills/demo-note-maker/`, `agent/runtime_integration/skill_action.py` | `docs/design/SKILL_SYSTEM_SDD.md`, `docs/SKILL_LOCAL_MVP.md` | L3 dispatch path verified (empty + non-empty registry) | SKILL_SELECT RuntimeActionType L3 dispatch path verified via loop.py turn-end hook → route_from_runtime_loop → catalog adapter；empty registry 路径（`no_suitable_skill`）✅；non-empty registry business operation（demo-note-maker body load）✅ (WP2)；多 skill marketplace 为 future work |
| **SubAgent System** | `agent/subagent_system/` (20 files), `agent/runtime_integration/subagent_action.py` | `docs/design/SUBAGENT_SYSTEM_SDD.md`, `docs/SUBAGENT_LOCAL_MVP.md`, `docs/specs/subagent-l3/SPEC.md` | L3 完整闭环（empty + non-empty registry） | SUBAGENT_DELEGATE_L0 RuntimeActionType L3 verified via loop.py turn-end hook → route_from_runtime_loop → catalog adapter；empty registry `no_suitable_subagent` ✅；non-empty registry business delegation（descriptor lookup → validation → SubAgentRequest → delegate_once → success）✅；production phase1_hook.py 使用 SubAgentRegistry(roots=[Path("tests/fixtures/subagents")]) |
| **Provider/Model** | `agent/provider/` (12 files), `agent/model_call.py`, `agent/model_output_dispatch.py` | `docs/LLM_PROVIDER_ADAPTER.md` | 集成在主流程中 | Anthropic/OpenAI/Fake provider 均通过 core.chat() 调用；FakeProvider 支撑所有 L3 测试 |
| **Confirmation** | `agent/confirmation/` (5 files), `agent/confirm_handlers.py`, `agent/pending_confirmation_dispatch.py` | `docs/specs/tool-branch-confirmation-required/` | L3 已验证 | tool confirmation_required 分支行为已验证 |
| **Context Build** | `agent/context_builder.py`, `agent/prompt_builder.py`, `agent/context.py` | 散见于各 spec | 集成在主流程中 | context injection（含 memory snapshot）经 core.chat() 验证 |
| **Session/Trace/Evidence** | `agent/session.py`, `agent/local_trace.py`, `agent/runtime_events.py`, `agent/runtime_observer.py`, `agent/runtime_integration/evidence.py` | `docs/LOCAL_TRACE_FOUNDATION.md`, `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | runtime trace path verified（非 RuntimeActionDispatcher evidence 模型） | evidence.py 提供 catalog-owned adapters（RuntimeActionDispatcher evidence 模型）；overclaim 防护已覆盖全部 12 个 catalog targets；local trace 通过 `on_trace_event` sink 接入 runtime loop，emit TraceEvent，不经过 RuntimeActionDispatcher evidence 模型——不使用 "L3" 标签，应使用 "runtime trace path verified" |
| **Dispatcher** | `agent/runtime_integration/dispatcher.py`, `agent/runtime_integration/schema.py`, `agent/runtime_integration/phase1_hook.py` | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | 基础设施 | route() 和 route_from_runtime_loop() 双入口；phase1_hook 连接 loop 与 dispatcher；8 个 handler 已注册（含 MEMORY_CONSOLIDATE） |
| **Streaming** | `agent/provider/streaming.py`, `agent/runtime_integration/streaming_provider.py`, `agent/model_call.py` | `docs/specs/streaming-l3/`, `docs/implementation-notes/streaming-l3.md` | L3 evidence path verified | STREAMING_PROVIDER_CALL + STREAMING_EVENT 均已激活；per-event evidence（validate_stream_event）+ 整轮聚合 evidence（collect_stream_response）双路径；用户可见逐字输出通过 emit_text_delta → print() 已实现 |
| **CLI/TUI** | `agent/cli/`, `agent/cli_renderer.py`, `agent/display_events.py`, `agent/input_backends/` | `docs/V0_2_BASIC_TUI_PLAN.md` | adapter boundary | 不参与 runtime decision；已阶段性收口 |
| **Planner** | `agent/planner.py`, `agent/plan_schema.py` | 散见于 core.py | 集成在主流程中 | planning phase 内嵌于 core.chat() |

## C. Evidence Matrix

| Area | L1 status | L2 status | L3 status | Evidence files/tests | Gap | Recommended next |
|---|---|---|---|---|---|---|
| **Tool: allowed** | ✅ | ✅ | ✅ | `test_tool_pipeline_l3_completion.py` | 无 | 已闭环 |
| **Tool: confirmation_required** | ✅ | ✅ | ✅ | `test_tool_branch_confirmation_required.py` | 无 | 已闭环 |
| **Tool: blocked** | ✅ | ✅ | ✅ | `test_tool_blocked_l3.py` | 无 | 已闭环 (commit 6cef9b8) |
| **Tool: not_found** | ✅ | ✅ | ✅ | `test_tool_gate_not_found_l3.py` | 无 | 已闭环 (commit 76a88e4) |
| **Tool: request** | ✅ | ✅ | ✅ | `test_tool_request_l3.py` (L3) | 无 | 已闭环 (本 commit) |
| **Tool: invoke** | ✅ | ✅ | ✅ | `test_tool_invoke_branch_behavior.py` | 无 | 已闭环 |
| **Tool: invoke error** | ✅ | ✅ | ✅ | `test_tool_invoke_error_l3.py` | 无 | 已闭环 (commit 748513c) |
| **Tool: invoke not_found** | ✅ | ✅ | ✅ | `test_tool_invoke_not_found_l3.py` | 无 | 已闭环 (commit f6d92f7) |
| **Tool: result feedback** | ✅ | ✅ | ✅ | `test_tool_result_feedback_branch_behavior.py` | 无 | 已闭环 |
| **MCP: confirmation="never"** | ✅ | ✅ | ✅ (Tool Pipeline L3) | `test_mcp_l3_real_core_loop.py` | 无 | 已闭环；MCP 是 Tool Pipeline adapter boundary，L3 证据归入 Tool lifecycle integration |
| **MCP: confirmation="always"** | ✅ | ✅ | ✅ (gate only) | `test_mcp_l3_real_core_loop.py::T5` | TOOL_INVOKE 不触发（设计如此） | confirmation 交互流程需产品决策；MCP 不独立于 Tool Pipeline |
| **MCP: Policy Re-Eval** | ❌ | ❌ | ❌ | 无 | 需要 runtime loop 中 confirmation 交互 | 需用户决策，暂缓 |
| **MCP: HOME isolation** | ✅ | ✅ | N/A | `test_mcp_l3_real_core_loop.py::T6` 在 HOME 隔离路径下通过 | 非覆盖缺口——测试正确要求隔离 HOME，CI/Makefile 应统一设置 | 已闭环（基础设施问题，非测试缺陷） |
| **Memory: retain** | ✅ | ✅ | ✅ | `test_memory_retain_branch_behavior.py`, `test_memory_propose_l3.py` | 无 | MEMORY_PROPOSE L3 已闭环 (本 commit) |
| **Memory: recall** | ✅ | ✅ | ✅ (L3 完整闭环，AD 裁决双路径互补) | `test_memory_recall_branch_behavior.py`, `test_memory_recall_l3.py` | MEMORY_RECALL AD 裁决：Path A（pre-loop prompt injection）与 Path B（turn-end dispatcher evidence）服务于不同目的，不统一。Path A 注入 system prompt（用户可见）；Path B 收集 L3 evidence。架构正确，互补不竞争。 | 已闭环 (commit e18595b + AD) |
| **Memory: consolidation** | ✅ | ✅ | ✅ (dispatch path) | `test_memory_consolidation*.py`, `test_memory_consolidate_l3.py` | MEMORY_CONSOLIDATE RuntimeAction dispatch path L3 verified via loop.py turn-end hook；real LLM consolidation（consolidation_llm.py）需真实 LLM/private data，仍 deferred | 已闭环 (本 commit)；real LLM consolidation deferred |
| **Checkpoint: save/resume** | ✅ | ✅ | ✅ | `test_checkpoint_save_resume_l3.py` | 无 | 已闭环 (commit cd6aaf6) |
| **Evidence: overclaim protection** | ✅ | ✅ | N/A | `test_runtime_action_contract.py` | CHECKPOINT_SAFE_SUMMARY overclaim 已覆盖（`test_forged_target_label_as_checkpoint` + `test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_checkpoint`） | 已闭环 |
| **Skill: action** | ✅ | ✅ | ✅ (dispatch path, empty + non-empty registry) | `test_skill_l3.py` (L3), `test_skill_select_pipeline_l3.py` (L3 non-empty registry), `test_skill_*.py` (L1/L2) | SKILL_SELECT RuntimeActionType dispatch path L3 verified（empty + non-empty registry）；demo-note-maker business operation（body_load_decision=True）✅ (WP2)；多 skill marketplace 为 future work | 已闭环 (commit 35009ed)；non-empty registry business operation L3 已验证 |
| **SubAgent: action** | ✅ | ✅ | ✅ (L3 完整闭环: empty + non-empty registry) | `test_subagent_l3.py` (L3 empty + non-empty registry), `test_subagent_*.py` (L1/L2) | SUBAGENT_DELEGATE_L0 RuntimeActionType L3 完整闭环：empty registry `no_suitable_subagent` ✅；non-empty registry business delegation（descriptor lookup → validation → SubAgentRequest → delegate_once → success）✅ | 已闭环 (commit 35009ed + 本轮)；business operation L3 已补齐 |
| **Provider/Model** | N/A | N/A | ✅ | 集成在主流程中 | 无 | FakeProvider 已支撑所有 L3 测试 |
| **Confirmation flow** | N/A | N/A | ✅ | `test_confirmation_flow.py` | 无 | 已集成在主流程中 |
| **Context injection** | N/A | N/A | ✅ | 集成在主流程中 | 无 | memory snapshot injection 已验证 |
| **Streaming** | ✅ | ✅ | ✅ (L3) | `test_streaming_l3.py` | STREAMING_PROVIDER_CALL + STREAMING_EVENT 均已激活（aggregate + per-event）；逐字输出已通过 emit_text_delta → print() 实现 | L3 evidence path verified；双路径（聚合+单event） |
| **Evidence/Trace** | ✅ | ✅ | runtime trace path verified | `test_local_trace_runtime_wiring_l3.py` | trace event emission 通过 `on_trace_event` sink，不经过 RuntimeActionDispatcher evidence 模型——不使用 "L3" 标签；使用 "runtime trace path verified" | runtime trace path verified（本 commit）；与 RuntimeActionDispatcher evidence 模型独立 |

## D. Backlog 分类（2026-05-24 E2E 审计后重组）

### 1. Safe focused fix

可安全继续的 P2/P3 修正或 hardening：

| Item | Evidence | Priority |
|---|---|---|
| (当前无已知 correctness/safety bug) | N/A | N/A |
| STREAMING_EVENT per-event evidence activation | `agent/runtime_integration/streaming_provider.py` — StreamingEventHandler + validate_stream_event | P2 — 已完成：handler 已注册，per-event dispatch 已接入 turn-end hook，catalog entry 已更新 |
| WP3: User Onboarding + First-Run Experience | `agent/cli_renderer.py` render_onboarding(), `main.py` --help/help | ✅ 完成 (commit b41193e) |
| WP4: First Usable Task E2E Smoke Test | `tests/smoke/test_first_usable_task_e2e.py` 6 tests | ✅ 完成 (commit bdbc806) |

### 2. Architecture Extension Loop candidate

需新增 RuntimeActionType / handler / catalog entry 或架构扩展，但方向清晰、可 fake-first、不需真实 secret/API：

| Item | Evidence | Why Architecture Extension | Priority |
|---|---|---|---|
| Pre-loop MEMORY_RECALL wiring | 当前 MEMORY_RECALL 在 turn-end hook 调度；实际 prompt injection 走 `snapshot_for_prompt()` → `build_system_prompt()`（不经 dispatcher）；两条路径未统一 | 需要新 branch point（pre-loop context build phase）或双路径统一设计 | 高 — 核心主线能力 |
| Skill non-empty registry business operation L3 | SKILL_SELECT dispatch path L3 verified（空 registry → non-empty registry）；demo-note-maker body_load_decision=True ✅；`test_skill_select_pipeline_l3.py` 6 tests (S1-S6)；注意：skill body_load 发生但不自动触发 tool call——完整"用户请求→skill匹配→tool调用→结果返回"闭环仍需 fake model tool intent 补齐 | ✅ 完成 (WP2, commit 35009ed) — 现有 SKILL_SELECT branch point 承载，branch behavior 补齐；tool call auto-trigger 为 future work | 完成 |
| SubAgent non-empty registry business delegation L3 | SUBAGENT_DELEGATE_L0 dispatch path L3 verified（空 registry）；`no_suitable_subagent` handler 已验证；non-empty registry 业务委托 L3 未验证 | 需要 non-empty SubAgentRegistry 和对应 SPEC/TDD；现有 branch point 可承载（SUBAGENT_DELEGATE_L0 已在 turn-end hook），是 branch behavior 补齐 | 中 — safe to auto-run after SPEC |
| WP1: Non-empty ToolRegistry + fake local tools | `agent/tool_registry.py` 注册 demo.echo_task_summary / demo.write_demo_note；Tool Pipeline 可承载（通过 `core.chat()` 路径），但 `main.py demo` 是独立 demo adapter 路径（`agent/local_demo.py`），不经过 Tool Pipeline | ✅ 完成 (WP1, commit 6880482) — 现有 Tool Pipeline branch point 承载；demo 路径和 runtime 路径的区分见 README "运行 fake/local demo" 节 | 完成 |
| MEMORY_PROPOSE confirmation flow wiring | confirmation 二次 turn-end action wiring | 现有 branch point（turn-end hook）可承载；可能需新增 RuntimeActionType 或复用现有 confirmation branch | 中 — safe to auto-run after Architecture Decision |
| Full user-visible streaming UX | STREAMING_PROVIDER_CALL dispatch path L3 verified；full UX（SSE/WebSocket/chunked response）未实现 | 需要 streaming protocol adapter / UX SPEC；现有 STREAMING_PROVIDER_CALL branch point 可承载 | 中低 — safe to auto-run after SPEC |

### 3. Product decision required

实现方向涉及产品/交互语义判断，需用户决策：

| Item | Evidence | Decision needed | Priority |
|---|---|---|---|
| MCP confirmation="always" full pipeline | 当前 gate 正确拦截 confirmation="always" 工具；TOOL_INVOKE 不触发（设计如此） | confirmation 二次交互的 UX 语义（阻塞等待？内联确认？pending queue？） | 中 — 不阻塞其他 work |
| MCP Policy Re-Eval per-call | 无现有实现 | 是否需要在 runtime loop 中做 MCP policy re-evaluation | 低 — 可长期 deferred |

### 4. Secret / API / private data blocked

需要真实外部资源才能继续，fake-first 下无法推进：

| Item | Evidence | What's blocked by | Priority |
|---|---|---|---|
| Memory real LLM consolidation | `consolidation_llm.py` 存在但 gated；MEMORY_CONSOLIDATE RuntimeAction dispatch path L3 verified | 需要真实 LLM / provider / private data | deferred — fake consolidation path 已完成 |

### 5. Do not do yet

当前不应开始的工作：

| Item | Reason |
|---|---|
| MCP as independent subsystem | MCP 是 Tool Pipeline adapter boundary，不独立；MCP L3 已在 Tool Pipeline L3 中覆盖 |
| 第二条主流程 | 违反 Contract Section 1：fake/real 共享同一 business flow |
| new Anchor | 违反 Contract Section 6：capability milestone 纪律 |

## E. 优先级规则

优先选择：
1. correctness / safety bug — 修复已知缺陷
2. evidence overclaim prevention — 补齐 target overclaim 防护
3. 已有 branch point 下的 branch behavior — 不新增架构元素
4. existing handler / RuntimeActionType L1/L2/L3 gap — evidence 缺口补齐
5. error-path hardening — 加固已有错误处理路径
6. architecture extension that enables existing deferred subsystem
7. model/provider/skill/checkpoint/mcp/memory existing assets with safe implementation path

**重要：需要新增 branch point / RuntimeActionType / handler / catalog entry / 架构决策不再是 stop condition。**
这些触发 Architecture Extension Loop（见 AUTO_RUN_WORKFLOW.md Section C2）。

仍然暂缓的只有：
- 需要真实 secret/API/外部服务/私人资料
- P0 级别问题
- 改变项目根本方向（新增第二条主流程、Anchor 等）

## F. 自动执行队列（2026-05-24 持续扩展版）

### 已完成 / 已闭环

| Order | Capability | Status |
|---|---|---|
| **#1** | **Tool blocked L3** | ✅ 完成 (commit 6cef9b8) |
| **#2** | **Tool invoke error L3** | ✅ 完成 (commit 748513c) |
| **#3** | **Tool invoke not_found L3** | ✅ 完成 (commit f6d92f7) — spy 拦截 gate→invoke pipeline 模拟竞态触发 not_found |
| **#4** | **Evidence overclaim: CHECKPOINT_SAFE_SUMMARY** | ✅ 已覆盖 |
| **#5** | **MCP HOME isolation** | ✅ 已闭环 |
| **#6** | **WP1: Non-empty ToolRegistry + demo tools** | ✅ 完成 (commit 6880482) |
| **#7** | **WP2: Non-empty SkillRegistry + demo-note-maker** | ✅ 完成 (commit 35009ed) |
| **#8** | **WP3: User Onboarding + --help/help** | ✅ 完成 (commit b41193e) |
| **#9** | **WP4: First Usable Task E2E Smoke Test** | ✅ 完成 (commit bdbc806) |

### 新发现候选（2026-05-24 discovery 扩展，已全部完成并移至上方"已完成/已闭环"）

### 下一批候选（E2E 审计后按新分类体系）

#### Group A: Architecture Extension Loop candidate（safe to auto-run）

| Priority | Capability | Category | Why Architecture Extension | Dependencies |
|---|---|---|---|---|
| **高** | ~~Pre-loop MEMORY_RECALL wiring~~ | ✅ AD 裁决不统一 (commit e18595b + AD) | MEMORY_RECALL AD (`docs/design/MEMORY_RECALL_DUAL_PATH_AD.md`) 裁决：Path A（pre-loop injection）与 Path B（turn-end dispatcher evidence）服务于不同目的，不统一。当前架构正确。 | N/A |
| **中** | ~~Skill non-empty registry business operation L3~~ | ✅ 完成 (WP2, commit 35009ed) — Branch behavior 补齐（现有 SKILL_SELECT branch point） | 已验证 demo-note-maker body_load_decision=True L3 完整闭环 | N/A |
| **中** | ~~SubAgent non-empty registry business delegation L3~~ | ✅ 完成 (本 commit) — Branch behavior 补齐（现有 SUBAGENT_DELEGATE_L0 branch point） | Non-empty registry business delegation L3 verified: T3 (success), T4 (reject unregistered), T5 (shell gate), T6 (adjudication gate) | N/A |
| **中** | ~~MEMORY_PROPOSE confirmation flow wiring~~ | ✅ 已完成 — turn-end hook MEMORY_PROPOSE dispatch 已完整闭环 | MEMORY_PROPOSE 在 loop.py:188-235 通过 turn-end hook dispatch；confirmation → pending_retain_proposals → MEMORY_PROPOSE → retain execution → store.write() 完整 evidence chain，91 tests pass | N/A |
| **中低** | Full user-visible streaming UX | Architecture Extension | STREAMING_PROVIDER_CALL dispatch path 已有；需 streaming protocol adapter / UX SPEC | SPEC → TDD → Plan → Implementation |

#### Group B: Product decision required

| Priority | Capability | Decision needed |
|---|---|---|
| **中** | MCP confirmation="always" full pipeline | confirmation 交互 UX 语义（阻塞等待/内联确认/pending queue） |
| **低** | MCP Policy Re-Eval per-call | 是否需要在 runtime loop 中做 MCP policy re-evaluation |

#### Group C: Secret / API / private data blocked

| Priority | Capability | What's blocked by |
|---|---|---|
| **deferred** | Memory real LLM consolidation | 需要真实 LLM / provider / potential private data |

#### Group D: Safe focused fix（P3）

| Priority | Capability | Action |
|---|---|---|
| **P3** | ~~STREAMING_EVENT activation~~ | ✅ 完成 — `StreamingEventHandler` + `validate_stream_event` 已注册；per-event L3 evidence dispatch 已接入 turn-end hook |

## G. Stop Conditions（2026-05-24 更新：Architecture Extension Loop 已启用）

**真正全局 stop condition:**

以下任一条件触发时停止：
- not main / behind origin/main / HEAD has tag / working tree dirty（非当前 loop）
- 需要真实 API / .env / secret / 外部服务 / 私人资料 / sessions / runs / episodes
- P0 级别问题
- P1 且无法通过回退修复
- 架构决策会改变项目根本方向
- context 接近耗尽 / tool failure

**不再是 stop condition（已迁移到 Architecture Extension Loop）:**

- 需要新增 branch point → Architecture Extension Loop
- 需要新增 RuntimeActionType / handler / catalog entry → Architecture Extension Loop
- 需要架构设计/决策 → Architecture Extension Loop
- 所有剩余候选都需要架构扩展 → 逐一进入 Architecture Extension Loop
- queue empty → 继续 discovery
- 完成 3 个 loops → 继续 discovery
