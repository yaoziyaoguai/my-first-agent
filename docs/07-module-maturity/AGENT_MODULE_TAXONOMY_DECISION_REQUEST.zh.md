# Agent Module Taxonomy Decision Request

**日期**: 2026-06-14
**性质**: taxonomy gate / decision request — 非 maturity audit
**阶段**: Post-Repair Module Maturity 之前的 Module Taxonomy Gate
**Audited runtime HEAD**: `9ab6670`(`docs(audit): freeze architecture repair docs navigation`)
**Scope**: docs-only；不改 production code / tests / North Star；不重开 Architecture Repair；不创建 Window 4；不 push
**Full suite reference**: 4730 passed, 12 skipped, 26 xfailed(引用 closure audit;本轮未重跑 full suite,仅新增 markdown)

---

## 1. Status

**MODULE_TAXONOMY_APPROVED = NO**

- Module Maturity Audit **未开始**,也**未创建**(`AGENT_MODULE_MATURITY_AUDIT.zh.md` 不存在,是有意为之)。
- 本文件只做 taxonomy gate:把 proposed module 分法与**当前代码事实 + North Star 目标 + post-repair open decisions** 对齐,并把需要用户拍板的边界决策**升级给用户**,不擅自重分模块后推进。
- Architecture Repair Mainline 仍 CLOSED(`ACCEPT_WITH_TRACKED_DEBT`);本文件不重开它、不把 North Star gap 当 must-fix。

> 为什么是 NO 而不是"approved with normalization":proposed taxonomy 对**能力/副作用面**(Tool/MCP/Memory/SubAgent/Skill/Provider/Scheduler/Checkpoint/Observability)基本准确、可保留;但它**缺少 3 个有硬证据的关键模块**(Runtime Spine / Security / Capability-Config),另有 **2 处高风险命名/捆绑**(Policy/Approval、Docs/Guardrails)与 **3 处中风险 rename**(Skill / Provider / Scheduler,见 §4)。其中"增删模块"恰好都属于 taxonomy gate 规则中"必须由用户决定、不能由 agent 擅自增删模块"的边界项:增删这些模块是**结构决策**,不是 rename/merge 级别的 normalization,因此必须停在 gate。命名 normalization(rename)可在批准后随 maturity audit 一并处理,不单独阻塞。

---

## 2. Proposed taxonomy(用户提议)

用户倾向"按 agent runtime 真实组成"分模块:

1. Agent Loop
2. Tool System
3. MCP
4. Memory
5. SubAgent
6. Skill
7. Provider / Model
8. Policy / Approval
9. Scheduler / Async
10. State / Checkpoint / Resume
11. Observability / Evidence
12. Docs / Guardrails

---

## 3. 方法与证据来源

- **Graphify**(`graphify-out/graph.json`,2026-06-14 构建)做 source/runtime discovery;query 结果对照真实文件核验。
- **真实文件 / 测试**:`agent/`、`tests/golden_e2e/`、`tests/adversarial/`、`tests/runtime_integration/`。
- **治理文档**:`AGENTS.md`、`docs/README.zh.md`、`docs/06-audit/README.md`、North Star、closure audit、retrospective、`docs/CAPABILITY_BOUNDARIES.md`、`docs/design/*`。
- 证据前缀沿用 North Star:`Fact:`(直接代码/测试)/ `Inference:`(合理推得)/ `Open:`(待决)。

---

## 4. Taxonomy gate findings(逐模块)

字段:Proposed module / Evidence in repo / North Star relevance / Keep·Merge·Split·Rename·Drop / Reason / Risk if kept as-is / Decision needed from user?

