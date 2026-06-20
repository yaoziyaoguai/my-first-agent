# S4 Baseline Status

> Current document (`docs/current/`). Records the **starting facts** for S4,
> grounded in the clean post-S3 repo state. It is a **baseline**, not a goal and
> not a gap list. It does **not** define what S4 will do. `S4_GOAL.md` and
> `S4_GOAL_GAP.md` follow (goal frozen on user approval).
>
> Authority order for the next stage: `docs/current/S_ROADMAP.md`, the archived
> S3 release record, and the user's explicit instruction (see `AGENTS.md`).

## 0. Verdict

S4 has a **clean, well-governed starting point**. S3 (Extensible Governed Agent
Runtime) is complete, committed, and archived; the working tree is clean; the
full pytest suite is green (4823 passed / 0 failed); the targeted S3 + S2
acceptance gates pass. The S-series same-spine runtime and the five-layer
capability surface are intact in code, with the L5 extension boundary now at
**governed-active for Skill + MCP + SubAgent** and **dormant for Scheduler**.
Carry-forward quality/fidelity debts (TD-001/002/003/004/007) and S4/Sn scope
boundaries (TD-008..011) remain. **S4's goal is not yet defined** — this document
only establishes where S4 starts, not where it should go.

## 1. Scope

- **In scope:** record the post-S3 doc layout, the archived S3 release, the
  capabilities S4 inherits as a must-not-regress floor, the runtime/code baseline
  (L1-L5), the test/verification baseline, carry-forward technical debt, and the
  known unknowns / candidate starting points.
- **Out of scope (deliberately not done here):** defining the S4 goal, generating
  an S4 gap list, choosing an S4 direction, modifying code/tests/config.
- **Method:** read-only audit of `docs/current/`, the S3 archive, plus graphify /
  file confirmation of the current code surface and a full-suite re-run captured
  during S3 close-out (2026-06-20).

## 2. Current doc layout

`docs/current/` after S3 close-out:

- `S_ROADMAP.md` — authoritative S-series version semantics + the five-layer line
  (L1-L5). Does not encode a hard S2/S3/S4/Sn implementation plan.
- `TECH_DEBT.md` — cross-stage carry-forward debt register (open + deferred only;
  resolved TD-006 removed at S3 close-out, recorded in the S3 archive).
- `S4_BASELINE_STATUS.md` — this file.
- `S4_GOAL.md` / `S4_GOAL_GAP.md` — created next (goal then gap).
- `WORK_LOG.md` — S4 work log (started this stage).

No `S3_*` stage docs remain in `docs/current/` (archived). The only references to
S3 from current docs are pointers into `docs/history/` (expected).

## 3. Archived S3 release

- Archive: `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/`.
- Release record: `S3_RELEASE_SUMMARY.md` — verdict **completed / release-ready**;
  S3-G01..S3-G13 satisfied (13/13); two independent audits' findings fixed or
  debt-tracked before close-out.
- Stage docs archived: `S3_BASELINE_STATUS.md`, `S3_GOAL.md`, `S3_GOAL_GAP.md`,
  `S3_REFERENCE_TASK.md`, `WORK_LOG.md`, plus scratch evidence under
  `_review_artifacts/` (`_tmp_s3_baseline_audit/`, `_tmp_s3_goal_draft/`,
  `_tmp_s3_goal_gap/`).

These are historical evidence, not routing authority (per `AGENTS.md`).

## 4. Capabilities inherited from S1+S2+S3 (must-not-regress floor)

- **S1 — Baseline usable product**: working runtime, CLI, fake/real provider.
- **S2 — Governed task agent**: governed task path
  `receive → plan → execute → advance → checkpoint → resume → done`; task
  state/progress; task-scoped context + memory boundary; governed tool contract +
  structured evidence; human review/takeover seam; Skill governed-active
  (default-off); acceptance gate (runtime_regression / doc_governance_debt /
  quality_debt / unknown_failure).
- **S3 — Extensible governed agent runtime**: unified extension capability
  contract; MCP as a controlled governed tool source (default-off / allowlist /
  policy / evidence); SubAgent read-only / audit-first / parent-mediated
  delegation (default-off; live inline-L0 records delegation evidence into
  checkpoint/evidence); extension evidence/checkpoint/task-state integration;
  acceptance gate `extension_regression` class; extension capability
  registry/report/health.

## 5. Runtime / code baseline (five layers, post-S3)

Confirmed in code (graphify + file confirmation):

- **L1 — Runtime spine**: `agent/core.py` (`chat()`), `agent/loop.py`
  (`LoopDependencies`), `agent/runtime_integration/{dispatcher,schema,tool_gate,evidence}.py`,
  `agent/acceptance_gate.py`. same-spine: FakeProvider/RealProvider differ only at
  factory/config (`agent/provider/`). **Stable; do not rewrite.**
- **L2 — Context / memory / state / checkpoint**: `agent/task_context.py`,
  `agent/state.py` (`TaskState`, incl. `delegation_log`), `agent/checkpoint.py`,
  `agent/memory.py` (runtime compression), `agent/memory_store.py`
  (`InMemoryMemoryStore`). **Memory is not activated by default** (per AGENTS.md
  "no memory activation unless explicitly authorized"). Evidence is structured
  summary, not byte-for-byte (TD-001).
- **L3 — Tools / policy / evidence**: `agent/tool_runtime_mediator.py`,
  `agent/task_tool_contract.py`, `agent/evidence_recorder.py`,
  `agent/task_evidence_report.py`. All tool calls (incl. MCP) route through the
  governed mediator/dispatcher/policy path.
