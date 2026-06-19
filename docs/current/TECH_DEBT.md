# Technical Debt Register

> Post-S2 / pre-S3 carry-forward register. S2 is complete and archived under
> `docs/history/S2_GOVERNED_TASK_AGENT/`. This file keeps only **unresolved**
> debt that may affect S3/Sn. Do not use this file as a general unfinished-task
> list; do not write S3 goals here (S3 is not started).

## Rules

- Carry-forward debt only — items the project deliberately deferred beyond S2.
- Resolved S1/S2 items belong in the S1/S2 archives, not here.
- If resolution status is uncertain, keep the item and mark it `needs_review`.
- Each item states: ID, title, status, source/reason, impact, recommended
  stage, and a verification idea.

## Open / Carry-forward items

### TD-006 - Stale guard / governance / architecture-boundary tests keep full-suite red

- ID: TD-006
- Title: Stale guard / documentation-governance / architecture-boundary / taxonomy
  / diagnostics / contract guard tests keep the full-suite health check red.
- Status: **resolved (S3-G09, 2026-06-20)**
- Source/reason: Guards assert against pre-S1/pre-S2 doc locations and frozen
  module inventories that have since moved to `docs/history/` or grown during
  S2. 33 full-pytest failures across
  `test_docs_source_of_truth.py` (17), `test_architecture_boundaries.py` (6),
  `test_v6_drift_addendum_boundary.py` (5), `test_evidence_taxonomy_guard.py` (2),
  `test_provider_diagnostics.py` (1), `test_streaming_protocol.py` (1),
  `test_capability_boundary_contract.py` (1).
- Impact: Full-suite health check is red. None are in the S1/S2 acceptance
  gate, observability, or core-runtime tests, so this is guard/governance
  cleanup, not a runtime regression. Note: S2 skill default-off test failures
  are a **separate test-contract class** (activation tests opt in via
  `MY_FIRST_AGENT_S2_SKILL_ENABLE=1`), NOT TD-006.
- Recommended stage: S3/Sn guard cleanup, before relying on full-suite status
  as a release signal. Update each guard against current governance docs/
  contracts (not by weakening assertions silently).
- Verification idea: After S3 docs settle, run full pytest, classify each
  failure against the known set, and update guards to point at current
  authority. Authoritative S2 failure list:
  `docs/history/S2_GOVERNED_TASK_AGENT/_review_artifacts/_tmp_s2_baseline_audit/fullsuite_failures.txt`.
- **Resolution (S3-G09, 2026-06-20):** all 39 stale-guard failures cleared by aligning to
  current S-series governance (NOT by weakening): retire_superseded 27 (guards of docs
  deliberately archived to `docs/history/` during S1/S2 closeout — no live subject),
  update_to_current_authority 7 (repoint to `docs/history/` / `docs/current/`), update_inventory
  3 (frozen baselines refreshed to scanner-observed modules), keep_as_xfail 2 (l3 taxonomy
  subsystem files, explicit xfail per existing precedent). Full pytest now
  **4813 passed / 15 skipped / 28 xfailed / 0 failed** (full-suite release signal is green;
  AC-9 met). Commit: see WORK_LOG / `git log` (S3-G09). TD-007 (ruff) remains open and is
  NOT an S3 release blocker.

### TD-007 - ruff full-suite lint is red with ~451 historical errors

- ID: TD-007
- Title: `ruff check .` red with ~451 historical lint errors (import org, etc.).
- Status: open / carry-forward
- Source/reason: Historical lint drift, independent of TD-006 (different source:
  lint style vs. doc/governance guards).
- Impact: Project-level lint gate is non-green. Not a runtime regression. S2
  policy (S2-G12) required focused ruff for new/modified files only.
- Recommended stage: S3/Sn batched lint pass, separate from TD-006 guard
  cleanup.
- Verification idea: `.venv/bin/ruff check .` exit 0. Do not mix into TD-006
  unless a shared root cause is proven.

### TD-001 - Evidence does not persist full model request/response body

- ID: TD-001
- Title: Evidence records safe_summary + size metadata, but cannot replay full
  model/tool payloads byte-for-byte.
- Status: open / carry-forward (S2 surfaced; full-fidelity deferred)
- Source/reason: S2-G11 delivered structured task-level evidence
  (`TaskEvidenceReport`), deliberately not byte-for-byte persistence.
- Impact: Human replay is structured-summary level, not full audit trace.
- Recommended stage: S3/Sn, when full-fidelity audit or compliance
  traceability is required.
- Verification idea: Review `agent/evidence_recorder.py` persistence behavior;
  decide if S3 needs raw body persistence.

### TD-002 - Planning/compress still use legacy client facade

- ID: TD-002
- Title: Planner/compress expose a second call shape via `ProviderBackedClient`,
  though the same provider underneath.
- Status: open / carry-forward
- Source/reason: Legacy `agent/provider/legacy_adapter.py` facade not refactored.
- Impact: Two call shapes for provider calls (same provider). Cosmetic
  inconsistency, not a runtime split (FakeProvider/RealProvider share one spine).
- Recommended stage: S3/Sn, when planner/compress or `legacy_adapter.py` is
  next refactored.
- Verification idea: Review `agent/provider/legacy_adapter.py` and call sites
  in `agent/core.py`.

### TD-003 - Secondary context compression path is unreachable dead code

- ID: TD-003
- Title: `agent/context.py:36 compress_history` is confirmed-unreachable dead
  code (cleanup target, not a reachability question).
- Status: open / carry-forward (confirmed unreachable during S2 baseline audit)
- Source/reason: Main runtime uses `agent/memory.py:220 compress_history` only;
  `agent/context.py` has zero imports in src.
- Impact: Dead code without tool-use/tool-result pairing guards; safe only
  because unreachable.
- Recommended stage: S3/Sn dead-code removal when `agent/context.py` or the L2
  context module is next touched.
- Verification idea: `rg "from agent\.context import|import agent\.context"
  agent/ main.py` → no matches; then delete after confirming zero reachability.

### TD-004 - Pending-tool events log omits tool output preview

- ID: TD-004
- Title: Pending-tool `events.jsonl` may show an empty `tool_output` preview.
- Status: open / carry-forward (S2 surfaced)
- Source/reason: S2-G11 surfaced this limitation; pending-tool results are
  stored in conversation/state logs but the event-log preview route can be empty.
- Impact: Event-log fidelity gap for pending-tool traces.
- Recommended stage: S3/Sn, when improving event-log fidelity.
- Verification idea: Review `execute_pending_tool` and mediator `_route_result`
  behavior around `turn_context[tool_use_id]`.
