# Agent Module Maturity Audit

**日期**: 2026-06-14
**性质**: post-repair module maturity audit — docs-only;非 repair queue
**Audited runtime HEAD**: `9bc20fc`(taxonomy decision request commit 之后的工作树)
**Taxonomy 来源**: 用户批准 Option γ + bounded-action rule(见 `AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md`)

---

## 1. Status

- **Architecture Repair Mainline: CLOSED**(`ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED`)。
- 本文件**不是** repair queue,不开启 Window 4,不重开 Architecture Repair。
- **North Star 是目标模型,不是待办清单**;North Star gap ≠ must-fix。Gap 经 Trigger 判断后才可能成为 action。
- 原 Module Maturity Audit 为 docs-only;后续 T-SKILL-GOLDEN 关闭只新增 golden test / fixture 与最小状态文档,不改 production code / North Star / 已关闭的 Window closure audits / 已关闭 Roadmap。
- **Pre-work full suite baseline**:**4730 passed, 12 skipped, 26 xfailed**。
- **T-SKILL-GOLDEN fresh full suite**:**4731 passed, 12 skipped, 26 xfailed**。

---

## 2. Approved Module Taxonomy

**MODULE_TAXONOMY_APPROVED = YES**(Option γ,用户批准)

| # | Module | 类型 |
|---|---|---|
| 1 | Agent Loop | 能力面/主流程 |
| 2 | RuntimeAction / Dispatcher Spine | 架构 spine |
| 3 | Tool System | 能力面 |
| 4 | MCP | 外部协议能力面 |
| 5 | Memory | 能力面 |
| 6 | SubAgent | 能力面 |
| 7 | Skill System | 能力面 |
| 8 | Provider / Model Boundary | 能力面/边界 |
| 9 | Policy / Approval | 横切治理 |
| 10 | Scheduler / Async | 能力面(dormant) |
| 11 | State / Checkpoint / Resume | 横切/恢复 |
| 12 | Observability / Evidence | 横切 |
| 13 | Security / Privacy | 横切治理 |
| 14 | Capability / Config / Registry Boundary | 横切/契约 |
| 15 | Docs / Guardrails | 横切/SoT |

### 用户决策(D1–D4 / C1–C2)

- **D1**:Agent Loop 与 RuntimeAction/Dispatcher Spine **拆分**。Agent Loop = 主运行流程/planning-execution loop/状态推进/fallback entry;Spine = RuntimeAction/dispatcher/handler routing/action contract/fallback dispatch semantics。
- **D2**:Security / Privacy **独立**;不折进 Docs/Guardrails。Docs/Guardrails = 文档/SoT 控制;Security/Privacy = runtime sanitization、safe metadata ownership、privacy boundary、policy safety、sensitive data handling。
- **D3**:Policy / Approval **保持一个顶层模块,但要求显式子边界**:policy gate / `policy_blocked` / `rejected` 是当前已实现能力;production approval hook / OD-7 仍 deferred。**不得把 policy 成熟度当成 approval production-ready 的证明**。
- **D4**:Capability / Config / Registry Boundary **独立**;拥有 declared/registered/routed/dormant/deferred 边界、capability metadata、config/provider import boundary、registry semantics、CM-2/OD-2 未来决策。不藏在 Provider/Tool 下。
- **C1**:State/Checkpoint/Resume **独立**,不并入 Agent Loop。Agent Loop 可成熟,而 cross-process/cross-host resume 仍 deferred。
- **C2**:Tool System 与 MCP **分离**。Tool = 内部 registry/execution/result/evidence;MCP = 外部 protocol/server/client/service 边界、permission、sanitization、external failure behavior。

### Bounded-action rule

只有同时满足"证据充分 + 下一步清晰 + 验收路径清晰 + 无外部 credential 依赖 + 无 owner 决策依赖 + 不重开 Architecture Repair + 不顺手实现 deferred 大特性"时,才标 **HARDEN_NEXT**。否则用 BLOCKED_BY_* / TRACKED_DEBT / OPTIONAL_OR_FUTURE / NO_ACTION 等。

---

## 3. Method

每个模块统一走:**North Star target(目标)→ Current fact(事实)→ Evidence(证据)→ Maturity(L0–L4)→ Gap → Trigger → Action**。

成熟度等级(保守):

- **L0**:只有文档/设想,无有效代码路径
- **L1**:有代码/stub,但默认关闭、路径不完整或缺验证
- **L2**:有最小闭环,有 targeted test / fixture / golden 证明
- **L3**:production-routed 或主路径可用,有 guardrails,有 integration/golden/observability
- **L4**:default-on ready,有真实环境/real provider/CI/credential/production-grade 验证

不夸大:L3≠L4;fake provider 成熟≠real provider E2E;minimal memory golden≠production memory owner;registered-not-routed≠production routed;policy gate≠production approval hook。

证据来源:Graphify(`graphify-out/graph.json`,2026-06-14)做 source/runtime discovery,load-bearing claim 全部回到真实 file:line / test / closure audit 核验;`docs/CAPABILITY_BOUNDARIES.md` Runtime Fact Diff Table;closure audit §20 rubric(12 维全 2);North Star(仅作 target)。

---

## 4. Module Maturity Summary

