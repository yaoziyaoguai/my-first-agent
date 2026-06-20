# S4 Release Summary — Auditable Governed Agent Runtime

> Archive summary for S4. This is an evidence/record document, not routing
> authority. S4 is complete; S5 planning now lives under `docs/current/`.

- **Release name**: S4 — Auditable Governed Agent Runtime
- **Verdict**: **completed / release-ready after independent audit**
- **Stage window**: S3 close-out → S4 baseline/goal/gap → S4 gap loop G01-G12 →
  whole-stage audit + fixes → S4 close-out (2026-06-20)
- **Close-out commit**: `d82e9cc`

## 1. S4 goal

S4 = **Auditable Governed Agent Runtime**. Core = **L3 Evidence & Audit Fidelity
Maturation**: preserve the S1/S2/S3 same-spine runtime while making governed work
**redacted-faithful**, replayable, and verifiable.

Selected scope:

- replay-faithful evidence over governed tasks, including MCP tool source and
  read-only SubAgent delegation;
- secret-safe redaction for the new high-fidelity replay surface;
- pending-tool event preview fidelity;
- evidence verifier for completeness/self-consistency/order/replayability;
- fake/local audit-replay reference task and key-safe opt-in real provider smoke
  harness;
- acceptance-gate classification for evidence-fidelity regressions.

Non-goals held: no raw secret persistence, no byte-for-byte full payload
persistence, no second runtime spine, no memory activation, no durable ledger, no
Scheduler productionization, no full MCP ecosystem, no writable/multi-agent
SubAgent expansion.

## 2. Completed gaps

| Gap | Status | Evidence |
|---|---|---|
| S4-G01 fidelity contract/reference task | satisfied | `S4_FIDELITY_CONTRACT.md` |
| S4-G02 replay-faithful model | satisfied | `agent/task_replay_chain.py`; `tests/test_s4_replay_chain.py` |
| S4-G03 secret-safe redaction | satisfied | `agent/evidence_redaction.py`; `tests/test_s4_evidence_redaction.py` |
| S4-G04 pending-tool preview | satisfied | `agent/tool_runtime_mediator.py`; `tests/test_s4_pending_tool_preview.py` |
| S4-G05 evidence verifier | satisfied | `agent/evidence_verifier.py`; `tests/test_s4_evidence_verifier.py` |
| S4-G06 fake/local reference E2E | satisfied | `tests/test_s4_reference_task_acceptance.py` |
| S4-G07 real provider key-path smoke | satisfied | opt-in/default-skip smoke harness in `tests/test_s4_reference_task_acceptance.py` |
| S4-G08 acceptance classification | satisfied | `agent/acceptance_gate.py`; `tests/test_s4_acceptance_gate_evidence_classification.py` |
| S4-G09 docs governance | satisfied | close-out checklist in archived `S4_GOAL_GAP.md` |
| S4-G10 non-regression/full-suite signal | satisfied | full pytest green after S2 safe-summary regression fix |
| S4-G11 audit observability | satisfied | `agent/audit_observability.py`; `tests/test_s4_audit_observability.py` |
| S4-G12 deferred triage | satisfied | deferred items remain in live `TECH_DEBT.md` |

## 3. Acceptance coverage

- **AC-1 S1/S2/S3 must-not-regress**: targeted S1/S2/S3/S4 gates passed during
  close-out audit; same-spine and extension boundaries held.
- **AC-2 replay-faithful evidence**: `build_replay_chain` reconstructs ordered
  decision/tool/delegation chains from existing task state.
- **AC-3 secret-safe fidelity**: replay-chain previews redact synthetic key
  patterns; raw secrets are not persisted in the S4 high-fidelity surface.
- **AC-4 pending-tool fidelity**: pending `TOOL_RESULT` preview is non-empty for
  result-bearing tools, and failed/rejected pending tools no longer report
  `executed/success`.
- **AC-5 evidence verification**: verifier detects missing entries, count/status
  mismatch, sequence disorder, empty chains, and same-kind duplicate refs.
- **AC-6 reference task**: fake/local governed MCP + SubAgent reference task
  completes execute→record→replay→verify; real provider smoke is opt-in and
  key-safe.
- **AC-7 acceptance gate**: evidence-fidelity failures classify as
  `EVIDENCE_FIDELITY_REGRESSION` without weakening runtime/extension/debt classes.
- **AC-8 governance**: S1/S2/S3 archives stayed untouched; S4 docs archived here;
  live `TECH_DEBT.md` keeps only unresolved/deferred/carry-forward items.
- **AC-9 release signal**: full pytest remained green during whole-stage audit.

## 4. Verification summary

Independent close-out audit re-ran targeted gates:

- S4 suite: `44 passed, 1 skipped` (`tests/test_s4_*.py`)
- S1 targeted: `22 passed`
- S2 targeted: `32 passed, 1 skipped`
- S3 targeted: `30 passed, 1 skipped`
- Focused ruff on S4-touched Python/test files: clean
- Prior S4 whole-stage audit full pytest: `4867 passed, 16 skipped, 28 xfailed,
  0 failed`

Final close-out verification is recorded in the user-facing close-out report and
in the post-S5 planning `WORK_LOG.md`.

## 5. Real provider caveat

S4's real provider audit smoke is **key-safe opt-in** via
`MY_FIRST_AGENT_RUN_S4_REAL_PROVIDER_SMOKE=1` and skips by default. The harness
uses the production provider factory and the same governed audit/replay path, but
live real-key success is not a release blocker. During S4 audit, one opt-in run
entered the real provider path and timed out in the environment without leaking a
key; release evidence remains structural + fake/local E2E.

## 6. Debt disposition

Resolved in S4 and removed from the live register at close-out:

- **TD-001**: resolved as **redacted-faithful replay**, not byte-for-byte raw
  persistence.
- **TD-004**: pending-tool `tool_output` preview gap resolved.

Remaining live debt in `docs/current/TECH_DEBT.md`:

- **Open / carry-forward**: TD-002, TD-003, TD-007, TD-012, TD-013.
- **Deferred**: TD-008, TD-009, TD-010, TD-011.

## 7. Safety statement

- No push was performed.
- No tags were created, deleted, retargeted, or pushed.
- No `.env` or `config/config.yaml` contents were read, printed, copied, moved,
  staged, or committed.
- No real MCP endpoint or external server was contacted.
