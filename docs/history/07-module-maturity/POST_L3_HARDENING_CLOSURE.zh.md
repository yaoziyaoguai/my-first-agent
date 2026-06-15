# Post-Repair L3 Hardening Closure

**日期**: 2026-06-15
**性质**: docs-only closure — 关闭 Post-Repair L3 hardening pass，记录最终状态
**Architecture Repair Mainline**: CLOSED（`ACCEPT_WITH_TRACKED_DEBT`）

---

## 1. Closure Verdict

**Post-Repair L3 hardening pass 关闭。**

- **14/15 模块已 scoped L3**
- **Scheduler / Async: L2, BLOCKED_BY_DECISION / no consumer**
- **This is not 15/15 L3**
- **This is not L4**
- **Architecture Repair remains closed**
- **No Window 4**

---

## 2. Final Module State Table (15 Modules)

| # | Module | Level | Status | Key remaining debt |
|---|--------|-------|--------|-------------------|
| 1 | Agent Loop | **L3** | NO_ACTION | — |
| 2 | RuntimeAction / Dispatcher Spine | **L3** | NO_ACTION | CM-2 统一 capability contract 未建(归 §14) |
| 3 | Tool System | **L3** | NO_ACTION | — |
| 4 | MCP | **L3 scoped** | NO_ACTION | Real external BLOCKED_BY_EXTERNAL (T-MCP-REAL) |
| 5 | Memory | **L3** | NO_ACTION | forget/SESSION_ONLY/update/agent_suggested/emotion/procedural/consolidation: tracked debt |
| 6 | SubAgent | **L3 scoped** | NO_ACTION | FOP-1 tracked pre-flip; real-provider V0 evidence; SA-2 design spike |
| 7 | Skill System | **L3** | NO_ACTION | 实验性，不是 production-ready |
| 8 | Provider / Model Boundary | **L3** | BLOCKED_BY_EXTERNAL | Real provider E2E (L4, W1-D5) |
| 9 | Policy / Approval | **L3 scoped** | NO_ACTION | OD-7 production approval hook deferred |
| 10 | Scheduler / Async | **L2** | BLOCKED_BY_DECISION | No consumer; registered-not-routed; T-SCHED-ROUTE |
| 11 | State / Checkpoint / Resume | **L3** | NO_ACTION | SPR-1 cross-host/HITL resume: OPTIONAL_OR_FUTURE |
| 12 | Observability / Evidence | **L3** | NO_ACTION | EOE-1 cost/latency 一等字段: OPTIONAL_OR_FUTURE |
| 13 | Security / Privacy | **L3** | NO_ACTION | — |
| 14 | Capability / Config / Registry Boundary | **L3 scoped** | NO_ACTION | CM-2 unified contract; OD-2; capability status 非统一 enum |
| 15 | Docs / Guardrails | **L3** | NO_ACTION | North Star stale current-state: blocked_by_approval |

---

## 3. 14/15 Scoped L3 — Module Checklist

| # | Module | L3 evidence | L3 scope boundary | Remaining debt beyond L3 |
|---|--------|------------|-------------------|--------------------------|
| 1 | Agent Loop | `core.chat()` → `run_main_loop` golden | Full L3 | — |
| 2 | RuntimeAction / Dispatcher Spine | 统一分发入口 + 7 值 result + fallback guard | Full L3 | CM-2 |
| 3 | Tool System | TOOL_GATE/TOOL_RESULT + mediator 单 owner | Full L3 | — |
| 4 | MCP | ~192 tests + FakeMCPClient + dry_run + policy/sanitizer | Scoped: local fake/dry_run boundary | Real external (T-MCP-REAL) |
| 5 | Memory | MemoryOwner runtime integration + create/noop/reject | Scoped: explicit_user_request retain | forget/SESSION_ONLY/update/consolidation/emergence |
| 6 | SubAgent | 415 tests + golden delegation + PolicyDecision mapped | Scoped: local delegation / fake-or-local boundary | FOP-1, SA-2, real-provider V0 |
| 7 | Skill System | Core-loop golden E2E (2 passed) | Full L3 (实验性) | — |
| 8 | Provider / Model Boundary | Factory/protocol/config + contract test + real smoke | Full L3 | Real provider E2E (L4) |
| 9 | Policy / Approval | Policy gate golden + adversarial stub + PolicyDecision | Scoped: Tool gate policy path | OD-7 production approval hook |
| 11 | State / Checkpoint / Resume | 47 tests + local roundtrip golden + L3 dispatcher evidence | Scoped: local roundtrip | SPR-1 cross-host/HITL |
| 12 | Observability / Evidence | RuntimeActionEvent + classification + golden | Full L3 | EOE-1 cost/latency |
| 13 | Security / Privacy | Secret masking owner + mcp_sanitizer + path/shell safety | Full L3 | — |
| 14 | Capability / Config / Registry | build_decision_frame() + 40+ boundary tests + PolicyDecision 13 actions | Scoped: local registry/config boundary | CM-2, OD-2 |
| 15 | Docs / Guardrails | SoT guard + 架构边界 invariants CI | Full L3 | North Star amendment blocked_by_approval |

---

## 4. Scheduler / Async — L2 Blocker Detail

**Scheduler / Async 是唯一 below-L3 模块。不可为 15/15 造 consumer。**

