# V0 Wiring Decision (U6)

Date: 2026-06-12
Author: ce-work (U6 of plan
`docs/plans/2026-06-12-001-fix-architecture-repair-sot-truth-plan.md`)

## Status

**Decision: PENDING (Option 2 lead; Option 1 fallback).** This run does
NOT wire V0 (per plan hard constraint). The doc records the two
plausible wiring options, the comparison, and the recommended path for
the next migration window.

## Context

The current live state is an incomplete L1/L2→V0 migration:

* `SubAgentV0Handler` is **registered** in
  `agent.runtime_integration.subagent_action` and contract-verified
  (12/12 dispatcher dispatch tests pass).
* `core.py`'s CLI/NL delegation entry still routes through
  `...ages 200-500 to migrate call sites and audit evidence shape.
2. **Option 2 risk:** A concurrent v0 contract change forces a
   re-audit. Mitigation: the v0 contract is currently stable
   (12/12 contract-verified); the next contract change must update
   this doc.

## Rollout of Option 2 (future, not in this run)

1. **Window:** post-2026-06.
2. **Owner:** the next owner of `core.py` (U6 defers to U7/U8 roadmap).
3. **Exit condition:** `core.py` delegates to `SubAgentV0Handler`;
   `SubAgentDelegateL0Handler` removed; integration tests at
   `tests/runtime_integration/test_subagent_v0_runtime_boundary.py`
   exercise the live path.
4. **Next step:** see the `CURRENT_AUDIT_STATUS.zh.md` U7 entry.