| # | Module | Level | Action | Blocks mainline? | Harden next? | Confidence |
|---|---|---|---|---|---|---|
| 1 | Agent Loop | **L3** | NO_ACTION | no | no | High |
| 2 | RuntimeAction / Dispatcher Spine | **L3** | NO_ACTION | no | no | High |
| 3 | Tool System | **L3** | NO_ACTION | no | no | High |
| 4 | MCP | **L2** | BLOCKED_BY_EXTERNAL | no | no | High |
| 5 | Memory | ~~L2~~ **L3** | NO_ACTION | no | no | High |
| 6 | SubAgent | ~~L2~~ **L3 scoped** | NO_ACTION (L3 scoped to local delegation contract / fake-or-local boundary / runtime dispatch evidence) | no | no | High |
| 7 | Skill System | ~~L2~~ **L3** | NO_ACTION | no | no | ~~Medium~~ High |
| 8 | Provider / Model Boundary | **L3** | BLOCKED_BY_EXTERNAL | no | no | High |
| 9 | Policy / Approval | ~~L2~~ **L3 scoped** | NO_ACTION (L3 scoped to Tool gate policy path) | no | no | High |
| 10 | Scheduler / Async | **L1** | BLOCKED_BY_DECISION | no | no | High |
| 11 | State / Checkpoint / Resume | ~~L2~~ **L3** | NO_ACTION | no | no | High |
| 12 | Observability / Evidence | **L3** | NO_ACTION | no | no | High |
| 13 | Security / Privacy | **L3** | NO_ACTION | no | no | High |
| 14 | Capability / Config / Registry Boundary | ~~L2~~ **L3 scoped** | NO_ACTION (L3 scoped to local capability registry / config boundary / policy alignment) | no | no | High |
| 15 | Docs / Guardrails | **L3** | NO_ACTION | no | no | High |

> **没有任何模块 blocks mainline**(mainline 已 closed)。最高成熟度为 **L3**;**全仓无 L4**(real provider/MCP/CI/credential 路径被项目规则与外部条件挡住)。当前无 HARDEN_NEXT;T-SKILL-GOLDEN 已完成并关闭。

---

## 5. Module Details

> 字段:Current fact / North Star target / Evidence / Maturity / Gap / Runtime risk now? / Blocks mainline? / Harden next? / Action / Why not now·why now / Trigger / Exit condition / Owner·decision / Confidence。

### 1. Agent Loop — L3 — NO_ACTION
- **Current fact**:`core.chat()` → `_run_main_loop` → `loop.run_main_loop` 是唯一生产主路径;turn 编排、planning/execution、状态推进、turn-end checkpoint save、fallback entry 均在此。
- **North Star target**:§5/§7 Core + Runtime Loop 层;§4.B 单一 Spine 入口。
- **Evidence**:`agent/core.py:763 chat()`、`:772 _run_main_loop`;`agent/loop.py run_main_loop`、`loop_context.py:80 LoopContext`;`tests/golden_e2e/test_golden_simple_conversation.py`。
- **Maturity L3**:主路径生产可用 + golden + integration;非 L4(无 real provider E2E)。
- **Gap**:pre-loop delegation seam 与 dormant scheduler 未统一进全部目标文本(closure: Runtime unity=2)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION。**Why not now**:主路径稳定,gap 属 target-only,无 trigger。
- **Trigger**:新增触碰主循环路由的功能 / 评测要求 Runtime unity 升 3。**Exit**:全 side-effect 统一进 spine 且无第二主路径。
- **Owner/decision**:无。**Confidence**:High。

### 2. RuntimeAction / Dispatcher Spine — L3 — NO_ACTION
- **Current fact**:`RuntimeActionDispatcher.route` 是统一分发入口;`ActionHandlerRegistry` 注册 ~20 handler;7 值 result 状态机(`success/rejected/confirmation_required/not_supported/failed/skipped/policy_blocked`);reserved-field fail-closed;fallback dispatch 由闭集约束防 silent success。
- **North Star target**:§4.B One Runtime Spine、§7 Dispatcher 层、§8 边界、§15 error/fallback。
- **Evidence**:`agent/runtime_integration/dispatcher.py:309`/`:78`、`phase1_hook.py:64 build_phase1_dispatcher`、`schema.py:21 RuntimeActionType`/`:367 RuntimeActionResult`/`VALID_RESULT_STATUSES`、`target_catalog.py`;`tests/runtime_integration/test_runtime_action_contract.py`、fallback dispatch guard tests。Graphify:图内最大枢纽簇(独立 community)。
- **Maturity L3**:生产 routing spine + contract test + golden 走它 + fallback guard;非 L4。
- **Gap**:CM-2 统一 capability contract 未建(归 §14 模块);全局 Agent 状态机未 canonical 化(North Star §4.E target)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION。**Why not now**:spine 已是治理扩展点且测试覆盖;CM-2/全局状态机属其它模块的 blocked 决策,不在本模块擅自做。
- **Trigger**:新 side-effect 类型接入 / CM-2 决策启动。**Exit**:扩展点稳定且 evidence 完整(已基本满足)。
- **Owner/decision**:无(CM-2 见 §14)。**Confidence**:High。