| Proposed module | Evidence in repo（Fact 除非标注） | North Star relevance | Keep/Merge/Split/Rename/Drop | Reason | Risk if kept as-is | Decision needed? |
|---|---|---|---|---|---|---|
| **1. Agent Loop** | `agent/core.py:763 chat()`、`agent/loop.py run_main_loop()`、`agent/loop_context.py:80 LoopContext`、`agent/state.py`、`agent/transitions.py` | §5/§7「Core」+「Runtime Loop」两层;§4.B One Runtime Spine | **Keep + Split-out** | Loop 真实存在,但它把 **Core / Loop / Dispatcher** 三层 North Star 明确区分的层压成一个模块 | 把枢纽 Dispatcher 隐藏在 "Loop" 内,未来 agent 看不到 spine 是独立硬化对象 | **YES**(见 D1:Loop vs RuntimeAction/Dispatcher 是否拆) |
| **2. Tool System** | `agent/tool_registry.py`、`agent/tool_executor.py:204 execute_single_tool()`、`agent/tool_runtime_mediator.py:172`、`agent/tools/`、`agent/runtime_integration/tool_gate.py:32`、`tool_invoke.py`、`tool_result_feedback.py`;`tests/golden_e2e/test_golden_tool_success.py` | §9 Tool;§7 Side-effect 层 | **Keep** | 真实、有 golden、边界清晰(mediator 执行 / dispatcher evidence) | 低 | 偏低(见 C2:Tool 与 MCP 是否合并) |
| **3. MCP** | `agent/mcp.py:65 FakeMCPClient`、`agent/mcp_models.py:23 MCPServerConfig`、`mcp_bridge.py:146 run_mcp_bridge()`、`agent/runtime_integration/mcp_tool_orchestrator.py`、`mcp_sanitizer.py`、`mcp_policy.py`、`mcp_config*.py`;`tests/runtime_integration/test_mcp_l3_real_core_loop.py`、`test_mcp_real_external_flight.py`、`tests/test_mcp_bridge.py` | §9 MCP「外部协议适配,不主导内部架构」;§22 MCP gap;OD-2 | **Keep** | MCP 是真实多文件子系统,非 stub、非 absent;有 L3/real-external-flight 测试 | 低(但 sanitizer 属安全面,见 D2) | 偏低 |
| **4. Memory** | `agent/memory_*.py`(数十文件)、`agent/memory_runtime.py:188`、`agent/memory_policy.py:86 DeterministicMemoryPolicy`、`agent/memory_consolidation_pipeline.py`(frozen);`tests/golden_e2e/test_golden_memory_checkpoint.py`、`fixtures/memory_disabled.json`;`docs/rfc/MEMORY_CANONICAL_RFC.md` | §10 Memory 目标;§4.I Governed memory;MEM-2 blocked_by_decision | **Keep** | 真实但 frozen/env-gated;MEM-2 canonical owner 未决 | 低(只要不把 frozen 说成 ready) | 否 |
| **5. SubAgent** | `agent/subagent_system/`(20+ 文件)、`agent/subagent_inline.py:37`、`agent/runtime_integration/subagent_action.py`、`agent/subagent_routing_flag.py`;`tests/golden_e2e/test_golden_subagent_delegation.py`;`docs/rfc/SUBAGENT_CANONICAL_RFC.md` | §11 SubAgent;§4.J Bounded subagents;SA-2 deferred | **Keep** | 真实;V0 registered + flag-gated routing,inline-local fallback | 低 | 否 |
| **6. Skill** | `agent/skill_system/`(registry/loader/selector/lifecycle/invocation/retriever/skill_tool 等);`agent/skills/__init__.py` 是 fail-closed tombstone;`docs/rfc/SKILL_CANONICAL_RFC.md`、`docs/design/skill-system-architecture.md` | §9 Skill「作为 evidence,不直接 side effect」 | **Keep + Rename** | 当前能力在 `agent/skill_system/`;legacy `agent/skills` 必须明确为 tombstone,否则误导 | 中:若不区分 `skill_system` vs `skills` tombstone,会把已废原型当现役 | 偏低(命名 normalization) |
| **7. Provider / Model** | `agent/provider/factory.py:18 build_model_provider()`、`fake_provider.py:306`、`openai_http.py`、`anthropic_http.py`、`openai_native.py`、`provider/protocol.py`(Provider 错误层级)、`simple_config.py`、`provider/config.py`;`tests/test_provider_contract.py`、`test_fake_provider_decision.py` | §16 Provider「内部 adapter,不主导主路径」;W1-D5 real provider E2E blocked_by_external | **Keep + Rename → Provider / Model Boundary** | fake↔real boundary 真实;real provider E2E 仍 blocked | 中:名字若不带 "Boundary",易被读成 real provider 已可用 | 否(rename normalization) |
| **8. Policy / Approval** | Policy: `agent/runtime_integration/tool_gate.py:32 ToolGateHandler`、`agent/memory_policy.py:86`。Approval **两层**要分清:(a) interactive confirmation flow 已 registered + 有测试 —— `agent/confirmation/tool.py:34 handle_tool_confirmation`、`plan.py:61 handle_plan_confirmation`/`:111 handle_step_confirmation`、`agent/memory_interaction.py:233 handle_memory_confirmation_reply`、`confirmation_required` status;`tests/test_pending_confirmation_dispatch.py`、`test_phase3_tool_confirmation_transitions.py`、`test_confirmation_observer_evidence.py`、`test_memory_interactive_confirmation.py`;(b) **OD-7 production/multi-user approval hook 仍 deferred** | §13 Policy/Permission/Guardrail/Human-Approval **明确分列**;§4.F Controlled side effects | **Split(候选)** | Policy gate 已 L2-ish(可拒绝 + no-execution golden + adversarial stub);interactive confirmation flow 已 registered + golden/test-covered(**非 L0**);仅 **OD-7 production approval hook** deferred | **高**:把 (a) interactive confirmation 与 (b) OD-7 hook 混为一谈会两头出错 —— 既可能把已测试的 confirmation 低估成 L0,也可能把 deferred 的 OD-7 高估成 ready | **YES**(见 D3:Policy 与 Approval 是否拆;Approval 的 caution 须收窄到 OD-7) |
| **9. Scheduler / Async** | `agent/action_scheduler.py:225 ActionScheduler`、`ActionNode`/`ActionRecoveryPolicy`/`ActionPlan`、`agent/runtime_integration/action_scheduler_handler.py`;`tests/runtime_integration/test_scheduler_main_path.py`(注入 seam 已接通)、`test_action_scheduler.py` | §22;CR-1;`Open:` 是否 production-route | **Keep + Rename → Scheduler (dormant)** | 真实但 **dormant-by-default / registered-not-routed**;`core.chat(..., action_scheduler=None)` 默认不注入,seam 可测试注入 | 中:"Async" 暗示存在异步 runtime;会被读成 production-routed | 否(命名 normalization,需标 dormant) |
| **10. State / Checkpoint / Resume** | `agent/checkpoint.py:370 save_checkpoint()`/`load_checkpoint`、`agent/session.py`、`agent/state.py`、`agent/runtime_integration/checkpoint_save.py`/`checkpoint_resume.py`/`checkpoint_summary.py`;`tests/golden_e2e/test_golden_memory_checkpoint.py`、`tests/runtime_integration/test_checkpoint_save_resume_l3.py` | §12 State/Checkpoint/Persistence/Recovery;SPR-1 deferred(cross-host resume) | **Keep** | 与 Loop 分离合理(North Star 把 Checkpoint/Resume 列为 turn-end cross-cutting) | 低 | 偏低(见 C1:是否并入 Agent Loop;建议 Keep separate) |
| **11. Observability / Evidence** | `agent/evidence_recorder.py`、`agent/runtime_integration/evidence.py:35 RuntimeActionModuleObserver` + `classify_evidence_level`、`agent/runtime_integration/schema.py:394 RuntimeActionEvent`、`agent/runtime_observer.py`、`agent/event_log.py`、`agent/runtime_trace_*`;`tests/golden_e2e/test_golden_policy_evidence.py`、`fixtures/evidence_trace.json` | §14 Evidence/Trace/Metrics;EOE-1(cost)deferred | **Keep** | 横切、真实、有 golden;`claims_real_provider_e2e=false` | 低 | 否 |
| **12. Docs / Guardrails** | Docs guard: `tests/test_docs_source_of_truth.py`、`tests/test_architecture_boundaries.py`、`tests/test_capability_boundary_contract.py`;"Guardrails" 在 North Star §13 指 secret masking 等运行时护栏 | §18 SoT 层级;§19 测试金字塔;§13 Guardrail | **Split + Rename** | "Docs guard"(SoT 测试,横切)与 "Guardrails"(运行时安全护栏 = Security 面)是**两个不同概念**,被同名捆绑 | **高**:把 docs SoT 测试与 runtime security guardrail 混为一谈,会让安全护栏无独立 owner | **YES**(并入 D2:Security/Privacy 是否独立) |

