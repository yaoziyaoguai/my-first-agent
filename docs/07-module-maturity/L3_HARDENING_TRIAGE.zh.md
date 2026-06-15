# L3 Hardening Triage

**日期**: 2026-06-14
**性质**: docs-only triage，不实现模块，不解冻任何 trigger
**Architecture Repair Mainline**: CLOSED
**Reference baseline**: `AGENT_MODULE_MATURITY_AUDIT.zh.md` §4 Module Maturity Summary

## 1. Status

- Architecture Repair Mainline: **CLOSED**（`ACCEPT_WITH_TRACKED_DEBT`）。
- Goal: 把核心模块逐个推进到至少 L3。
- 本文是 triage，不是 active implementation queue，不是 Window 4。
- 本轮不改 `agent/` 源码，不改 `tests/`，不实现任何模块。
- North Star 仍是目标模型，不是待办清单；North Star gap ≠ automatic task。

## 2. L3 Working Definition

**L3 = 主路径可用 + 明确 owner/boundary + guardrails + integration/golden/evidence。**

L3 不等于 L4。具体判据：

| Criterion | L3 requires | L4 requires (not L3) |
|-----------|-------------|----------------------|
| 主路径 production-routed | ✓ | ✓ |
| Owner/boundary 明确 | ✓ | ✓ |
| Guardrails（fail-closed, policy gate） | ✓ | ✓ |
| Integration/golden/evidence | ✓ | ✓ |
| Observability | ✓ | ✓ |
| CI credential / real external 环境 | ✗ | ✓ |
| Default-on ready | ✗ | ✓ |
| Full adversarial suite | ✗ | ✓ |
| Cross-session/cross-host | ✗ | ✓ |

不夸大：fake local-only 路径不算 L3；minimal golden 不算 production owner；registered-not-routed 不算 routed。

## 3. Current L3 Modules

从 maturity audit §4 确认，以下模块已 L3，不再作为本次 triage 目标：

| # | Module | Level | Evidence |
|---|--------|-------|----------|
| 1 | Agent Loop | L3 | `core.chat()` → `run_main_loop` 唯一主路径；golden conversation/tool/subagent |
| 2 | RuntimeAction / Dispatcher Spine | L3 | 统一分发入口；20+ handler；7 值 result 状态机；fallback guard |
| 3 | Tool System | L3 | TOOL_GATE/TOOL_RESULT/evidence；mediator 单执行 owner |
| 8 | Provider / Model Boundary | L3 | Factory/protocol/config precedence；contract test；**real smoke passed (not L4)** |
| 12 | Observability / Evidence | L3 | RuntimeActionEvent + evidence classification + golden |
| 13 | Security / Privacy | L3 | Secret masking canonical owner；mcp_sanitizer；path/shell safety |
| 15 | Docs / Guardrails | L3 | SoT guard + 架构边界 invariants CI 强制 |

> **Provider 是特殊 case**：L3 满足（boundary/factory/protocol/config + contract test + observability），real smoke evidence 已有但不是 L4。Provider 不纳入本轮 triage（已 L3）。

## 4. Modules Below L3

| # | Module | Level | Blocker type | Why not L3 |
|---|--------|-------|-------------|------------|
| 4 | MCP | ~~L2~~ **L3 scoped** | ~~EXTERNAL_DEPENDENCY~~ **DONE** (local fake/dry_run contract boundary) | Code path complete; real external remains BLOCKED_BY_EXTERNAL |
| 5 | Memory | L2 | OWNER_DECISION | Canonical owner 未定；noop/update 缺；consolidation frozen |
| 6 | SubAgent | L2 | TRACKED_DEBT | V0 default-off；FOP-1 pre-flip blocker；无 real-provider V0 evidence |
| 7 | Skill System | L2 | NONE（可直接硬升） | 有 local sample golden；缺 production core-loop golden |
| 9 | Policy / Approval | L2 | OWNER_DECISION | OD-7 production approval hook deferred；仅 policy gate + minimal adversarial stub |
| 10 | Scheduler / Async | L1 | OWNER_DECISION | Dormant-by-default / registered-not-routed；无消费者 |
| 11 | State / Checkpoint / Resume | L2 | TRACKED_DEBT | 本地 roundtrip golden；缺完整 resume 协议/canonical 状态机 |
| 14 | Capability / Config / Registry | L2 | OWNER_DECISION | CM-2 unified contract 未建；capability status 为口径非 enum |