### 3. Tool System — L3 — NO_ACTION
- **Current fact**:TOOL_GATE/TOOL_RESULT/evidence 走 dispatcher;`TOOL_INVOKE` 为 evidence-only;真实 side effect 由 `ToolRuntimeMediator` 在 gate 通过后调 `execute_single_tool`。
- **North Star target**:§9 Tool 单一 registry owner;§7 Side-effect 层。
- **Evidence**:`agent/tool_registry.py`、`agent/tool_executor.py:204 execute_single_tool`、`agent/tool_runtime_mediator.py:172`、`agent/runtime_integration/tool_gate.py:32`/`tool_invoke.py:30`/`tool_result_feedback.py:163`;`tests/golden_e2e/test_golden_tool_success.py`。
- **Maturity L3**:主路径 + golden + 单一执行 owner(无第二执行路径);非 L4。
- **Gap**:统一 capability contract(OD-2/CM-2,归 §14)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION。**Why not now**:执行拓扑已治理且锁测试。
- **Trigger**:新增 tool execution path 风险 / CM-2。**Exit**:维持单 owner + golden。
- **Owner/decision**:无。**Confidence**:High。

### 4. MCP — L2 — BLOCKED_BY_EXTERNAL
- **Current fact**:MCP external flight **代码语义路径已完整**(opt-in 激活、dry_run vs real 区分、`server_allowlist` 生效、destructive tool 执行前 block、discovery→`TOOL_REGISTRY`→model-visible、invocation 走 mediator→GATE/INVOKE/RESULT、dispatcher/decision-frame evidence + `mcp_available` 动态、not-fakeable guards);**默认不启用**;**未做真实外部 server 连接**(REAL-EVIDENCE-007)。
- **North Star target**:§9/§K MCP 外部协议适配,wrap 成 Tool 同 schema 再走 dispatcher,不主导内部架构。
- **Evidence**:`agent/mcp.py:65 FakeMCPClient`、`mcp_models.py:23 MCPServerConfig`、`mcp_bridge.py:146`、`runtime_integration/mcp_tool_orchestrator.py`、`mcp_sanitizer.py`、`mcp_policy.py`;`tests/runtime_integration/test_mcp_l3_real_core_loop.py`、`test_mcp_real_external_flight.py`(docstring 自述 code-path-complete,仅剩真实外部连接);`docs/design/mcp-architecture.md`。
- **Maturity L2**:有最小闭环 + 多项 targeted test + not-fakeable guards,但 real flight 默认 off 且真实外部未验证(保守不记 L3)。
- **Gap**:real external MCP server 连接(L4)= REAL-EVIDENCE-007。
- **Runtime risk now?** no(默认 fake/local)。**Blocks mainline?** no。**Harden next?** no。
- **Action**:**BLOCKED_BY_EXTERNAL**。**Why not now**:AGENTS.md 硬禁真实 MCP endpoint;real flight 需受控外部 server + owner 授权。
- **Trigger**:获授权的受控外部 MCP server + CI。**Exit**:REAL-EVIDENCE-007 real external green。
- **Owner/decision**:owner 授权 real MCP + 外部环境。**Confidence**:High。

### 5. Memory — L2 — BLOCKED_BY_DECISION
- **Current fact**:基础 store/recall/retain/propose 有 runtime 路径与 targeted/L3 测试;consolidation/emergence pipeline **frozen**,`MEMORY_CONSOLIDATION_ENABLED`/`MEMORY_EMERGENCE_ENABLED` **默认 off**;golden 锁定当前 `disabled_by_env` 事实;canonical write owner **未定(MEM-2)**。
- **North Star target**:§10/§4.I governed memory(policy gate + provenance + lifecycle + 单 canonical owner)。
- **Evidence**:`agent/memory_runtime.py:188`、`memory_policy.py:86 DeterministicMemoryPolicy`、`memory_fs_store.py:556`、`memory_consolidation_pipeline.py`、`memory_runtime_hooks.py:33/152`(默认 off);`tests/golden_e2e/test_golden_memory_checkpoint.py`、`fixtures/memory_disabled.json`、`tests/runtime_integration/test_memory_recall_l3.py`/`test_memory_propose_l3.py`/`test_memory_shared_store_l3.py`;`docs/rfc/MEMORY_CANONICAL_RFC.md`。
- **Maturity L3**:explicit_user_request/semantic memory 主路径通过 MemoryOwner runtime integration；create/delete/noop/reject on path；confirmation flow retained；consolidation/emergence frozen；**不标 L4**。agent_suggested/emotion/procedural/update 仍 tracked debt。
- **Gap**:MEM-2 canonical write owner;consolidation 是否解冻为默认 production 路径(OD-4)。
- **Runtime risk now?** no(frozen/env-gated)。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION (L3 achieved)。**Why**:MemoryOwner wired into MemoryRuntime resolve_confirmation path for explicit_user_request retain；create/delete/noop/reject semantics on runtime path；policy/privacy enforced；audit evidence per mutation；consolidation/emergence still frozen。**Not L4**:agent_suggested/emotion/procedural/update semantics/consolidation-default-on still tracked debt。
- **Trigger**:owner 决定解冻 memory 并指定 canonical owner。**Exit**:MEM-2 owner 决策 + single-owner tests。
- **Owner/decision**:**需要 owner(MEM-2 / OD-4)**。**Confidence**:High。

