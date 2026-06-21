# Technical Debt Register

> Cross-stage carry-forward debt register. S1-S5 + S_FINAL are complete and
> archived under `docs/history/`; the S-series roadmap mainline is closed. This
> file keeps only **unresolved** carry-forward debt plus scope boundaries
> deliberately deferred to Sn/future by prior frozen goals.
> Resolved items live in their stage archive (e.g. TD-006 resolved in S3-G09;
> TD-001/TD-004 resolved in S4; TD-011 resolved in S5) and are recorded in the
> relevant `docs/history/<STAGE>/<STAGE>_RELEASE_SUMMARY.md`, not here. Do not use
> this file as a general unfinished-task list; do not write stage goals here.

## Rules

- Carry-forward debt only — items the project deliberately deferred beyond S2.
- Resolved S1/S2 items belong in the S1/S2 archives, not here.
- If resolution status is uncertain, keep the item and mark it `needs_review`.
- Each item states: ID, title, status, source/reason, impact, recommended
  stage, and a verification idea.

### Productization gap intake (gaps-first)

Productization work enters `docs/current/PRODUCTIZATION_GAP_LEDGER.md` first.
`TECH_DEBT.md` is **not** a dumping ground for ordinary gaps.

An item may move from the gap ledger to `TECH_DEBT.md` only when ALL of these
hold:

1. it is genuinely blocked in its current phase by a concrete
   code/architecture/external dependency blocker (not "large scope");
2. it has a clear future trigger that would reopen it;
3. it does not block the current phase exit;
4. the `TECH_DEBT.md` entry records the blocker, the phase impact, the future
   trigger, and a verification idea.

"Large scope", "later", or "future work" are NOT valid debt reasons. When a gap
moves to debt, mark the ledger gap `moved_to_tech_debt` with the debt ID.

## Open / Carry-forward items

> TD-006 (stale guard / doc-governance / architecture-boundary tests keeping the
> full suite red) was **resolved in S3-G09** (full pytest green) and removed from
> this live register at S3 close-out; its resolution record lives in
> `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/S3_RELEASE_SUMMARY.md §7`.
>
> TD-003 (`agent/context.py` unreachable dead code) was **resolved in S_FINAL**
> (FINAL-G02: the whole `agent/context.py` module — all 3 functions, unused
> duplicates of the live `agent/memory.py` versions — was deleted after
> re-confirming zero reachability) and removed from this live register; its
> resolution record lives in the S_FINAL release summary.
>
> TD-007 (full-suite `ruff check .` red, 443 historical lint errors) was
> **resolved in S_FINAL** (FINAL-G01: `.venv/bin/ruff check .` now exits 0 via
> 269 safe auto-fixes + manual fixes across 62 files — E501 / N803 / SIM / B / N
> — with full pytest `4940 passed` and behavior preserved) and removed from this
> live register.

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
- **S_FINAL triage (2026-06-20):** deferred (carry-forward). Consolidating the
  second call shape would refactor L1/L2 provider-call hot paths for a cosmetic
  benefit only (same provider, no spine split); not safely fixable within the
  closure/hardening scope. Stays live here for a future stage that legitimately
  refactors the facade.

## Deferred to Sn / future (prior-stage scope boundaries)

> These are scope boundaries deliberately excluded from prior frozen goals and
> carried forward for Sn/future consideration. Each stays deferred unless a future
> stage's frozen goal explicitly authorizes it.
>
> TD-011 (durable task ledger) was **resolved in S5** (S5-G01..G11) and removed
> from this live register at S5 close-out; its resolution record lives in
> `docs/history/S5_DURABLE_GOVERNED_TASK_RECOVERY/S5_RELEASE_SUMMARY.md`.

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
  never passes the kwarg (proven by AST boundary tests
  `tests/test_architecture_boundaries.py::test_cr1_chat_default_action_scheduler_is_none`
  and
  `tests/test_architecture_boundaries.py::test_cr1_main_py_does_not_pass_action_scheduler_kwarg`),
  and execution is gated by `if action_scheduler is not None`. Note: `agent/planner.py`
  lazily imports `build_action_plan_from_model_output` for plan generation, but module
  import ≠ scheduler activation/routing; `tests/runtime_integration/test_action_scheduler.py`
  and the two `tests/test_architecture_boundaries.py` cr1 boundary tests
  (`test_cr1_chat_default_action_scheduler_is_none`,
  `test_cr1_main_py_does_not_pass_action_scheduler_kwarg`) cover the dormant surface.

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

## S4 whole-stage audit findings (2026-06-20)

> Surfaced by the S4 whole-stage audit (multi-dimension adversarial review). Each is real but
> out-of-scope/risky to fix within S4's surgical boundaries; recorded here per `AGENTS.md`
> Technical Debt Rules. The audit's HIGH finding (pending-tool status fidelity, AC-4) was
> **fixed in-audit** (not debt) — see the S4 archive work log
> (`docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/`).
>
> TD-012 (redaction not wired into legacy mediator TOOL_RESULT preview /
> `record_evidence` metadata) was **resolved in S_FINAL** (FINAL-G03: `redact_text`
> wired into `tool_runtime_mediator._route_result` / `mediate_pending` `tool_output`
> preview + `redact_metadata` into `record_evidence` metadata; TDD
> `tests/test_final_legacy_redaction.py`) and removed from this live register.
>
> TD-013 (verifier did not detect cross-kind duplicate refs) was **resolved in
> S_FINAL** (FINAL-G04: `_duplicate_refs` now flags a `ref_id` shared across tool
> and delegation events as `cross_kind`; TDD
> `tests/test_final_verifier_cross_kind.py`) and removed from this live register.
> Both S4 whole-stage audit findings are now resolved; this section is retained as
> a historical record.
