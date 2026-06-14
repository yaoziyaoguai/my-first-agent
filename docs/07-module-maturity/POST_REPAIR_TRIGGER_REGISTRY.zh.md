# Post-Repair Trigger Registry

**日期**: 2026-06-14
**性质**: docs-only trigger registry / activation playbook — 非 active queue,非 repair
**Registry baseline HEAD**: `70354a2`(module maturity audit commit 之后；本次 activation audit 基于当前工作树另行核验)
**来源**: `AGENT_MODULE_MATURITY_AUDIT.zh.md`、`ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`、`CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md`(§10 债务表 / §11 OD 寄存器 / §9 综合分类)、`docs/CAPABILITY_BOUNDARIES.md`、North Star。

---

## 1. Status

- **Architecture Repair Mainline: CLOSED**(`ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED`)。
- **Module Maturity Audit: COMPLETED**(15 模块,Option γ)。
- **本文件不是 active queue**:它是 trigger 寄存器 + 激活 playbook,只回答"什么条件下才允许开工、怎么开工、谁拍板、要什么证据"。
- **核心原则:No trigger, no work.**(没有触发条件,不开工;触发达成后,才允许进入 scoped hardening / experiment / repair。)
- North Star 仍是目标模型,不是待办清单;North Star gap ≠ 自动任务。
- T-SKILL-GOLDEN 关闭只新增 golden test / fixture 与本目录状态文档;**不改 production code / North Star**,**不开 Window 4**,**不重开 Architecture Repair**。
- **T-PROVIDER-E2E activation audit: COMPLETED**。审计入口为 `PROVIDER_API_KEY_ACTIVATION_AUDIT.zh.md`;trigger 本身仍为 `BLOCKED_BY_EXTERNAL`,未运行真实 API,未产生 L4 evidence。
- **T-PROVIDER-E2E secret safety hardening: COMPLETED**。`api_key_env` indirection 已实现；`config/config.local.yaml` 已支持（git 忽略，本地优先，可含 inline key）；real/fake guard 已修正；response body leak 已修复；real smoke preview 已脱敏。
- **Pre-work full suite baseline**:**4730 passed, 12 skipped, 26 xfailed**。
- **T-SKILL-GOLDEN fresh full suite**:**4731 passed, 12 skipped, 26 xfailed**。

---

## 2. Method

- **Trigger = gap activation condition, not automatic task.** 一个 gap 存在,不等于现在要修;只有对应 trigger 达成,才进入 scoped work。
- 每个 trigger 用统一字段刻画(见 §4):含义、为何未激活、激活路径、所需决策/外部资源/证据、达成后允许做什么、达成前禁止做什么、退出判据、owner、忽视风险、提前强行风险、引用证据。
- Category 取自固定枚举:`HARDEN_NEXT_READY` / `BLOCKED_BY_DECISION` / `BLOCKED_BY_EXTERNAL` / `BLOCKED_BY_EVIDENCE` / `TRACKED_DEBT` / `OPTIONAL_OR_FUTURE` / `DROP_OR_NOOP` / `COMPLETED`。不使用 maybe / later / TBD。
- 所有 claim 以真实 file:line / test / closure audit / roadmap 交叉核验;Graphify(`graphify-out/graph.json`,2026-06-14)用于本 session 各模块 runtime fact discovery,不作单独依据。

---

## 3. Trigger Summary

| Trigger ID | Module | Category | Active now? | Next action | Owner needed | External dep |
|---|---|---|---|---|---|---|
| **T-SKILL-GOLDEN** | Skill System | COMPLETED | no(closed) | none | no | no |
| T-PROVIDER-E2E (W1-D5) | Provider/Model Boundary | BLOCKED_BY_EXTERNAL | no(audit completed) | 先做 secret/endpoint/output safety hardening；再等 credential/CI 授权运行 | yes(授权) | **yes** |
| T-MCP-REAL (REAL-EVIDENCE-007) | MCP | BLOCKED_BY_EXTERNAL | no | 等受控外部 server | yes(授权) | **yes** |
| T-MEM2 (MEM-2) | Memory | BLOCKED_BY_DECISION | no | owner 决策 spike | **yes** | no |
| T-OD7 (OD-7 / W2-D2) | Policy / Approval | BLOCKED_BY_DECISION | no | owner/产品决策 | **yes** | no |
| T-CM2 (OD-2) | Capability/Config/Registry | BLOCKED_BY_DECISION | no | owner 决策 + 出现跨消费者 | **yes** | no |
| T-SCHED-ROUTE (W3-D3) | Scheduler / Async | BLOCKED_BY_DECISION | no | owner 决策 + 消费者 | **yes** | no |
| T-SUBAGENT-FLIP (FOP-1) | SubAgent | TRACKED_DEBT(pre-flip blocker) | no | flip 决策 + 修 FOP-1 | **yes** | yes(real provider) |
| T-SA2 (SA-2) | SubAgent | BLOCKED_BY_EVIDENCE | no | design spike | yes(架构) | no |
| T-SPR1 (SPR-1 / OD-8) | State/Checkpoint/Resume | OPTIONAL_OR_FUTURE | no | 等真实需求(任一消费者)+ OD-8 | yes(OD-8,次要) | no |
| T-EOE1 (EOE-1 / OD-6) | Observability/Evidence | OPTIONAL_OR_FUTURE | no | OD-6 决策 + 评测消费者 | yes | no |
| T-W2D4 (L1 dead-code) | SubAgent | TRACKED_DEBT | no | 独立 cleanup 窗口 | no | no |
| T-NS-CLEANUP | Docs/Guardrails(North Star) | OPTIONAL_OR_FUTURE(blocked_by_approval) | no | owner 批准 amendment | **yes** | no |