### 6. SubAgent — L2 — TRACKED_DEBT
- **Current fact**:V0 handler registered + contract-verified;`SUBAGENT_V0_ROUTING_ENABLED` truthy 时经 `route_from_runtime_loop` 路由 V0,**默认 off** 走 inline-local / `local_fake` fallback;evidence level 为 subsystem_integration(不伪造 core_loop)。
- **North Star target**:§11/§4.J parent-controlled bounded delegation;目标 V0 production-routed,inline-local 退为 fallback。
- **Evidence**:`agent/subagent_system/request.py:12`、`subagent_inline.py:37`、`runtime_integration/subagent_action.py`、`subagent_routing_flag.py`;`tests/golden_e2e/test_golden_subagent_delegation.py`、fallback dispatch guard;`docs/rfc/SUBAGENT_CANONICAL_RFC.md`。(Graphify NL 查 "SubAgent" 主要命中 decision-spine 设计文档;file/test 证据为准。)
- **Maturity L2**:V0 registered + contract + golden + flag-gated;默认 off,未 default-on,无 real provider E2E。
- **Gap**:default-on flip(FOP-1 pre-flip:provider_mode_allowed 传播)、SA-2 L3 lifecycle、real provider E2E。
- **Runtime risk now?** no。**Blocks mainline?** no(默认 off 稳定)。**Harden next?** no。
- **Action**:NO_ACTION（L3 scoped achieved）。**Why**:38 SubAgent test files, 415 tests passed；`test_golden_subagent_delegation.py` golden locked；V0 registered + contract-verified via `subagent_routing_flag.py`；`PolicyDecision.SUBAGENT_DELEGATION → REQUIRE_APPROVAL` mapped；`build_decision_frame()` subagent branch point tracked。FOP-1 (`provider_mode_allowed` propagation) is tracked pre-flip blocker for default-on, not L3 blocker。**Not L4**:real provider-backed subagent, async multi-agent, MCP delegation。
- **Trigger**:准备 V0 default-on / real-provider dogfood。**Exit**:provider_mode 传播 + real-provider V0 test(flip 前 FOP-1 转 blocker)。
- **Owner/decision**:default-on flip 需 owner(+ external for real provider)。**Confidence**:High。

### 7. Skill System — ~~L2~~ L3 — NO_ACTION
- **Current fact**:当前能力在 `agent/skill_system/`(registry/loader/selector/lifecycle/invocation/retriever/skill_tool);turn-start probe 选 skill 作为 evidence,不直接执行工具、不写 memory;legacy `agent/skills/__init__.py` 是 fail-closed tombstone;README 标"实验性"。`tests/golden_e2e/test_golden_skill_system.py` 已用本地 sample fixture 锁定 discovery / selection metadata / direct dispatcher selection / lifecycle handoff。**L3 core-loop golden**: `tests/golden_e2e/test_golden_skill_l3_core_loop.py` → 2 passed（core.chat() + FakeProvider + skill registry → discovery/selection/evidence, no forbidden side effects）。
- **North Star target**:§9 Skill = `RuntimeActionType.SKILL_SELECT` evidence,渐进能力发现,不作 side effect。
- **Evidence**:`agent/skill_system/registry.py:26 SkillRegistry`、`loader.py:37`、`runtime_integration/skill_action.py`/`skill_lifecycle.py`/`skill_selection_probe.py`;`agent/skills/__init__.py`(tombstone, `__all__=[]`);`tests/golden_e2e/test_golden_skill_system.py`、`tests/golden_e2e/fixtures/skill_system_current_behavior.json`。
- **Maturity ~~L2~~ L3**:registered + lifecycle/selection 有 targeted test + golden + core-loop E2E golden,但仍是实验性本地能力,不产生 side effect,不记 L4。
- **Gap**:本轮 Golden fixture 对等缺口已关闭;实验性状态不是自动 hardening trigger。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION。**Why now**:T-SKILL-GOLDEN 已完成;没有证据或授权支持继续实现/重构 Skill System。
- **Trigger**:closed。**Exit**:golden green,且 `git diff agent/` 为空。
- **Owner/decision**:无。**Confidence**:Medium(skill 为实验性,golden 应锁"当前"而非"目标"行为,避免把实验当成 production-ready)。

### 8. Provider / Model Boundary — L3 — BLOCKED_BY_EXTERNAL
- **Current fact**:provider selection 是 explicit factory branch;config precedence `config/config.yaml → legacy profile/env → fake`;FakeProvider 默认且增长冻结;real provider(OpenAI/Anthropic http+native)代码存在,但 **real provider E2E 未做(W1-D5)**,`claims_real_provider_e2e=false`。
- **North Star target**:§16 Provider 内部 adapter,不主导主路径;§4.K capability interface。
- **Evidence**:`agent/provider/factory.py:18 build_model_provider`、`fake_provider.py:306`、`openai_http.py`、`anthropic_http.py`、`provider/protocol.py`(错误层级)、`simple_config.py`、`provider/config.py`;`tests/test_provider_contract.py`、`test_fake_provider_decision.py`、`test_provider_openai_http.py`。
- **Maturity L3**:boundary/factory/protocol/config precedence 生产可用 + contract test + observability;real-call E2E 属 L4 未达。
- **Gap**:real provider E2E(L4,W1-D5)。
- **Runtime risk now?** no(默认 fake/safe-local)。**Blocks mainline?** no。**Harden next?** no。
- **Action**:**BLOCKED_BY_EXTERNAL**。**Why not now**:AGENTS.md 禁真实 provider call;real E2E 需 credential/CI secret/稳定外部 provider + owner 授权。
- **Trigger**:受控 credential + CI + owner 授权 real provider E2E。**Exit**:real-provider failure/success E2E green。
- **Owner/decision**:owner 授权 + external credential。**Confidence**:High。

