# S_FINAL Baseline Status — Roadmap Final Audit

> Status: roadmap收尾 baseline audit (post-S5 close-out). This is **not** a new
> product stage (no S6). It records the state of the S-series roadmap after S1-S5
> are complete and archived, and feeds `S_FINAL_GOAL.md` / `S_FINAL_GAP.md`. The
> final gap loop is **not** executed by this document.

## 1. Baseline Verdict

**S1-S5 are complete and archived under `docs/history/`. The S-series five-layer
mainline is realizable, explained, and acceptance-tested end-to-end. There are no
blockers to roadmap mainline closure.** All open items are carry-forward
hardening/cleanup debt or scope boundaries deliberately deferred to Sn/future —
none of which a frozen final goal is obligated to consume. The final stage is
therefore a **closure/hardening** stage (close the remaining low-risk debt that
materially tightens the mainline, document the closure, and prove no regression),
not a capability-expansion stage.

Authoritative sources: `docs/current/S_ROADMAP.md`, `docs/current/TECH_DEBT.md`,
and the S1-S5 release summaries under `docs/history/<STAGE>/`.

## 2. S1-S5 Stage Completions

- **S1 — Baseline Usable Product** (archived). Established the usable runtime
  baseline: one `chat()` main loop, `build_model_provider_from_env()` provider
  factory with FakeProvider/RealProvider sharing the same spine, tool registry +
  mediator, checkpoint state save, event-log evidence lifecycle, and skeleton
  boundaries for L1-L5. Subsequent stages' non-regression gates lock this baseline.
- **S2 — Governed Task Agent** (13/13, archived). Upgraded the baseline to a
  governed multi-step task agent without changing the spine: formal governed task
  lifecycle state model (`GovernedTaskLifecycle` / `GovernedStepStatus` /
  `GovernedTaskProgress`), orchestration skeleton (receive→plan→execute→advance→
  checkpoint→resume→complete), task memory boundary, governed tool-contract
  report, `TaskProgressReview`, `HumanTakeoverDecision`, `TaskEvidenceReport`, and
  the first acceptance-gate classifier.
- **S3 — Extensible Governed Agent Runtime** (13/13, archived). Moved extension
  boundaries from dormant/boundary-clear to governed-activation, scoped to
  **MCP + SubAgent**: MCP as a controlled tool source (default-off, two-layer
  policy, allowlist, registration evidence); SubAgent as read-only / audit-first /
  parent-mediated delegation. Skill stayed governed-activated; Scheduler stayed
  dormant. **TD-006 resolved** (full pytest green for the first time).
- **S4 — Auditable Governed Agent Runtime** (12/12, archived). Made governed work
  replay-faithful, secret-safe, and verifiable: replay chain, evidence redaction,
  pending-tool preview fidelity, evidence verifier, fake/local audit-replay
  reference task, opt-in key-safe real-provider smoke, evidence-fidelity acceptance
  classification, audit observability. **TD-001** and **TD-004** resolved.
- **S5 — Durable Governed Task Recovery** (11/11 satisfied; G12 deferred/non-goal,
  archived). Added a local-only, governed, append-only JSONL durable task ledger
  (lifecycle/step/checkpoint-ref/evidence-ref records) with redaction boundary,
  crash-survivable read, checkpoint-ledger cooperation + consistency diagnostics,
  fake/local recovery E2E, S4 ReplayChain ref coherence, same-spine AST guard,
  `DURABILITY_REGRESSION` acceptance class, extension-boundary recovery coverage,
  and operator summary. **TD-011 resolved.** Full pytest `4940 passed`; independent
  audit passed with all findings fixed.

## 3. L1-L5 Current State

### L1 — Runtime Spine
Same-spine invariant holds: FakeProvider and RealProvider share one runtime spine
after entering the core loop (`agent/core.py:781 chat()` via `LoopDependencies`).
No second agent path was introduced in S4 or S5. Acceptance gates classify
runtime / extension / evidence-fidelity / durability / debt regressions.
Boundary: planner/compress expose a legacy second call shape over the same provider
(`agent/provider/legacy_adapter.py`) — **TD-002** (cosmetic, not a spine split).

### L2 — Context / Memory / State / Checkpoint
Checkpoint/resume (`agent/checkpoint.py`) remains the live durability mechanism and
the state restoration source. **S5 added the durable task ledger** (`task_ledger.py`
+ `task_ledger_store.py`) that supplements checkpoint with durable audit/progress
continuity. Memory v0 contracts exist; full memory activation remains deferred
(non-goal of every frozen stage so far). Boundary: `agent/context.py:36
compress_history` is confirmed-unreachable dead code — **TD-003**.

### L3 — Tools / Policy / Evidence
Tool execution runs through the governed mediator/executor/policy/evidence path;
MCP shares the same governed registry→mediator path. S4 matured evidence fidelity
(replay chain, redaction, verifier, audit observability); S5 extended redaction
onto the ledger write path. Boundaries: S4 redaction is **not** wired into the
legacy mediator TOOL_RESULT preview nor `record_evidence` metadata — **TD-012**;
the verifier does not detect cross-kind duplicate refs — **TD-013**.