> **当前无 active trigger。T-SKILL-GOLDEN 已完成并关闭。** 其余全部 No,且每条都有明确 trigger / owner / external 标注。已 `completed` / `completed-docs` 的历史项(RS-1 / CM-1 / SA-1 / MEM-1 / SPA-1 / SPA-2 / CR-1..4 / GE-1..3)不进本寄存器(无 trigger,已闭)。
>
> 编号说明:**OD-4**(consolidation 默认 production)有意折叠进 **T-MEM2**(与 canonical-owner OD-9 同属一次 memory 决策,不会独立 fire),不单列。roadmap §9 的 **W-Low 债务簇**(W1-D1/D2/D3/D6/D7、W2-D1、W3-D1/D2)均为已治理 Low debt,owner/trigger/exit 由 roadmap §9.3–9.5 管辖,**有意不提升为本寄存器行**(避免把 Low debt 扩成 active surface)。

---

## 4. Trigger Details

### T-SKILL-GOLDEN — Skill System golden
- **Related module**: Skill System
- **Current status**: L2;`agent/skill_system/` 真实(registry/loader/selector/lifecycle),`agent/skills/__init__.py` 是 tombstone;Skill golden 已在 `tests/golden_e2e/test_golden_skill_system.py` + `fixtures/skill_system_current_behavior.json` 锁定当前实验事实。
- **Category**: `COMPLETED`
- **What it means**: 已用本地 sample fixture 锁定当前 discovery / selection metadata / direct dispatcher selection / lifecycle handoff,明确不是 real `core.chat` E2E 或 production-ready 证明。
- **Activation state**: **completed / closed** —— 不再是 active hardening trigger,也不打开其它 trigger。
- **Completed path**: inventory → RED fixture absence → golden fixture Green → targeted verification → maturity docs 最小更新;全程未改 `agent/`。
- **Required decisions**: 无。
- **Required external resources**: 无。
- **Required evidence**: 已满足;当前 Skill discovery/dispatcher/lifecycle 本地行为由 fixture 可重复复现。
- **Allowed work after fires**: 已完成;无后续实现工作自动获得授权。
- **Forbidden during work**(执行硬约束):**禁止重构 Skill System;禁止把实验行为写成 production-ready;禁止解冻/升级 skill 为 side-effect;golden 只新增于 `tests/golden_e2e/` + fixtures**。
- **Validation / exit**: 已满足;Skill golden green + maturity doc 更新,且 `git diff agent/` 为空。golden 明确锁"当前实验事实",不声明真实 core-loop E2E。
- **Owner needed**: 无(无需 owner 决策)。
- **Risk if ignored**: Skill 行为静默漂移,与其它能力面 golden 覆盖不对等。
- **Risk if forced early**: 低;唯一风险是把实验行为锁成"目标",必须用措辞规避。
- **Reference evidence**: `agent/skill_system/registry.py:26`、`agent/skills/__init__.py`(tombstone)、`tests/golden_e2e/test_golden_skill_system.py`、`tests/golden_e2e/fixtures/skill_system_current_behavior.json`;maturity audit §7。