### 9. Policy / Approval — L2 — BLOCKED_BY_DECISION
- **Current fact**:**子边界 (a) policy gate**:`ToolGateHandler` 可拒绝 forbidden/not-allowed,`confirmation_required` 进等待态不执行;有 no-execution golden + adversarial stub。**子边界 (b) interactive confirmation flow**:`confirmation/` handlers 已 registered + 有测试。**子边界 (c) OD-7 production/multi-user approval hook**:**deferred**。
- **North Star target**:§13 Policy/Permission/Guardrail/Human-Approval 分列;§4.F 治理次序。
- **Evidence**:`agent/runtime_integration/tool_gate.py:32`、`agent/memory_policy.py:86`;`agent/confirmation/tool.py:34 handle_tool_confirmation`、`plan.py:61`/`:111`、`memory_interaction.py:233`;`tests/golden_e2e/test_golden_policy_evidence.py`、`tests/adversarial/test_minimal_policy_stub.py`、`test_pending_confirmation_dispatch.py`、`test_phase3_tool_confirmation_transitions.py`。
- **Maturity L2(混合,显式标注)**:policy gate ≈ L3(golden + adversarial stub);interactive confirmation ≈ L2(有测试);**OD-7 production approval hook ≈ L1(deferred)**。模块取**保守 L2**,**不得用 policy 成熟度证明 approval production-ready**。
- **Gap**:OD-7 production approval hook;adversarial 仅 minimal stub。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:**BLOCKED_BY_DECISION**。**Why not now**:OD-7 需产品/安全策略决策;当前只锁 policy gate + no-execution evidence。adversarial 扩展虽不需决策,但属可选,不在本轮当 must-fix(避免把非 gap 转成工作)。
- **Trigger**:出现多用户/生产高风险 side-effect approval 需求。**Exit**:OD-7 决策 + approval-hook 实现计划。
- **Owner/decision**:**OD-7 需 owner**。**Confidence**:High。

### 10. Scheduler / Async — L1 — BLOCKED_BY_DECISION
- **Current fact**:`ActionScheduler` 真实(含 `ActionNode`/`ActionRecoveryPolicy`/`ActionPlan`),但 **dormant-by-default / registered-not-routed**;`core.chat(..., action_scheduler=None)` 默认不注入;注入 seam 已接通且可测试(`test_scheduler_main_path` 证明非 dead code)。
- **North Star target**:§5 横切;`Open:` 是否 production-route。
- **Evidence**:`agent/action_scheduler.py:225`、`runtime_integration/action_scheduler_handler.py`、`agent/core.py:697/772`(默认 None);`tests/runtime_integration/test_scheduler_main_path.py`、`test_action_scheduler.py`。
- **Maturity L1**:代码 + 注入 seam 存在但默认关闭、production 未 routed(registered-not-routed ≠ production routed)。
- **Gap**:production routing(无当前消费者)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:**BLOCKED_BY_DECISION**。**Why not now**:接入 production routing 会触碰 runtime routing(closure 明列为 reopen trigger),且无当前消费者;属架构决策。
- **Trigger**:出现真实异步/delayed-action 消费者 + owner 决定 routing。**Exit**:production routing 决策 + 路由 + evidence。
- **Owner/decision**:**需 owner(会触发 repair reopen 评估)**。**Confidence**:High。

### 11. State / Checkpoint / Resume — ~~L2~~ L3 — NO_ACTION
- **Current fact**:local-file / per-run checkpoint schema v1/v2 + best-effort load;golden 锁本地 roundtrip / intra-process restore;turn-end 自动 save。`tests/test_resume_full_flow.py` 已覆盖 accept/decline/pipe-mode/continue-task-after-restore 全流程（9 个 resume flow 测试），`tests/test_checkpoint_roundtrip.py` 覆盖 schema migration/truncation/summary 等（11 个测试），`tests/golden_e2e/test_golden_memory_checkpoint.py` 锁定 local roundtrip golden，`tests/runtime_integration/test_checkpoint_save_resume_l3.py` 通过 `route_from_runtime_loop()` 产生 L3 evidence。**不标 L4**。cross-host/long-task/HITL resume 仍 deferred。
- **North Star target**:§12 checkpoint + resume + failure recovery;§4.H durable execution。
- **Evidence**:`agent/checkpoint.py:370 save_checkpoint`/`load_checkpoint`、`agent/session.py`、`agent/state.py`、`runtime_integration/checkpoint_save.py`/`checkpoint_resume.py`;`tests/golden_e2e/test_golden_memory_checkpoint.py`、`fixtures/checkpoint_local_roundtrip.json`、`tests/runtime_integration/test_checkpoint_save_resume_l3.py`。
- **Maturity L3**:本地 roundtrip golden + resume flow tests + L3 dispatcher evidence。
- **Gap**:SPR-1 cross-host/long-task/HITL resume;全局状态机 canonical 化。
- **Runtime risk now?** no。**Blocks mainline?** no(C1:Agent Loop 可成熟而 cross-host resume deferred)。**Harden next?** no。
- **Action**:NO_ACTION（L3 achieved）。**Why**:本地 roundtrip golden + resume flow 测试 + L3 dispatcher evidence 已存在；cross-host/完整状态机仍 debt 但不阻塞 L3。**Not L4**:cross-host/HITL resume,canonical global state enum。
- **Trigger**:出现 cross-host/long-task/HITL resume 消费者。**Exit**:OD-8 决策 + canonical resume/state 协议。
- **Owner/decision**:SPR-1/OD-8 需 owner(无当前消费者)。**Confidence**:High。

