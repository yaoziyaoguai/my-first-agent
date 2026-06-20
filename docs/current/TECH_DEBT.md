# Technical Debt Register

> Cross-stage carry-forward debt register. S2, S3, and S4 are complete and
> archived under `docs/history/`. **S5 is preparing**. This file keeps
> **unresolved** debt that may affect S5/Sn plus S5/Sn scope boundaries
> deliberately deferred by prior frozen goals. Resolved items live in their stage
> archive (e.g. TD-006 was resolved in S3-G09; TD-001/TD-004 were resolved in S4
> and recorded in
> `docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/S4_RELEASE_SUMMARY.md`), not
> here. Do not use this file as a general unfinished-task list; do not write stage
> goals here.

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

### TD-007 - ruff full-suite lint is red with 443 historical errors

- ID: TD-007
- Title: `ruff check .` red with 443 historical lint errors (import org, etc.).
- Status: open / carry-forward
- Source/reason: Historical lint drift, independent of TD-006 (different source:
  lint style vs. doc/governance guards).
- Impact: Project-level lint gate is non-green. Not a runtime regression. S2
  policy (S2-G12) required focused ruff for new/modified files only.
- Recommended stage: S5/Sn batched lint pass, separate from TD-006 guard
  cleanup.
- Verification idea: `.venv/bin/ruff check .` exit 0. Do not mix into TD-006
  unless a shared root cause is proven.
- Latest check (S5 planning self-review, 2026-06-20):
  `.venv/bin/ruff check .` exited non-zero with `Found 443 errors`.

### TD-002 - Planning/compress still use legacy client facade

- ID: TD-002
- Title: Planner/compress expose a second call shape via `ProviderBackedClient`,
  though the same provider underneath.
- Status: open / carry-forward
- Source/reason: Legacy `agent/provider/legacy_adapter.py` facade not refactored.
- Impact: Two call shapes for provider calls (same provider). Cosmetic
  inconsistency, not a runtime split (FakeProvider/RealProvider share one spine).
- Recommended stage: S5/Sn, when planner/compress or `legacy_adapter.py` is
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
- Recommended stage: S5/Sn dead-code removal when `agent/context.py` or the L2
  context module is next touched.
- Verification idea: `rg "from agent\.context import|import agent\.context"
  agent/ main.py` → no matches; then delete after confirming zero reachability.
- **Reachability re-confirmed (S3-G13 triage, 2026-06-20):** grep across `agent/`
  + `main.py` returns **zero** `agent.context` imports; `agent/context.py:36
  compress_history` remains present + dead. Not deleted in S3 (CLAUDE.md §3:
  unrelated dead code is mentioned, not deleted; not S3-triggered). Ready for
  safe deletion when the L2 context module is next touched (S5/Sn).

## Deferred to S5/Sn (prior-stage scope boundaries)

> These are scope boundaries deliberately excluded from prior frozen goals and
> carried forward for S5/Sn consideration. Each stays deferred unless a future
> stage's frozen goal explicitly authorizes it.

### TD-008 - Scheduler productionization / main-loop activation deferred

- ID: TD-008
- Title: `ActionScheduler`/`ActionPlan` (`agent/action_scheduler.py`) + handler + tests
  exist but are NOT activated in the default runtime loop.
- Status: deferred (S5/Sn)
- Source/reason: Frozen S3 goal keeps Scheduler as boundary-only (S3 does not productionize
  it / wire it into the main loop). Capability is dormant by design.
- Impact: Scheduler-driven action planning is not a runtime path in S3. No regression —
  dormant, not broken.
- Recommended stage: S5/Sn, when scheduler-driven action planning becomes a product goal.
- Verification idea: confirm the Scheduler is not **activated/routed** in the default
  runtime loop — `chat()`/`LoopDependencies.action_scheduler` defaults to `None`, `main.py`
  never passes the kwarg (proven by `test_cr1_*` AST boundary tests), and execution is gated
  by `if action_scheduler is not None`. Note: `agent/planner.py` lazily imports
  `build_action_plan_from_model_output` for plan generation, but module import ≠ scheduler
  activation/routing; `test_scheduler_main_path.py` + `test_cr1_*` cover the dormant surface.

### TD-009 - Full MCP ecosystem deferred

- ID: TD-009
- Title: Multi-server MCP orchestration / dynamic discovery ecosystemization.
- Status: deferred (S5/Sn)
- Source/reason: Frozen S3 goal limits MCP to a **controlled tool source** (S3-G03) —
  registered via `register_mcp_tools`, governed by `mcp_policy` + allowlist + evidence,
  default-off. Full ecosystem is a non-goal.
- Impact: MCP is single-tool-source governed only; no multi-server orchestration.
- Recommended stage: S5/Sn, when multi-server MCP orchestration is required.
- Verification idea: confirm MCP stays on the governed tool path (register_mcp_tools →
  TOOL_REGISTRY → mediator); no multi-server orchestration module in S3.

### TD-010 - Full multi-agent ecosystem deferred

