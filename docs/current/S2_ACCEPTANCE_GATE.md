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
