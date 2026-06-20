# S5 Goal Gap Backlog

> Status: **proposed / not executed**. This backlog is derived from
> `S5_BASELINE_STATUS.md` and the proposed `S5_GOAL.md`. It must not be executed
> until the S5 goal is explicitly approved/frozen by the user.

## Priority Model

- **P0**: blocks S5 goal definition, reference task, or release judgment.
- **P1**: required S5 product capability.
- **P2**: hardening, acceptance, or governance required for release confidence.
- **P3**: optional enhancement that can be deferred without breaking the goal.
- **P4**: S6/Sn deferred or explicit non-goal boundary.

## Backlog Summary

| Gap | Priority | Layer | Title | Status |
|---|---:|---|---|---|
| S5-G01 | P0 | L2/L4 | Ledger contract and reference recovery task | done |
| S5-G02 | P0 | L2/L3 | Ledger safety/redaction boundary | done |
| S5-G03 | P1 | L2 | Local durable ledger storage API | done |
| S5-G04 | P1 | L2/L4 | Checkpoint-ledger cooperation | done |
| S5-G05 | P1 | L4 | Fake/local recovery E2E | done |
| S5-G06 | P1 | L3 | Ledger-aware audit/replay alignment | done |
| S5-G07 | P1 | L1 | Same-spine durability guard | proposed/open |
| S5-G08 | P2 | L3/L4 | Durability regression acceptance signal | proposed/open |
| S5-G09 | P2 | L1-L5 | Non-regression and release governance | proposed/open |
| S5-G10 | P2 | L5 | Extension-boundary recovery coverage | proposed/open |
| S5-G11 | P3 | L3/L4 | Operator-facing ledger summary | proposed/open |
| S5-G12 | P4 | L5/Sn | Deferred capability guardrails | deferred/non-goal |

## S5-G01 - Ledger contract and reference recovery task

- Gap ID: S5-G01
- Title: Ledger contract and reference recovery task
- Priority: P0
- Layer: L2/L4
- Related goal section / AC: `S5_GOAL.md §5`, `§7 AC-2`, `§7 AC-5`
- Baseline evidence: S5 baseline states checkpoint/resume exists, but no
  independent durable task ledger exists (`TD-011`).
- Gap description: S5 cannot be implemented or released without a narrow ledger
  contract and one deterministic reference recovery task that defines what
  "durable governed recovery" means.
- Needed action: Define the ledger record types, required fields, ordering
  rules, reference task fixture, and interruption/resume point. Keep the contract
  local-only and safe-summary.
- Verification: Contract tests fail before implementation and pass after the
  ledger contract/reference task is implemented. The reference task must prove
  lifecycle, step, checkpoint ref, and evidence ref expectations.
- Dependencies: S5 goal approval; existing checkpoint/task state model.
- Non-goal boundary: Do not define a production database schema or Scheduler
  activation contract here.
- Suggested order: 1
- Status: done
- Evidence (2026-06-20):
  - `agent/task_ledger.py`: ledger contract — 4 record kinds (task_lifecycle /
    step_progress / checkpoint_ref / evidence_ref), required-field validation
    (`validate_ledger_record`), per-task_id strictly-increasing seq ordering
    (`assert_monotonic_order`), deterministic reference recovery task with
    `REFERENCE_RESUME_AFTER_SEQ = 6`.
  - `tests/test_s5_ledger_contract.py`: 16 passed (RED→GREEN). Covers all 4
    kinds, the safe-summary field contract (no raw payload/secret fields), the
    per-task_id ordering invariant, and the reference-task resume boundary.
  - Focused ruff on both files: clean.
- Risk if ignored: S5 implementation would be unbounded and release judgment
  would collapse into subjective "it works" claims.

## S5-G02 - Ledger safety/redaction boundary

- Gap ID: S5-G02
- Title: Ledger safety/redaction boundary
- Priority: P0
- Layer: L2/L3
- Related goal section / AC: `S5_GOAL.md §5`, `§7 AC-2`, `§7 AC-7`
- Baseline evidence: S4 made replay-chain redaction safe, but `TD-012` records
  that legacy mediator/evidence-recorder preview paths are not globally wired to
  the S4 redaction helpers.
