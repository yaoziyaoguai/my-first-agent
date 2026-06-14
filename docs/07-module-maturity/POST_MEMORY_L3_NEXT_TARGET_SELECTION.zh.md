# Post-Memory-L3 Next Target Selection

**日期**: 2026-06-14
**性质**: docs-only next-target selection，不是实现
**Architecture Repair Mainline**: CLOSED
**前置**: Memory L3 已完成 explicit_user_request runtime main path

## 1. Status

- Memory L3 completed (explicit_user_request / semantic retain-create-noop-reject runtime main path)
- 本文从冻结/治理文档推导下一刀应该推进哪个模块
- 本文不是实现，不是 trigger 激活，不是 L4 claim
- 选择的输出是一个目标类型 + 范围 + 验证路径

## 2. Governance Hierarchy

以下文档约束本选择，优先级递减：

```
North Star (target authority)
  → Architecture Repair closure (freeze mainline)
    → Module maturity audit (module state)
      → Trigger registry (activation gates)
        → L3 hardening triage (execution aid)
```

任何 agent 的 "recommended next target" 不能覆盖 trigger registry 或 maturity audit。

## 3. Current Module State (post-Memory L3)

| # | Module | Level | Status | Gap/Blocker |
|---|--------|-------|--------|-------------|
| 1 | Agent Loop | L3 | NO_ACTION | — |
| 2 | Dispatcher Spine | L3 | NO_ACTION | — |
| 3 | Tool System | L3 | NO_ACTION | — |
| 4 | MCP | L2 | BLOCKED_BY_EXTERNAL | real external server |
| 5 | Memory | L3 | NO_ACTION (L3 achieved) | tracked debt: forget, SESSION_ONLY, update, etc. |
| 6 | SubAgent | L2 | TRACKED_DEBT | FOP-1 pre-flip blocker; no real-provider V0 evidence |
| 7 | Skill System | L3 | NO_ACTION (L3 achieved) | — |
| 8 | Provider | L3 | NO_ACTION (real smoke done) | adversarial suite deferred |
| 9 | Policy/Approval | L2 | BLOCKED_BY_DECISION | OD-7 production approval hook |
| 10 | Scheduler | L1 | BLOCKED_BY_DECISION | no consumer, would reopen repair |
| 11 | State/Checkpoint/Resume | L2 | TRACKED_DEBT | cross-host resume deferred; need local resume golden |
| 12 | Observability | L3 | NO_ACTION | — |
| 13 | Security/Privacy | L3 | NO_ACTION | — |
| 14 | Capability/Config | L2 | BLOCKED_BY_DECISION | CM-2 unified contract |
| 15 | Docs/Guardrails | L3 | NO_ACTION | — |

**已 L3 模块**: 9 (Agent Loop, Dispatcher Spine, Tool, Memory, Skill, Provider, Observability, Security, Docs)
**仍 below L3**: 6 (MCP, SubAgent, Policy, Scheduler, State, Capability)

## 4. Current Trigger State

| Trigger | Module | Status | Blocker | Can implement? |
|---------|--------|--------|---------|---------------|
| T-SKILL-GOLDEN | Skill | COMPLETED | none | n/a (done) |
| T-PROVIDER-E2E | Provider | COMPLETED (smoke) | adversarial suite = future | n/a (done) |
| T-MEM2 | Memory | COMPLETED (L3) | forget/SESSION_ONLY/update = debt | n/a (done) |
| T-MCP-REAL | MCP | BLOCKED_BY_EXTERNAL | real server credential | ✗ |
| T-OD7 | Policy | BLOCKED_BY_DECISION | owner decision | ✗ (only DESIGN_SPIKE) |
| T-CM2 | Capability | BLOCKED_BY_DECISION | owner decision | ✗ (only DESIGN_SPIKE) |
| T-SCHED-ROUTE | Scheduler | BLOCKED_BY_DECISION | no consumer | ✗ |
| T-SUBAGENT-FLIP | SubAgent | TRACKED_DEBT (pre-flip) | FOP-1 code-internal; needs real provider for verification | △ |
| T-SA2 | SubAgent | BLOCKED_BY_EVIDENCE | design spike | ✗ (only DESIGN_SPIKE) |
| T-SPR1 | State | OPTIONAL_OR_FUTURE (local golden = TRACKED_DEBT) | no cross-host consumer; local golden = none | ✓ (local golden only) |
| T-EOE1 | Observability | OPTIONAL_OR_FUTURE | no eval consumer | ✗ |
| T-W2D4 | SubAgent | TRACKED_DEBT | needs V0 default-on first | ✗ |
| T-NS-CLEANUP | Docs | OPTIONAL_OR_FUTURE | owner approval | ✗ |