- **L4 — Task orchestration**: `agent/task_state_model.py`,
  `agent/task_orchestration.py`, `agent/task_runtime.py`, `agent/task_review.py`.
- **L5 — Extension boundary**:
  - **Skill** — governed-active, default-off (`agent/skill_system/*`,
    `MY_FIRST_AGENT_S2_SKILL_ENABLE`).
  - **MCP** — governed-active controlled tool source, default-off
    (`agent/mcp_capability.py`, `agent/mcp*.py`, `main.py:_init_mcp_bridge_if_enabled`,
    `MY_FIRST_AGENT_MCP_ENABLE`); fake-first/dry-run; NOT a full ecosystem (TD-009).
  - **SubAgent** — governed-active read-only/parent-mediated, default-off
    (`agent/subagent_capability.py`, `agent/subagent_system/*`,
    `MY_FIRST_AGENT_S3_SUBAGENT_ENABLE`); live inline-L0 records evidence; L1/L2
    dispatcher delegation has no registered handler (frozen); NOT writable /
    multi-agent (TD-010).
  - **Scheduler** — **dormant / not productionized** (`agent/action_scheduler.py`
    + handler + tests exist; `chat()`/`LoopDependencies.action_scheduler` default
    None; `main.py` never passes it; gated by `if action_scheduler is not None`).
    Deferred (TD-008).
- **unified extension contract**: `agent/extension_capability.py`,
  `agent/extension_registry.py` (registry/report/health over MCP+SubAgent).

## 6. Test and verification baseline

- **Full pytest (2026-06-20, post-S3-fixes):** **4823 passed, 15 skipped,
  28 xfailed, 0 failed, exit 0.** The 28 xfailed are explicit/documented xfails
  (FakeProvider semantic shifts, config.yaml provider-isolation, an unwritten RFC
  file, l3-taxonomy naming) — a green release signal (S3 AC-9).
- **Targeted gates:** S3 acceptance (8 modules) 32 passed / 1 skipped; S2
  must-not-regress 7 passed / 1 skipped.
- **ruff:** project-wide `ruff check .` ≈ **443 errors = TD-007** (carry-forward
  quality debt; NOT a release blocker). Changed files pass focused ruff (S2-G12
  policy carried forward).
- **Acceptance-gate doctrine (carried into S4):** targeted gate = product signal;
  full pytest/ruff = health/debt signals; extension failures classify as
  `extension_regression`; any unknown failure is release-blocking until classified.

## 7. Technical debt baseline

Carry-forward register (`docs/current/TECH_DEBT.md`):

- **Open / carry-forward:** TD-001 (evidence not byte-for-byte), TD-002 (legacy
  provider facade), TD-003 (`agent/context.py` unreachable dead code), TD-004
  (pending-tool event preview gap), TD-007 (ruff ~443 historical lint).
- **Deferred to S4/Sn (scope boundaries):** TD-008 (Scheduler productionization),
  TD-009 (full MCP ecosystem), TD-010 (writable/multi-agent SubAgent delegation),
  TD-011 (durable task ledger).
- **Resolved (in archive, not here):** TD-006 (resolved S3-G09; see S3 archive).

## 8. Risks, unknowns, and candidate S4 starting points

- **S4 goal is undefined.** No S4 direction is chosen. The roadmap states S2+ does
  selective deepening "by the priority decided when the stage is entered" — that
  priority is not yet set.
- **Candidate starting points (options, NOT a committed plan):** these are where
  S4 *could* begin, grounded in the roadmap five-layer line + carry-forward debt.
  The goal phase picks at most one primary direction with explicit boundaries:
  1. **L3 evidence fidelity / auditability deepening** — TD-001 (byte-for-byte or
     fuller replay) + TD-004 (pending-tool preview). Lowest-risk, reuses S2/S3
     evidence spine.
  2. **L4 task intelligence deepening** — re-plan / failure self-recovery /
     evidence-driven decision within the governed state machine (must stay
     "governed", not autonomous AutoGPT).
  3. **L2 durability** — durable cross-session task ledger (TD-011) and/or scoped
     memory activation (memory activation needs explicit user authorization per
     AGENTS.md).
  4. **L5 selective deepening** — e.g. Scheduler governed-active (TD-008) **only
     with a hard boundary**, or MCP multi-server (TD-009) — both are currently
     non-goals and would need an explicit, bounded S4 goal decision.
- **Hard constraints for any S4 direction:** must not overturn the S1/S2/S3
  same-spine main line; must not silently activate dormant L5 (Scheduler) or
  widen MCP/SubAgent beyond their governed boundaries unless the frozen S4 goal
  explicitly selects and bounds it; memory activation requires explicit user
  authorization.
- **Full-suite is green** (unlike the S3 starting point, where TD-006 made it
  red), so S4 can use full pytest as a release signal from day one — provided
  TD-007 (ruff) stays classified as quality debt, not a runtime regression.

## 9. Recommended next step

Grounded only in `S_ROADMAP.md`, the archived S3 release, and `AGENTS.md`:

> The next authorized step is to **define the S4 goal with the user** — list 2-3
> candidate directions (from §8), pick one with explicit non-goals and AC, freeze
> it on approval in `docs/current/S4_GOAL.md`, then derive `S4_GOAL_GAP.md`.

This document does **not** pick that goal. No new goals, phases, architecture
docs, modules, roadmaps, or cleanup plans are proposed here (per `AGENTS.md`
Recommendation Rules).