### 4.1 缺失模块候选(proposed 里没有,但代码 + North Star 有一等证据)

| 缺失模块 | Evidence in repo | North Star relevance | Risk if absent | Decision |
|---|---|---|---|---|
| **A. RuntimeAction / Dispatcher / Spine** | `agent/runtime_integration/dispatcher.py:309 RuntimeActionDispatcher` + `:78 ActionHandlerRegistry`、`phase1_hook.py:64 build_phase1_dispatcher()`(注册 ~20 handler 类型)、`schema.py:21 RuntimeActionType` / `:213 RuntimeActionRequest` / `:367 RuntimeActionResult`、`target_catalog.py`;`tests/runtime_integration/test_runtime_action_contract.py`。(非承重旁证:Graphify 中该枢纽是图内最大连接簇之一) | §4.B One Runtime Spine、§5 spine 方框、§7「Dispatcher」单独一层、§8 边界、§20「Runtime unity」「Extension cost」维度 | **极高**:这是项目架构心脏,被折进 "Agent Loop" 后不可见;两个 rubric 维度(均 2 分)的硬化对象将无独立模块 | **YES**(D1) |
| **B. Security / Privacy(AI 风险与对抗治理)** | secret masking **canonical owner = `agent/display_events.py:129 mask_user_visible_secrets`**;`agent/runtime_integration/safe_metadata.py` 是其 import-stable projector(delegate,不是第二个 masker);`agent/security.py:25 is_sensitive_file()` / `:74 is_protected_source_file()`、`agent/mcp_sanitizer.py`(零依赖对抗扫描)、`agent/tools/path_safety.py`、`tools/write.py:58 pre_write_check()`、`tools/shell.py:88 check_shell_blacklist()`;`tests/test_security_baseline.py`、`test_file_tool_safety_parity.py`、`test_tool_sensitive_path_policy.py`、`test_shell_tool_boundary.py`、`test_config_secret_safety.py` | §7 专设「AI 风险与对抗提示治理」层、§13 Guardrail、§4.F | **高**:proposed 零安全模块;安全/隐私硬化会"无人认领",分散在 Tool/MCP/Policy 各处 | **YES**(D2) |
| **C. Capability / Config / Registry** | `agent/runtime_decision_frame.py:679 build_decision_frame()`(capability status SoT owner)、`tests/unit/test_runtime_decision_frame.py:248 test_capability_summary_never_claims_complete()`、`agent/tool_registry.py`(registry)、`config.py` + `agent/local_config.py` + `agent/provider/simple_config.py`/`config.py`/`profiles.py` + `mcp_config*.py`;`docs/design/runtime-decision-spine.md`、`docs/design/unified-project-config-contract.md`;`tests/test_config_authority_boundaries.py`、`test_capability_boundary_contract.py` | §9 统一能力模型、§16 Configuration、OD-2(Tool/Skill/MCP 统一 Capability Contract)、CM-2 blocked_by_decision、CM-1 config import boundary | **高**:CM-2/OD-2 是公开 open decision;capability-status + config 没有归属模块会孤立该决策 | **YES**(D4:Config/Registry/Capability 是否独立,及拆分粒度) |
| **D. Decision / Plan(model call + parser)** | `agent/planner.py generate_action_plan`、`agent/model_call.py`、`agent/model_output_dispatch.py`/`model_output_resolution.py`、`agent/plan_schema.py:46 Plan` | §5/§7「Decision / Plan」单独一层;§4.C | 中:目前模糊归入 Agent Loop / Provider | 偏低(可作为 Agent Loop 子层注明) |
| **E. CLI / Input / App entrypoint** | `main.py`、`agent/cli/`、`agent/cli_commands.py`、`agent/cli_renderer.py`、`agent/input_backends/`、根目录 `tui/`(独立 TS) | §7「User / Input」层;§24 Non-Goal(无新协议) | 低-中:入口层不在 taxonomy,CLI/TUI 边界工作无归属 | 偏低 |
| **F. Prompt / System instruction** | `agent/prompt_builder.py`、`agent/context_builder.py`、`agent/core_contexts.py` | §4 原则隐含;附录 A | 低 | 偏低(可并入 Agent Loop 或 Decision/Plan) |