### T-PROVIDER-E2E — real provider E2E(W1-D5)
- **Related module**: Provider / Model Boundary(L3)
- **Activation audit**: **COMPLETED**(2026-06-14),见 `PROVIDER_API_KEY_ACTIVATION_AUDIT.zh.md`。这只完成现状/安全路径审计,不关闭 trigger。
- **Current status**: provider factory/protocol/config precedence 生产可用 + contract test;real provider(OpenAI/Anthropic)代码存在但**无真实 E2E**;`claims_real_provider_e2e=false`;FakeProvider 默认且冻结。
- **Category**: `BLOCKED_BY_EXTERNAL`
- **What it means**: 用真实 provider credential 跑端到端 success/failure/fallback,验证 real-call 路径(L3→L4)。
- **Why not active now**: AGENTS.md 硬禁未授权真实 provider call;无本次受控 credential / CI secret / 稳定外部 provider evidence。现有 `tests/test_provider_real_smoke.py` 是机械上可 opt-in 的 adapter smoke,但缺安全 secret indirection、HTTPS + exact-host allowlist、provider response/exception 脱敏和 tracked fail-closed marker/guard;完整 success/failure/fallback 与 real adversarial evidence 也未建立。本地 `config/config.yaml` 还存在 tracked + skip-worktree 的疑似非占位 key 风险,需先 rotate/remove。(GE-1 Phase B golden infra 已就绪 —— roadmap L950。)
- **Activation path**(参考):
  1. 明确 provider profile(哪个 provider/model);
  2. rotate 并移除 tracked local config 中的真实 key 风险;
  3. 先实现 secret indirection、endpoint allowlist、response/exception 脱敏、禁止 provider-content print、tracked marker + fail-closed guard;
  4. 修正 real/fake guard,避免 `FakeProvider` 满足 real-provider gate;
  5. 准备 credential / secret(CI secret store 或受控 process env);
  6. 先运行单个 minimal adapter smoke;
  7. 独立补 success/failure/fallback tests,再做 bounded adversarial suite,且不影响 default suite;
  8. 通过后**再单独**考虑 default-on(不在本 trigger 内)。
- **Required decisions**: owner 授权 real provider E2E。
- **Required external resources**: real provider credential + CI secret + 稳定外部 provider。
- **Required evidence**: opt-in real-provider E2E green(success + failure + fallback)。
- **Allowed work after fires**: opt-in real-provider test + 受控本地/CI 运行。
- **Forbidden work before fires**: 不接真实 provider、不把 fake evidence 当 real、不改默认 suite 为 real、不 default-on flip。
- **Validation / exit**: real-provider failure/success E2E green(W1-D5 exit)。
- **Owner needed**: 项目 owner(授权)。
- **Risk if ignored**: 低(默认 fake/safe-local);real path 长期未端到端验证。
- **Risk if forced early**: 泄露 secret、违反安全边界、把 fake 当 real 的 overclaim。
- **Reference evidence**: `PROVIDER_API_KEY_ACTIVATION_AUDIT.zh.md`;roadmap §10 W1-D5(L767)、§9(L965);`agent/provider/factory.py`;`tests/test_provider_real_smoke.py`;`tests/runtime_integration/test_memory_anchor_real.py`;`tests/golden_e2e/fixtures/evidence_trace.json`(`claims_real_provider_e2e=false`)。

### T-MCP-REAL — real external MCP(REAL-EVIDENCE-007)
- **Related module**: MCP(L2)
- **Current status**: MCP external flight **代码路径已完整**(opt-in、allowlist、destructive block、discovery→TOOL_REGISTRY→model-visible、mediator→GATE/INVOKE/RESULT、not-fakeable guards),**默认 `is_mcp_active()=False`**;**未做真实外部 server 连接**。
- **Category**: `BLOCKED_BY_EXTERNAL`
- **What it means**: 连接真实外部 MCP server,验证真实 discovery/invocation/失败行为(L2→L3/L4)。
- **Why not active now**: AGENTS.md 硬禁真实 MCP endpoint/连接/可达性检查;无受控外部 server。
- **Activation path**(参考):
  1. 提供受控/授权的外部 MCP server + allowlist 条目;
  2. 准备 server 凭证/连接配置(受控环境,不写真实 home config);
  3. opt-in 激活(保持默认 off);
  4. 验证 discovery / invocation / external failure / timeout / sanitization;
  5. opt-in test 不影响默认 suite;
  6. 通过后再评估是否纳入常规。
- **Required decisions**: owner 授权 real MCP。
- **Required external resources**: 受控外部 MCP server + 连接凭证 + 网络。
- **Required evidence**: REAL-EVIDENCE-007 real external flight green。
- **Allowed work after fires**: opt-in real-external MCP test(受控环境)。
- **Forbidden work before fires**: 不连真实 endpoint、不做可达性检查、不写真实 home config、不把 fixture 当 real-external。
- **Validation / exit**: REAL-EVIDENCE-007 green;`is_capability_complete()` 对 mcp.discover/invoke 转 true。
- **Owner needed**: 项目 owner(授权 + 外部环境)。
- **Risk if ignored**: 低(默认 fake/local);真实外部行为未验证。
- **Risk if forced early**: 违反安全边界、连真实外部服务、泄露配置。
- **Reference evidence**: `tests/runtime_integration/test_mcp_real_external_flight.py`(docstring + `is_mcp_active` 默认 False);`docs/design/mcp-architecture.md`;maturity audit §5.4。