- Gap description: Before writing durable records, S5 must specify exactly which
  fields can be persisted and where redaction is mandatory.
- Needed action: Define ledger-safe metadata rules, redaction application points,
  and tests with synthetic key-like strings across task input, tool preview,
  recovery metadata, and ledger summary output.
- Verification: Red tests show synthetic secrets would leak without the safety
  layer; green tests prove ledger files/reports/replay summaries contain only
  redacted or safe-summary values.
- Dependencies: S5-G01 ledger field contract.
- Non-goal boundary: Do not claim that every legacy event-log projection is
  globally redacted unless `TD-012` is actually closed with tests.
- Suggested order: 2
- Status: done
- Evidence (2026-06-20):
  - `agent/task_ledger.py`: `redact_ledger_record` + `_FREE_TEXT_FIELDS` rule.
    Free-text fields (user_goal / plan_goal / completion_summary / safe_summary)
    are routed through `evidence_redaction.redact_text`; structural fields
    (task_id / seq / step_id / checkpoint_ref / evidence_ref / controlled vocab)
    are preserved exactly so recovery (AC-4) and ref matching (AC-8) still work.
  - `tests/test_s5_ledger_redaction.py`: 8 passed (RED→GREEN). Synthetic keys
    injected into task input, plan goal, step/tool preview, and evidence summary;
    asserts `[REDACTED]` present + secret absent, structural fields preserved,
    `None` preserved, original record immutable, and a whole-summary JSON
    projection is secret-free (AC-7).
  - Focused ruff on touched files: clean.
- Risk if ignored: A durable ledger could become a long-lived secret leak surface.

## S5-G03 - Local durable ledger storage API

- Gap ID: S5-G03
- Title: Local durable ledger storage API
- Priority: P1
- Layer: L2
- Related goal section / AC: `S5_GOAL.md §6 L2`, `§7 AC-2`, `§7 AC-3`
- Baseline evidence: Existing resume uses checkpoint files; there is no
  dedicated ledger module or storage contract.
- Gap description: S5 needs a simple local persistence API for ledger records
  that is deterministic, fixture-friendly, and easy to audit.
- Needed action: Implement the smallest useful ledger module/service, record
  schema, append/read behavior, validation, and local path injection for tests.
- Verification: Unit tests cover append/read ordering, malformed record handling,
  fixture path isolation, and no external service access.
- Dependencies: S5-G01, S5-G02
- Non-goal boundary: Do not add a production database, network storage, or user
  home config write path.
- Suggested order: 3
- Status: done
- Evidence (2026-06-20):
  - `agent/task_ledger.py`: `ledger_record_kind` / `ledger_record_to_dict` /
    `ledger_record_from_dict` + `_RECORD_CLASSES_BY_KIND` — kind-tagged record
    serialization (one JSON object per JSONL line).
  - `agent/task_ledger_store.py` (new): `TaskLedger` — append-only JSONL store.
    `append` validates required fields, enforces per-task_id strictly-increasing
    seq at write time, routes through `redact_ledger_record` before persistence,
    and writes one line. `read_all` is crash-survivable (skips empty / half-written
    / malformed lines so the durable prefix stays recoverable). Caller injects the
    file path; no DB / network / home-config write (AC-3).
  - `tests/test_s5_ledger_store.py`: 11 passed (RED→GREEN). Covers roundtrip +
    type preservation, redaction-before-persist (raw bytes + read-back), monotonic
    seq enforcement at write time, required-field validation, missing-file → empty,
    malformed-line tolerance, and local-path-only isolation.
  - Focused ruff on touched files: clean.
- Risk if ignored: Recovery logic would keep relying on checkpoint-only state and
  fail to address `TD-011`.

## S5-G04 - Checkpoint-ledger cooperation

- Gap ID: S5-G04
- Title: Checkpoint-ledger cooperation
- Priority: P1
- Layer: L2/L4
- Related goal section / AC: `S5_GOAL.md §6 L2`, `§7 AC-4`
- Baseline evidence: Checkpoint is the current restoration mechanism; the
  proposed goal requires ledger to supplement, not replace, checkpoint.
- Gap description: Ledger and checkpoint can diverge unless integration rules
  define how checkpoint refs are recorded and validated.
