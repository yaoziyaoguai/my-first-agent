# Technical Debt Register

> Cross-stage carry-forward debt register. S2 and S3 are complete and archived
> under `docs/history/S2_GOVERNED_TASK_AGENT/` and
> `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/`; **S4 is preparing**. This
> file keeps **unresolved** debt that may affect S4/Sn plus **S4/Sn scope
> boundaries** deliberately deferred by the frozen S3 goal. Resolved items live in
> their stage archive (e.g. TD-006 was resolved in S3-G09 — see
> `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/S3_RELEASE_SUMMARY.md §7`),
> not here. Do not use this file as a general unfinished-task list; do not write
> stage goals here.

## Rules

- Carry-forward debt only — items the project deliberately deferred beyond S2.
- Resolved S1/S2 items belong in the S1/S2 archives, not here.
- If resolution status is uncertain, keep the item and mark it `needs_review`.
- Each item states: ID, title, status, source/reason, impact, recommended
  stage, and a verification idea.

## Open / Carry-forward items

> TD-006 (stale guard / doc-governance / architecture-boundary tests keeping the
> full suite red) was **resolved in S3-G09** (full pytest green) and removed from
> this live register at S3 close-out; its resolution record lives in
> `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/S3_RELEASE_SUMMARY.md §7`.

### TD-007 - ruff full-suite lint is red with ~451 historical errors

- ID: TD-007
- Title: `ruff check .` red with ~451 historical lint errors (import org, etc.).
- Status: open / carry-forward
- Source/reason: Historical lint drift, independent of TD-006 (different source:
  lint style vs. doc/governance guards).
- Impact: Project-level lint gate is non-green. Not a runtime regression. S2
  policy (S2-G12) required focused ruff for new/modified files only.
- Recommended stage: S4/Sn batched lint pass, separate from TD-006 guard
  cleanup.
- Verification idea: `.venv/bin/ruff check .` exit 0. Do not mix into TD-006
  unless a shared root cause is proven.

### TD-001 - Evidence does not persist full model request/response body

- ID: TD-001
- Title: Evidence records safe_summary + size metadata, but cannot replay full
  model/tool payloads byte-for-byte.
- Status: **resolved (S4-G02/G03/G05/G06, 2026-06-20)** — kept in register until
  S4 close-out (then moves to the S4 archive, mirroring TD-006/TD-004 handling).
- Source/reason: S2-G11 delivered structured task-level evidence
  (`TaskEvidenceReport`), deliberately not byte-for-byte persistence.
- Impact: Human replay is structured-summary level, not full audit trace.
- Recommended stage: S4/Sn, when full-fidelity audit or compliance
  traceability is required.
- Verification idea: Review `agent/evidence_recorder.py` persistence behavior;
  decide if S3 needs raw body persistence.
- **Resolution (S4):** the frozen S4 goal re-scoped TD-001 from "byte-for-byte"
  to **redacted-faithful replay** (`S4_GOAL.md §8-2`). Delivered by: replay-faithful
  chain model (`agent/task_replay_chain.py`, G02) projecting tool/delegation/decision
  chain at safe-summary granularity; secret-safe redaction enforcement
  (`agent/evidence_redaction.py`, G03); evidence verifier (`agent/evidence_verifier.py`,
  G05); and the audit/replay E2E anchor (`tests/test_s4_reference_task_acceptance.py`,
  G06) proving execute→record→replay→verify on a governed MCP+SubAgent task. Evidence is
  now reconstructable + verifiable (not byte-for-byte, by design — see non-goal).

### TD-002 - Planning/compress still use legacy client facade

- ID: TD-002
- Title: Planner/compress expose a second call shape via `ProviderBackedClient`,
  though the same provider underneath.
- Status: open / carry-forward
- Source/reason: Legacy `agent/provider/legacy_adapter.py` facade not refactored.
- Impact: Two call shapes for provider calls (same provider). Cosmetic
  inconsistency, not a runtime split (FakeProvider/RealProvider share one spine).
- Recommended stage: S4/Sn, when planner/compress or `legacy_adapter.py` is
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
- Recommended stage: S4/Sn dead-code removal when `agent/context.py` or the L2
  context module is next touched.
- Verification idea: `rg "from agent\.context import|import agent\.context"
  agent/ main.py` → no matches; then delete after confirming zero reachability.
- **Reachability re-confirmed (S3-G13 triage, 2026-06-20):** grep across `agent/`
  + `main.py` returns **zero** `agent.context` imports; `agent/context.py:36
  compress_history` remains present + dead. Not deleted in S3 (CLAUDE.md §3:
  unrelated dead code is mentioned, not deleted; not S3-triggered). Ready for
  safe deletion when the L2 context module is next touched (S4/Sn).

### TD-004 - Pending-tool events log omits tool output preview

- ID: TD-004
- Title: Pending-tool `events.jsonl` may show an empty `tool_output` preview.
- Status: **resolved (S4-G04, 2026-06-20)** — kept in register until S4 close-out
  (then moves to the S4 archive, mirroring TD-006 handling).
- Source/reason: S2-G11 surfaced this limitation; pending-tool results are
  stored in conversation/state logs but the event-log preview route can be empty.
- Impact: Event-log fidelity gap for pending-tool traces.
- Recommended stage: S4/Sn, when improving event-log fidelity.
- Verification idea: Review `execute_pending_tool` and mediator `_route_result`
  behavior around `turn_context[tool_use_id]`.