---

## 5. Decision set(分层)

> 按 fresh-context reviewer 校准:**真正的结构决策只有 4 个(D1–D4)**——增删模块、reversal cost 高、gate 规则要求用户拍板;另有 **2 个 confirmation(C1–C2)**——作者已倾向 Keep separate,用户若不同意再翻;其余是 **normalization-tier FYI**——批准后随 maturity audit 处理,不阻塞 gate。

### 5.1 必须拍板的结构决策(D1–D4)

**D1 — Agent Loop 与 RuntimeAction / Dispatcher 是否拆为两个模块?**(本 gate **最关键**)
- 证据:`RuntimeActionDispatcher`(dispatcher.py:309)+ `ActionHandlerRegistry`(:78)+ `build_phase1_dispatcher`(phase1_hook.py:64,注册 ~20 handler)+ `RuntimeActionType/Request/Result`(schema.py)是 North Star 的 "One Runtime Spine"(§4.B / §5 spine 方框 / §7 单独一层 / §8 边界)。
- 影响:决定 "Runtime unity / Extension cost"(两个 §20 rubric 维度,均 2 分)的硬化是否有独立模块 owner。折进 "Agent Loop" 会让这两个维度的硬化对象无法作为模块被审计。

**D2 — Security / Privacy 是否独立成模块(并把 "Guardrails" 从 "Docs/Guardrails" 拆出归入它)?**
- 证据:canonical masker `display_events.py:129 mask_user_visible_secrets`(+ projector `safe_metadata.py`)、`security.py`、`mcp_sanitizer.py`、path/shell/file 安全 + 5 个专门安全测试;North Star §7 专设治理层、§13 Guardrail。
- 影响:决定安全/隐私是否有独立 owner,还是继续散在 Tool/MCP/Policy;同时澄清 "Docs guard"(SoT 测试)≠ "runtime guardrail"(安全护栏)。

