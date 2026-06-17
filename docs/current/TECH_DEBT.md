# Technical Debt Register

> Current cross-stage technical debt register. This file intentionally keeps only
> unresolved or needs-review debt that may affect S2/Sn.

## Rules

- Do not use this file as a general unfinished-task list.
- Resolved, approved, or completed S1 items belong in the S1 archive, not in the
  current-stage debt register.
- If resolution status is uncertain, keep the item and mark it `needs_review`.

## Open Items

## S2 Triage Summary

| Debt | S2/S3/Sn lane | Current disposition |
|---|---|---|
| TD-001 | S2 surfaced; S3/Sn full-fidelity audit if needed | Open; S2-G11 records structured task evidence, not full bodies |
| TD-002 | S3/Sn cleanup | Open; defer until planner/compress/provider adapter refactor |
| TD-003 | S2/Sn cleanup candidate | Open; confirmed unreachable, deletion deferred |
| TD-004 | S2 surfaced; S2/Sn event-log fidelity cleanup | Open; S2-G11 surfaces limitation when relevant |
| TD-006 | S2 cleanup candidate, not product release gate | Open; S2-G10 classifies as doc-governance debt |
| TD-007 | S2/Sn lint pass, not product release gate | Open; S2-G12 requires focused ruff for new/modified Python files |

See `docs/current/S2_TECH_DEBT_TRIAGE.md` for the S2-G13 triage rationale.

### TD-001 - Evidence does not persist full model request/response body

- ID: TD-001
- Title: Evidence does not persist full model request/response body.
- Status: open
- Priority: P2
- Scope: L3 Evidence
- Impact: Evidence records keep `safe_summary` and size metadata, but cannot
  replay full model/tool payloads byte-for-byte.
- Suggested phase: S2/Sn, when full-fidelity audit or compliance traceability is
  required.
- Verification: Review `agent/evidence_recorder.py` evidence persistence behavior
  and archived S1 gap G-11.

### TD-002 - Planning/compress still use legacy client facade

- ID: TD-002
- Title: Planning/compress still use legacy client facade.
- Status: open
- Priority: P3
- Scope: L1 Runtime Spine
- Impact: Provider calls share the same provider underneath, but planner/compress
  still expose a second call shape through `ProviderBackedClient`.
- Suggested phase: S2/Sn, when planner/compress or `legacy_adapter.py` is next
  refactored.
- Verification: Review `agent/provider/legacy_adapter.py` and call sites in
  `agent/core.py`.

### TD-003 - Secondary context compression path is unreachable dead code

- ID: TD-003
- Title: Secondary context compression path is confirmed-unreachable dead code
  (cleanup target, not a reachability question).
- Status: open (confirmed unreachable during S2 baseline audit, 2026-06-17;
  dead code not yet removed)
- Priority: P3
- Scope: L2 Context
- Impact: Main runtime uses guarded memory compression (`agent/memory.py:220
  compress_history`, imported by `agent/core.py:66`, called at `core.py:1305`),
  while the older `agent/context.py:36 compress_history` has **zero imports in
  src** and is not reachable from any active entrypoint. It is dead code without
  tool-use/tool-result pairing guards; safe only because it is unreachable.
- Suggested phase: S2/Sn dead-code cleanup when `agent/context.py` or the L2
  context module is next touched.
- Verification: 2026-06-17 S2 baseline audit —
  `rg "from agent\.context import|import agent\.context|from \.context import"
  agent/ main.py` -> no matches; active compression path is `agent/memory.py:220`
  only. Reachability question closed: path is unreachable; remaining work is dead
  code removal, not a pairing-guard fix.

### TD-004 - Pending-tool events log omits tool output preview

- ID: TD-004
- Title: Pending-tool events log omits tool output preview.
- Status: open
- Priority: P3
- Scope: L3 Evidence
- Impact: Pending-tool results are stored in conversation/state logs, but
  `events.jsonl` may show an empty `tool_output` preview for that route.
- Suggested phase: S2/Sn, when improving event-log fidelity or debugging
  pending-tool traces.
- Verification: Review `execute_pending_tool` and mediator `_route_result`
  behavior around `turn_context[tool_use_id]`.

### TD-006 - Stale guard / documentation-governance / architecture-boundary tests keep full-suite red

- ID: TD-006
- Title: Stale guard / documentation-governance / architecture-boundary / taxonomy /
  diagnostics / contract guard tests keep the full-suite health check red.
- Status: open
- Priority: P1
- Scope: Cross-cutting Tests + Docs Governance
- Impact: Full-suite health is red. The 36 failures span more than pre-S1 doc
  locations: documentation-governance / source-of-truth guards
  (`test_docs_source_of_truth.py`), architecture-boundary guards
  (`test_v6_drift_addendum_boundary.py`, `test_architecture_boundaries.py`,
  `test_capability_boundary_contract.py`), taxonomy guards
  (`test_evidence_taxonomy_guard.py`), a diagnostics string/flag mismatch
  (`test_provider_diagnostics.py`), and a guard referencing a doc moved to history
  (`test_streaming_protocol.py`). None are in the S1 acceptance gate, observability
  verification, or core-runtime tests, so this is a guard/governance cleanup rather
  than a runtime regression.
- Suggested phase: S2 baseline cleanup, or a separate Sn pass, before relying on
  full-suite status as a release signal. Update each guard only against confirmed
  current governance docs/contracts.
- Verification: Run full pytest after S2 docs settle; classify each failure and
  update the guard against current governance docs/contracts (not by weakening
  assertions silently). See
  `docs/current/_tmp_s2_baseline_audit/fullsuite_failures.txt` for the
  authoritative failure list.

### TD-007 - ruff full-suite lint is red with ~451 historical errors

- ID: TD-007
- Title: `ruff check .` is red with ~451 historical lint errors (import
  organization, etc.).
- Status: open
- Priority: P3
- Scope: Cross-cutting Lint / Quality gate
- Impact: Project-level lint gate is non-green. Independent of TD-006 (different
  source: lint style vs. doc/governance guards). Not an S2 startup blocker and not
  a runtime regression; tracked so lint health is not silently ignored.
- Suggested phase: S2/Sn lint pass, separate from TD-006 guard cleanup, when a
  batched lint fix is in scope.
- Verification: `.venv/bin/ruff check .`; target exit 0. Do not mix into TD-006
  unless a shared root cause is proven.