### T-MEM2 — Memory canonical write owner / unfreeze(MEM-2)
- **Related module**: Memory(L2)
- **Current status**: 职责拆分(`memory.py` 压缩/抽取;`memory_store`/`memory_fs_store` 持久化;`memory_runtime_hooks`+`memory_policy` 触发治理);consolidation/emergence **frozen + 默认 off**;canonical write owner **未定**。
- **Category**: `BLOCKED_BY_DECISION`
- **What it means**: 选定唯一 canonical memory write owner,并(如决定)解冻 consolidation 为生产路径。
- **Why not active now**: owner 未决(North Star §4.D/§10.1 标 `Open:`);擅自选会破坏 SoT 单 owner 不变量、触碰 memory 路径(reopen 风险)。
- **Activation path**(参考):
  1. 决定 memory owner;
  2. 决定 memory schema;
  3. 决定 create/update/delete/noop 语义;
  4. 决定 privacy boundary;
  5. 决定 persistence backend;
  6. 决定 replay / audit evidence;
  7. **再写实现计划**(先 decision spike,后实现)。
- **Required decisions**: MEM-2 canonical owner = **OD-9**(roadmap §11 本地编号);OD-4(consolidation 是否默认 production,次要)。
- **Required external resources**: 无。
- **Required evidence**: decision spike 文档 + 决策记录;选定后 single-owner test。
- **Allowed work after fires**: ownership decision spike → (裁决后)single-owner 实现 + test-lock。
- **Forbidden work before fires**: 不解冻 memory、不选 owner、不移动持久化实现、不动 provenance 格式、不接真实 LLM consolidation。
- **Validation / exit**: canonical owner 被裁决并 test-locked。
- **Owner needed**: 项目 owner(决策)。
- **Risk if ignored**: SoT 维度无法到 3;memory 长期 frozen。
- **Risk if forced early**: 双 owner / SoT 漂移、解冻引入未治理写入、扩 scope 重开 repair。
- **Reference evidence**: roadmap MEM-2(L360-376)、§9 表 L963;`agent/memory_runtime_hooks.py:33/152`(默认 off);North Star §4.D/§10。

### T-OD7 — production approval hook(OD-7 / W2-D2)
- **Related module**: Policy / Approval(L2)
- **Current status**: policy gate(`ToolGateHandler` 可拒绝 + no-execution golden + adversarial stub)≈L3;interactive confirmation(`confirmation/` handlers + `awaiting_user_input` 状态 + 测试)≈L2 **已存在**;**production/multi-user approval hook deferred**。
- **Category**: `BLOCKED_BY_DECISION`
- **What it means**: 为高风险 side effect 引入生产强制 approval hook(独立于 debug 路径)。
- **Why not active now**: 需产品/安全策略决策;当前 `confirmation_required`→AWAITING_USER 与 debug 路径已够覆盖现状;**policy 成熟 ≠ approval production-ready**。
- **Activation path**(参考):
  1. 决定哪些 action 需要 approval;
  2. 决定 confirmation UX;
  3. 决定 timeout / reject / cancel 行为;
  4. 决定 audit trail;
  5. 决定 bypass policy;
  6. **再做 scoped implementation**。
- **Required decisions**: OD-7 裁决(产品/安全 owner)。
- **Required external resources**: 无(可能涉及多用户语境)。
- **Required evidence**: OD-7 决策 + approval-hook 实现计划。
- **Allowed work after fires**: scoped approval-hook 实现 + 审计 trail + tests。
- **Forbidden work before fires**: 不把 policy gate 当 production approval、不在 dispatcher 接强制 hook、不绕过现有 `confirmation_required` 语义。
- **Validation / exit**: OD-7 裁决后独立窗口实现并 test-lock。
- **Owner needed**: 项目 owner(产品/安全)。
- **Risk if ignored**: 多用户/生产高风险 side effect 无强制人审。
- **Risk if forced early**: 过度设计无消费者的 approval UX;把 deferred 当 ready 的 overclaim。
- **Reference evidence**: roadmap SPA-2 注(L484-485)、§10 W2-D2(L781)、§11 OD-7(L872)、§9(L964);`agent/transitions.py`(`TOOL_CONFIRMATION_REQUIRED`/`awaiting_user_input`)。