**D3 — Policy 与 Approval 是否拆为两个模块(或一个模块两子项)?**
- 证据:Policy(`tool_gate`/`memory_policy`)已有可拒绝 + no-execution golden + adversarial stub(L2-ish);Approval **两层**:interactive confirmation flow(`confirmation/` handlers + `test_pending_confirmation_dispatch` 等测试)已 registered + 有测试(**非 L0**),而 **OD-7 production/multi-user approval hook 仍 deferred**;North Star §13 明确分列 Policy/Permission/Guardrail/Human-Approval。
- 影响:决定成熟度评分颗粒度;并确保 Approval 的 deferred caution **只收窄到 OD-7**,不把已测试的 confirmation flow 误判为 L0。

**D4 — Config / Registry / Capability 是否单独成模块?如果是,拆成几个?**(原 D6)
- 证据:见 §4.1-C;`runtime_decision_frame`(capability status owner)、多个 config owner、tool/skill registry、CM-2/OD-2 open decision、两份 design 契约文档。
- 影响:决定 CM-2(unified capability contract)这一公开决策是否有归属模块;三者最异质,**拆分粒度尤其需要用户定**。

### 5.2 Confirmations(作者倾向 Keep separate;不同意再翻,不必当成开放题)

- **C1 — State / Checkpoint / Resume 是否并入 Agent Loop?** → **建议 Keep separate**:North Star 把 Checkpoint/Resume 列为 turn-end cross-cutting(非主路径);`checkpoint.py`/`session.py`/`state.py` 独立。SPR-1 cross-host resume deferred。
- **C2 — Tool System 与 MCP 是否合并?** → **建议 Keep separate**:`CAPABILITY_BOUNDARIES.md` 已把 "Tool execution" 与 "MCP / external config" 列为**两行**;MCP 另有 config/bridge/lifecycle/audit/policy/sanitizer/stdio 独立面。

### 5.3 Normalization-tier FYI(批准后随 maturity audit 处理,不单独阻塞 gate)

- Rename:Provider → "Provider / Model Boundary";Scheduler → "Scheduler (dormant)";Skill 注明 "skill_system(legacy `agent/skills` = tombstone)"。
- 可选子层:**Decision / Plan**(`planner.py`/`model_call.py`/`plan_schema.py`)、**CLI / Input / App entrypoint**(`main.py`/`agent/cli/`/`tui/`)、**Prompt / System instruction**(`prompt_builder.py`)—— North Star §7 有对应层,但属 normalization。

---

## 6. Recommended options(给选项,不替用户选)

> 三套候选,按"改动量从小到大";本文件**不**自行选定。

