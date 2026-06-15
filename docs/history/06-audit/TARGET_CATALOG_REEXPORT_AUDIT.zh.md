# TargetCatalog identity + re-export audit (U4)

Date: 2026-06-12
Author: ce-work (U4 of plan
`docs/plans/2026-06-12-001-fix-architecture-repair-sot-truth-plan.md`)

## Scope

WP-C / U4: audit three things per the plan:

1. **callable_identity shape and stability** — must not break external
   callers; the re-exports must keep working.
2. **In-process-only invariant** — `callable_identity` is a
   process-local value derived from `id(callable)` plus
   `function:<module>.<qualname>`. It is NOT a stable external
   contract.
3. **Private re-export consumers** — `evidence.py` re-exports
   `RuntimeActionTargetCatalog`, `RuntimeActionTargetDescriptor`,
   `_callable_identity`, and `_checkpoint_safe_summary_adapter` from
   `target_catalog.py`. If any production caller depends on these
   imports, they must be moved to direct imports from
   `target_catalog.py` first; the re-export can be narrowed once
   nothing imports the private names from `evidence.py`.

## Findings

### 1. callable_identity shape

`agent.runtime_integration.target_catalog._callable_identity(callable)` returns
`f"function:{callable.__module__}.{callable.__qualname__}"` with a `id()`-derived
shorter discriminator prefix. **Process-local** by design: the id-derived
component is stable within a process but not across processes or restarts.
This is documented in
`tests/runtime_integration/test_target_catalog_extraction.py:41-50`
and locked by the existing
`test_callable_identity_still_uses_function_module_path` test.

**Conclusion:** callers must treat callable_identity as process-local.
The plan's hard constraint "do not redesign identity or freeze a
concrete module path as external contract" is preserved.

### 2. Re-export consumer census

A `grep` for each of the four re-exported names across `agent/` and
`tests/` (excluding the re-export site itself) returned:

| Re-exported name | Production callers | Test callers |
|---|---|---|
| `RuntimeActionTargetCatalog` | 0 | 1 (`test_target_catalog_boundary.py:19`) |
| `RuntimeActionTargetDescriptor` | 0 (only used inside `evidence.py` itself) | 0 |
| `_callable_identity` | 1 (inside `evidence.py` itself, line 263) | 1 (`test_target_catalog_extraction.py:45`) |
| `_checkpoint_safe_summary_adapter` | 1 (inside `evidence.py` via re-export import) | 0 |

Production code outside `evidence.py` does not import any of these
names from `evidence.py`. All four re-exports exist only for back-compat
with the pre-extraction code path. The single test consumer of
`RuntimeActionTargetCatalog` (line 19) is the only external import
site.

### 3. Decision: keep all four re-exports

The plan's gate is "narrow only if zero consumers; else exit plan".
External consumers exist for three of the four names (one test
consumer each), so the re-export cannot be narrowed without breaking
the back-compat contract. The audit returns **no production diff**.

## Doc-note change (the only real diff for U4)

A one-paragraph doc note is added to
`agent/runtime_integration/target_catalog.py` documenting the
process-local callable_identity invariant, so future readers of the
catalog do not assume the identity is a stable external contract.

A one-line note is added to the re-export block in
`agent/runtime_integration/evidence.py` linking to the audit doc and
stating the re-export is **process-local** back-compat only.

## Rollback

`git revert` of the U4 commit removes the two doc-only additions. No
code behavior changes; no callers touched; no test removed.

## Deferred debt

- The plan defers any further narrowing of the re-export to a future
  window when callers have been migrated. Recorded as
  documented_pending in `CURRENT_AUDIT_STATUS.zh.md` (U7).
