# S2 Goal Gap — Generation Matrix (intermediate, non-authoritative)

> Under `_tmp_s2_goal_gap/`. Not routing authority. Authoritative gap file is
> `docs/current/S2_GOAL_GAP.md`.

## Skills used

- superpowers: gap decomposition; priority sanity (P0 not abused); dependency
  ordering; verification-before-completion before commit.
- compound-engineering: baseline vs goal comparison; P0-P4 grading; S2 vs S3/Sn
  boundary; TECH_DEBT→S2 admission rules.
- g-stack / graphify: confirmed L4 task-state nodes (TaskState, mark_step_complete,
  advance_current_step_if_needed — legacy Plan minimal) and L5 SubAgent L1
  parent-mediated wiring (delegate_l1/execute_l1/build_context_package/
  SubAgentRegistry) is the most activation-ready L5 candidate; L3 ToolGateHandler
  governed path intact.

## Baseline vs Goal matrix (target → current → gap)

| S2 goal target (§/AC) | Baseline current | Verdict | Gap |
|---|---|---|---|
| reference task closed-loop (§3, AC-1/7) | no S2 reference task defined; S1 only had minimal multistep | missing (blocked by OD) | S2-G01 |
| formal task state model (§4-L4, AC-2) | legacy Plan `current_plan/step_index/status`; no formal task/step/progress/failure/resume/done model | partial→missing | S2-G02 |
| task orchestration skeleton (§4-L4, AC-1) | legacy Plan path only; ActionPlan/Scheduler dormant | partial | S2-G03 |
| task context/memory/state/checkpoint coord (§4-L2, AC-3) | compression pairing safe; checkpoint resume incl. large results; but no task-level context boundary; memory recall/retain not task-scoped | partial | S2-G04 |
| governed tool/policy/evidence (§4-L3, AC-4/5) | mediator/dispatcher/policy/evidence usable; but no task-level evidence contract; TD-001/004 depth open | partial | S2-G05 |
| task progress + human review/takeover (§4-L4, AC-2/9) | progress = checkpoint snapshot; no human-visible progress/blockage seam | missing | S2-G06 |
| fake+real S2 E2E (§4-L1, AC-1/7) | S1 acceptance green; real smoke opt-in; no S2 reference-task E2E | missing (blocked by G01) | S2-G07 |
| L5 selectively-active (§4-L5, AC-6) | all L5 dormant/boundary-clear; SubAgent L1 most ready | missing (blocked by OD-2) | S2-G08→G09 |
| acceptance gate debt classification (§4-L1, AC-8) | full-suite red (TD-006); ruff red (TD-007); no taxonomy to separate signal | missing | S2-G10 |
| task-level evidence depth (§5-AC5, OD-5) | evidence skeleton-level; TD-001/004 open | depends on OD-5 | S2-G11 |
| ruff quality gate (§8) | TD-007 ~451 errors | tech-debt-only | S2-G12 |
| TECH_DEBT triage (§8) | TD-001..004,006,007 open | needs triage | S2-G13 |

## TECH_DEBT admission decisions

- TD-006 → S2-G10 (P2): the subset blocking S2 acceptance signal enters S2; not a
  full cleanup as a product goal.
- TD-007 → S2-G12 (P3): strategy-ized, not full zeroing.
- TD-001/TD-004 → S2-G11 (P2): conditional on OD-5 (evidence depth).
- TD-002/TD-003 → S2-G13 (P4): legacy facade + dead code; S2/Sn cleanup, not core.
- Durable task ledger / full L5 ecosystem → P4 deferred (S3+).

## Final gap count: 13 (P0=1, P1=6, P2=4, P3=1, P4=1)