- **Current level**: L2（从 L1 升级）
- **Blocker**: BLOCKED_BY_DECISION (T-SCHED-ROUTE)
- **Why L2 not L3**: `core.chat(..., action_scheduler=None)` 默认不注入；production 无消费者；registered-not-routed ≠ production-routed；L3 需要 production-routed evidence
- **What IS achieved at L2**: 95+ scheduler tests pass; handler registered in dispatcher; injection seam verified; 6 no-consumer boundary tests pass; PolicyDecision SCHEDULER_ASYNC→REQUIRE_APPROVAL; RuntimeDecisionFrame reflects scheduler state
- **What prevents L3**: No active consumer; owner decision for production routing (可能触发 repair reopen)
- **What must NOT be done**: 不为 15/15 造 fake consumer; 不接 production routing; 不把 registered-not-routed 当 routed

---

## 5. Honest Claims

- ✅ 14/15 modules scoped L3
- ❌ Not 15/15 L3 — Scheduler / Async is L2
- ❌ Not L4 — no module has real external/CI/credential evidence
- ✅ Architecture Repair remains closed
- ✅ No Window 4
- ✅ No code changes in this pass (docs-only coherence fix)

---

## 6. Cross-Module Docs Coherence Pass — Changes Made

本次 coherence pass 修复了以下 stale/不一致 docs:

| File | Stale item | Fix |
|------|-----------|-----|
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §5 headers for modules 4/5/6/9/14 still showing L2 | Updated to ~~L2~~ L3/L3 scoped |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §5.6 SubAgent body "Maturity L2" contradicted header | Updated to "Maturity ~~L2~~ L3 scoped" with scoped boundary explanation |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §5.9 Policy body "Maturity L2(混合)" + "模块取保守L2" contradicted header | Updated to "Maturity ~~L2~~ L3 scoped(混合)" + "L3 scoped to Tool gate policy path" |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §6 cross-module risks: "L2 簇(共 7 个)" + "L1: Scheduler" | Updated to "14/15 scoped L3" + "L2: Scheduler" |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §6 "Capability/Config(L2)" | Updated to "Capability/Config(L3 scoped)" |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §7 "Skill 保持 L2" + "recommended next: Skill → L3" | Updated to "Skill 已升 L3" + "Triage CLOSED" |
| `AGENT_MODULE_MATURITY_AUDIT.zh.md` | §9 "L2/L1 模块" | Updated to "L2 模块(Scheduler)" |
| `POST_REPAIR_TRIGGER_REGISTRY.zh.md` | T-MCP-REAL/T-OD7/T-CM2/T-SUBAGENT-FLIP/T-SA2/T-SPR1 module levels stale (L2) | Updated all to current levels |
| `POST_REPAIR_TRIGGER_REGISTRY.zh.md` | §3 summary table module levels stale | Updated summary table with current levels |
| `POST_REPAIR_TRIGGER_REGISTRY.zh.md` | "L3 Hardening Triage: COMPLETED ... recommended next: Skill → L3" | Updated to "CLOSED ... 14/15 scoped L3" |
| `L3_HARDENING_TRIAGE.zh.md` | §4 Modules Below L3: Memory/SubAgent/Skill/Policy/State/Capability still showing L2 | Updated to current levels |
| `L3_HARDENING_TRIAGE.zh.md` | §5 Triage Table: SubAgent/Policy/Capability Lvl column still showing L2, with stale HARDEN_NEXT recommendations | Updated to ~L2~ L3 scoped, changed active recommendations to COMPLETED/BLOCKED |
| `L3_HARDENING_TRIAGE.zh.md` | §6 execution order stale | Updated with completion status per item |
| `L3_HARDENING_TRIAGE.zh.md` | §7 Scheduler "L1", MCP "L2" | Updated to L2 and L3 scoped |
| `L3_HARDENING_TRIAGE.zh.md` | §9 missing "Not claiming 15/15 L3" | Added |
| `README.md` | "L1 dormant scheduler" | Updated to "L2 BLOCKED_BY_DECISION" |
| `README.md` | Missing 14/15 L3 statement | Added |
| `README.md` | File table: L3 triage status "recommended next: State or SubAgent FOP-1" | Updated to "triage CLOSED; 14/15 scoped L3" |
| `README.md` | File table: Policy status "Policy remains L2" | Updated to "Policy L3 scoped; OD-7 still deferred" |
| `README.md` | Orphaned table row at end | Added proper table context |

---

## 7. What Must NOT Be Done

- 不为 15/15 造 Scheduler consumer
- 不声称 15/15 L3
- 不声称 Scheduler L3
- 不声称任何模块 L4
- 不重开 Architecture Repair
- 不创建 Window 4
- 不改 North Star
- 不改 agent/ 源码
- 不改 tests/

---

## 8. Remaining Work Requires Owner Decision

唯一 below-L3 模块 Scheduler / Async 的推进条件:

1. **T-SCHED-ROUTE 激活**: 需要 owner 决策 + 真实消费者需求
2. **Production routing decision**: 可能触发 Architecture Repair reopen 评估
3. **Consumer identification**: 当前无 delayed-action / async task 消费者

所有其它 blocked/deferred 项（MEM-2 剩余债务/OD-7/CM-2/T-MCP-REAL 等）均按 trigger registry 管理，无 trigger 不动。

---

## 9. Evidence Appendix

- **Maturity audit**: `docs/07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md` §4
- **Trigger registry**: `docs/07-module-maturity/POST_REPAIR_TRIGGER_REGISTRY.zh.md`
- **L3 triage**: `docs/07-module-maturity/L3_HARDENING_TRIAGE.zh.md`
- **MCP/Scheduler audit**: `docs/07-module-maturity/MCP_SCHEDULER_FEASIBILITY_AUDIT.zh.md`
- **Architecture Repair closure**: `docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md`
- **Capability boundaries**: `docs/CAPABILITY_BOUNDARIES.md`