### T-CM2 — Unified Capability Contract(OD-2)
- **Related module**: Capability / Config / Registry Boundary(L2)
- **Current status**: Tool/Skill/MCP 各自 schema;`idempotency_key`/`cost_hint`/`latency_hint` 仅 North Star 文字,**无 .py 实现**;capability status 是口径(declared/registered/routed/dormant/deferred)非统一 enum;CM-1 config import boundary 已 inventory。
- **Category**: `BLOCKED_BY_DECISION`
- **What it means**: 让 Tool/MCP/Skill/SubAgent/Provider 共享统一 Capability Contract / status 枚举。
- **Why not active now**: **无当前跨三者消费者**;现在建设属投机抽象(North Star 原则 A 红线)。
- **Activation path**(参考):
  1. 明确 capability 状态枚举;
  2. 明确 declared / registered / routed / dormant / deferred 语义;
  3. 明确 Tool/MCP/Skill/SubAgent/Provider 共享合同;
  4. 迁移策略;
  5. backwards compatibility;
  6. test guard。
- **Required decisions**: OD-2 裁决。
- **Required external resources**: 无。
- **Required evidence**: 出现真实跨 Tool/Skill/MCP 消费者;OD-2 决策 + tests。
- **Allowed work after fires**: 统一 contract 设计 + 迁移 + test guard。
- **Forbidden work before fires**: 不为"像某框架"引入统一 contract、不加无消费者 schema 字段、不藏在 Provider/Tool 下。
- **Validation / exit**: OD-2 被裁决并落地 contract + tests。
- **Owner needed**: 项目 owner(决策)。
- **Risk if ignored**: capability status 长期靠文档+per-surface 测试维持,存在 drift 风险。
- **Risk if forced early**: 投机抽象、扩 scope、违反原则 A。
- **Reference evidence**: roadmap CM-2(L176-192)、§11 OD-2(L867)、§9(L962);`agent/runtime_decision_frame.py`;`docs/design/unified-project-config-contract.md`。

### T-SCHED-ROUTE — Scheduler production routing(W3-D3)
- **Related module**: Scheduler / Async(L1)
- **Current status**: `ActionScheduler` 真实但 **dormant-by-default / registered-not-routed**;`core.chat(action_scheduler=None)` 默认不注入;注入 seam 已接通且可测试。
- **Category**: `BLOCKED_BY_DECISION`
- **What it means**: 把 action_scheduler 接入 production routing(L1→更高)。
- **Why not active now**: 无当前消费者;接入会触碰 runtime routing(closure 明列为 reopen trigger);属架构决策。
- **Activation path**(参考):
  1. owner 决定接入 + 明确多 turn planning / delayed-action 消费者;
  2. 独立 plan 证明收益 / 接线 / rollback / tests;
  3. 不在其它项里顺手接入。
- **Required decisions**: owner 决策(可能触发 repair reopen 评估)。
- **Required external resources**: 无。
- **Required evidence**: 真实异步/delayed-action 消费者 或 multi-turn planning benchmark 需求。
- **Allowed work after fires**: 独立 scheduler routing plan + 接线 + evidence + rollback + tests。
- **Forbidden work before fires**: 不接 production routing、不把 registered-not-routed 当 routed、不在 CM-1/其它项顺手接。
- **Validation / exit**: production routing 决策 + 路由 + evidence + rollback。
- **Owner needed**: action_scheduler 维护者 + 项目 owner。
- **Risk if ignored**: 低;scheduler 长期 dormant。
- **Risk if forced early**: 触碰 runtime routing 重开 repair;无消费者的过度接线。
- **Reference evidence**: roadmap CR-1(L492-525)、§10 W3-D3(L793);`agent/core.py:697/772`(默认 None);`agent/action_scheduler.py:225`。

### T-SUBAGENT-FLIP — SubAgent V0 default-on flip / FOP-1 pre-flip blocker
- **Related module**: SubAgent(L2)
- **Current status**: V0 registered + contract + golden,flag `SUBAGENT_V0_ROUTING_ENABLED` **默认 off**,inline-local fallback;**FOP-1**:flag-on + real provider 时 V0 因 `provider_mode_allowed` 未传播(默认 `fake_only`)返回 `policy_blocked`。
- **Category**: `TRACKED_DEBT`(pre-flip blocker;default-off 非当前风险,**P1-on-flip**)
- **What it means**: 把 V0 routing 默认开启(inline-local 退为 fallback),前提先修 FOP-1。
- **Why not active now**: flag 默认 off,无当前生产风险;翻默认是独立决策 + 需 real provider(external)。
- **Activation path**(参考):
  1. owner 决定准备 default-on flip;
  2. 修 FOP-1:在 core.py V0 payload 传播 `provider_mode_allowed`(对齐 `v0_contract.py:357` 默认 `fake_only`);
  3. 加 real-provider V0 路径测试(依赖 T-PROVIDER-E2E 的 credential);
  4. flag-on 全 suite green(success/error/fallback/rollback);
  5. 再翻默认值。