### 12. Observability / Evidence — L3 — NO_ACTION
- **Current fact**:`RuntimeActionEvent` 可 flush 为 evidence trace;evidence 分类有单一逻辑;trace 写 `agent_log.jsonl`;tool result feedback 回流;policy golden 明确 `claims_real_provider_e2e=false`。
- **North Star target**:§14 可重建 decision/tool/memory/fallback/error/cost/latency/result。
- **Evidence**:`agent/runtime_integration/evidence.py:35`/`classify_evidence_level`、`schema.py:394 RuntimeActionEvent`、`agent/evidence_recorder.py`、`agent/runtime_observer.py`、`agent/event_log.py:153`、`runtime_integration/tool_result_feedback.py`;`tests/golden_e2e/test_golden_policy_evidence.py`、`fixtures/evidence_trace.json`、`test_evidence_storage_hygiene.py`/`test_evidence_taxonomy_guard.py`。
- **Maturity L3**:可观测 + golden + 分类 + 存储 hygiene 测试;非 L4。
- **Gap**:cost/latency 作为一等字段(EOE-1 / OD-6)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION(EOE-1 属 OPTIONAL_OR_FUTURE,见 §8)。**Why not now**:evidence/trace 已可重建主要维度;cost 字段无评测消费者。
- **Trigger**:eval harness 将 cost 作一等信号消费。**Exit**:OD-6 决策 + cost 字段集成。
- **Owner/decision**:EOE-1/OD-6(无当前消费者)。**Confidence**:High。

### 13. Security / Privacy — L3 — NO_ACTION
- **Current fact**:secret masking canonical owner = `display_events.py`,`safe_metadata.py` 为其 import-stable projector(delegate);`security.py` 提供 sensitive/protected file 判定;`mcp_sanitizer.py` 零依赖对抗扫描;tool 层有 path safety / shell blacklist / pre-write check;运行时每次 display 都过 masker。
- **North Star target**:§7 「AI 风险与对抗提示治理」层、§13 Guardrail、§4.F。
- **Evidence**:`agent/display_events.py:129 mask_user_visible_secrets`、`agent/runtime_integration/safe_metadata.py:31`、`agent/security.py:25`/`:74`、`agent/mcp_sanitizer.py`、`agent/tools/path_safety.py`/`write.py:58 pre_write_check`/`shell.py:88 check_shell_blacklist`;`tests/test_security_baseline.py`、`test_file_tool_safety_parity.py`、`test_tool_sensitive_path_policy.py`、`test_shell_tool_boundary.py`、`test_config_secret_safety.py`、`runtime_integration/test_safe_metadata_ownership.py`。
- **Maturity L3**:production-active guardrails + 单一 masker owner + 多测试;非 L4(无真实敏感数据/隐私合规外部验证,按项目规则也不做)。
- **Gap**:更广 adversarial injection 语料 / 隐私边界对真实数据的验证(项目规则禁真实数据)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no(已 L3;扩 adversarial 语料属可选,不在本轮当 must-fix,避免把非 gap 转工作)。
- **Action**:NO_ACTION。**Why not now**:安全护栏已 production-active 且有 owner + 测试;扩展是可选增量。
- **Trigger**:出现新 injection/泄露类回归或新 untrusted surface。**Exit**:维持单 owner masker + 安全测试 green。
- **Owner/decision**:无。**Confidence**:High。