### L4 — Task Orchestration / State Machine / Progress
The governed task state model supports steps, progress, review, pending-tool
approval, delegation logs, and evidence-derived replay. **S5 added durable-ledger
durability**: checkpoint-ledger cooperation + consistency diagnostics + recovery
E2E so crash recovery is no longer checkpoint-only. No open L4 debt remains
(TD-011 consumed). Scheduler stays dormant (**TD-008**).

### L5 — Skill / MCP / SubAgent / Scheduler
All four boundaries are governed and tested. Skill = governed-activated,
default-off. MCP = controlled tool source, default-off. SubAgent = read-only /
audit-first / parent-mediated. Scheduler = dormant by design. Three scope
boundaries deliberately deferred to Sn/future: Scheduler productionization
(**TD-008**), full MCP ecosystem (**TD-009**), writable/multi-agent SubAgent
(**TD-010**).

## 4. Completed Capabilities (post-S5)

- **L1**: unified `chat()` loop; same-spine Fake/Real provider factory; AST-enforced
  same-spine guard; 5-class acceptance gate.
- **L2**: task-scoped memory boundary; checkpoint save/load; **durable JSONL task
  ledger** (S5) with safe-summary redaction + crash-survivable read.
- **L3**: governed tool-contract report + bypass detection; safe evidence summary;
  pending-tool preview fidelity; replay-faithful evidence; secret-safe redaction;
  evidence verifier; audit observability; MCP controlled tool source.
- **L4**: formal governed task state model; orchestration skeleton; progress review;
  non-side-effecting human-takeover decision; **durable recovery E2E** (S5);
  durability acceptance signal.
- **L5**: governed Skill lifecycle; governed MCP; read-only/parent-mediated SubAgent;
  extension-capability contract; dormant Scheduler.

## 5. Remaining Roadmap Mainline

Per `S_ROADMAP.md`, the S-series mainline is **open-by-design**: §3/§5 deliberately
do not encode a hard S2/S3/Sn implementation plan and do not commit scope/timeline —
each later stage defines its goal only when entered. With S1-S5 archived, **no
mainline stage work is currently "in progress"**. The remaining "work" is
carry-forward technical debt (§6) plus scope boundaries deferred to Sn/future (§7).
The roadmap mainline is therefore closable: there is no unfinished mainline
capability blocking closure.

## 6. Open Debt (`docs/current/TECH_DEBT.md`)

- **TD-007** — full-suite `ruff check .` red with 443 historical lint errors
  (open/carry-forward). Project-level lint gate; not a runtime regression.
- **TD-002** — planner/compress legacy `ProviderBackedClient` facade, a second call
  shape over the same provider (open/carry-forward). Cosmetic.
- **TD-003** — `agent/context.py:36 compress_history` confirmed-unreachable dead
  code (open/carry-forward). Safe to delete when L2 is next touched.
- **TD-012** — S4 redaction not wired into legacy mediator TOOL_RESULT preview /
  `record_evidence` metadata (open/carry-forward, S4 audit). No active live leak.
- **TD-013** — evidence verifier does not detect cross-kind duplicate refs
  (open/carry-forward, S4 audit). Low impact (separate id spaces).

## 7. Deferred to Sn / Future (NOT final-must)

These are scope boundaries set by prior frozen goals; they **must stay deferred
unless a future frozen goal explicitly authorizes them** — they are not final-must:

- **TD-008** — Scheduler productionization / main-loop activation (L5, dormant).
- **TD-009** — full multi-server MCP ecosystem (L5).
- **TD-010** — writable / non-mediated / multi-agent SubAgent delegation (L5).

## 8. Verification State (pytest / ruff / targeted)

- Full pytest: **4940 passed, 16 skipped, 28 xfailed, 0 failed** (post-S5 close-out).
- S5 targeted (`tests/test_s5_*.py`): **73 passed**.
- Ruff full-suite: **red, 443 errors** — known carry-forward **TD-007** (not a
  regression; S2-G12 policy requires focused ruff only for new/modified files, which
  all S1-S5 touched files pass).
- Stage gates: S1 `22 passed`; S2 `32 passed, 1 skipped`; S3 extension `124 passed`;
  S4 `44 passed, 1 skipped`.

## 9. docs/current + docs/history Cleanliness

- `docs/current/` holds only `S_ROADMAP.md` + `TECH_DEBT.md` (plus the `S_FINAL_*`
  planning docs this final phase produces). No stale S5 in-progress references.
- `docs/history/` holds S1-S5 stage archives (each with baseline/goal/gap/release
  summary/work log). S5 archive complete (4 docs + `S5_RELEASE_SUMMARY.md`).
- No secret/config tracking: `git ls-files config/config.yaml .env` is empty; both
  are `.gitignore`-d.

## 10. Blockers to Roadmap Mainline Closure

**None.** Every open TD is carry-forward hardening/cleanup, not a closure blocker:
TD-007 (lint) and TD-002 (facade) are cosmetic; TD-003 (dead code) is safe-until-
touched; TD-012/TD-013 are bounded S4-audit hardening with no active leak. The three
deferred items (TD-008/009/010) are scope boundaries that must remain deferred. The
roadmap mainline can close; the final stage decides which carry-forward debt is
worth closing now vs. leaving for Sn/future.