- **Required decisions**: default-on flip 决策。
- **Required external resources**: real provider credential(仅 flip **验证阶段**需要,经 T-PROVIDER-E2E);**FOP-1 修复本身 code-internal,无 external/owner**(roadmap L985)。
- **Required evidence**: `provider_mode_allowed` 传播修复 + real-provider V0 test green。
- **Allowed work after fires**: 修 FOP-1 + real-provider V0 test + (裁决后)翻默认。
- **Forbidden work before fires**: 不翻默认值、不删 inline-local fallback、不伪造 provenance、不在 default-off 下当紧急 bug。
- **Validation / exit**: `provider_mode_allowed` 正确传播 + real-provider V0 路径测试 green;flip 后 full suite green。
- **Owner needed**: `core.py` delegation 入口维护者 + 项目 owner。
- **Risk if ignored**: 低(默认 off);flip 时若未修则 real provider V0 直接 `policy_blocked`。
- **Risk if forced early**: 在无 real provider 验证下翻默认 → 生产 V0 失败;扩 scope。
- **Reference evidence**: roadmap §9.6 FOP-1(L807-814)、§9(L966);`agent/subagent_system/v0_contract.py:322/357`;`agent/subagent_routing_flag.py`。

### T-SA2 — SubAgent lifecycle integration / L3 evidence design spike(SA-2)
- **Related module**: SubAgent(L2)
- **Current status**: SA-1 落地后 live V0 真实 evidence label = `subsystem_integration`(pre-loop seam 不可伪造 `core_loop`);是否搬迁 delegation 进 `run_main_loop` 取 L3 标签**未论证**。
- **Category**: `BLOCKED_BY_EVIDENCE`(`documented_pending`)
- **What it means**: 出 design spike 文档,比较 L3 相对 `subsystem_integration` 的可观察收益与搬迁代价。
- **Why not active now**: 收益未证明;"无充分收益,不实施"是合法结论;为评分搬迁会破坏 single Runtime Spine。
- **Activation path**(参考):
  1. 以 SA-1 真实 `subsystem_integration` 为 baseline;
  2. 写收益表(含可拒绝项)+ 风险/影响面清单;
  3. 明确结论("进入 active 实施" 或 "保持 `subsystem_integration` 为 final");
  4. 仅当收益与合法性两点都满足才考虑实施(独立 plan)。
- **Required decisions**: 架构 owner(spike 结论)。
- **Required external resources**: 无。
- **Required evidence**: spike 文档 (a)收益表 (b)风险清单 (c)明确结论。
- **Allowed work after fires**: design spike 文档(doc-only);裁决后才独立实施 plan。
- **Forbidden work before fires**: 不为 gate→3 搬迁 lifecycle、不伪造 `source=core_loop`、不引入第二 runtime、不在 spike 期改 SA-1 验收。
- **Validation / exit**: spike 完成且结论明确(可为"不实施")。
- **Owner needed**: 架构 owner(待指派)。
- **Risk if ignored**: 下游可能为分数擅自搬迁 lifecycle,破坏 North Star B/§15。
- **Risk if forced early**: 为分数搬迁 → 第二 runtime / 伪造 provenance。
- **Reference evidence**: roadmap SA-2(L290-328);`agent/runtime_integration/evidence.py`(`classify_evidence_level`)。

### T-SPR1 — 完整全局状态机 / 跨主机 resume(SPR-1 / OD-8)
- **Related module**: State / Checkpoint / Resume(L2)
- **Current status**: dispatcher 7 值 result 已实现;local-file checkpoint save/load/resume **已接线**(`checkpoint.py:370/466`,`main.py:731`),intra-process resume 为隐含默认;**无跨主机/跨进程 resume,无统一 global state-machine enum**。
- **Category**: `OPTIONAL_OR_FUTURE`(主 gate 为"无 cross-host/long-task 消费者"= deferred,与 roadmap §9 L960 / closure audit 一致;OD-8 为出现需求后的次要决策 gate)
- **What it means**: 定义完整 global state machine enum + 跨主机/跨进程 resume 协议(L2→更高)。
- **Why not active now**: 无 long-task/HITL/cross-host 消费者;OD-8 未裁决;当前 intra-process checkpoint 已够(模块本体属 TRACKED_DEBT、可接受)。
- **Activation path**(参考):
  1. 出现真实长任务/HITL/cross-host 需求;
  2. OD-8 决定 checkpoint 兼容/resume 协议(replay / cross-host / stable identity);
  3. 决定 canonical global state enum;
  4. 独立 plan 实施 + tests。
