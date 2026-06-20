# S5 Release Summary — Durable Governed Task Recovery

> Archive summary for S5. This is an evidence/record document, not routing
> authority. S5 is complete; roadmap final-audit planning now lives under
> `docs/current/`.

- **Release name**: S5 — Durable Governed Task Recovery
- **Verdict**: **completed / release-ready after independent audit + findings fixed**
- **Stage window**: S4 close-out → S5 baseline/goal/gap → goal freeze → S5 gap loop
  G01-G11 (G12 non-goal) → independent audit + fixes → S5 close-out (2026-06-20)
- **Close-out commit**: `fb677ed` (audit-findings fix) → close-out commit (this archive)

## 1. S5 goal

S5 = **Durable Governed Task Recovery**. Core = **L2/L4 Durability Maturation**: add
a local-only, governed, durable task ledger that records task lifecycle, step
progress, checkpoint refs, and evidence refs at a safe-summary level — supplementing
(not replacing) the existing checkpoint/runtime spine.

Selected scope (frozen 2026-06-20):

- narrow ledger contract (lifecycle / step / checkpoint-ref / evidence-ref records);
- secret-safe redaction boundary for every persisted ledger field;
- local JSONL durable storage (append-only, crash-survivable read);
- checkpoint-ledger cooperation + recovery consistency diagnostics;
- fake/local recovery E2E (interrupt → reload → continue, completed steps not repeated);
- ledger-aware audit/replay alignment (S4 ReplayChain ref coherence);
- same-spine durability guard (no second runtime/runner/tool-exec path);
- durability regression acceptance classification;
- extension-boundary recovery coverage (governed MCP + read-only SubAgent);
- operator-facing ledger summary.

Non-goals held: no second runtime spine, no Scheduler/memory/full-MCP/writable-
SubAgent activation, no production DB, no raw-secret persistence, no real-provider
live-success requirement, no UI/demo/commercial packaging.

Frozen decisions (§9): ledger storage = local append-only JSONL; durability
acceptance = new `DURABILITY_REGRESSION` class; `TD-012` stays out of the critical
path (ledger never sources a persisted field from the legacy preview); `TD-013`
stays deferred (ledger consistency is ledger-internal + replay-ref alignment).

## 2. Completed gaps

| Gap | Status | Evidence |
|---|---|---|
| S5-G01 ledger contract + reference task | satisfied | `agent/task_ledger.py`; `tests/test_s5_ledger_contract.py` |
| S5-G02 ledger safety/redaction boundary | satisfied | `redact_ledger_record` in `agent/task_ledger.py`; `tests/test_s5_ledger_redaction.py` |
| S5-G03 local durable ledger storage API | satisfied | `agent/task_ledger_store.py`; `tests/test_s5_ledger_store.py` |
| S5-G04 checkpoint-ledger cooperation | satisfied | `agent/task_ledger_cooperation.py`; `tests/test_s5_ledger_cooperation.py` |
| S5-G05 fake/local recovery E2E | satisfied | `tests/test_s5_reference_task_acceptance.py` |
| S5-G06 ledger-aware audit/replay alignment | satisfied | `agent/ledger_audit_alignment.py`; `tests/test_s5_ledger_audit_alignment.py` |
| S5-G07 same-spine durability guard | satisfied | `tests/test_s5_same_spine_guard.py` |
| S5-G08 durability regression acceptance signal | satisfied | `agent/acceptance_gate.py`; `tests/test_s5_acceptance_gate_durability_classification.py` |
| S5-G09 non-regression + release governance | satisfied | gates + full pytest in WORK_LOG |
| S5-G10 extension-boundary recovery coverage | satisfied | `tests/test_s5_extension_recovery_coverage.py` |
| S5-G11 operator-facing ledger summary | satisfied | `agent/ledger_summary.py`; `tests/test_s5_ledger_summary.py` |
| S5-G12 deferred capability guardrails | deferred/non-goal | guardrail only; not executed |

## 3. Acceptance coverage

- **AC-1 no regression**: full pytest green (`4940 passed`); S1-S5 targeted gates pass.
- **AC-2 narrow ledger contract**: 4 frozen record kinds; required-field validation;
  per-task_id strictly-increasing seq; no raw-payload/secret fields.
- **AC-3 local deterministic persistence**: local JSONL, caller-injected path,
  crash-survivable read; no DB/network/home-config.
- **AC-4 checkpoint-ledger cooperate**: checkpoint stays the state restoration source;
  ledger provides audit/progress continuity; consistency diagnostics detect
  missing/stale/mismatch.
- **AC-5 recovery E2E**: fake/local task interrupts after a durable point, reloads
  from checkpoint+ledger, resumes at the next step (completed step not repeated), and
  finishes via the governed runtime path.