## 5. Triage Table

| Module | Lvl | Target | Gap to L3 | Blocker | Can harden now? | Recommended Action | Next Artifact | Do-not-do-yet | Exit Criteria | Confidence |
|--------|-----|--------|-----------|---------|-----------------|-------------------|---------------|---------------|---------------|------------|
| **MCP** | ~~L2~~ **L3 scoped** | L3 | ~~real external server~~ local fake/dry_run contract boundary evidence → **PASSED** (~192 tests, 198 collected) | ~~EXTERNAL_DEPENDENCY~~ **DONE** | — | ~~WAIT_FOR_EXTERNAL~~ **COMPLETED** | — | 不连真实 endpoint; 不标 L4 | REAL-EVIDENCE-007 green for real external | High |
| **Memory** | ~~L2~~ **L3** | L3 | explicit_user_request retain-create-noop-reject runtime path → **PASSED** | ~~OWNER_DECISION~~ **DONE** | — | ~~BLOCKED_RECORD_DEBT~~ **COMPLETED** | ~~OD-9~~ **Evidence achieved** | 不解冻 consolidation/emergence；forget/SESSION_ONLY/update tracked debt | MemoryOwner runtime integration green ✓ | High |
| **SubAgent** | L2 | L3 | FOP-1 fix; real-provider V0 smoke; L3 lifecycle evidence | TRACKED_DEBT (FOP-1 internal, real provider external) | △ (FOP-1 code-internal) | HARDEN_NEXT (FOP-1 only) | FOP-1 fix + V0 provider_mode test | 不翻默认值; 不删除 inline-local fallback | provider_mode_allowed 传播 + V0 real smoke | High |
| **Skill** | ~~L2~~ **L3** | L3 | production core-loop golden → **PASSED** (`test_golden_skill_l3_core_loop.py`, 2 passed) | ~~NONE~~ **DONE** | — | ~~HARDEN_NEXT~~ **COMPLETED** | ~~Core-loop golden E2E~~ **Evidence achieved** | 不升 production-ready; 不把实验行为当目标 | Core-loop golden green ✓ | Medium → **High** |
| **Policy** | L2 | L2→L3 | OD-7 production approval hook deferred；adversarial 仅 minimal stub | OWNER_DECISION (design spike completed) | ✗ (spike done; implementation needs scoped hardening) | DESIGN_SPIKE → **DONE**; next: HARDENING (PolicyDecision golden) | OD-7 decision spike (`POLICY_APPROVAL_OD7_DECISION_SPIKE.zh.md`) | 不把 policy gate 当 production approval | OD-7 裁决 + design spike ✓; next: PolicyDecision golden test | High |
| **Scheduler** | L1 | — | production routing 无消费者 | OWNER_DECISION | ✗ | OPTIONAL_SKIP | — | 不接入 production routing | 出现 real consumer + owner decision | High |
| **State** | ~~L2~~ **L3** | L3 | local resume golden + flow tests + L3 dispatcher evidence → **PASSED** (47 tests) | ~~TRACKED_DEBT~~ **DONE** | — | ~~HARDEN_NEXT~~ **COMPLETED** | ~~Local resume golden~~ **Evidence achieved** | 不做 cross-host/cross-session | Local resume golden green ✓ (47 passed) | High |
| **Capability** | L2 | L2→? | CM-2 unified contract; capability status enum | OWNER_DECISION | ✗ | DESIGN_SPIKE | CM-2/OD-2 decision spike | 不为无消费者建 contract | OD-2 裁决 | High |

### Blocker Types Legend

- **NONE** — 无阻塞，可以直接推进
- **OWNER_DECISION** — 需要项目 owner 明确决策
- **EXTERNAL_DEPENDENCY** — 需要外部 credential/server/环境
- **EVIDENCE_GAP** — 测试/golden 不足
- **DESIGN_SPIKE_NEEDED** — 需要先做 design spike
- **TRACKED_DEBT** — 已知技术债，可独立窗口修复
- **OPTIONAL_OR_FUTURE** — 不纳入当前 triage

