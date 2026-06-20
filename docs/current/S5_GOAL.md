# S5 Goal - Durable Governed Task Recovery

> Status: **frozen (approved)**. The user approved/froze this S5 goal on
> 2026-06-20 via explicit `/goal` authorization. The selected direction is
> **Durable Governed Task Recovery**. This goal is now frozen: per `AGENTS.md`
> Goal Rules it changes only on a future explicit user decision. The S5 gap loop
> may now execute `S5_GOAL_GAP.md` in recommended order.

## 1. Executive Summary

Recommended S5 goal:

**S5 = Durable Governed Task Recovery**.

S5 should mature L2/L4 durability by adding a local-safe, governed task ledger
that records task lifecycle, step progress, checkpoint references, and evidence
references at a redacted/safe-summary level. The ledger must supplement the
existing checkpoint/runtime spine rather than creating a second agent loop.

Why this direction:

- It addresses the clearest remaining deferred roadmap item: durable task ledger
  (`TD-011`).
- It creates the recovery foundation needed before activating more ambitious L5
  capabilities such as Scheduler or broader MCP/SubAgent ecosystems.
- It preserves the S1-S4 same-spine architecture and builds directly on S4's
  audit/replay/verifier maturity.

## 2. Roadmap Constraints

S5 must stay within the S-series roadmap:

- Use the five-layer model in `S_ROADMAP.md`.
- Do not revive historical roadmaps as routing authority.
- Do not create a second fake/real agent path.
- Do not activate memory, Scheduler, full MCP ecosystem, or writable SubAgent
  paths unless explicitly selected by this goal.
- Do not turn S5 into a UI, demo, commercial packaging, or full agent platform
  milestone.
- Keep all real-provider behavior key-safe and optional.

## 3. Inherited Baseline

Inherited facts from `S5_BASELINE_STATUS.md`:

- S1 established the local-first product/runtime baseline.
- S2 added governed task semantics, policy, progress, and same-spine regression
  protection.
- S3 matured Skill/MCP/SubAgent/Scheduler extension boundaries while keeping
  broader activation deferred.
- S4 added redacted-faithful governed task replay, audit observability, verifier,
  pending-tool fidelity, fake/local reference E2E, and evidence-fidelity
  acceptance classification.
- Checkpoint/resume exists, but no independent durable cross-session task ledger
  exists.
- Live debt relevant to this goal:
  - `TD-011` durable task ledger deferred.
  - `TD-012` legacy evidence preview redaction boundary.
  - `TD-013` verifier cross-kind duplicate-ref blind spot.

## 4. Candidate Directions

### Candidate A - Durable governed task recovery

Scope:

- Introduce a local-only durable task ledger contract.
- Record governed task lifecycle, step transitions, checkpoint refs, and evidence
  refs without raw secret payloads.
- Prove deterministic crash/restart-style recovery through fake/local tests.
- Integrate with existing checkpoint and S4 evidence/replay surfaces.

Fit:

- Directly addresses `TD-011`.
- Strengthens L2 and L4 without changing L5 activation policy.
- Provides a stable foundation for later Scheduler and extension activation.

Risk:

- Requires careful boundary design so the ledger does not become a second task
  runner or raw evidence store.

Verdict: **recommended selected direction**.

### Candidate B - S4 evidence hardening

Scope:

- Close `TD-012` by wiring redaction into legacy mediator/evidence-recorder
  previews.
- Close `TD-013` by detecting cross-kind duplicate refs.

Fit:

- Valuable and bounded L3 hardening.
- Builds on S4 directly.

Risk:

- Too narrow for a whole S5 product-stage goal if S5 is expected to move the
  runtime forward beyond audit fidelity.
- Can be included as supporting work only when it is necessary for safe ledger
  integration; otherwise keep it as separate carry-forward debt.

Verdict: good secondary hardening, not the primary S5 direction.

### Candidate C - Selective L5 activation

Scope options:

- Scheduler productionization.
- Full MCP ecosystem.
- Writable or multi-agent SubAgent expansion.
- Memory activation around user/task state.

Fit:

- Roadmap-compatible in principle.

Risk:

- Too broad without a durable task/recovery foundation.
- Scheduler and multi-extension activation would increase state/evidence
  complexity before crash/recovery semantics are reliable.
- Memory activation risks product/permission scope creep.

Verdict: defer until S5 or later has a durable governed recovery base.

## 5. Selected Direction

S5 should select **Durable Governed Task Recovery**.

Target capability:

> A governed task can persist safe lifecycle/progress/evidence references to a
> local ledger, restart from that durable record plus checkpoint state in a
> deterministic fake/local path, and produce auditable evidence that the resumed
> task stayed on the same runtime spine.

The ledger should be:

- local-only by default;
- safe-summary/redacted, not raw-payload;
- append-oriented or otherwise auditable;
- tied to task IDs, step IDs, checkpoint refs, and evidence refs;
- replay/verifier aware enough to prove consistency;
- thin enough that checkpoint remains the state restoration mechanism.

The ledger should not be:

- a second runtime loop;
- a substitute for policy/approval gates;
- a raw transcript or raw secret persistence layer;
- a production database integration;
- an implicit Scheduler or memory activation.

## 6. Layer Goals

### L1 - Runtime Spine

- Preserve the existing runtime loop.
- Add ledger integration only through existing task/checkpoint/evidence
  boundaries.
- Prove FakeProvider and RealProvider still share the same governed path after
  entering the core runtime.

### L2 - Context / Memory / State / Checkpoint

- Define a task-ledger contract for lifecycle/progress/checkpoint references.
- Keep checkpoint as the state restoration source.
- Keep memory activation out of scope.
- Ensure ledger persistence is local, fixture-friendly, and safe to test.

### L3 - Tools / Policy / Evidence

- Link ledger entries to evidence refs without storing raw tool output or raw
  secrets.
- Reuse S4 redaction and verifier semantics where ledger records surface
  previews or replay summaries.
- Do not bypass mediator/policy/evidence paths.

### L4 - Task Orchestration / State Machine / Progress Tracking

- Record governed task step transitions and recovery points.
- Support deterministic fake/local recovery after an interruption point.
- Verify resumed tasks do not repeat completed steps unless explicitly designed
  and recorded.

### L5 - Skill / MCP / SubAgent / Scheduler Extension Boundary

- Keep Scheduler dormant by default.
- Keep MCP and SubAgent on existing governed paths.
- Use extension actions only as part of fake/local reference coverage when they
  are needed to prove ledger/evidence integration.

## 7. Acceptance Criteria

### AC-1 - No regression across S1-S4

S1/S2/S3/S4 targeted gates and full pytest remain green with only explicit known
xfails/skips.

### AC-2 - Ledger contract exists and is narrow

There is a documented, tested ledger contract for governed task lifecycle, step
transition, checkpoint ref, and evidence ref records. It excludes raw secrets and
raw payload persistence.

### AC-3 - Ledger persistence is local and deterministic

Ledger read/write behavior is testable with local fixture paths and does not use
real external services, private config, or real provider calls.

### AC-4 - Checkpoint and ledger cooperate

Checkpoint remains responsible for restoring runtime state; the ledger provides
durable audit/progress continuity. Tests prove the two do not diverge silently.

### AC-5 - Recovery E2E works in fake/local mode

A fake/local governed task can be interrupted after a recorded progress point,
reloaded from checkpoint + ledger, continued, and verified as one coherent
governed task history.

### AC-6 - Same-spine guarantee holds

Ledger integration must not create a separate fake path, real path, task runner,
tool executor, policy gate, or evidence recorder.

### AC-7 - Secret-safe ledger evidence

Synthetic key-like strings in task inputs, tool previews, or recovery metadata
must not appear unredacted in ledger records, reports, or replay summaries.