## 5. Candidate Targets

### 5.1 State / Checkpoint / Resume — local resume golden

| Dimension | Value |
|-----------|-------|
| Current level | L2 |
| Blocker | None for local golden (cross-host is OPTIONAL_OR_FUTURE) |
| Can do now? | ✓ — code-internal, no owner decision, no external dep |
| Risk | Low — deterministic local fixture, fake provider |
| Validation | `tests/golden_e2e/test_golden_checkpoint_resume.py` or similar |
| Would it move module to L3? | No (need full resume protocol + canonical state enum), but produces L3 evidence |
| Scope | 1 golden test + 1 fixture |
| Type | GOLDEN_EVIDENCE |

### 5.2 SubAgent FOP-1 fix

| Dimension | Value |
|-----------|-------|
| Current level | L2 |
| Blocker | Code-internal (provider_mode_allowed propagation) but needs real provider for V0 test |
| Can do now? | △ — FOP-1 code fix is internal; verification needs real provider |
| Risk | Medium — touching core.py V0 payload propagation |
| Validation | V0 provider_mode test + real-provider V0 smoke |
| Would it move module to L3? | Partially (FOP-1 fix alone does not reach L3) |
| Scope | ~10-20 lines in core.py + test |
| Type | HARDENING |

### 5.3 Policy / Approval — OD-7 design spike

| Dimension | Value |
|-----------|-------|
| Current level | L2 |
| Blocker | OWNER_DECISION (OD-7) |
| Can do now? | ✗ — only DESIGN_SPIKE, cannot implement |
| Risk | Low (docs-only) |
| Validation | Decision spike accepted by owner |
| Would it move module to L3? | No (only spike, not implementation) |
| Scope | 1 decision spike document |
| Type | DESIGN_SPIKE |

### 5.4 Capability / Config — CM-2 design spike

| Dimension | Value |
|-----------|-------|
| Current level | L2 |
| Blocker | OWNER_DECISION (CM-2/OD-2) |
| Can do now? | ✗ — only DESIGN_SPIKE, cannot implement |
| Risk | Low (docs-only) |
| Validation | Decision spike accepted by owner |
| Would it move module to L3? | No |
| Scope | 1 decision spike document |
| Type | DESIGN_SPIKE |

### 5.5 MCP real external smoke

| Dimension | Value |
|-----------|-------|
| Current level | L2 |
| Blocker | EXTERNAL_DEPENDENCY (real server + credential) |
| Can do now? | ✗ — AGENTS.md hard blocks |
| Risk | — |
| Validation | — |
| Type | WAIT_EXTERNAL |

### 5.6 Scheduler route

| Dimension | Value |
|-----------|-------|
| Current level | L1 |
| Blocker | OWNER_DECISION; no consumer; would reopen repair |
| Can do now? | ✗ |
| Type | OPTIONAL_SKIP |

## 6. Selection Criteria

选择标准按优先级：

1. **Governance alignment**: 符合 North Star 目标 + maturity audit 状态
2. **No owner blocker**: 不需要 owner decision（可以直接推进）
3. **No external dependency**: 不需要 real provider / external server / credential
4. **Validation path clear**: 可以产生 deterministic evidence
5. **Scoped**: 单次 commit 可完成，不触发大重构
6. **Agent core value**: 与 Agent 运行时安全/能力边界强相关

## 7. Recommended Next Target

### **State / Checkpoint / Resume — local resume golden**

**Target type**: GOLDEN_EVIDENCE

**Why this target**:

