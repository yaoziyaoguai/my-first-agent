# Architecture Repair Mainline Closure Audit

**日期**: 2026-06-13
**状态**: final-audit — GE-3 rubric re-score completed
**Audited runtime HEAD**: `b53e5eecf2326877d13704868916123485747058`
**Scope**: docs-only final acceptance; no production code; no tests changed

---

## Final Verdict

**MAINLINE_CLOSE_READY = YES**

**ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED**

本结论关闭 Architecture Repair mainline，不关闭后续 tracked debt / deferred /
blocked / optional work。North Star 仍是 Target / Principle authority；本审计只把
当前 runtime / tests / docs evidence 回填到 North Star §20 rubric 与 §21 gate。
North Star §20 同时保留了 full Architecture Repair Done 的更高阈值：全部维度
达到 3。本审计的结论是 mainline closed with tracked debt，不宣称 full Done。

---

## Scope Guard

本轮只做 GE-3 rubric re-score、mainline closure decision、repair roadmap 更新和本
closure audit。明确未做：

- production code change
- test change or new golden
- GE-1 / GE-2 work
- Window 4
- North Star modification
- real provider E2E
- production approval hook
- CM-2 unified capability contract
- action_scheduler production routing
- memory unfreeze / MEM-2 owner decision
- rollback path deletion
- push

---

## Completed Windows / Closure Steps

| Item | Status | Evidence |
|---|---|---|
| Window 1 | CLOSED | `WINDOW_1_CLOSURE_AUDIT.zh.md`: ACCEPT_WITH_TRACKED_DEBT, GE-1 Phase A, 0 Blocker / 0 High |
| Window 2 | CLOSED | `WINDOW_2_CLOSURE_AUDIT.zh.md`: ACCEPT_WITH_TRACKED_DEBT, SPA-1 / CR-1, full suite green at closure |
| Window 3 | CLOSED | `WINDOW_3_CLOSURE_AUDIT.zh.md`: ACCEPT_WITH_TRACKED_DEBT, CM-1 inventory, scheduler label precision, 0 Blocker / 0 High |
| RED-1 | DONE | stale docs guard restored; roadmap records full suite green after fix |
| GE-1 Phase A/B/C | DONE | `tests/golden_e2e/` and `tests/adversarial/` cover conversation, tool, subagent, memory, checkpoint, policy, evidence trace, adversarial stub |
| GE-2 + doc-align | DONE | `docs/CAPABILITY_BOUNDARIES.md` runtime fact diff table; repair roadmap marks RS-1 / SPA-2 / MEM-1 / CR-2 / CR-3 / CR-4 completed-docs |
| GE-3 | DONE | This audit: North Star §20 12 dimensions re-scored, all after score = 2 |

---

## Evidence Summary

Graphify was used for source/runtime evidence discovery; rubric scoring also uses
tests, closure audits, and docs. Graphify output was verified against real files.

| Claim | Evidence sources |
|---|---|
| SubAgent V0 production routing is implemented but remains honest subsystem evidence | `agent/core.py`, `tests/golden_e2e/test_golden_subagent_delegation.py`, W1 closure audit |
| RuntimeAction / dispatcher / handler registry is the governed extension point | `agent/runtime_integration/schema.py`, `dispatcher.py`, `phase1_hook.py` |
| Tool policy gate rejects unsafe or disallowed tools without execution | `agent/runtime_integration/tool_gate.py`, `tests/golden_e2e/test_golden_policy_evidence.py`, `tests/adversarial/test_minimal_policy_stub.py` |
| safe metadata canonical masking owner is display_events | `agent/display_events.py`, `agent/runtime_integration/safe_metadata.py`, `tests/runtime_integration/test_safe_metadata_ownership.py` |
| action_scheduler is dormant-by-default / registered-not-routed in production | `agent/action_scheduler.py`, `agent/core.py`, `main.py`, W2/W3 closure audits |
| Provider/config import boundary is inventoried; no provider registry was introduced | `agent/provider/factory.py`, `WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md` |
| Memory current behavior is frozen / env-gated / golden-locked | `tests/golden_e2e/test_golden_memory_checkpoint.py`, `fixtures/memory_disabled.json`, `docs/CAPABILITY_BOUNDARIES.md` |
| Checkpoint current behavior is local-file / intra-process roundtrip | `agent/checkpoint.py`, `agent/runtime_integration/checkpoint_save.py`, `fixtures/checkpoint_local_roundtrip.json` |
| Evidence trace is observable and does not claim real provider E2E | `agent/runtime_integration/evidence.py`, `tool_result_feedback.py`, `fixtures/evidence_trace.json` |
| Adversarial stub fails closed without dangerous execution | `tests/adversarial/test_minimal_policy_stub.py`, `fixtures/adversarial_stub.json` |

