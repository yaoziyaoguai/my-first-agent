# Audit Documents Navigation

Architecture Repair Mainline is closed.

**ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED**

This directory contains both current post-repair entrypoints and historical
repair evidence. Do not use these files to start Window 4. Do not treat old
plans, audits, or inventories as active work queues unless a new user request
explicitly reopens a documented repair mainline.

## Current Entrypoints

Read these first for post-repair Module Maturity / Module Hardening work:

| Path | Role | Default read? |
|---|---|---|
| ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md | Human-readable final summary and fastest orientation path | yes |
| ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md | Final GE-3 rubric re-score and closure decision | yes |
| ../CAPABILITY_BOUNDARIES.md | Current runtime/capability fact table for module work | yes |
| CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md | Closed historical repair record, remaining triggers/debt | only when you need repair history |
| ../architecture/ARCHITECTURE_NORTH_STAR.zh.md | Target/principle authority | only for target/principle questions |
| ../07-module-maturity/AGENT_MODULE_MATURITY_AUDIT.zh.md | Post-repair module maturity audit (15 modules, taxonomy APPROVED = YES). Not a repair queue | when doing module maturity/hardening work |

## Final Closure Evidence

These files are evidence and must not be deleted or rewritten for convenience:

| Path | Role | Notes |
|---|---|---|
| ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md | Final closure audit | MAINLINE_CLOSE_READY = YES |
| ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md | Final retrospective | Explains why closure is not "all future work done" |
| CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md | Closed Roadmap record | Not an active queue |

## Historical Window Evidence

Window closure audits remain at their original paths to preserve references:

| Path | Role | Default read? |
|---|---|---|
| WINDOW_1_CLOSURE_AUDIT.zh.md | Window 1 closure evidence for SA-1 and GE-1 Phase A | no |
| WINDOW_2_CLOSURE_AUDIT.zh.md | Window 2 closure evidence for SPA-1, CR-1, W1-D4 | no |
| WINDOW_3_CLOSURE_AUDIT.zh.md | Window 3 closure evidence for CM-1 | no |

## Supporting Inventories And Decisions

These files support specific historical findings. Read them only when the topic
matches the file:

| Path | Role |
|---|---|
| WINDOW_2_COMPAT_INVENTORY.zh.md | Compatibility-path inventory from Window 2 |
| WINDOW_3_CM1_CONFIG_IMPORT_BOUNDARY_INVENTORY.zh.md | Config/provider import-boundary inventory from Window 3 |
| SPA1_MASKING_OWNERSHIP_DECISION.zh.md | Safe metadata masking owner decision |
| V0_WIRING_DECISION.zh.md | Pre-Window-1 V0 routing decision record |
| TARGET_CATALOG_REEXPORT_AUDIT.zh.md | Target catalog re-export audit |
| POST_REPAIR_AUDIT_DELTA.zh.md | Early post-repair delta log |
| CURRENT_CAPABILITY_DRIFT.zh.md | Historical drift audit |
| CURRENT_AUDIT_STATUS.zh.md | Superseded source-of-truth cleanup status |

## Historical Plans

Plans live in ../plans/. They are historical execution artifacts, not current
instructions. Start with ../plans/README.md before reading a plan file.

## Reopen Triggers

Reopen Architecture Repair only when a documented trigger fires, such as:

- preparing a default-on capability flip;
- approved real provider E2E with credentials and CI support;
- production approval hook work;
- CM-2 unified capability contract work;
- MEM-2 memory owner decision and memory unfreeze;
- action_scheduler production routing;
- full suite, docs guard, or architecture boundary tests becoming red;
- a new feature touching runtime routing, provider, memory, scheduler, policy,
  fallback, or evidence boundaries.

Without a trigger, remaining work stays tracked debt / deferred / blocked /
optional and does not reopen the repair mainline.