1. **Governance alignment**: North Star §12 将 checkpoint + resume 列为 core recovery capability。当前已有 `checkpoint.py` save/load + `test_golden_memory_checkpoint.py`，但缺 explicit local resume roundtrip golden。
2. **No blocker**: 本地 resume golden 是 code-internal tracked debt，不需要 owner decision、不需要 real provider、不需要 external server。
3. **Scoped**: 1 个 golden test + 1 个 fixture，不触动 runtime architecture。
4. **Validation path**: 用 FakeProvider 驱动 `core.chat()` → checkpoint save → checkpoint restore → verify state — 完全 deterministic。
5. **Agent core value**: State/Checkpoint/Resume 与 Agent 恢复能力直接相关，L3 evidence 使该模块从 "代码存在但无独立 golden" 变为 "有 deterministic 恢复路径证据"。
6. **不违反任何 entry**: AGENTS.md 不禁止 checkpoint golden; trigger registry 将本地 golden 列为 TRACKED_DEBT (not blocked); maturity audit 将其列为 HARDEN_NEXT candidate。

### Why this target is not just "easy"

State resume golden 是最小 blocker (TRACKED_DEBT) + 最高自由度 (code-internal) 的候选，但它同时满足两条高层约束：
- North Star §12 defines checkpoint/resume as core — 这是架构目标
- Maturity audit 将 State 列为 L2 + TRACKED_DEBT — 这是可推进的证据

"容易做" 是必要条件但非充分条件。充分性来自它是 governance-aligned + the only non-blocked below-L3 module that can produce immediate L3 evidence without external dependency。

## 8. Why Not Other Targets Now

| Target | Reason for deferral |
|--------|---------------------|
| **SubAgent FOP-1** | 验证需要 real provider (T-PROVIDER-E2E smoke exists but using it for V0 is extra complexity). FOP-1 code fix is internal but the full L3 path (provider_mode_allowed + V0 test + default-on readiness) requires multiple rounds. State golden is simpler and more impactful for module maturity. |
| **Policy OD-7** | BLOCKED_BY_DECISION — only DESIGN_SPIKE possible. Design spike can be done anytime, but producing actual L3 evidence is blocked. Defer until after State golden. |
| **Capability CM-2** | BLOCKED_BY_DECISION — needs consumer before design. No current cross-surface consumer. Lowest priority of all L2 modules. |
| **MCP real external** | BLOCKED_BY_EXTERNAL — cannot proceed without controlled server. |
| **Scheduler** | No consumer, dormant. OPTIONAL_SKIP. |
| **Memory debt** | Remaining debt items (forget/SESSION_ONLY/update) are tracked but should not be the immediate next target. Memory just reached L3; debt items are lower priority than advancing another L2 module. |

## 9. Risks and Guardrails

| Risk | Mitigation |
|------|-----------|
| Golden test may expose checkpoint system bugs | Scope limited to deterministic local fixture; no real state change |
| May need minimal agent loop adjustment for checkpoint injection | If needed, scope is single-digit lines in checkpoint seam |
| Test may fail if checkpoint format is unstable | Golden fixture locks current schema version |

## 10. Required Prompt Shape For Next Target

If this selection is accepted, the next execution prompt should be:

```
TARGET: State / Checkpoint / Resume — local resume golden
TYPE: GOLDEN_EVIDENCE
SCOPE: 1 golden test proving checkpoint save → resume roundtrip via core.chat() + FakeProvider
BOUNDARIES:
- No cross-host resume
- No canonical state enum
- No real provider
- No external service
- Deterministic fake provider
EXPECTED EVIDENCE: test passed + golden fixture locked
EXPECTED COMMIT: test(state): add local resume golden evidence
```

## 11. Evidence Appendix

### Governance docs
- `AGENT_MODULE_MATURITY_AUDIT.zh.md` §5.11 — State L2, TRACKED_DEBT
- `POST_REPAIR_TRIGGER_REGISTRY.zh.md` — T-SPR1 OPTIONAL_OR_FUTURE; local golden = TRACKED_DEBT
- `L3_HARDENING_TRIAGE.zh.md` — State row: HARDEN_NEXT (local resume golden only)
- `ARCHITECTURE_NORTH_STAR.zh.md` §12 — checkpoint + resume as core capability

### Source
- `agent/checkpoint.py` — save/load checkpoint
- `agent/core.py` — chat() with checkpoint_save_on_turn_end
- `tests/golden_e2e/test_golden_memory_checkpoint.py` — existing checkpoint golden

### Recent commits (for context)
- `5b328b9` docs(memory): reconcile L3 owner path evidence
- `c41a67a` feat(memory): route explicit memory through owner
- `a58bd2b` test(memory): cover owner decisions for explicit memory