### AC-8 - S4 audit/replay alignment

S4 replay/verifier/audit observability must remain valid after ledger
integration, and recovered tasks must expose enough refs for audit consistency.

### AC-9 - Acceptance gate can flag durability regressions

Durability/recovery failures must be categorized in a stable acceptance signal
without weakening existing runtime, extension, evidence-fidelity, or debt
classification.

### AC-10 - Governance and docs are current

The S5 gap register, work log, release evidence, and live technical debt must
reflect what was actually implemented, deferred, or left open.

## 8. Non-goals

- No S5 implementation before this goal is approved.
- No UI/demo/business packaging.
- No memory activation or user-memory product semantics.
- No Scheduler productionization or main-loop activation.
- No full MCP ecosystem or multi-server orchestration.
- No writable/non-mediated SubAgent or multi-agent collaboration.
- No real provider live success requirement.
- No raw secret persistence or byte-for-byte replay.
- No broad ruff cleanup unless a focused ledger change touches a file.
- No broad provider facade refactor.

## 9. Decisions

> The four open decisions below were resolved at goal freeze (2026-06-20) so the
> S5 gap loop has a single, consistent interpretation. Each resolution stays
> within the roadmap/baseline: no Scheduler/memory/full-MCP/writable-SubAgent
> activation, no production database, no secret/config surface.

### Resolved decisions (resolved at freeze, 2026-06-20)

- **Ledger storage shape = JSONL.** The durable ledger is a local-only,
  append-oriented, line-delimited JSON file: one record per line, record types
  for lifecycle / step / checkpoint-ref / evidence-ref. Rationale: append-oriented
  and auditable per §5, fixture-friendly and deterministic in tests, no schema
  migration tooling, trivial line-by-line diff. A production database, network
  storage, and home-config write path remain non-goals.
- **Durability acceptance classification = new `DURABILITY_REGRESSION` class.**
  `acceptance_gate.py` gains a dedicated durability/recovery category, parallel
  to the S4 `EVIDENCE_FIDELITY_REGRESSION` precedent, instead of reusing an
  existing runtime/evidence category. This satisfies AC-9 (a stable signal
  without weakening existing runtime/extension/evidence-fidelity/debt classes).
  Implementation lands in S5-G08.
- **`TD-012` stays out of the S5 critical path.** Ledger records are
  safe-summary only and must never use the legacy mediator `TOOL_RESULT` preview
  or `record_evidence` metadata as the source of any persisted field. Any
  preview-like content the ledger surfaces goes through the already-wired S4
  `evidence_redaction` helpers (replay-chain surface), not the legacy preview
  path. `TD-012` therefore remains open/debted; it re-enters scope only if a
  concrete ledger surface is later proven to require the legacy preview.
- **`TD-013` stays deferred/open.** Ledger consistency checks are ledger-internal
  (task/step/checkpoint-ref/evidence-ref ordering and checkpoint-ref match); they
  do not require the evidence verifier's cross-kind duplicate-ref detection.
  `TD-013` only re-enters scope if S5-G06 proves recovered-task replay
  verification needs cross-kind detection, which the current design does not.

### Resolved decisions (inherited from draft)

- S5 should not activate Scheduler or memory as a primary goal.
- S5 should not use durable ledger work to introduce a production database.
- S5 should build on checkpoint/resume instead of replacing it.

### Deferred decisions

- Scheduler productionization remains deferred unless a future stage selects it.
- Full MCP ecosystem remains deferred.
- Writable/multi-agent SubAgent remains deferred.
- Global lint cleanup remains separate from the S5 product goal.

## 10. Next Step

The S5 goal is frozen. Execute `S5_GOAL_GAP.md` in recommended order
(S5-G01 → S5-G11; S5-G12 is a non-goal guardrail, not executed). Each gap runs
as a focused mini-run with TDD red→green for behavior changes, a focused commit,
and `S5_GOAL_GAP.md` + `WORK_LOG.md` evidence updates.