- Needed action: Wire ledger recording at checkpoint/save/recovery boundaries
  and add consistency checks between task state, checkpoint refs, and ledger
  records.
- Verification: Tests cover matching checkpoint refs, missing checkpoint refs,
  stale ledger entries, and recovery refusal/diagnostics for inconsistent state.
- Dependencies: S5-G03
- Non-goal boundary: Do not make ledger the state restoration source; checkpoint
  remains responsible for restoring runtime state.
- Suggested order: 4
- Status: done
- Evidence (2026-06-20):
  - `agent/task_ledger_cooperation.py` (new): `record_checkpoint_boundary` derives
    lifecycle / step / checkpoint_ref records from a `GovernedTaskState` at the
    checkpoint save boundary and appends them via `TaskLedger.append` (which
    redacts + validates + enforces seq). It does NOT read or write the checkpoint
    file — checkpoint stays the state restoration source (AC-4).
    `check_recovery_consistency` returns a `LedgerConsistencyReport` flagging
    `missing_checkpoint_ref`, `stale_ledger_entry`, and `task_state_mismatch`;
    `report.ok` drives recovery refusal (AC-5). Readers: `latest_checkpoint_ref`,
    `latest_ledger_lifecycle`, `ledger_completed_step_count`.
  - `tests/test_s5_ledger_cooperation.py`: 8 passed (RED→GREEN). Covers matching
    (ok), missing checkpoint ref, stale ledger (checkpoint ahead), ledger-ahead-
    of-checkpoint (completed work would repeat), lifecycle mismatch, boundary
    append shape, lifecycle de-duplication, and a boundary→consistency integration.
  - Focused ruff on touched files: clean.
- Risk if ignored: S5 could record durable-looking history that does not match
  actual recoverable state.

## S5-G05 - Fake/local recovery E2E

- Gap ID: S5-G05
- Title: Fake/local recovery E2E
- Priority: P1
- Layer: L4
- Related goal section / AC: `S5_GOAL.md §5`, `§7 AC-5`
- Baseline evidence: S4 has fake/local audit/replay E2E, but no
  interruption/restart recovery E2E.
- Gap description: The selected S5 capability must be proven by an end-to-end
  governed task that stops after a durable progress point, reloads, continues,
  and verifies one coherent task history.
- Needed action: Add a deterministic fake/local test fixture and recovery flow
  covering interruption, reload, resume, and completion.
- Verification: E2E test fails before recovery implementation and passes after;
  assertions prove completed steps are not silently repeated and pending work
  resumes through the governed runtime path.
- Dependencies: S5-G03, S5-G04
- Non-goal boundary: No real provider success requirement and no external
  process/service dependency.
- Suggested order: 5
- Status: done
- Evidence (2026-06-20):
  - `tests/test_s5_reference_task_acceptance.py` (new): fake/local recovery E2E
    mirroring the S2/S4 reference-task harness, layered with the S5 ledger. Phase 1
    runs step 0 to completion, records a checkpoint+ledger boundary, then
    "interrupts". Phase 2 reloads from checkpoint + ledger, runs
    `check_recovery_consistency` (ok), resumes at step 1 (step 0 NOT repeated),
    and continues step 1 to `DONE` through the governed runtime path
    (`receive`/`accept`/`advance`/`resume`). Asserts one coherent history:
    completed step indices `{0, 1}`, monotonic ordering, latest checkpoint_ref
    present. Integrated AC-7: a synthetic key in a step-0 completion summary is
    redacted in the raw ledger file.
  - This is an acceptance test composing the verified G01-G04 units (same pattern
    as the S2/S4 reference-task tests); it passed on first run, which is the
    expected outcome for an integration of already-verified units.
  - Full S5 suite (`test_s5_*`): 44 passed. Focused ruff on touched files: clean.
- Risk if ignored: S5 would have ledger records but no product-level recovery
  proof.

## S5-G06 - Ledger-aware audit/replay alignment

- Gap ID: S5-G06
- Title: Ledger-aware audit/replay alignment
- Priority: P1
- Layer: L3
- Related goal section / AC: `S5_GOAL.md §6 L3`, `§7 AC-8`
- Baseline evidence: S4 replay/verifier/audit observability works over task
  state; ledger refs do not exist yet.
