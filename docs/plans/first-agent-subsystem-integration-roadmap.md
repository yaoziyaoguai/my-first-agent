# First Agent Subsystem / Intervention Point Integration Roadmap

Date: 2026-05-23
Status: active
Based on: repository evidence as of commit 55c900c

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
| **Tool Pipeline** | `agent/runtime_integration/tool_gate.py`, `tool_invoke.py`, `tool_result_feedback.py`, `agent/tool_registry.py`, `agent/tool_executor.py` | `docs/specs/tool-pipeline-l3-completion/`, `docs/specs/tool-branch-confirmation-required/`, `docs/specs/tool-invoke-branch-behavior/`, `docs/specs/tool-result-feedback-branch-behavior/` | L3 完整闭环 | TOOL_GATE→TOOL_INVOKE→TOOL_RESULT 三阶段全部 L3 verified |
| **MCP** | `agent/mcp.py`, `agent/mcp_models.py`, `agent/mcp_policy.py`, `agent/mcp_bridge.py`, `agent/runtime_integration/mcp_tool_orchestrator.py` | `docs/specs/mcp-runtime-integration/`, `docs/specs/mcp-l3-real-core-loop/` | L3 基础闭环 | confirmation="never" 工具走通完整管线；confirmation="always" 工具在 gate 被正确拦截 |
| **Memory (retain)** | `agent/runtime_integration/memory_retain.py`, `agent/memory.py`, `agent/memory_runtime.py`, `agent/memory_policy.py`, `agent/memory_store.py` | `docs/specs/memory-retain-branch-behavior/` | L3 完整闭环 | retain 经 phase1_hook → dispatcher → handler 全链路验证 |
| **Memory (recall)** | `agent/runtime_integration/memory_recall.py`, `agent/memory.py`, `agent/memory_suggestions.py` | `docs/specs/memory-recall-branch-behavior/` | L3 完整闭环 | snapshot→prompt injection 经 core.chat() 验证 |
| **Memory (consolidation)** | `agent/memory_consolidation.py`, `agent/memory_consolidation_engine.py`, `agent/memory_consolidation_llm.py`, `agent/memory_extraction.py` | `docs/rfc/MEMORY_CANONICAL_RFC.md` | L1/L2 基础 | consolidation pipeline 存在但 L3 evidence 未验证；real LLM consolidation gated |
| **Checkpoint** | `agent/checkpoint.py`, `agent/runtime_integration/checkpoint_summary.py` | `docs/CHECKPOINT_RESUME_SEMANTICS.md` | L1/L2 已验证 | save/load/clear 经 dispatcher 验证；L3 via core.chat() 未专项验证 |
| **Skill System** | `agent/skill_system/` (15 files), `agent/legacy_skills/`, `agent/runtime_integration/skill_action.py` | `docs/design/SKILL_SYSTEM_SDD.md`, `docs/SKILL_LOCAL_MVP.md` | L1/L2 Safe Local MVP | runtime_integration/skill_action.py 已有 dispatcher handler；L3 未验证 |
| **SubAgent System** | `agent/subagent_system/` (20 files), `agent/runtime_integration/subagent_action.py` | `docs/design/SUBAGENT_SYSTEM_SDD.md`, `docs/SUBAGENT_LOCAL_MVP.md` | L1/L2 Safe Local MVP | runtime_integration/subagent_action.py 已有 dispatcher handler；L3 未验证 |
| **Provider/Model** | `agent/provider/` (12 files), `agent/model_call.py`, `agent/model_output_dispatch.py` | `docs/LLM_PROVIDER_ADAPTER.md` | 集成在主流程中 | Anthropic/OpenAI/Fake provider 均通过 core.chat() 调用；FakeProvider 支撑所有 L3 测试 |
| **Confirmation** | `agent/confirmation/` (5 files), `agent/confirm_handlers.py`, `agent/pending_confirmation_dispatch.py` | `docs/specs/tool-branch-confirmation-required/` | L3 已验证 | tool confirmation_required 分支行为已验证 |
| **Context Build** | `agent/context_builder.py`, `agent/prompt_builder.py`, `agent/context.py` | 散见于各 spec | 集成在主流程中 | context injection（含 memory snapshot）经 core.chat() 验证 |
| **Session/Trace/Evidence** | `agent/session.py`, `agent/local_trace.py`, `agent/runtime_events.py`, `agent/runtime_observer.py`, `agent/runtime_integration/evidence.py` | `docs/LOCAL_TRACE_FOUNDATION.md`, `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | L1/L2 已验证 | evidence.py 提供 catalog-owned adapters；local trace 未接入 runtime |
| **Dispatcher** | `agent/runtime_integration/dispatcher.py`, `agent/runtime_integration/schema.py`, `agent/runtime_integration/phase1_hook.py` | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | 基础设施 | route() 和 route_from_runtime_loop() 双入口；phase1_hook 连接 loop 与 dispatcher |
| **Streaming** | `agent/provider/streaming.py`, `agent/runtime_integration/streaming_provider.py` | `docs/02-architecture/STREAMING_PROTOCOL.zh.md` | L1 基础 | streaming provider adapter 存在；L3 via core.chat() 未专项验证 |
| **CLI/TUI** | `agent/cli/`, `agent/cli_renderer.py`, `agent/display_events.py`, `agent/input_backends/` | `docs/V0_2_BASIC_TUI_PLAN.md` | adapter boundary | 不参与 runtime decision；已阶段性收口 |
| **Planner** | `agent/planner.py`, `agent/plan_schema.py` | 散见于 core.py | 集成在主流程中 | planning phase 内嵌于 core.chat() |

## C. Evidence Matrix

| Area | L1 status | L2 status | L3 status | Evidence files/tests | Gap | Recommended next |
|---|---|---|---|---|---|---|
| **Tool: allowed** | ✅ | ✅ | ✅ | `test_tool_pipeline_l3_completion.py` | 无 | 已闭环 |
| **Tool: confirmation_required** | ✅ | ✅ | ✅ | `test_tool_branch_confirmation_required.py` | 无 | 已闭环 |
| **Tool: blocked** | ✅ | ✅ | ❌ | `test_tool_anchor_fake.py` (L1/L2) | L3 未专项验证 | branch behavior，低优先级 |
| **Tool: not_found** | ❌ | ❌ | ❌ | 无专项测试 | tool_gate handler 未验证 not_found 分支 | **今晚候选 #1** |
| **Tool: invoke** | ✅ | ✅ | ✅ | `test_tool_invoke_branch_behavior.py` | 无 | 已闭环 |
| **Tool: result feedback** | ✅ | ✅ | ✅ | `test_tool_result_feedback_branch_behavior.py` | 无 | 已闭环 |
| **MCP: confirmation="never"** | ✅ | ✅ | ✅ | `test_mcp_l3_real_core_loop.py` | 无 | 已闭环 |
| **MCP: confirmation="always"** | ✅ | ✅ | ✅ (gate only) | `test_mcp_l3_real_core_loop.py::T5` | TOOL_INVOKE 不触发（设计如此） | confirmation 交互流程需要新设计，deferred |
| **MCP: Policy Re-Eval** | ❌ | ❌ | ❌ | 无 | 需要 runtime loop 中 confirmation 交互 | 需用户决策，暂缓 |
| **Memory: retain** | ✅ | ✅ | ✅ | `test_memory_retain_branch_behavior.py` | 无 | 已闭环 |
| **Memory: recall** | ✅ | ✅ | ✅ | `test_memory_recall_branch_behavior.py` | 无 | 已闭环 |
| **Memory: consolidation** | ✅ | ✅ | ❌ | `test_memory_consolidation*.py` | L3 via core.chat() 未验证 | **今晚候选 #3** |
| **Checkpoint: save/resume** | ✅ | ✅ | ❌ | `test_checkpoint_roundtrip.py`, `test_checkpoint_resume_semantics.py` | L3 via core.chat() 未专项验证 | **今晚候选 #2** |
| **Skill: action** | ✅ | ✅ | ❌ | `test_skill_*.py` (L1/L2) | L3 via core.chat() 未验证 | deferred（需先稳定 Skill 语义） |
| **SubAgent: action** | ✅ | ✅ | ❌ | `test_subagent_*.py` (L1/L2) | L3 via core.chat() 未验证 | deferred（需先稳定 SubAgent 语义） |
| **Provider/Model** | N/A | N/A | ✅ | 集成在主流程中 | 无 | FakeProvider 已支撑所有 L3 测试 |
| **Confirmation flow** | N/A | N/A | ✅ | `test_confirmation_flow.py` | 无 | 已集成在主流程中 |
| **Context injection** | N/A | N/A | ✅ | 集成在主流程中 | 无 | memory snapshot injection 已验证 |
| **Streaming** | ✅ | ❌ | ❌ | `test_streaming_protocol.py` | L2/L3 未验证 | deferred |
| **Evidence/Trace** | ✅ | ✅ | N/A | `test_runtime_action_contract.py` | local_trace 未接入 runtime | deferred |

## D. Backlog 分类

### 1. Must-fix correctness / safety

| Item | Evidence | Priority |
|---|---|---|
| Tool D4 not_found 分支未验证 | tool_gate.py handler 存在 not_found 逻辑但无专项测试 | P2 |

### 2. L3 主路径接入

| Item | Evidence | Priority |
|---|---|---|
| Tool not_found L3 | tool_gate.py 已有 `not_found` disposition，需 L3 验证 | 高 — 补齐 Tool gate 四个 disposition 的 L3 覆盖 |
| Checkpoint save/resume L3 | checkpoint.py 已通过 dispatcher 验证 L1/L2，需 L3 | 中 — 巩固基础设施 L3 |
| Memory consolidation L3 | consolidation pipeline 已有 L1/L2 基础，需 L3 | 中 — 但涉及 LLM consolidation 语义，边界需先理清 |

### 3. Policy / approval / governance

| Item | Evidence | Priority |
|---|---|---|
| MCP confirmation="always" 完整管线 | 当前 gate 正确拦截，需 runtime loop confirmation 交互 | 需用户决策设计 |
| MCP Policy Re-Eval per-call | 无现有实现 | 需用户决策设计 |

### 4. Error path hardening

| Item | Evidence | Priority |
|---|---|---|
| Tool invoke error/failure L3 | tool_invoke handler 已有 error 分支 | 低 |
| MCP tool error classification L3 | mcp_tool_orchestrator 已有错误分类 | 低 |

### 5. Deferred advanced capability

| Item | Evidence | Priority |
|---|---|---|
| Skill L3 activation | skill_action.py handler 存在，L3 需 core.chat() 路径 | deferred |
| SubAgent L3 delegation | subagent_action.py handler 存在，L3 需 core.chat() 路径 | deferred |
| Streaming L3 | streaming_provider.py adapter 存在 | deferred |
| Local trace runtime wiring | local_trace.py 存在但未接入 runtime | deferred |
| Memory real LLM consolidation | consolidation_llm.py 存在但 gated | deferred |

## E. 优先级规则

优先选择：
1. 已有 branch point 下的 branch behavior（Tool gate not_found）
2. 不需要真实 API / .env / 外部系统
3. 不处理真实私人资料
4. 能强化统一主流程
5. 能补齐当前 evidence 缺口
6. 能在今晚自动跑完并通过 gates

暂缓：
- 需要真实 secret/API（MCP Policy Re-Eval 需要确认交互设计）
- 需要新增 branch point
- 需要真实外部服务
- 跨多个子系统的大重构
- UI / product 语义不清的问题（Skill/SubAgent L3）
- 会诱发 fake/real 两套主流程的问题

## F. 今晚自动执行队列

| Order | Capability | Repository evidence | Why next | Expected SPEC path | Expected tests | Stop conditions | Safe to auto-run |
|---|---|---|---|---|---|---|---|
| **#1** | **Tool D4 not_found L3** | `tool_gate.py` 已有 `not_found` disposition 逻辑；`dispatcher.py` 已有 TOOL_GATE handler | 补齐 Tool gate 四个 disposition 全部 L3 覆盖；纯 branch behavior；零 pipeline 改动 | `docs/specs/tool-gate-not-found-l3/` | `tests/runtime_integration/test_tool_gate_not_found_l3.py` (~4 tests) | 需要新增 branch point / 需要真实 API | ✅ 是 |
| **#2** | **Checkpoint save/resume L3** | `checkpoint.py` + `checkpoint_summary.py` handler 存在；dispatcher 已注册 | 基础设施 L3 验证；巩固 save→resume 闭环经过 core.chat() | `docs/specs/checkpoint-l3/` | `tests/runtime_integration/test_checkpoint_l3.py` (~3 tests) | 需要新增 branch point / 需要真实 session | ✅ 是 |
| **#3** | **Memory consolidation L3** | `memory_consolidation.py` + `consolidation_engine.py` 存在 | consolidation pipeline L3 验证 | `docs/specs/memory-consolidation-l3/` | `tests/runtime_integration/test_memory_consolidation_l3.py` (~3 tests) | 涉及 LLM consolidation 语义不清 / 需要真实 LLM | ⚠️ 需先理清边界 |

## G. Stop Conditions

以下任一条件触发时停止并 Ask User：
- 需要新增 branch point
- 需要真实 API / .env / 外部服务
- 需要真实 secret
- 需要用户安全/产品决策
- 同一问题在同一阶段已修 2 次仍未通过 gate
- 发现架构分歧
- 安全/隐私问题
- ahead > 0 且不是当前 capability 的 commit
