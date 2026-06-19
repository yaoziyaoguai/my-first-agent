# S2 Acceptance Gate

S2 release judgment uses targeted S2 acceptance checks as the product signal.
Full pytest and full ruff remain health/debt signals unless their failures are
classified as runtime regressions.

## Signal Classes

- `passed`: check passed and is not release blocking.
- `runtime_regression`: targeted S2 runtime acceptance failed; release blocking.
- `doc_governance_debt`: known TD-006 documentation-governance /
  architecture-boundary / taxonomy / diagnostics / contract guard failures; not
  release blocking by itself.
- `quality_debt`: known TD-007 lint/ruff debt; not release blocking by itself.
- `unknown_failure`: unclassified failure; release blocking until classified.

## Rules

- Targeted S2 acceptance failures are release blockers.
- Full pytest failures that are entirely in the TD-006 guard set are health/debt
  signals, not runtime regression signals.
- Ruff failures are TD-007 quality-debt signals, not S2 product failures.
- Unknown failures stay release-blocking until they are classified.
- This document does not close TD-006 or TD-007; it only prevents their signal
  from being mixed into S2 runtime acceptance.

## Full-pytest failure classification

When running the full pytest suite, every failure MUST be classified into one of:

- **TD-006 doc-governance debt** — stale guard / source-of-truth /
  architecture-boundary / taxonomy / diagnostics / contract guard tests asserting
  against pre-S2 or frozen inventories. Known file set:
  `test_docs_source_of_truth.py`, `test_v6_drift_addendum_boundary.py`,
  `test_architecture_boundaries.py`, `test_evidence_taxonomy_guard.py`,
  `test_provider_diagnostics.py`, `test_streaming_protocol.py`,
  `test_capability_boundary_contract.py`. Not release blocking by itself.
- **TD-007 quality debt** — `ruff check .` historical lint errors. Not release
  blocking by itself.
- **runtime regression** — a failure in targeted S2/S1 acceptance, observability,
  or core-runtime tests. Release blocking.
- **unknown failure** — any failure not in the TD-006/TD-007 known set and not yet
  classified. **Release blocking until classified.**

A failure may be moved out of "unknown" only by proving it belongs to a known TD
set or by fixing it. Relabeling without evidence is forbidden.

## Skill default-off test contract (S2-G09)

S2 Skill activation is default-off. Tests are split by what they exercise:

- **discovery / metadata tests** (registry scanning, selector, descriptor shape)
  do NOT opt in — `MY_FIRST_AGENT_S2_SKILL_ENABLE` stays unset. Discovery stays
  S1 behavior (registry still scans `skills/`).
- **activation / execution tests** (SKILL_SELECT registration/handler execution,
  prompt body injection, checkpoint restore, full selection→activation path) MUST
  opt in explicitly via `monkeypatch.setenv("MY_FIRST_AGENT_S2_SKILL_ENABLE", "1")`
  (module-level autouse fixture or per-test/class).

A skill-activation test that fails because it did not opt in is a **test-contract
gap**, not a runtime regression and not TD-006. The fix is to add the opt-in, not
to weaken the gate or relabel the failure as doc-governance debt.