### 14. Capability / Config / Registry Boundary — L2 — BLOCKED_BY_DECISION
- **Current fact**:capability status 由 `runtime_decision_frame.build_decision_frame` 表达,`capability_summary` 被 contract 锁定"永不声称 complete";config/provider import boundary 已 inventory(CM-1);状态词汇 declared/registered/routed/dormant/deferred 为**口径**而非统一 enum;**CM-2 unified capability contract 未建(blocked_by_decision)**。
- **North Star target**:§9 统一能力模型、§16 Configuration、OD-2/CM-2。
- **Evidence**:`agent/runtime_decision_frame.py:679 build_decision_frame`、`tests/unit/test_runtime_decision_frame.py:248 test_capability_summary_never_claims_complete`、`agent/tool_registry.py`、多 config owner(`config.py`/`provider/simple_config.py`/`profiles.py`/`mcp_config*.py`);`docs/06-audit/WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md`、`docs/design/unified-project-config-contract.md`、`docs/CAPABILITY_BOUNDARIES.md`;`tests/test_config_authority_boundaries.py`、`test_capability_boundary_contract.py`。
- **Maturity L3 scoped**:`build_decision_frame()` + `capability_summary()` + `StrategyFrame` + `BranchPointStatus`；40+ boundary tests；PolicyDecision 13 action kinds；config precedence chain；capability terms (declared/registered/routed/dormant/deferred) 为口径但非 enum（这是 tracked debt）。
- **Gap**:CM-2 unified capability contract;OD-2(Tool/Skill/MCP 是否共享统一 contract)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION (L3 scoped achieved)。**Why**:**40 existing tests** (`test_runtime_decision_frame.py` 40 passed, `test_capability_boundary_contract.py`, `test_config_authority_boundaries.py`);`build_decision_frame()` 覆盖 20 branch points + capability_summary + readiness；`PolicyDecision`/`PolicyActionKind` 映射 13 action types；config source priority 已实施。**Not L4**:dynamic remote discovery, MCP real sync, broader capability-policy enforcement。
- **Trigger**:出现跨 Tool/Skill/MCP 消费者或 OD-2 决定统一 contract。**Exit**:CM-2 contract 决策 + tests。
- **Owner/decision**:**CM-2/OD-2 需 owner**。**Confidence**:High。

### 15. Docs / Guardrails — L3 — NO_ACTION
- **Current fact**:docs source-of-truth guard + architecture boundary invariants 在 CI 强制;capability boundary contract、safe metadata ownership 等不变量测试;RED-1 已修复 stale docs guard。
- **North Star target**:§18 SoT 层级、§19 测试金字塔。
- **Evidence**:`tests/test_docs_source_of_truth.py`(78 passed)、`tests/test_architecture_boundaries.py`(40 passed)、`tests/test_capability_boundary_contract.py`、`tests/runtime_integration/test_safe_metadata_ownership.py`。
- **Maturity L3**:SoT guard + 架构边界测试 green + CI 强制;非 L4(无全自动 docs↔runtime 一致性生成)。
- **Gap**:docs↔runtime fact 持续 CI 化(North Star §22);North Star 自身 stale current-state 文本(blocked_by_approval)。
- **Runtime risk now?** no。**Blocks mainline?** no。**Harden next?** no。
- **Action**:NO_ACTION。**Why not now**:guard 已 green 且强制;North Star amendment 需 owner 批准。
- **Trigger**:docs guard 转红 / North Star amendment 获批。**Exit**:维持 guard green。
- **Owner/decision**:North Star amendment 需 owner(blocked_by_approval)。**Confidence**:High。

---

## 6. Cross-module risks

**结论:mainline 已串通,问题是模块成熟度不均衡 —— 不是主线没接通。**

- **Mainline wired?** 是。Core→Loop→(Decision/Plan)→Policy gate→**Dispatcher Spine**→Handler→Side effect→Evidence 这条生产主路径已串通,且有 golden(conversation/tool/subagent/memory-checkpoint/policy-evidence)与 architecture boundary 测试守护;无第二条生产主路径。
- **Maturity uneven?** 是,且这是当前主要张力:
  - **L3 成熟簇**(主路径骨架 + 横切守护):Agent Loop、Dispatcher Spine、Tool、Provider Boundary、Observability、Security、Docs。
  - **L2 簇**(能力/横切,可用但受 owner·external 决策牵制):MCP、Memory、SubAgent、Skill、Policy/Approval、State/Checkpoint/Resume、Capability/Config(共 7 个,与 §4 L2 计数一致)。
  - **L1**:Scheduler(dormant)。
- **不均衡来源**几乎全是**有意 deferred/blocked**(MEM-2、OD-7、OD-2/CM-2、W1-D5 real provider、REAL-EVIDENCE-007 real MCP、SPR-1、FOP-1、scheduler routing),不是断裂或回归。
- **原唯一"非 owner/external 阻塞"的成熟度洞已关闭**:Skill System golden 已补齐;没有自动产生新的 HARDEN_NEXT。
- **跨模块一致性风险(需持续守护,非现在修)**:capability status 仍是口径而非统一 enum(CM-2 未建),所以"declared/registered/routed/dormant/deferred"靠文档 + per-surface 测试维持,存在长期 drift 风险 —— 由 Docs/Guardrails(L3)与 Capability/Config(L2)共同看守,触发条件出现前不强行 CM-2。

---

## 7. Recommended Next Hardening Candidates

> T-SKILL-GOLDEN 已完成;当前重新按 bounded-action rule 过滤后无 HARDEN_NEXT。

### Completed — T-SKILL-GOLDEN

- `tests/golden_e2e/test_golden_skill_system.py` + `fixtures/skill_system_current_behavior.json` 已锁定当前实验性本地 dispatcher/lifecycle 行为。
- Skill System 保持 L2;本次完成不表示 production-ready、real provider E2E 或新 side-effect 能力。
- 当前无新的 HARDEN_NEXT;其它 blocked/deferred 项状态不变。
- **L3 Hardening Triage: COMPLETED**（`L3_HARDENING_TRIAGE.zh.md`），8 模块逐模块 triage，recommended next target: **Skill System → L3**（HARDEN_NEXT, 0 blockers）。