- **AC-6 same-spine**: ledger modules import no execution spine (AST guard), expose
  only `{append, read_all}`, and do not drive stepping.
- **AC-7 secret-safe**: free-text ledger fields are redacted before persistence
  (synthetic keys stripped in raw bytes + read-back).
- **AC-8 S4 audit/replay alignment**: ledger evidence/step refs align with the S4
  ReplayChain ref_ids; S4 `build_replay_chain`/verifier contracts unchanged.
- **AC-9 durability acceptance signal**: `DURABILITY_REGRESSION` classifies durability
  failures without weakening runtime/extension/evidence-fidelity/debt classes.
- **AC-10 governance/docs current**: gap/work-log/debt reflect what was implemented,
  deferred, or left open.

## 4. durable recovery / ledger / checkpoint / evidence boundaries

- **Ledger ≠ second spine**: `TaskLedger` is storage-only (`append`/`read_all`); it
  never executes tools, calls the provider, drives the loop, or restores state.
- **Checkpoint remains recovery truth**: `load_checkpoint_to_state` restores runtime
  state; the ledger only records durable audit/progress continuity and is never the
  restoration source (frozen §9).
- **`report.ok` is a signal, not a gate**: `check_recovery_consistency().ok` is a
  callable consistency diagnostic a recovery flow *can* consult; S5 added **no**
  production resume gate that auto-blocks on it (corrected from an earlier overclaim).
- **No raw payloads**: ledger records carry only ids/paths/counts/safe-summary;
  free-text fields pass through `evidence_redaction.redact_text` on persist.
- **Audit coherence**: recovered-task ledger refs align with the S4 ReplayChain;
  `record_evidence_ref` records tool/delegation events as ledger evidence refs.

## 5. Verification summary

- Full pytest: `.venv/bin/python -m pytest -q -rx` -> `4940 passed, 16 skipped,
  28 xfailed, 0 failed` (post audit-findings fix; S1-S4 baseline + S5 tests).
- S5 targeted (`tests/test_s5_*.py`): `73 passed`.
- Stage gates: S1 `22 passed`; S2 `32 passed, 1 skipped`; S3 extension `124 passed`;
  S4 `44 passed, 1 skipped`.
- Focused ruff on all S5 agent modules + tests: clean (global ruff remains red under
  `TD-007`, untouched by S5).
- Independent read-only audit (project-auditor): verdict **PASS (release-ready)**,
  no P0/P1/P2/P3 findings; AC-1..AC-10 satisfied.

## 6. Debt disposition

Resolved in S5 and removed from the live register at close-out:

- **TD-011**: resolved as the **durable governed task ledger** (S5-G01..G11).

Remaining live debt in `docs/current/TECH_DEBT.md`:

- **Open / carry-forward**: TD-002, TD-003, TD-007, TD-012, TD-013.
- **Deferred to Sn/future**: TD-008 (Scheduler), TD-009 (full MCP), TD-010 (writable
  SubAgent).

## 7. Independent audit issues and fixes

A post-implementation independent audit surfaced findings; all were fixed in commit
`fb677ed` (none deferred to debt):

- **MEDIUM-1 (overclaim)**: corrected "`report.ok` drives recovery refusal" →
  "callable consistency signal / diagnostic; NOT auto-wired as a production resume
  gate" in the G04 evidence and WORK_LOG. AC-5 holds via checkpoint + governed-runtime
  semantics (S5-G05 E2E).
- **MEDIUM-2 (guard coverage)**: `agent.ledger_summary` was missing from the same-spine
  guard's module list; added to `_LEDGER_MODULES` and the scheduler-dormancy set;
  "four modules" wording → "five".
- **MEDIUM-3 (stale status)**: S5 stage docs no longer say "proposed / not executed";
  README/AGENTS updated to "S5 implemented" (then "archived" at close-out).
- **LOW (test hardening, all fixed in-place)**: expanded forbidden-field aliases;
  added ghp_/AKIA/xox/AIza/password secret-pattern coverage; half-written-tail crash
  case; delegation `evidence_kind` alignment; dynamic-import guard; summary-stats
  structural secret-exclusion.

## 8. Real provider caveat

S5 had **no real-provider live-success requirement** (explicit non-goal). All S5
evidence is structural + fake/local deterministic. No real provider/MCP/external
endpoint was contacted during S5.

## 9. Safety statement

- No push was performed.
- No tags were created, deleted, retargeted, or pushed.
- No `.env` or `config/config.yaml` contents were read, printed, copied, moved,
  staged, or committed (`git ls-files config/config.yaml .env` is empty; both are
  `.gitignore`-d).
- No S1/S2/S3/S4 history was modified.
- `report.ok` is documented as a non-gating signal (no false production-gate claim).