- **Resolution (S4-G04):** root cause = `mediate_pending` (Step 4) read
  `turn_context[tool_use_id]` for the TOOL_RESULT `tool_output` preview, but
  `execute_pending_tool` never wrote it (unlike `execute_single_tool` at
  `tool_executor.py:543`), so the preview was always empty. Fix: populate
  `self._turn_context[tool_use_id] = result` in `mediate_pending` before the
  TOOL_RESULT dispatch (parity with the non-pending `_route_result` path; result
  already masked for failed/rejected outcomes — no execution-semantics change).
  Evidence: `tests/test_s4_pending_tool_preview.py` (3 passed) asserts non-empty
  preview + safe truncation; S2/S3 + subagent mediator tests non-regressed.

## Deferred to S4/Sn (frozen S3 scope boundaries)

> These are **not active S3 debt** — they are scope boundaries the frozen S3 goal
> (`S3_GOAL.md §7 Non-goals` / `§8 Future deferred decisions`; `S3_GOAL_GAP.md G13`)
> deliberately excludes from S3. Recorded here (S3-G13 triage, 2026-06-20) so they
> persist across the eventual S3 closeout (when `docs/current/` stage docs are
> archived) and are not silently dropped or prematurely pulled into a later stage.
> Each stays deferred unless a future stage's frozen goal explicitly authorizes it.

### TD-008 - Scheduler productionization / main-loop activation deferred

- ID: TD-008
- Title: `ActionScheduler`/`ActionPlan` (`agent/action_scheduler.py`) + handler + tests
  exist but are NOT activated in the default runtime loop.
- Status: deferred (S4/Sn)
- Source/reason: Frozen S3 goal keeps Scheduler as boundary-only (S3 does not productionize
  it / wire it into the main loop). Capability is dormant by design.
- Impact: Scheduler-driven action planning is not a runtime path in S3. No regression —
  dormant, not broken.
- Recommended stage: S4/Sn, when scheduler-driven action planning becomes a product goal.
- Verification idea: confirm the Scheduler is not **activated/routed** in the default
  runtime loop — `chat()`/`LoopDependencies.action_scheduler` defaults to `None`, `main.py`
  never passes the kwarg (proven by `test_cr1_*` AST boundary tests), and execution is gated
  by `if action_scheduler is not None`. Note: `agent/planner.py` lazily imports
  `build_action_plan_from_model_output` for plan generation, but module import ≠ scheduler
  activation/routing; `test_scheduler_main_path.py` + `test_cr1_*` cover the dormant surface.

### TD-009 - Full MCP ecosystem deferred

- ID: TD-009
- Title: Multi-server MCP orchestration / dynamic discovery ecosystemization.
- Status: deferred (S4/Sn)
- Source/reason: Frozen S3 goal limits MCP to a **controlled tool source** (S3-G03) —
  registered via `register_mcp_tools`, governed by `mcp_policy` + allowlist + evidence,
  default-off. Full ecosystem is a non-goal.
- Impact: MCP is single-tool-source governed only; no multi-server orchestration.
- Recommended stage: S4/Sn, when multi-server MCP orchestration is required.
- Verification idea: confirm MCP stays on the governed tool path (register_mcp_tools →
  TOOL_REGISTRY → mediator); no multi-server orchestration module in S3.

### TD-010 - Full multi-agent ecosystem deferred

- ID: TD-010
- Title: Writable / non-mediated SubAgent delegation + multi-agent collaboration.
- Status: deferred (S4/Sn)
- Source/reason: Frozen S3 goal limits SubAgent to **read-only / audit-first /
  parent-mediated** delegation (S3-G04). Writable or non-mediated delegation is a non-goal.
- Impact: SubAgent is read-only second-opinion only; no writable delegation / multi-agent
  collaboration.
- Recommended stage: S4/Sn, when writable SubAgent delegation / multi-agent orchestration
  is required.
- Verification idea: confirm SubAgent stays parent-mediated (delegate_l1/execute_l1 route
  tools+memory through tool_mediator; child holds no MemoryStore); no writable delegation path.
- Note (S3 audit H1 fix, 2026-06-20): the **live** delegation path is inline-L0
  (`subagent_inline.execute_subagent_delegation`), which now records delegation evidence into
  `state.task.delegation_log` (checkpoint/evidence). The L1/L2 dispatcher delegation paths
  (`delegate_l1`/`delegate_l2`) currently have **no registered handler** (frozen), so they are
  not a live path. When S4/Sn activates L1/L2 or writable delegation, the evidence recording
  (`record_delegation_run`) must be wired into that path too, mirroring the inline-L0 wiring.

### TD-011 - Durable task ledger deferred

- ID: TD-011
- Title: Independent durable (cross-session, crash-survivable) task ledger.
- Status: deferred (S4/Sn)
- Source/reason: Frozen S3 goal lists durable ledger as a non-goal / S3+ candidate
  (also S2_TECH_DEBT_TRIAGE S3+ item). S2/S3 use checkpoint-based resume (file-scoped).
- Impact: No durable cross-session task ledger; resume relies on checkpoint files.
- Recommended stage: S4/Sn, when durability / compliance / crash-recovery requires it.
- Verification idea: confirm no durable-ledger module; `agent/checkpoint.py` remains the
  resume mechanism (save_checkpoint / load_checkpoint_to_state).
