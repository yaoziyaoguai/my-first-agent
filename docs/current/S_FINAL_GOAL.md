# S_FINAL Goal — Roadmap Mainline Closure

> Status: **proposed** (roadmap final goal, not yet frozen). This is **not** a new
> product stage (no S6) and **not** capability expansion. It defines how the
> S-series roadmap mainline closes after S1-S5 are archived, derived from
> `S_ROADMAP.md`, `S_FINAL_BASELINE_STATUS.md`, and `TECH_DEBT.md`. The final gap
> loop is **not** executed by this document.

## 1. Executive Summary

**S_FINAL = Roadmap Mainline Closure (quality gate + safe hardening + closure
evidence).**

S1-S5 delivered a realizable, explainable, acceptance-tested agent runtime across
L1-L5. The baseline found **no blockers** to mainline closure — all open items are
carry-forward hardening/cleanup debt or scope boundaries deliberately deferred to
Sn/future. The final stage therefore closes the **bounded, low-risk** debt that
materially tightens the mainline, documents the closure, and proves no regression —
without adding capability, activating deferred scope, or forcing risky/large debt.

Why this direction:

- It closes the most visible "not finished" signal — the red full-suite lint gate
  (`TD-007`, 443 historical errors, explicitly earmarked "S5/Sn batched lint pass").
- It removes confirmed-safe dead code (`TD-003`).
- It opportunistically tightens L3 evidence fidelity (`TD-012`/`TD-013`) where
  low-risk.
- It preserves the S1-S5 same-spine, durability, and acceptance guarantees.

## 2. Selected Final Objective

> Close the carry-forward debt that is bounded and low-risk — prioritize driving
> the full-suite quality gate to green (`TD-007`) and removing confirmed-safe dead
> code (`TD-003`) — opportunistically close bounded L3 evidence-hardening
> (`TD-012`, `TD-013`) where safe, keep all deferred extension scope (`TD-008/
> 009/010`) dormant, and produce a roadmap closure record with full pytest + ruff +
> targeted gates green and no regression.

The final stage MUST stay within the roadmap (`S_ROADMAP.md`): no second runtime
spine, no Scheduler/memory/full-MCP/writable-SubAgent activation, no production DB,
no raw-secret persistence, no real-provider live-success requirement, no UI/demo/
commercial packaging, no new product stage (no S6).

## 3. Debt Disposition (final-must vs Sn/future)

**Final loop MUST close:**

- `TD-007` — full-suite `ruff check .` green (the headline closure objective; the
  project-level lint gate is the most visible open signal).

**Final loop SHOULD close (safe / bounded):**

- `TD-003` — delete confirmed-unreachable `agent/context.py:36 compress_history`
  dead code (zero `agent.context` imports; safe).
- `TD-012` — wire S4 redaction into the legacy mediator TOOL_RESULT preview +
  `record_evidence` metadata (close if low-risk during the loop; else defer with
  rationale).
- `TD-013` — evidence verifier cross-kind duplicate-ref detection (close if
  low-risk; else defer with rationale).

**Final loop MUST NOT force (stay Sn/future):**

- `TD-002` — planner/compress legacy facade (cosmetic; carry-forward).
- `TD-008` — Scheduler productionization / main-loop activation (deferred scope).
- `TD-009` — full MCP ecosystem (deferred scope).
- `TD-010` — writable / multi-agent SubAgent (deferred scope).

## 4. Acceptance Criteria

### AC-1 — No regression across S1-S5
S1/S2/S3/S4/S5 targeted gates and full pytest remain green with only explicit known
xfails/skips. Same-spine, durability, and acceptance-classification invariants hold.

### AC-2 — Project quality gate is green (TD-007 closed)
`.venv/bin/ruff check .` exits 0. Any historical error that proves unsafe to fix
without behavior change is recorded as residual debt with rationale, not silently
left.

### AC-3 — Confirmed-safe dead code removed (TD-003 closed)
`agent/context.py:36 compress_history` is deleted after re-confirming zero
reachability; full pytest stays green.

### AC-4 — Bounded evidence hardening triaged (TD-012 / TD-013)
Each of TD-012 / TD-013 is either closed with tests (redaction wired into the legacy
preview / cross-kind dup detection) or explicitly re-deferred to Sn with a recorded
rationale. Neither is silently left ambiguous.

### AC-5 — Deferred scope stays dormant
TD-008 / TD-009 / TD-010 remain deferred; no Scheduler/memory/full-MCP/writable-
SubAgent activation is introduced. TD-002 stays carry-forward.

### AC-6 — Roadmap closure record
`TECH_DEBT.md` reflects exactly what the final loop closed vs deferred;
`docs/current/` is the post-closure working set; a roadmap closure summary records
final pytest/ruff/targeted state, resolved debt, remaining debt, and the no-push /
no-secrets statement.

## 5. Non-goals

- No new runtime/extension/durability capability (the mainline is functionally
  complete after S5).
- No Scheduler productionization, memory activation, full MCP ecosystem, or writable
  SubAgent (TD-008/009/010 stay deferred).
- No provider-facade refactor (TD-002 cosmetic; carry-forward).
- No UI/demo/commercial packaging.
- No new product stage (no S6).
- No real-provider live-success requirement.
- No raw-secret persistence or byte-for-byte replay.

## 6. Open / Deferred Decisions

- **Open**: whether TD-012 and TD-013 can be closed low-risk during the final loop
  or are re-deferred to Sn — decided per-gap with TDD + risk check.
- **Open**: residual TD-007 errors that cannot be safely auto-fixed — recorded as
  residual debt with rationale rather than forced.
- **Resolved**: TD-008/009/010 stay deferred (not final-must); TD-002 stays
  carry-forward (not final-must).
- **Deferred to Sn/future**: TD-002 (facade), TD-008 (Scheduler), TD-009 (full MCP),
  TD-010 (writable SubAgent), plus any TD-012/013 the final loop re-defers.

## 7. Roadmap Fit

This goal does not expand the roadmap. `S_ROADMAP.md` defines the five-layer
mainline and refuses to encode a hard Sn plan; the mainline is functionally complete
after S5 with no blockers. The final stage closes bounded debt + produces closure
evidence so the S-series runtime is clean-shippable. It is the natural "Sn batched
lint pass + closure" that `TECH_DEBT.md` earmarked, not a new direction.