---

## Rubric Re-score Table

North Star §20 uses 0/1/2/3, where 2 means present but not fully consistent and 3
means fully satisfying the target. §21 item 8 requires every dimension >= 2 for
this mainline closure gate; §20 reserves full Architecture Repair Done for all
dimensions reaching 3. This audit deliberately does not assign any 3 and does
not claim full Done.

| Dimension | Target expectation | Current evidence | Before repair | After Window 1/2/3 + closure | Remaining gap | Category | Blocks close? | Confidence |
|---|---|---|---|---|---|---|---|---|
| Runtime unity | Single runtime spine covers side effects | RuntimeAction schema, dispatcher registry, phase1 hook, SubAgent V0 route, mediated tool gate/result evidence | provisional | 2 | pre-loop delegation seam and dormant scheduler remain governed but not unified to all target text | TRACKED_DEBT | no | High |
| Boundary clarity | Core / loop / dispatcher / handler / adapter boundaries are explicit | dispatcher records/routes evidence and handlers own action-specific behavior; capability boundary docs name mediated execution | provisional | 2 | SA-2 / L3 lifecycle spike deferred | TRACKED_DEBT | no | High |
| SoT consistency | Key concepts have one owner | target catalog, display_events masking owner, capability facts table, W2/W3 inventories | provisional | 2 | CM-2 and MEM-2 owner decisions open | TRACKED_DEBT | no | High |
| Side-effect safety | Policy / permission / validate / exec / evidence gate | ToolGateHandler rejection, no-execution golden, adversarial forbidden-tool stub | provisional | 2 | production approval hook OD-7 deferred | TRACKED_DEBT | no | High |
| Observability | Decision / tool / memory / fallback / error / result can be reconstructed | RuntimeActionEvent, evidence classification, evidence-trace golden, tool result feedback | provisional | 2 | cost as first-class eval field EOE-1 deferred | TRACKED_DEBT | no | High |
| Recoverability | Checkpoint + resume + failure recovery | checkpoint save/load local schema and checkpoint golden roundtrip | provisional | 2 | cross-host / long-task resume SPR-1 deferred | DEFERRED | no | High |
| Memory governance | policy gate + provenance + lifecycle | memory frozen/env-gated golden locks current disabled_by_env behavior | provisional | 2 | MEM-2 canonical write owner blocked by decision | BLOCKED_BY_DECISION | no | High |
| Subagent governance | parent-controlled + bounded delegation | flag-on V0 routing, fallback guard, provenance assertions, provider mode constraints | provisional | 2 | L3 lifecycle / gate-to-3 spike SA-2 and real-provider E2E remain outside current closure | DEFERRED / TRACKED_DEBT | no | High |
| Extension cost | New capabilities join through stable extension points | RuntimeActionType, ActionHandlerRegistry, phase1 dispatcher registrations | provisional | 2 | CM-2 unified capability contract not built without consumer | BLOCKED_BY_DECISION | no | High |
| Test / evaluation coverage | Unit / contract / architecture / integration / Golden E2E | golden Phase A/B/C, adversarial stub, runtime integration, architecture boundary tests | provisional | 2 | real provider E2E W1-D5 blocked by external credentials | TRACKED_DEBT / BLOCKED_BY_EXTERNAL | no | High |
| Compatibility debt | explicit classification + exit windows | W1/W2/W3 debt tables, remaining gap classification, trigger/exit table | provisional | 2 | low/P3 cleanup remains tracked | TRACKED_DEBT | no | High |
| Documentation accuracy | docs/runtime facts agree | GE-2 fact table, roadmap closure readiness, docs guard | provisional | 2 | North Star remains target/principle doc and still has current-state text that must not be treated as latest runtime fact | TRACKED_DEBT | no | High |

All 12 dimensions are >= 2. No dimension is claimed as 3.

---

## Architecture Repair Mainline Closure Readiness

1. P0/P1 open 是否为 0? 是。
2. MUST_FIX_NOW 是否为 0? 是。
3. Blocker / High debt 是否为 0? 是；初稿 review 的 High 为 §20/§21 阈值措辞歧义，已收紧为 mainline closure gate，不作为 open High 保留。
4. Full suite 是否 green? 本轮验证结果见下方 Verification Results。
5. Golden E2E Phase A/B/C 是否完成? 是。
6. Docs fact alignment 是否完成? 是。
7. Rubric GE-3 是否完成? 是。
8. 剩余项是否都属于 tracked debt / deferred / blocked / optional? 是。
9. 是否仍有 runtime-risk must-fix? 否。
10. 是否可以关闭 architecture repair mainline? 是。