### 为什么没有第 2、3 个(透明过滤)

- MCP / Provider:下一步是 real external / real provider E2E → **BLOCKED_BY_EXTERNAL**(credential/外部环境)。
- Memory / Policy-Approval / Capability-Config / Scheduler:下一步是 MEM-2 / OD-7 / CM-2·OD-2 / scheduler routing → **BLOCKED_BY_DECISION**(owner)。
- SubAgent:default-on flip 需 decision + real provider → **TRACKED_DEBT**。
- Checkpoint:SPR-1 无当前消费者 → **TRACKED_DEBT / OPTIONAL_OR_FUTURE**。
- Security / Observability / Docs / Agent Loop / Spine / Tool:已 L3,扩展属可选,不把非 gap 转成 must-fix。

---

## 8. Do Not Do Yet

除非对应 documented trigger 出现,本轮及后续维护**不要**做:

- Window 4 / 重开 Architecture Repair mainline
- CM-2 unified capability contract(blocked_by_decision)
- MEM-2 memory canonical owner / memory unfreeze(blocked_by_decision)
- OD-7 production approval hook(blocked_by_decision)
- real provider E2E(W1-D5,blocked_by_external)
- real external MCP server 连接(REAL-EVIDENCE-007,blocked_by_external)
- action_scheduler production routing(blocked_by_decision,触 reopen)
- SPR-1 cross-host / long-task / HITL resume(deferred / OD-8)
- SubAgent V0 default-on flip(FOP-1 pre-flip blocker)
- EOE-1 cost/latency 一等字段(OD-6)
- 修改 North Star current-state 文本(blocked_by_approval)
- 把 fake provider / fixture evidence 说成 real;把 policy gate 说成 production approval;把 registered-not-routed scheduler 说成 routed;把 minimal memory golden 说成 production memory owner

---

## 9. Reopen / Revisit Triggers

- 准备把某条 default-off capability 改成 default-on(SubAgent V0 / memory / scheduler);
- 获授权的 real provider / real MCP credential + CI;
- 启动 OD-7 / CM-2·OD-2 / MEM-2·OD-4 / OD-6 / OD-8 任一决策;
- full suite、docs/source-of-truth guard、architecture boundary tests 变红;
- 新功能触碰 runtime routing / provider / memory / scheduler / policy / fallback / evidence 边界;
- 评测或真实用户路径证明某 L2/L3 维度必须升级。

无 trigger 时,L2/L1 模块保持 tracked debt / deferred / blocked / optional,不重开 repair、不强行 harden。

---

## 10. Evidence Appendix

- **Taxonomy gate**:`docs/07-module-maturity/AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md`。
- **治理/事实**:`docs/CAPABILITY_BOUNDARIES.md`(Runtime Fact Diff Table)、`docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`(§20 rubric 全 2;full suite 4730/12/26)、`ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md`。
- **目标**:`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`(§4–§24,OD-1..OD-8)。
- **Spine**:`agent/runtime_integration/dispatcher.py`、`phase1_hook.py`、`schema.py`、`target_catalog.py`;`tests/runtime_integration/test_runtime_action_contract.py`。
- **Tool/MCP**:`agent/tool_runtime_mediator.py`、`tool_executor.py`、`agent/mcp*.py`、`runtime_integration/mcp_tool_orchestrator.py`;`tests/golden_e2e/test_golden_tool_success.py`、`tests/runtime_integration/test_mcp_l3_real_core_loop.py`、`test_mcp_real_external_flight.py`。
- **Memory/Checkpoint**:`agent/memory_*.py`、`agent/checkpoint.py`;`tests/golden_e2e/test_golden_memory_checkpoint.py`、`tests/runtime_integration/test_memory_*_l3.py`、`test_checkpoint_save_resume_l3.py`。
- **SubAgent/Skill**:`agent/subagent_system/`、`subagent_inline.py`、`subagent_routing_flag.py`、`agent/skill_system/`;`tests/golden_e2e/test_golden_subagent_delegation.py`。
- **Provider**:`agent/provider/*`;`tests/test_provider_contract.py`、`test_fake_provider_decision.py`。
- **Policy/Security/Evidence**:`agent/runtime_integration/tool_gate.py`、`agent/confirmation/*`、`agent/display_events.py`、`agent/mcp_sanitizer.py`、`agent/security.py`、`agent/runtime_integration/evidence.py`、`safe_metadata.py`;`tests/golden_e2e/test_golden_policy_evidence.py`、`tests/adversarial/test_minimal_policy_stub.py`、`tests/test_security_baseline.py`、`tests/runtime_integration/test_safe_metadata_ownership.py`。
- **Capability/Config/Docs**:`agent/runtime_decision_frame.py`、`agent/tool_registry.py`;`tests/unit/test_runtime_decision_frame.py`、`tests/test_capability_boundary_contract.py`、`test_config_authority_boundaries.py`、`tests/test_docs_source_of_truth.py`、`tests/test_architecture_boundaries.py`。
- **Graphify**:`graphify-out/graph.json`(2026-06-14);query 主题覆盖 §3 所列 15 模块全部主题。
