# S_FINAL Gap Backlog — Roadmap Mainline Closure

> Status: **proposed / not executed**. Derived from `S_FINAL_BASELINE_STATUS.md`
> and the proposed `S_FINAL_GOAL.md`. This is the **last** gap document. The final
> gap loop is **not** executed by this document (and not authorized here).

## Priority Model

- **P0**: blocks roadmap closure judgment (the headline closure objective).
- **P1**: required safe closure cleanup.
- **P2**: bounded hardening or governance required for closure confidence.
- **P3**: optional enhancement, deferrable without blocking closure.
- **P4**: Sn/future deferred or explicit non-goal boundary.

## Baseline vs Final Goal

| Area | Baseline (post-S5) | Final goal |
|---|---|---|
| Project quality gate | `ruff check .` red, 443 errors (`TD-007`) | green (`.venv/bin/ruff check .` exit 0) |
| Dead code | `agent/context.py:36 compress_history` unreachable (`TD-003`) | deleted after re-confirming zero reachability |
| L3 evidence hardening | TD-012 (legacy preview redaction) + TD-013 (cross-kind dup) open | each closed-with-tests OR re-deferred with rationale |
| Deferred extension scope | TD-008/009/010 dormant (Scheduler/MCP/SubAgent) | stays dormant (not activated) |
| Planner facade | TD-002 cosmetic second call shape | carry-forward (not forced) |
| Tests / gates | full pytest `4940 passed`; S1-S5 targeted green | unchanged green (no regression) |
| Governance | S1-S5 archived; docs/current = roadmap + debt + final docs | closure record + clean TECH_DEBT |

## Backlog Summary

| Gap | Priority | Layer | Title | Status |
|---|---:|---|---|---|
| FINAL-G01 | P0 | L1-L5 | Full-suite quality gate green (TD-007) | proposed/open |
| FINAL-G02 | P1 | L2 | Remove confirmed-safe dead code (TD-003) | proposed/open |
| FINAL-G03 | P2 | L3 | Wire redaction into legacy mediator/record_evidence (TD-012) | proposed/open |
| FINAL-G04 | P2 | L3 | Verifier cross-kind duplicate-ref detection (TD-013) | proposed/open |
| FINAL-G05 | P2 | L1-L5 | Non-regression, closure record, debt/docs governance | proposed/open |
| FINAL-G06 | P3 | L1 | Planner/compress legacy facade (TD-002) | proposed/open (optional) |
| FINAL-G07 | P4 | L5/Sn | Deferred scope guardrails (TD-008/009/010) | deferred/non-goal |

## FINAL-G01 - Full-suite quality gate green (TD-007)

- Gap ID: FINAL-G01
- Title: Full-suite quality gate green (TD-007)
- Priority: P0
- Layer: L1-L5
- Related goal section / AC: `S_FINAL_GOAL.md §2`, `§4 AC-2`
- Baseline evidence: `.venv/bin/ruff check .` exits non-zero, `Found 443 errors`
  (257 auto-fixable); explicitly earmarked "S5/Sn batched lint pass" in
  `TECH_DEBT.md`.
- Gap description: The project-level lint gate is red — the most visible open
  "not finished" signal on an otherwise green mainline.
- Needed action: Drive `.venv/bin/ruff check .` to exit 0 via safe fixes
  (auto-fix + manual), file by file, each verified by targeted pytest so no runtime
  behavior changes.
- Verification: `.venv/bin/ruff check .` exit 0; full pytest + S1-S5 targeted gates
  stay green. Any error unsafe to fix without behavior change is recorded as residual
  debt with rationale, not silently left.
- Dependencies: none (carry-forward lint drift).
- Non-goal boundary: Do not change runtime behavior to satisfy lint; do not weaken
  tests; do not touch secrets/config.
- Suggested order: 1
- Status: proposed/open
- Risk if ignored: the red gate keeps the project looking unfinished and masks any
  future real lint regression.

## FINAL-G02 - Remove confirmed-safe dead code (TD-003)

- Gap ID: FINAL-G02
- Title: Remove confirmed-safe dead code (TD-003)
- Priority: P1
- Layer: L2
- Related goal section / AC: `S_FINAL_GOAL.md §4 AC-3`
- Baseline evidence: `agent/context.py:36 compress_history` is confirmed-unreachable
  (zero `agent.context` imports in `agent/` + `main.py`, re-confirmed at S3-G13).
- Gap description: Unreachable dead code without tool-use/tool-result pairing guards;
  safe only because unreachable.
- Needed action: Re-confirm zero reachability, delete `compress_history` from
  `agent/context.py`, keep full pytest green.
- Verification: `rg "from agent\.context import|import agent\.context" agent/ main.py`
  → no matches; full pytest green.
- Dependencies: FINAL-G01 (do not widen the lint surface mid-cleanup).
- Non-goal boundary: Do not delete other unrelated dead code; do not refactor
  `agent/memory.py` compress (the live path).
- Suggested order: 2
- Status: proposed/open
- Risk if ignored: dead code stays as a latent guard-gap.

## FINAL-G03 - Wire redaction into legacy mediator/record_evidence (TD-012)

- Gap ID: FINAL-G03
- Title: Wire redaction into legacy mediator/record_evidence (TD-012)
- Priority: P2
- Layer: L3
- Related goal section / AC: `S_FINAL_GOAL.md §4 AC-4`
- Baseline evidence: S4 `redact_text`/`redact_metadata` are wired into the replay
  chain but NOT the legacy `tool_runtime_mediator._route_result`/`mediate_pending`
  TOOL_RESULT preview nor `evidence_recorder.record_evidence` metadata. No active
  live leak (callers pre-filter; failed/rejected masked upstream).