- Gap description: Recovered tasks must remain auditable and should expose
  enough ledger/evidence refs for replay consistency checks.
- Needed action: Extend audit/replay/report integration only as needed to include
  ledger refs or summaries. Preserve S4 contracts and avoid raw payload storage.
- Verification: Tests prove existing S4 replay/verifier cases still pass and a
  recovered task has coherent task/evidence/ledger refs.
- Dependencies: S5-G03, S5-G04, S5-G05
- Non-goal boundary: Do not expand verifier semantics beyond what S5 recovery
  needs; `TD-013` can remain open unless directly required.
- Suggested order: 6
- Status: done
- Evidence (2026-06-20):
  - `agent/ledger_audit_alignment.py` (new): `LedgerAuditAlignment` +
    `align_ledger_with_replay`. Verifies ledger evidence/step refs are all present
    in the S4 `ReplayChain` ref_ids; reports the latest checkpoint_ref; is
    structurally secret-free (only refs / counts / checkpoint_ref, no summaries).
    Read-only over the replay chain + ledger; no S4 module modified.
  - `agent/task_ledger_cooperation.py`: added `record_evidence_ref` — the seam that
    records a replay-chain tool/delegation event as a ledger evidence ref (redacted
    on append).
  - `tests/test_s5_ledger_audit_alignment.py`: 8 passed (RED→GREEN). Covers coherent
    alignment, unaligned evidence/step refs, checkpoint-ref reporting, structural
    secret-freedom, and that `build_replay_chain` is unaffected by ledger presence.
  - S4 replay/verifier/audit gate (`test_s4_replay_chain.py`,
    `test_s4_evidence_verifier.py`, `test_s4_audit_observability.py`): 19 passed —
    S4 contracts preserved.
  - Focused ruff on touched files: clean.
- Risk if ignored: Durable recovery would be operationally opaque and could
  weaken the S4 audit trail.

## S5-G07 - Same-spine durability guard

- Gap ID: S5-G07
- Title: Same-spine durability guard
- Priority: P1
- Layer: L1
- Related goal section / AC: `S5_GOAL.md §6 L1`, `§7 AC-6`
- Baseline evidence: S1-S4 guard against fake/real runtime splits; ledger work
  introduces a new persistence boundary that could accidentally create a second
  task runner.
- Gap description: Ledger integration must not bypass the core loop, tool
  mediator, policy/approval, checkpoint, or evidence paths.
- Needed action: Add structural and behavioral tests proving ledger writes happen
  through existing task/checkpoint/evidence seams and do not introduce a separate
  execution loop.
- Verification: Tests fail if a separate fake-only recovery runner or direct tool
  execution path is introduced.
- Dependencies: S5-G03, S5-G04
- Non-goal boundary: Do not refactor the full runtime spine to make ledger
  integration "cleaner".
- Suggested order: 7
- Status: proposed/open
- Risk if ignored: S5 could regress the project's core same-spine invariant.

## S5-G08 - Durability regression acceptance signal

- Gap ID: S5-G08
- Title: Durability regression acceptance signal
- Priority: P2
- Layer: L3/L4
- Related goal section / AC: `S5_GOAL.md §7 AC-9`
- Baseline evidence: S4 added evidence-fidelity acceptance classification, but
  there is no stable category for durability/recovery regressions.
- Gap description: Release triage needs a clear signal when recovery/ledger
  consistency fails.
- Needed action: Extend or map acceptance classification for durability failures
  with tests and docs, without weakening existing categories.
- Verification: Acceptance tests classify forged durability failures
  deterministically and preserve current evidence/runtime/debt classifications.
- Dependencies: S5-G04, S5-G05
- Non-goal boundary: Do not turn acceptance gate into a broad product-health
  dashboard.
- Suggested order: 8
- Status: proposed/open
- Risk if ignored: Durability failures could be misreported as generic runtime
  failures or hidden behind known debt.

## S5-G09 - Non-regression and release governance

- Gap ID: S5-G09
- Title: Non-regression and release governance
- Priority: P2
- Layer: L1-L5
- Related goal section / AC: `S5_GOAL.md §7 AC-1`, `§7 AC-10`
- Baseline evidence: S4 close-out required targeted gates, full pytest, work-log
  evidence, debt triage, and archive discipline.