- **Required decisions**: OD-8 裁决 + canonical enum。
- **Required external resources**: 无(可能涉及多主机部署语境)。
- **Required evidence**: 真实长任务/HITL/cross-host 需求出现(**任一消费者即可触发,不需三者齐备**)。
- **Allowed work after fires**: resume 协议设计 + global state enum + 跨进程/主机实现 + tests。
- **Forbidden work before fires**: 不实施完整状态机 enum、不建跨主机 resume、不擅自裁决 canonical enum。
- **Validation / exit**: 出现真实需求后重新进入 active 并落地协议 + tests。
- **Owner needed**: 项目 owner(OD-8)。
- **Risk if ignored**: 低;长任务/跨主机场景未支持(当前非目标)。
- **Risk if forced early**: 为无消费者的协议过度设计;扩 scope。
- **Reference evidence**: roadmap SPR-1(L385-403)、§11 OD-8(L873)、§9(L960);`agent/checkpoint.py:370/466`;`main.py:731`;North Star §12。

### T-EOE1 — Cost / Latency 进入 observability(EOE-1 / OD-6)
- **Related module**: Observability / Evidence(L3)
- **Current status**: `latency_ms` 已捕获(`dispatcher.py:425`);evidence/trace 可重建主要维度;**cost 非一等字段**。
- **Category**: `OPTIONAL_OR_FUTURE`
- **What it means**: 把 cost(可能含 latency)升为 observability 必填一等字段。
- **Why not active now**: 无评测 harness 消费 cost;现在强制属投机。
- **Activation path**(参考):
  1. 出现评测 harness 消费 cost;
  2. OD-6 决定 cost/latency 是否必填(缺则拒写);
  3. scoped 加字段 + evidence 集成 + tests。
- **Required decisions**: OD-6 裁决。
- **Required external resources**: 无。
- **Required evidence**: 评测 harness 将 cost 作一等信号消费。
- **Allowed work after fires**: cost 字段集成 + evidence schema 更新 + tests。
- **Forbidden work before fires**: 不强制 cost 字段、不为无消费者加 schema。
- **Validation / exit**: OD-6 裁决 + cost 字段集成。
- **Owner needed**: 项目 owner(OD-6)。
- **Risk if ignored**: 低;cost 维度暂缺。
- **Risk if forced early**: 投机字段、无消费者维护负担。
- **Reference evidence**: roadmap EOE-1(L409-425)、§11 OD-6(L871)、§9(L961);`agent/runtime_integration/dispatcher.py:425`(latency_ms)。

### T-W2D4 — L1 attempt dead-code removal
- **Related module**: SubAgent
- **Current status**: L1 attempt 是 dead code(`SUBAGENT_DELEGATE_L1` 未注册,dispatcher get_handler→None,branch 不可达);SA-1 明列保留,不在其 exit 范围。
- **Category**: `TRACKED_DEBT`
- **What it means**: 删除不可达的 L1 attempt 分支。
- **Why not active now**: 删除需独立 cleanup 窗口,且与 V0 default-on 相关;当前保留无害。
- **Activation path**(参考):
  1. V0 default-on(T-SUBAGENT-FLIP)后;
  2. 独立 cleanup 窗口评估 + 删除 + tests 更新。
- **Required decisions**: 无(随 V0 default-on cleanup)。
- **Required external resources**: 无。
- **Required evidence**: dispatcher 无 L1 handler(已核验)。
- **Allowed work after fires**: 删 L1 dead branch + 更新 tests。
- **Forbidden work before fires**: 不在 V0 default-on 前删(SA-1 R8 保留)、不顺手在其它项删。
- **Validation / exit**: L1 dead branch 删除 + tests green。
- **Owner needed**: SubAgent routing 维护者。
- **Risk if ignored**: 极低;少量 dead code。
- **Risk if forced early**: 低,但破坏 SA-1 "保留 L1 attempt" 验收边界。
- **Reference evidence**: roadmap §10 W2-D4(L783)、§9 表 L969;SA-1 Non-goals(L250-251)。

### T-NS-CLEANUP — North Star stale current-state cleanup
- **Related module**: Docs / Guardrails(North Star 文档)
- **Current status**: North Star 是 target/principle authority,部分 current-state 文本 stale;closure audit 明列为 `tracked debt / blocked_by_approval`。
- **Category**: `OPTIONAL_OR_FUTURE`(`blocked_by_approval`)
- **What it means**: 在不改 target/principle 的前提下,刷新 North Star 的 current-state 注记。
- **Why not active now**: North Star 修改需 owner 明确批准(本轮及多轮明令禁止改 North Star)。
- **Activation path**(参考):
  1. owner 明确批准 North Star amendment 在 scope 内;
  2. 仅刷新 current-state 注记,不改 target/principle;
  3. 同步 §20 full-Done 阈值与 §21 closure gate 措辞。
