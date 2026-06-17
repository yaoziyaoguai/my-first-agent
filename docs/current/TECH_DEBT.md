# Technical Debt Register

> Current cross-stage technical debt register. This file intentionally keeps only
> unresolved or needs-review debt that may affect S2/Sn.

## Rules

- Do not use this file as a general unfinished-task list.
- Resolved, approved, or completed S1 items belong in the S1 archive, not in the
  current-stage debt register.
- If resolution status is uncertain, keep the item and mark it `needs_review`.

## Open Items

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

### TD-003 - Secondary context compression path needs reachability review

- ID: TD-003
- Title: Secondary context compression path is unreachable dead code.
- Status: open (confirmed unreachable during S2 baseline audit, 2026-06-17)
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

### TD-006 - Pre-S1 documentation-governance guard tests are stale

- ID: TD-006
- Title: Pre-S1 documentation-governance guard tests are stale.
- Status: open
- Priority: P1
- Scope: Cross-cutting Tests + Docs Governance
- Impact: Full-suite health may remain red because several guard tests encode
  pre-S1 documentation locations and README/source-of-truth expectations.
- Suggested phase: S2 baseline audit, before relying on full-suite status as a
  release signal.
- Verification: Run full pytest after S2 docs settle; inspect failures in
  documentation-governance tests and update them only against confirmed current
  governance docs.
