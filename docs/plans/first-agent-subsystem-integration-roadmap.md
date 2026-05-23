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
| **Tool Pipeline** | `agent/runtime_integration/tool_gate.py`, `tool_invoke.py`, `tool_result_feedback.py`, `agent/tool_registry.py`, `agent/tool_executor.py` | `docs/specs/tool-pipeline-l3-completion/`, `docs/specs/tool-branch-confirmation-required/`, `docs/specs/tool-invoke-branch-behavior/`, `docs/specs/tool-result-feedback-branch-behavior/`, `docs/specs/tool-gate-not-found-l3/` | L3 完整闭环 | TOOL_GATE→TOOL_INVOKE→TOOL_RESULT 三阶段全部 L3 verified；four dispositions: allowed✅, confirmation_required✅, not_found✅, blocked ❌(L3 gap) |
| **MCP** | `agent/mcp.py`, `agent/mcp_models.py`, `agent/mcp_policy.py`, `agent/mcp_bridge.py`, `agent/runtime_integration/mcp_tool_orchestrator.py` | `docs/specs/mcp-runtime-integration/`, `docs/specs/mcp-l3-real-core-loop/` | L3 基础闭环 | confirmation="never" 工具走通完整管线；confirmation="always" 工具在 gate 被正确拦截 |
| **Memory (retain)** | `agent/runtime_integration/memory_retain.py`, `agent/memory.py`, `agent/memory_runtime.py`, `agent/memory_policy.py`, `agent/memory_store.py` | `docs/specs/memory-retain-branch-behavior/` | L3 完整闭环 | retain 经 phase1_hook → dispatcher → handler 全链路验证 |
| **Memory (recall)** | `agent/runtime_integration/memory_recall.py`, `agent/memory.py`, `agent/memory_suggestions.py` | `docs/specs/memory-recall-branch-behavior/` | L3 完整闭环 | snapshot→prompt injection 经 core.chat() 验证 |
| **Memory (consolidation)** | `agent/memory_consolidation.py`, `agent/memory_consolidation_engine.py`, `agent/memory_consolidation_llm.py`, `agent/memory_extraction.py` | `docs/rfc/MEMORY_CANONICAL_RFC.md` | L1/L2 基础 | consolidation pipeline 存在但 L3 evidence 未验证；real LLM consolidation gated；⚠️ deferred — consolidation runtime trigger 语义待用户澄清 |
| **Checkpoint** | `agent/checkpoint.py`, `agent/runtime_integration/checkpoint_summary.py` | `docs/specs/checkpoint-save-resume-l3/`, `docs/CHECKPOINT_RESUME_SEMANTICS.md` | L3 完整闭环 | CHECKPOINT_SAFE_SUMMARY 经 turn-end hook → dispatcher → handler L3 verified |
| **Skill System** | `agent/skill_system/` (15 files), `agent/legacy_skills/`, `agent/runtime_integration/skill_action.py` | `docs/design/SKILL_SYSTEM_SDD.md`, `docs/SKILL_LOCAL_MVP.md` | L1/L2 Safe Local MVP | runtime_integration/skill_action.py 已有 dispatcher handler；L3 未验证；RuntimeActionType SKILL_SELECT 存在但未在 phase1_hook 注册 |
| **SubAgent System** | `agent/subagent_system/` (20 files), `agent/runtime_integration/subagent_action.py` | `docs/design/SUBAGENT_SYSTEM_SDD.md`, `docs/SUBAGENT_LOCAL_MVP.md` | L1/L2 Safe Local MVP | runtime_integration/subagent_action.py 已有 dispatcher handler；L3 未验证；RuntimeActionType SUBAGENT_DELEGATE_L0 存在但未在 phase1_hook 注册 |
| **Provider/Model** | `agent/provider/` (12 files), `agent/model_call.py`, `agent/model_output_dispatch.py` | `docs/LLM_PROVIDER_ADAPTER.md` | 集成在主流程中 | Anthropic/OpenAI/Fake provider 均通过 core.chat() 调用；FakeProvider 支撑所有 L3 测试 |
| **Confirmation** | `agent/confirmation/` (5 files), `agent/confirm_handlers.py`, `agent/pending_confirmation_dispatch.py` | `docs/specs/tool-branch-confirmation-required/` | L3 已验证 | tool confirmation_required 分支行为已验证 |
| **Context Build** | `agent/context_builder.py`, `agent/prompt_builder.py`, `agent/context.py` | 散见于各 spec | 集成在主流程中 | context injection（含 memory snapshot）经 core.chat() 验证 |
| **Session/Trace/Evidence** | `agent/session.py`, `agent/local_trace.py`, `agent/runtime_events.py`, `agent/runtime_observer.py`, `agent/runtime_integration/evidence.py` | `docs/LOCAL_TRACE_FOUNDATION.md`, `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | L1/L2 已验证 | evidence.py 提供 catalog-owned adapters；local trace 未接入 runtime；test_runtime_action_contract.py 已有 overclaim 防护但未覆盖 CHECKPOINT_SAFE_SUMMARY |
| **Dispatcher** | `agent/runtime_integration/dispatcher.py`, `agent/runtime_integration/schema.py`, `agent/runtime_integration/phase1_hook.py` | `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md` | 基础设施 | route() 和 route_from_runtime_loop() 双入口；phase1_hook 连接 loop 与 dispatcher；7 个 handler 已注册 |
| **Streaming** | `agent/provider/streaming.py`, `agent/runtime_integration/streaming_provider.py` | `docs/02-architecture/STREAMING_PROTOCOL.zh.md` | L1 基础 | streaming provider adapter 存在；L3 via core.chat() 未专项验证；RuntimeActionType STREAMING_PROVIDER_CALL / STREAMING_EVENT 存在但未在 phase1_hook 注册 |
| **CLI/TUI** | `agent/cli/`, `agent/cli_renderer.py`, `agent/display_events.py`, `agent/input_backends/` | `docs/V0_2_BASIC_TUI_PLAN.md` | adapter boundary | 不参与 runtime decision；已阶段性收口 |
| **Planner** | `agent/planner.py`, `agent/plan_schema.py` | 散见于 core.py | 集成在主流程中 | planning phase 内嵌于 core.chat() |

## C. Evidence Matrix

| Area | L1 status | L2 status | L3 status | Evidence files/tests | Gap | Recommended next |
|---|---|---|---|---|---|---|
| **Tool: allowed** | ✅ | ✅ | ✅ | `test_tool_pipeline_l3_completion.py` | 无 | 已闭环 |
| **Tool: confirmation_required** | ✅ | ✅ | ✅ | `test_tool_branch_confirmation_required.py` | 无 | 已闭环 |
| **Tool: blocked** | ✅ | ✅ | ✅ | `test_tool_blocked_l3.py` | 无 | 已闭环 (commit 6cef9b8) |
| **Tool: not_found** | ✅ | ✅ | ✅ | `test_tool_gate_not_found_l3.py` | 无 | 已闭环 (commit 76a88e4) |
| **Tool: invoke** | ✅ | ✅ | ✅ | `test_tool_invoke_branch_behavior.py` | 无 | 已闭环 |
| **Tool: invoke error** | ✅ | ✅ | ✅ | `test_tool_invoke_error_l3.py` | 无 | 已闭环 (commit 748513c) |
| **Tool: invoke not_found** | ✅ | ✅ | ❌ | `tool_invoke.py:127-128` 已有 not_found disposition；无专项 L3 test | TOOL_INVOKE mid-pipeline not_found 路径未 L3 验证 | **今晚候选 #3** |
| **Tool: result feedback** | ✅ | ✅ | ✅ | `test_tool_result_feedback_branch_behavior.py` | 无 | 已闭环 |
| **MCP: confirmation="never"** | ✅ | ✅ | ✅ | `test_mcp_l3_real_core_loop.py` | 无 | 已闭环 |
| **MCP: confirmation="always"** | ✅ | ✅ | ✅ (gate only) | `test_mcp_l3_real_core_loop.py::T5` | TOOL_INVOKE 不触发（设计如此） | confirmation 交互流程需要新设计，deferred |
| **MCP: Policy Re-Eval** | ❌ | ❌ | ❌ | 无 | 需要 runtime loop 中 confirmation 交互 | 需用户决策，暂缓 |
| **MCP: HOME isolation** | ✅ | ✅ | N/A | `test_mcp_l3_real_core_loop.py::T6` 在 HOME 隔离路径下通过 | 非覆盖缺口——测试正确要求隔离 HOME，CI/Makefile 应统一设置 | 已闭环（基础设施问题，非测试缺陷） |
| **Memory: retain** | ✅ | ✅ | ✅ | `test_memory_retain_branch_behavior.py` | 无 | 已闭环 |
| **Memory: recall** | ✅ | ✅ | ✅ | `test_memory_recall_branch_behavior.py` | 无 | 已闭环 |
| **Memory: consolidation** | ✅ | ✅ | ❌ | `test_memory_consolidation*.py` | L3 via core.chat() 未验证；consolidation runtime trigger 语义待用户澄清 | ⚠️ deferred |
| **Checkpoint: save/resume** | ✅ | ✅ | ✅ | `test_checkpoint_save_resume_l3.py` | 无 | 已闭环 (commit cd6aaf6) |
| **Evidence: overclaim protection** | ✅ | ✅ | N/A | `test_runtime_action_contract.py` | CHECKPOINT_SAFE_SUMMARY overclaim 已覆盖（`test_forged_target_label_as_checkpoint` + `test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_checkpoint`） | 已闭环 |
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
| Tool blocked L3 | `tool_gate.py` 已有 blocked/rejected disposition；`test_tool_anchor_fake.py` + `test_tool_branch_confirmation_required.py` 有 L1/L2 | **P0 — 补齐 Tool gate 四 disposition 全 L3 覆盖的最后一块** |
| Evidence overclaim: CHECKPOINT_SAFE_SUMMARY | `test_runtime_action_contract.py` 未覆盖 CHECKPOINT_SAFE_SUMMARY 的 forged target_label 防护 | P1 |

### 2. L3 主路径接入

| Item | Evidence | Priority |
|---|---|---|
| Tool blocked L3 | 同上 | **高 — 今晚 #1** |
| Tool invoke error L3 | `tool_invoke.py:130-132` execution_status="error" 路径 | 中 — error-path hardening |
| Tool invoke not_found L3 | `tool_invoke.py:127-128` disposition="not_found" 路径 | 中 — defensive path hardening |

### 3. Policy / approval / governance

| Item | Evidence | Priority |
|---|---|---|
| MCP confirmation="always" 完整管线 | 当前 gate 正确拦截，需 runtime loop confirmation 交互 | 需用户决策设计 |
| MCP Policy Re-Eval per-call | 无现有实现 | 需用户决策设计 |

### 4. Error path hardening

| Item | Evidence | Priority |
|---|---|---|
| Tool invoke error/failure L3 | tool_invoke handler 已有 error 分支 | 中 |
| Tool invoke not_found L3 | tool_invoke handler 已有 not_found 分支 | 中 |
| MCP HOME isolation test fix | T6 在非隔离 HOME 下失败 | 低 — test env fix |

### 5. Deferred advanced capability

| Item | Evidence | Priority |
|---|---|---|
| Memory consolidation L3 | consolidation pipeline L1/L2 完成，runtime trigger 语义待澄清 | ⚠️ deferred |
| Skill L3 activation | skill_action.py handler 存在，L3 需 core.chat() 路径 | deferred |
| SubAgent L3 delegation | subagent_action.py handler 存在，L3 需 core.chat() 路径 | deferred |
| Streaming L3 | streaming_provider.py adapter 存在 | deferred |
| Local trace runtime wiring | local_trace.py 存在但未接入 runtime | deferred |
| Memory real LLM consolidation | consolidation_llm.py 存在但 gated | deferred |

## E. 优先级规则

优先选择：
1. 已有 branch point 下的 branch behavior（Tool gate blocked）
2. 不需要真实 API / .env / 外部系统
3. 不处理真实私人资料
4. 能强化统一主流程
5. 能补齐当前 evidence 缺口
6. 不需要新增 RuntimeActionType / handler / flow
7. 能在今晚自动跑完并通过 gates

暂缓：
- 需要真实 secret/API（MCP Policy Re-Eval 需要确认交互设计）
- 需要新增 branch point
- 需要真实外部服务
- 跨多个子系统的大重构
- UI / product 语义不清的问题（Skill/SubAgent L3）
- 会诱发 fake/real 两套主流程的问题
- Memory consolidation L3（consolidation runtime trigger 语义待用户澄清）

## F. 自动执行队列（2026-05-24 持续扩展版）

### 已完成 / 已闭环

| Order | Capability | Status |
|---|---|---|
| **#1** | **Tool blocked L3** | ✅ 完成 (commit 6cef9b8) |
| **#2** | **Tool invoke error L3** | ✅ 完成 (commit 748513c) |
| **#3** | **Tool invoke not_found L3** | ⚠️ deferred — 非自然可达路径 |
| **#4** | **Evidence overclaim: CHECKPOINT_SAFE_SUMMARY** | ✅ 已覆盖 |
| **#5** | **MCP HOME isolation** | ✅ 已闭环 |

### 新发现候选（2026-05-24 discovery 扩展）

| Order | Capability | Repository evidence | Why safe | Why next | Expected SPEC path | Expected tests | Stop conditions | Safe to auto-run |
|---|---|---|---|---|---|---|---|---|
| **#6** | **Evidence overclaim: SubAgent (ForgedTargetLabel + CatalogAllowedForgedCallable)** | `evidence.py` catalog 已注册 `subagent.delegate_l0→SubAgentExecutor` descriptor；`is_runtime_e2e_evidence()` 有特殊 `parent_adjudicated is True` 规则；但 `test_runtime_action_contract.py` 中零覆盖 | 纯测试添加，零生产代码改动，严格复用现有 `_ForgedTargetLabelHandler` / `_CatalogAllowedForgedCallableHandler` 模式 | SubAgent 是安全边界（delegated execution），缺 overclaim 防护是 correctness/safety gap | `docs/specs/evidence-overclaim-subagent/` | `test_runtime_action_contract.py` 新增 2 测试 | 无 | ✅ 是 |
| **#7** | **Evidence overclaim: StreamingProvider ForgedTargetLabel** | `test_runtime_action_contract.py` 有 `test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_streaming_provider` 但缺 plain `_ForgedTargetLabelHandler` 测试 | 纯测试添加，零生产代码改动 | 补齐 StreamingProtocol overclaim 防护对称性 | `docs/specs/evidence-overclaim-streaming/` | `test_runtime_action_contract.py` 新增 1 测试 | 无 | ✅ 是 |
| **#8** | **Direct call downgrade: handler L2 分类一致性审计** | `test_runtime_action_handlers.py` 验证各 handler direct dispatcher 分类 | 纯测试审计+补充 | 确保 direct dispatcher 不能伪装 L3 | TBD after #6/#7 | 补充缺失 L2 downgrade 断言 | 需先完成 #6/#7 | ⚠️ 待评估 |

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