- **Required decisions**: owner 批准 amendment。
- **Required external resources**: 无。
- **Required evidence**: owner 授权记录。
- **Allowed work after fires**: 受限的 current-state 文本刷新(target/principle 不动)。
- **Forbidden work before fires**: 不改 North Star(任何部分),不把现状当目标。
- **Validation / exit**: amendment 获批并刷新 current-state,target/principle 不变。
- **Owner needed**: 项目 owner(批准)。
- **Risk if ignored**: 低;North Star current-state 文本与最新 runtime fact 有差(已由 capability docs / closure audit 兜底)。
- **Risk if forced early**: 把现状写成目标、污染 target authority。
- **Reference evidence**: closure audit Remaining Debt(North Star threshold/current-state cleanup);North Star 头部修改约束。

---

## 5. What Can Be Done Now

**当前无 active trigger。T-SKILL-GOLDEN 已完成并关闭。**

- 关闭证据:`tests/golden_e2e/test_golden_skill_system.py` + `fixtures/skill_system_current_behavior.json`。
- 其它 trigger 状态不变,没有因本次 golden 自动激活任何后续工作。

---

## 6. What Must Not Be Done Yet

除非对应 trigger 达成,**禁止**:

- real provider E2E(T-PROVIDER-E2E 未达)
- real external MCP 连接(T-MCP-REAL 未达)
- MEM-2 / memory unfreeze / 选 canonical owner(T-MEM2 未达)
- OD-7 production approval hook(T-OD7 未达)
- CM-2 unified capability contract(T-CM2 未达)
- scheduler production routing(T-SCHED-ROUTE 未达)
- SubAgent V0 default-on flip(T-SUBAGENT-FLIP 未达)
- cross-host / 完整状态机 resume(T-SPR1 未达)
- EOE-1 cost 一等字段(T-EOE1 未达)
- L1 dead-code 删除(T-W2D4 未达)
- 改 North Star(T-NS-CLEANUP 未达)
- **任何情况下**:Window 4 / 重开 Architecture Repair / 把 fake 当 real / 把 policy gate 当 production approval / 把 minimal memory golden 当 production memory owner / 把 registered-not-routed scheduler 当 routed。

---

## 7. Activation Workflow

任一 trigger 达成后,统一走:

1. **Confirm trigger evidence** —— 确认该 trigger 的 Required decisions / external / evidence 全部满足(对照本寄存器对应条目)。
2. **Write scoped plan** —— 只针对该 trigger 的最小 scope(可用 `ce-plan`),明确 Non-goals 与 rollback。
3. **Review with architecture + adversarial reviewer** —— fresh-context 双 reviewer;有 Blocker/High 必须先修。
4. **Implement only scoped change** —— 不顺手做其它 trigger;不扩 scope。
5. **Verify targeted + full suite as needed** —— targeted green;本轮已跑 fresh full suite(`4731 passed, 12 skipped, 26 xfailed`)。
6. **Update maturity audit / trigger registry** —— 更新对应模块 L 级与本寄存器条目状态。
7. **Do not reopen Architecture Repair unless explicitly required** —— 只有 trigger 明确要求(如触碰 runtime routing/provider/memory/scheduler/policy/fallback/evidence 边界)且 owner 批准时,才评估是否需要新的 documented repair mainline;否则保持 closed。

---

## 8. Evidence Appendix

- **本阶段产物**:`docs/07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md`、`AGENT_MODULE_TAXONOMY_DECISION_REQUEST.zh.md`。
- **Roadmap(trigger/exit/owner 权威)**:`docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md` §10 债务表(W1-D5/W2-D2/W2-D4/W3-D3/FOP-1)、§11 OD 寄存器(OD-2/5/6/7/8)、§9 综合分类、各 Theme(CM-2/SA-2/MEM-2/SPR-1/EOE-1/SPA-2/CR-1)。
- **Closure/事实**:`ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`(Remaining Debt 表)、`ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md`、`docs/CAPABILITY_BOUNDARIES.md`。
- **目标**:`docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md`(§9/§10/§12/§13/§14/§23 OD-1..OD-8)。
- **源码核验**:`agent/subagent_system/v0_contract.py:322/357`(FOP-1)、`agent/transitions.py`(OD-7 confirmation/awaiting_user)、`tests/runtime_integration/test_mcp_real_external_flight.py`(REAL-EVIDENCE-007)、`agent/core.py:697/772`(scheduler 默认 None)、`agent/memory_runtime_hooks.py:33/152`(memory 默认 off)、`tests/golden_e2e/test_golden_skill_system.py`。
- **Graphify**:`graphify-out/graph.json`(2026-06-14),本 session 跨全部 trigger 模块做 runtime fact discovery。