- ID: TD-010
- Title: Writable / non-mediated SubAgent delegation + multi-agent collaboration.
- Status: deferred (S5/Sn)
- Source/reason: Frozen S3 goal limits SubAgent to **read-only / audit-first /
  parent-mediated** delegation (S3-G04). Writable or non-mediated delegation is a non-goal.
- Impact: SubAgent is read-only second-opinion only; no writable delegation / multi-agent
  collaboration.
- Recommended stage: S5/Sn, when writable SubAgent delegation / multi-agent orchestration
  is required.
- Verification idea: confirm SubAgent stays parent-mediated (delegate_l1/execute_l1 route
  tools+memory through tool_mediator; child holds no MemoryStore); no writable delegation path.
- Note (S3 audit H1 fix, 2026-06-20): the **live** delegation path is inline-L0
  (`subagent_inline.execute_subagent_delegation`), which now records delegation evidence into
  `state.task.delegation_log` (checkpoint/evidence). The L1/L2 dispatcher delegation paths
  (`delegate_l1`/`delegate_l2`) currently have **no registered handler** (frozen), so they are
  not a live path. When S5/Sn activates L1/L2 or writable delegation, the evidence recording
  (`record_delegation_run`) must be wired into that path too, mirroring the inline-L0 wiring.

### TD-011 - Durable task ledger deferred

- ID: TD-011
- Title: Independent durable (cross-session, crash-survivable) task ledger.
- Status: deferred (S5/Sn)
- Source/reason: Frozen S3 goal lists durable ledger as a non-goal / S3+ candidate
  (also S2_TECH_DEBT_TRIAGE S3+ item). S2/S3 use checkpoint-based resume (file-scoped).
- Impact: No durable cross-session task ledger; resume relies on checkpoint files.
- Recommended stage: S5/Sn, when durability / compliance / crash-recovery requires it.
- Verification idea: confirm no durable-ledger module; `agent/checkpoint.py` remains the
  resume mechanism (save_checkpoint / load_checkpoint_to_state).

## S4 whole-stage audit findings (2026-06-20)

> Surfaced by the S4 whole-stage audit (multi-dimension adversarial review). Each is real but
> out-of-scope/risky to fix within S4's surgical boundaries; recorded here per `AGENTS.md`
> Technical Debt Rules. The audit's HIGH finding (pending-tool status fidelity, AC-4) was
> **fixed in-audit** (not debt) — see `WORK_LOG.md` S4 whole-stage audit entry.

### TD-012 - G03 redaction not wired into legacy mediator/evidence-recorder preview paths

- ID: TD-012
- Title: `evidence_redaction.redact_text`/`redact_metadata` is wired into the S4 replay-chain
  projection (`build_replay_chain`, `audit_observability`) but NOT into the legacy
  `tool_runtime_mediator._route_result`/`mediate_pending` TOOL_RESULT `tool_output` preview
  (`str(...)[:500]` with no redact pass) nor `evidence_recorder.record_evidence` metadata.
- Status: open / carry-forward (S4 audit)
- Source/reason: S4-G03 scoped redaction to the new higher-fidelity surface (replay chain).
  The legacy mediator/`record_evidence` paths rely on pre-existing upstream
  `mask_user_visible_secrets` (failed/rejected) + safe-metadata discipline; broadening
  `redact_text` to these hot paths is regression-prone and beyond G03's frozen surgical scope.
- Impact: the archived S4 fidelity contract §1 previously overclaimed "所有 input/output 投影强制
  redaction"; corrected in-audit to scope the hard boundary to the replay-chain surface. No
  active leak on live paths (callers pre-filter metadata; failed/rejected results are masked
  upstream), but a secret surviving upstream masking could reach the legacy event-log preview
  unredacted. `redact_metadata` is currently dead code on the write path (docstring corrected).
- Recommended stage: S5/Sn, when the mediator TOOL_RESULT preview or `record_evidence` metadata
  path is next touched (wire `redact_text`/`redact_metadata` at both projection points + tests).
- Verification idea: grep `redact_text|redact_metadata` call sites; currently only
  `task_replay_chain.py` + `audit_observability.py`. After wiring: a fake secret injected into
  a tool result must not appear in the mediator TOOL_RESULT `tool_output` nor `record_evidence`
  metadata.

### TD-013 - Evidence verifier does not detect cross-kind duplicate refs

- ID: TD-013
- Title: `evidence_verifier._duplicate_refs` groups by kind (tool / delegation separately), so a
  ref_id shared across kinds (e.g. `tool_use_id == delegation_id`) is not flagged —
  `verify_replay_chain(...).ok` stays True.
- Status: open / carry-forward (S4 audit)
- Source/reason: S4-G05 scoped `self_consistent` to count-level consistency per
  the archived S4 fidelity contract §5.2 (tool/delegation counts). Cross-kind duplicate detection is a
  contract expansion not required by the frozen goal.
- Impact: Low. `tool_use_id` and `delegation_id` come from different id spaces, so real-world
  collision is unlikely; but it is a genuine verifier blind spot.
- Recommended stage: S5/Sn, when hardening the verifier beyond count-level consistency.
- Verification idea: a chain with a tool and a delegation sharing the same `ref_id` should fail
  `self_consistent` with `duplicate_ref` (currently passes).