### Recommended Action Legend

- **HARDEN_NEXT** — 可直接进入 scoped hardening
- **DESIGN_SPIKE** — 需要先产 decision spike
- **BLOCKED_RECORD_DEBT** — 记录 debt，等待 owner/external
- **WAIT_FOR_EXTERNAL** — 需要外部资源
- **WAIT_FOR_OWNER** — 需要 owner 决策
- **OPTIONAL_SKIP** — 跳过，不纳入当前轮

## 6. Recommended Next Hardening Target

### **Skill System → L3** (recommended as NEXT)

**Why this one:**
1. **Zero blocker** — 无 owner/external/credential 依赖
2. **Small scope** — 只需补一个 `core.chat()` 驱动的 golden E2E test（当前 golden 是 local sample fixture）
3. **High value** — Skill 是 agent 运行的当前活跃能力面
4. **Validation path clear** — `tests/golden_e2e/test_golden_skill_system.py` 已有 framework，只需扩展到 core-loop
5. **No architecture risk** — 不改 Skill runtime，只加 test

**Expected scope:**
- 1 test file: `tests/golden_e2e/test_golden_skill_core_loop.py`
- 1-2 fixture files under `tests/golden_e2e/fixtures/`
- 最小 docs 更新
- No `agent/` changes

**Expected risk:** Low — golden test only, fake provider, deterministic

**Expected validation:**
```bash
.venv/bin/python -m pytest -q tests/golden_e2e/test_golden_skill_core_loop.py
# → all green
```

### Why not the others now

| Module | Why not now |
|--------|-------------|
| **Memory** | 需要 OD-9 owner decision（MemoryOwner）；consolidation unfreeze 需要 OD-4。不能在没有 owner 审批下实现 MemoryOwner。 |
| **SubAgent FOP-1** | FOP-1 修复是 code-internal（不需要 decision），可以作为第二刀。但需要 real provider evidence（已有 smoke），且 skill golden 先做更稳妥。 |
| **Policy** | OD-7 是完整 production approval hook，需产品/安全策略决策。Design spike 可以先出，但不应是第一个 code harden 目标。 |
| **MCP** | 需要 external MCP server，被 AGENTS.md 硬禁。不能在本轮做。 |
| **Scheduler** | 无消费者；dormant。不纳入 L3 triage。 |
| **State** | 本地 resume golden 可以做，但价值低于 Skill golden（Skill 是正在使用的活跃能力面）。 |
| **Capability** | CM-2 需要 OD-2 决策 + 跨 surface 消费者。Design spike 可以先出，但 implementation 需等 owner。 |

### Recommended execution order

```
1. Skill System → L3 (HARDEN_NEXT, 0 blockers)
2. SubAgent FOP-1 fix (HARDEN_NEXT, code-internal)
3. State local resume golden (HARDEN_NEXT)
4. Policy OD-7 design spike (DESIGN_SPIKE)
5. Capability CM-2 design spike (DESIGN_SPIKE)
6. Memory OD-9/OD-4 (BLOCKED — wait for owner)
7. MCP real external (BLOCKED — wait for external)
8. Scheduler (OPTIONAL_SKIP)
```

## 7. Modules Not Ready Yet

以下模块经过 triage 判定为**不纳入当前 L3 hardening priority**：

| Module | Level | Reason for deferral |
|--------|-------|---------------------|
| Scheduler / Async | L1 | Dormant, no consumer, would require architecture routing decision that reopens repair |
| MCP | L2 | Needs external server credential + connection (AGENTS.md hard blocks) |
| Memory (consolidation/emergence) | L2 | Frozen/env-gated; needs OD-4 + safety hardening before unfreeze |
| Procedural Memory | L1 (conceptual) | Needs entire MemoryOwner + emergence + adoption infrastructure |

这些模块的 deferred/blocked 状态已在 trigger registry 中记录。后续 owner 决策或 external 资源到位后再重新 triage。

## 8. Debt / Blocker Registry