- Gap description: A secret surviving upstream masking could reach the legacy
  event-log preview unredacted.
- Needed action: Wire `redact_text`/`redact_metadata` at the legacy projection
  points + TDD (inject a fake secret into a tool result, assert it does not appear
  in the mediator preview nor `record_evidence` metadata). If low-risk, close;
  else re-defer to Sn with rationale.
- Verification: a fake secret in a tool result is absent from the mediator
  TOOL_RESULT preview and `record_evidence` metadata; S4 replay/redaction tests
  still pass; full pytest green.
- Dependencies: FINAL-G01.
- Non-goal boundary: Do not broaden to byte-for-byte replay or raw-payload
  persistence; do not regress the hot path.
- Suggested order: 3
- Status: proposed/open
- Risk if ignored: a genuine (low-probability) legacy leak surface stays open.

## FINAL-G04 - Verifier cross-kind duplicate-ref detection (TD-013)

- Gap ID: FINAL-G04
- Title: Verifier cross-kind duplicate-ref detection (TD-013)
- Priority: P2
- Layer: L3
- Related goal section / AC: `S_FINAL_GOAL.md §4 AC-4`
- Baseline evidence: `evidence_verifier._duplicate_refs` groups by kind, so a ref_id
  shared across kinds (`tool_use_id == delegation_id`) is not flagged;
  `verify_replay_chain(...).ok` stays True. Low impact (separate id spaces).
- Gap description: A genuine verifier blind spot for cross-kind duplicate refs.
- Needed action: Extend `_duplicate_refs` to flag cross-kind duplicates + TDD. If
  low-risk, close; else re-defer to Sn with rationale.
- Verification: a chain with a tool and a delegation sharing the same `ref_id`
  fails `self_consistent` with `duplicate_ref`; existing verifier tests still pass.
- Dependencies: FINAL-G01.
- Non-goal boundary: Do not expand verifier semantics beyond duplicate-ref detection.
- Suggested order: 4
- Status: proposed/open
- Risk if ignored: a minor verifier blind spot stays open.

## FINAL-G05 - Non-regression, closure record, debt/docs governance

- Gap ID: FINAL-G05
- Title: Non-regression, closure record, debt/docs governance
- Priority: P2
- Layer: L1-L5
- Related goal section / AC: `S_FINAL_GOAL.md §4 AC-1`, `AC-6`
- Baseline evidence: S1-S5 close-outs required targeted gates, full pytest, debt
  triage, and archive discipline.
- Gap description: Roadmap closure needs the same release discipline so the final
  loop does not overclaim or silently defer.
- Needed action: Run S1-S5 targeted gates + full pytest + ruff before closure;
  keep `TECH_DEBT.md` / `docs/current/` reflecting what was closed vs deferred;
  produce a roadmap closure record mirroring the S1-S5 release summaries (final
  pytest/ruff/targeted state, resolved debt, remaining debt, no-push/no-secrets).
- Verification: work log/commits record commands + results; full pytest + ruff
  green; statuses carry evidence; unresolved items are either open here or carried
  to `TECH_DEBT.md`.
- Dependencies: FINAL-G01..G04.
- Non-goal boundary: Do not close the roadmap by report-only changes if a selected
  behavior is not implemented and tested.
- Suggested order: 5
- Status: proposed/open
- Risk if ignored: closure overclaim or silent defer.

## FINAL-G06 - Planner/compress legacy facade (TD-002)

- Gap ID: FINAL-G06
- Title: Planner/compress legacy facade (TD-002)
- Priority: P3
- Layer: L1
- Related goal section / AC: `S_FINAL_GOAL.md §5 Non-goals`
- Baseline evidence: planner/compress expose a second call shape via
  `ProviderBackedClient` over the same provider (cosmetic, not a spine split).
- Gap description: Two provider-call shapes (same provider) — cosmetic
  inconsistency.
- Needed action: Optional — consolidate to one call shape IF it falls out of the
  FINAL-G01 lint cleanup naturally; otherwise leave as carry-forward.
- Verification: if touched, Fake/Real provider still share one spine; full pytest
  green.
- Dependencies: FINAL-G01.
- Non-goal boundary: Do not force a provider-facade refactor; this is optional.
- Suggested order: 6
- Status: proposed/open (optional)
- Risk if ignored: cosmetic inconsistency remains (acceptable).

## FINAL-G07 - Deferred scope guardrails (TD-008/009/010)

- Gap ID: FINAL-G07
- Title: Deferred scope guardrails (TD-008/009/010)
- Priority: P4
- Layer: L5/Sn
- Related goal section / AC: `S_FINAL_GOAL.md §5 Non-goals`, `§6 Deferred decisions`
- Baseline evidence: TD-008 (Scheduler), TD-009 (full MCP), TD-010 (writable
  SubAgent) are scope boundaries deliberately deferred by prior frozen goals.
- Gap description: S_FINAL must avoid accidentally turning deferred scope into
  mandatory implementation.
- Needed action: Keep Scheduler productionization, full MCP ecosystem, and
  writable/multi-agent SubAgent dormant; confirm via existing boundary tests.
- Verification: self-review confirms deferred scope remains documented in
  `TECH_DEBT.md`, not silently implemented or falsely marked done.
- Dependencies: none.
- Non-goal boundary: This is a guardrail, not a work item to execute.
- Suggested order: 7
- Status: deferred/non-goal
- Risk if ignored: closure silently expands into a platform milestone.