**MAINLINE_CLOSE_READY = YES**

Remaining must-fix items:

- none

---

## Remaining Debt / Deferred / Blocked / Optional Items

| Item | Classification | Trigger | Exit condition | Blocks mainline close? |
|---|---|---|---|---|
| SA-2 | DEFERRED / blocked_by_evidence | real L3 or gate-to-3 need appears | spike decides implement or keep subsystem_integration | no |
| CM-2 | BLOCKED_BY_DECISION | cross Tool / Skill / MCP consumer appears or OD-2 is decided | unified contract decision plus tests, if approved | no |
| MEM-2 | BLOCKED_BY_DECISION | memory owner decision starts | canonical owner decision plus single-owner tests | no |
| OD-7 | BLOCKED_BY_DECISION / accepted_deferred | multi-user or production approval need appears | OD-7 decision and approval-hook implementation plan | no |
| W1-D5 real provider E2E | BLOCKED_BY_EXTERNAL | credential / CI secret / stable external test provider available | real-provider failure E2E green | no |
| FOP-1 | TRACKED_DEBT, pre-flip blocker | SubAgent V0 default-on flip is proposed | provider_mode_allowed propagation plus real-provider V0 test | no for current default-off; yes for default-on flip |
| W1/W2/W3 tracked debt | TRACKED_DEBT | owner-specific trigger in roadmap debt tables | listed exit condition per debt id | no |
| SPR-1 | DEFERRED | cross-host / long-task / HITL resume demand appears | OD-8 decision plus canonical resume/state protocol | no |
| EOE-1 | DEFERRED | eval harness consumes cost as first-class signal | OD-6 decision plus cost field integration | no |
| DOC_ONLY remaining (GE-2 cluster) | DONE / none | n/a | GE-2 doc-align cluster completed | no |
| North Star threshold/current-state cleanup | TRACKED_DEBT / blocked_by_approval | approved North Star amendment is explicitly in scope | reconcile §20 full-Done threshold with §21 closure gate and refresh current-state notes without changing target principles | no |

---

## Verification Results

These results are refreshed during this closure step after the docs are written.

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest -q tests/golden_e2e/ tests/adversarial/ -rx --tb=short` | 13 passed in 2.13s |
| `.venv/bin/python -m pytest -q tests/test_docs_source_of_truth.py -rx --tb=short` | 78 passed in 0.83s |
| `.venv/bin/python -m pytest -q tests/test_architecture_boundaries.py -rx --tb=short` | 40 passed in 7.58s |
| `.venv/bin/python -m pytest -q tests/runtime_integration/ -rx --tb=short` | 1076 passed, 4 skipped, 6 xfailed in 14.12s |
| `.venv/bin/python -m pytest -q tests/ -rx --tb=short` | 4730 passed, 12 skipped, 26 xfailed in 96.69s |
| `git diff --check` | clean |

Only Markdown docs were changed, so Ruff is not required unless Python files become touched.

---

## Review Findings

Fresh-context reviewers completed after the first draft and before commit.

| Reviewer | Highest severity | Finding | Resolution |
|---|---|---|---|
| architecture reviewer | High | North Star §20 says full Architecture Repair Done requires all dimensions = 3, while §21 item 8 uses >=2; draft wording over-relied on >=2 as a generic DoD claim | Accepted. This audit and Roadmap now explicitly limit the verdict to `MAINLINE_CLOSE_READY` / mainline closure gate, and state that full Architecture Repair Done remains the §20 all-3 threshold. |
| adversarial document reviewer | Medium | Same threshold ambiguity could be overread as complete Architecture Repair Done; North Star current-state text still has stale facts because North Star was intentionally not edited | Accepted. Documentation accuracy remains score 2, North Star cleanup is tracked debt / blocked_by_approval, and current facts are sourced from closure audit, Roadmap, capability docs, tests, and runtime source. |

Final local checklist after adopting reviewer findings:

- GE-3 rubric is逐项复算, not a total-score average.
- deferred / blocked items are not marked done.
- real provider E2E is not claimed.
- production approval hook is not claimed.
- memory owner / MEM-2 is not claimed.
- no code or tests are changed.
- no North Star change.
- no Window 4.
- no push.