| ID | Module | Blocker | Owner needed | Expected resolution |
|----|--------|---------|-------------|---------------------|
| OD-9 | Memory | OWNER_DECISION | Project owner | Approve MemoryOwner abstraction design |
| OD-4 | Memory | OWNER_DECISION | Project owner | Decide if consolidation should be default production path |
| OD-7 | Policy | OWNER_DECISION | Project owner | Decide production approval hook scope |
| OD-2 | Capability | OWNER_DECISION | Project owner | Decide if CM-2 unified contract needed |
| OD-8 | State | OWNER_DECISION | Project owner | Decide canonical state machine enum |
| FOP-1 | SubAgent | TRACKED_DEBT (code-internal) | None | Fix provider_mode_allowed propagation in core.py |
| REAL-EVIDENCE-007 | MCP | EXTERNAL_DEPENDENCY | Owner + external env | Controlled external MCP server |
| W1-D5 | Provider | COMPLETED (minimal smoke) | None | Success/failure/fallback + adversarial suite (future) |

## 9. Do Not Do Yet

- Do not create Window 4 or reopen Architecture Repair
- Do not implement MemoryOwner before OD-9 approval
- Do not unfreeze memory consolidation/emergence before OD-4 + safety hardening
- Do not default-on SubAgent V0 before FOP-1 + real provider V0 tests
- Do not connect real MCP server without controlled external environment
- Do not implement CM-2 unified capability contract without consumer
- Do not implement production approval hook (OD-7) without owner decision
- Do not route scheduler into production without consumer
- Do not implement cross-host checkpoint resume without use case
- Do not mark any module L3 without real evidence
- Do not mark any module L4
- Do not change North Star
- Do not rewrite maturity audit history

## 10. Evidence Appendix

### Primary source
- `docs/07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md` §4 — 15 module L0-L4 maturity table
- `docs/07-module-maturity/POST_REPAIR_TRIGGER_REGISTRY.zh.md` — trigger register with owner/external/exit criteria
- `docs/07-module-maturity/MEMORY_OWNER_DECISION_SPIKE.zh.md` — 12 decision domains
- `docs/07-module-maturity/MEMORY_TAXONOMY_MAPPING.zh.md` — source × type mapping
- `docs/07-module-maturity/PROVIDER_API_KEY_ACTIVATION_AUDIT.zh.md` — real smoke evidence

### Module evidence
- Agent Loop: `agent/core.py:763`, `agent/loop.py`, `tests/golden_e2e/test_golden_simple_conversation.py`
- Dispatcher Spine: `agent/runtime_integration/dispatcher.py:309`, `tests/runtime_integration/test_runtime_action_contract.py`
- Tool: `agent/tool_runtime_mediator.py`, `tests/golden_e2e/test_golden_tool_success.py`
- Provider: `agent/provider/factory.py`, `tests/test_provider_real_smoke.py` (1 passed)
- MCP: `tests/runtime_integration/test_mcp_real_external_flight.py` (code-path-complete, default off)
- Memory: `agent/memory_runtime.py`, `memory_disabled.json` (golden locked)
- SubAgent: `agent/subagent_routing_flag.py` (default off), `tests/golden_e2e/test_golden_subagent_delegation.py`
- Skill: `agent/skill_system/`, `tests/golden_e2e/test_golden_skill_system.py` (local sample fixture)
- Policy: `agent/runtime_integration/tool_gate.py`, `tests/adversarial/test_minimal_policy_stub.py`
- Scheduler: `agent/action_scheduler.py:225`, `agent/core.py:697/772` (默认 None)
- State: `agent/checkpoint.py`, `tests/golden_e2e/test_golden_memory_checkpoint.py`
- Observability: `agent/runtime_integration/evidence.py`, `tests/golden_e2e/test_golden_policy_evidence.py`
- Security: `agent/display_events.py:129`, `tests/test_security_baseline.py`
- Capability: `agent/runtime_decision_frame.py`, `tests/unit/test_runtime_decision_frame.py`
- Docs: `tests/test_docs_source_of_truth.py` (78 passed), `tests/test_architecture_boundaries.py` (40 passed)