- Gap description: S5 needs the same release discipline so ledger work does not
  overclaim or silently defer unfinished issues.
- Needed action: Keep `S5_GOAL_GAP.md`, `WORK_LOG.md`, and `TECH_DEBT.md`
  updated during the S5 gap loop; run targeted S1-S5 gates and full pytest before
  close-out.
- Verification: Work log records commands/results; full pytest is green; gap
  statuses include evidence; unresolved issues are either open in the gap file or
  carried to `TECH_DEBT.md`.
- Dependencies: All P1 implementation gaps.
- Non-goal boundary: Do not close S5 by report-only changes if the selected
  behavior is not implemented and tested.
- Suggested order: 9
- Status: proposed/open
- Risk if ignored: S5 could repeat historical overclaim patterns and undermine
  stage governance.

## S5-G10 - Extension-boundary recovery coverage

- Gap ID: S5-G10
- Title: Extension-boundary recovery coverage
- Priority: P2
- Layer: L5
- Related goal section / AC: `S5_GOAL.md §6 L5`, `§7 AC-5`, `§7 AC-6`
- Baseline evidence: S4 reference coverage uses governed MCP + read-only
  SubAgent paths; Scheduler remains dormant.
- Gap description: Durable recovery should be proven across at least one existing
  governed extension path without activating deferred ecosystems.
- Needed action: Extend the fake/local recovery reference task to include only
  existing governed MCP/SubAgent surfaces if needed to prove ledger/evidence
  integration.
- Verification: Tests prove extension events are recorded/recovered through the
  existing mediator/evidence path; Scheduler remains dormant by default.
- Dependencies: S5-G05, S5-G06, S5-G07
- Non-goal boundary: Do not implement Scheduler productionization, full MCP
  discovery, or writable SubAgent delegation.
- Suggested order: 10
- Status: proposed/open
- Risk if ignored: Ledger recovery may pass only for the simplest core task path
  and miss extension-boundary regressions.

## S5-G11 - Operator-facing ledger summary

- Gap ID: S5-G11
- Title: Operator-facing ledger summary
- Priority: P3
- Layer: L3/L4
- Related goal section / AC: `S5_GOAL.md §6 L3`, `§7 AC-8`, `§7 AC-10`
- Baseline evidence: S4 audit observability summarizes replay/verifier outcomes;
  no ledger summary exists.
- Gap description: A compact safe ledger summary would make recovery evidence
  easier to inspect, but it is not required if tests and release docs provide
  enough evidence.
- Needed action: Add a small safe-summary report only if it materially improves
  release evidence.
- Verification: Snapshot/unit tests prove summary includes lifecycle/checkpoint
  refs and excludes raw payloads/secrets.
- Dependencies: S5-G03, S5-G06
- Non-goal boundary: No UI/dashboard/demo.
- Suggested order: 11
- Status: proposed/open
- Risk if ignored: Lower operator ergonomics, but not a blocker if audit/replay
  evidence is otherwise clear.

## S5-G12 - Deferred capability guardrails

- Gap ID: S5-G12
- Title: Deferred capability guardrails
- Priority: P4
- Layer: L5/Sn
- Related goal section / AC: `S5_GOAL.md §8`, `§9 Deferred decisions`
- Baseline evidence: `TD-008`, `TD-009`, `TD-010`, `TD-012`, `TD-013`, and
  `TD-007` remain live/open/deferred unless an approved goal selects them.
- Gap description: S5 must explicitly avoid accidentally turning deferred scope
  into mandatory implementation.
- Needed action: Keep Scheduler productionization, full MCP ecosystem,
  writable/multi-agent SubAgent, broad memory activation, global lint cleanup,
  and non-critical verifier/redaction hardening out of the S5 critical path
  unless directly required by durable recovery.
- Verification: Self-review confirms deferred scope remains documented in
  `TECH_DEBT.md` or non-goals, not silently implemented or falsely marked done.
- Dependencies: S5 goal approval and all implementation planning.
- Non-goal boundary: This is a guardrail, not a work item to execute in the S5
  gap loop.
- Suggested order: 12
- Status: deferred/non-goal
- Risk if ignored: S5 could become an unreviewable platform expansion instead of
  a focused durability stage.