**Option α — Minimal correction(在现有 12 模块上做最小修补)**
- 拆出 **RuntimeAction/Dispatcher**(D1=拆)。
- 新增 **Security/Privacy**,并把 "Docs/Guardrails" 改名为 "Docs / SoT Guards"(D2)。
- "Policy/Approval" 保持一个模块,但**显式标注 Approval=deferred 子项**(D3=不拆但标注)。
- Provider→"Provider / Model Boundary";Scheduler 标 "(dormant)";Skill 标 "skill_system(legacy agent/skills=tombstone)"。
- 结果:**14 模块**。Config/Capability 作为 cross-cutting 注记,暂不单列(D4=暂不)。
- 适合:想尽快进入 maturity audit,只补最关键的两个洞(Spine + Security)。

**Option β — Runtime-faithful(忠于 North Star 分层)**
- 在 α 基础上:
  - **Policy 与 Approval 拆开**(D3=拆),Approval 单列(interactive confirmation flow 已有测试;仅 OD-7 production hook deferred)。
  - 新增 **Capability / Config / Registry**(D4=单列,合一)。
  - 新增 **Decision / Plan** 子层(D 项)。
- 结果:**~17 模块**,与 North Star §7 分层基本同构。
- 适合:想让 taxonomy 直接对齐 North Star,便于逐层评分与长期硬化。

**Option γ — Capability-surface only(收敛,不含横切)**
- 只保留"会产生副作用的能力面 + spine":Agent Loop、RuntimeAction/Dispatcher、Tool、MCP、Memory、SubAgent、Skill、Provider、Scheduler、Checkpoint。
- 把 Policy/Approval、Security/Privacy、Observability/Evidence、Capability/Config、Docs-guard **显式标为 cross-cutting concerns**(单独一节,不计入"模块"评分,但仍审计)。
- 结果:**10 能力模块 + 5 横切关注**。
- 适合:想用"模块 vs 横切"二分,避免横切项被当成可独立硬化的模块。

---

## 7. What was not done(本轮明确未做)

- **未创建** `AGENT_MODULE_MATURITY_AUDIT.zh.md`(taxonomy 未批准前不得创建最终 maturity audit)。
- 未写任何模块的最终成熟度评分 / L0-L4 结论 / HARDEN_NEXT 推荐。
- 未改 production code、未改 tests、未改 North Star。
- 未重开 Architecture Repair、未创建 Window 4、未继续 GE-1/GE-2/GE-3。
- 未接 real provider、未做 production approval hook(OD-7)、未做 CM-2、未接 action_scheduler routing、未解冻 memory。
- 未修改 frozen 的 docs navigation(`docs/06-audit/README.md`、`docs/README.zh.md` 未触碰);taxonomy 批准后再考虑加入口。
- 未 `git push`;未提交 `graphify-out/*`;未删除任何文件。

---

## 8. 下一步(取决于用户)

1. 用户回答 **D1–D4**(+ 确认 C1/C2),或直接选 Option α / β / γ(可带修改)。
2. 用户答复后,taxonomy 锁定 → `MODULE_TAXONOMY_APPROVED = YES` → 才创建 `AGENT_MODULE_MATURITY_AUDIT.zh.md` 做逐模块成熟度审计。
3. 在用户拍板前,本目录仅含本 decision request,不含 maturity 结论。

---

## 9. Evidence Appendix(关键引用)

- 治理:`AGENTS.md`、`docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`(MAINLINE_CLOSE_READY=YES)、`ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md`、`docs/CAPABILITY_BOUNDARIES.md`(Runtime Fact Diff Table)。
- 目标:`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`(§4.B/§5/§7/§8/§9/§13/§16/§20/§23 OD-2/OD-7)。
- Spine:`agent/runtime_integration/dispatcher.py`、`phase1_hook.py`、`schema.py`、`target_catalog.py`;`tests/runtime_integration/test_runtime_action_contract.py`。
- Security:`agent/security.py`、`agent/display_events.py`、`agent/mcp_sanitizer.py`、`agent/runtime_integration/safe_metadata.py`;`tests/test_security_baseline.py`、`test_file_tool_safety_parity.py`。
- Capability/Config:`agent/runtime_decision_frame.py`、`docs/design/runtime-decision-spine.md`、`docs/design/unified-project-config-contract.md`;`tests/unit/test_runtime_decision_frame.py`。
- Graphify:`graphify-out/graph.json`(2026-06-14);query 覆盖 dispatcher/security/capability/policy/MCP/provider/scheduler/skill/checkpoint/loop。
