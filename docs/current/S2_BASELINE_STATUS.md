# S2 Baseline Status

> Current authoritative document. This is the **S2 starting-state audit** result, not
> the S2 goal and not the S2 gap. S2 goal is defined separately in `S2_GOAL.md`
> (pending user confirmation); the S2 gap is generated only after both the baseline
> and the goal are confirmed. Source evidence: S1 archive under
> `docs/history/S1_BASELINE_USABLE_PRODUCT/`, current code/runtime, current tests,
> and `docs/current/TECH_DEBT.md`.

## 0. Verdict

- **S2 baseline audit date**: 2026-06-17 CST.
- **S1 status inherited**: S1 (Baseline Usable Product) is **complete**. All P0
  release blockers (G-15, G-16, G-17, G-19), all P1 must-fix (G-07b, G-12, G-03),
  and all P2 should-fix (G-10, G-07) are satisfied per the archived
  `S1_GOAL_GAP.md`. Satisfied baselines G-01, G-02, G-04, G-05, G-08, G-09 are
  must-not-regress.
- **Overall baseline verdict**: **S2 has a clean, usable starting point.** The S1
  core runtime, deterministic acceptance gate, and observability baseline are green
  and intact. The only red on the full-suite health check is documentation-governance
  / architecture-boundary guard tests (TD-006) that still encode pre-S1 doc
  locations; these do not block S2 startup and do not indicate any runtime
  regression. S2 goal is not yet confirmed.

## 1. Scope

- This file describes **only the S2 starting state** as of the audit date.
- It does **not** define the S2 goal (`S2_GOAL.md` stays a skeleton pending user
  confirmation).
- It does **not** generate the S2 gap (`S2_GOAL_GAP.md` stays a skeleton until the
  goal is confirmed).
- Numbers and commands here are the audit evidence, not a release gate for S2.

## 2. Current doc layout

`docs/current/` (active workspace):

- `README.md`, `S_ROADMAP.md` — stage/governance framing; not rewritten this audit.
- `S2_BASELINE_STATUS.md` — this file.
- `S2_GOAL.md`, `S2_GOAL_GAP.md` — skeletons, pending goal confirmation.
- `TECH_DEBT.md` — cross-stage open debt (TD-001, TD-002, TD-003, TD-004, TD-006).
- `WORK_LOG.md` — S2 current-stage work log.

Boundaries confirmed:

- No `S1_*` files and no `_tmp_s1*` directories remain in `docs/current/`.
- S1 evidence and work log are archived under
  `docs/history/S1_BASELINE_USABLE_PRODUCT/` (S1_GOAL.md, S1_GOAL_GAP.md,
  S1_ACCEPTANCE_BASELINE.md, S1_OBSERVABILITY_BASELINE.md,
  S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md, WORK_LOG.md, plus `_tmp_s1*` evidence).
- Historical docs are evidence only, not routing authority (per AGENTS.md).

## 3. Inherited from S1

Capability matrix source-verified via graphify + S1 archived evidence.

| Capability | Current status | Evidence | Known limitation |
|---|---|---|---|
| Unified entry + runtime loop (L1) | usable | `main.py main()` → `main_loop` → `_run_chat_for_backend` → `agent/core.py:763 chat()` → `agent/loop.py run_main_loop`; S1 G-01 satisfied | — |
| FakeProvider deterministic baseline (L1) | usable | `agent/provider/fake_provider.py:306`; golden_e2e green (G-02) | — |
| RealProvider smoke (L1) | satisfied (opt-in, key-safe) | real adapters `provider/{anthropic_http,anthropic_native,openai_http,openai_native}.py`; G-03 3 passed at S1 close | Not re-run this audit (no new real-provider authorization; safety boundary) |
| Same-spine fake/real (L1) | satisfied (must-not-regress) | thin `protocol.py:78`; single `factory.py` dispatch; `loop.py` does not read `provider_type`; `legacy_adapter.py:29-63` forwards to same provider; G-04/G-17 | — |
| Context compression pairing safety (L2) | usable | active path `agent/memory.py:220 compress_history` (core.py:66 import, core.py:1305 call) with tool_use/tool_result pairing guards | Legacy `agent/context.py:36 compress_history` is unreachable dead code → TD-003 |
| Memory recall/retain (L2) | usable | `core.py:1065` recall, `core.py:961` retain, turn-end proposal hook; G-07 satisfied | — |
| Checkpoint save/resume incl. large results (L2) | usable | `checkpoint.py:370 save_checkpoint`; G-07b: summary-only `tool_result` rehydrated to provider-callable content at resume boundary | Raw large results not persisted in checkpoint (by design) |
| Minimal multistep task state (L4) | usable (legacy Plan path) | `state.py TaskState` (`current_plan`/`current_step_index`/`status`), `mark_step_complete` + `STEP_COMPLETION_THRESHOLD`, `advance_current_step_if_needed`; G-12 plan→advance→resume→done | No independent durable task ledger (S1 non-goal); ActionPlan/Scheduler not wired |
| Tool registration + mediated execution (L3) | usable | `tool_registry.py`, `ToolRuntimeMediator tool_runtime_mediator.py:186`, `tool_executor.py`, `RuntimeActionDispatcher dispatcher.py:309` | No single top-level policy switch (logic distributed, functional) |
| Policy/approval gate (L3) | usable, consistent across providers | `ToolGateHandler tool_gate.py:32`; G-08 | — |
| Tool result into context + state (L3) | usable | `conversation_events.py append_tool_result`; `state.task.tool_execution_log` copy; G-09 | Pending-tool `events.jsonl` tool_output preview may be empty → TD-004 |
| Evidence path skeleton (L3) | usable (skeleton-level) | `evidence_recorder.py record_evidence` envelope; per-session `sessions/<id>/events.jsonl` via `event_log.py:153`; S1 observability baseline satisfied | No full model request/response body persistence → TD-001 |
| Checkpoint evidence | usable | `checkpoint.*` event family; S1 G-10 | — |
| Skill / MCP / SubAgent / Scheduler boundary (L5) | boundary-clear (activation = S2+) | Scheduler dormant (`action_scheduler.py` file-level, main.py 0 refs); MCP configurable default off (`MY_FIRST_AGENT_MCP_ENABLE`); SubAgent V0 configurable default off (local_fake stub); Skill experimental; G-13/G-14 | Production activation is S2 or later, by design |

## 4. Runtime and code baseline

- **Main runtime loop**: intact and source-verified (graphify). `core.chat()` →
  runtime action dispatcher → tool gate/mediator/executor → evidence/checkpoint, with
  fake/real sharing the same spine.
- **Provider state**: FakeProvider is the deterministic baseline; RealProvider is
  behind an opt-in, key-safe smoke step (no real call in this audit). The
  fake/real boundary stays at factory/config layer only — not two agents.
- **Tool / policy / evidence / checkpoint state**: all usable; the S1 acceptance
  gate and observability verification are green (see §5).
- **Dormant boundaries**: Scheduler is dormant (not wired, not deleted). MCP /
  SubAgent V0 / Skill are configurable and default-off / experimental. Boundaries
  are explicit and match S1 non-promises; no S2 action is forced by the current
  state.

## 5. Test and verification baseline

| Check | Command | Result |
|---|---|---|
| S1 fake/local acceptance (AC-1) | `.venv/bin/python -m pytest tests/golden_e2e -q` | **15 passed** |
| S1 baseline-usable smoke | `.venv/bin/python -m pytest tests/smoke/test_first_usable_task_e2e.py -q` | **6 passed** |
| S1 same-spine wiring | `.venv/bin/python -m pytest tests/runtime_integration/test_phase1_real_core_loop.py::TestCoreChatWiring::test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook -q` | **1 passed** |
| S1 observability (G-10) | `.venv/bin/python -m pytest tests/test_evidence_lifecycle_and_summary.py tests/test_b7_event_log.py -q` | **91 passed** |
| Full-suite health | `.venv/bin/python -m pytest -q` (excluding opt-in/network real tests) | 4727 passed, **36 failed**, 7 skipped, 26 xfailed |
| Full-suite lint | `.venv/bin/ruff check .` | exit 1, **451 pre-existing errors** |

Full-suite failure breakdown (authoritative, saved in
`docs/current/_tmp_s2_baseline_audit/fullsuite_failures.txt`):

| File | Failures | Class |
|---|---|---|
| `tests/test_docs_source_of_truth.py` | 23 | docs-governance guard (TD-006) |
| `tests/runtime_integration/test_v6_drift_addendum_boundary.py` | 5 | architecture-boundary guard (TD-006) |
| `tests/test_architecture_boundaries.py` | 3 | architecture-boundary guard (TD-006) |
| `tests/test_evidence_taxonomy_guard.py` | 2 | taxonomy guard (TD-006) |
| `tests/test_streaming_protocol.py` | 1 | references moved doc (TD-006) |
| `tests/test_provider_diagnostics.py` | 1 | diagnostics string mismatch (TD-006) |
| `tests/test_capability_boundary_contract.py` | 1 | capability-boundary contract (TD-006) |

Findings:

- **Targeted acceptance and observability are fully green** and remain the trusted
  S2-entry verification surface.
- **All 36 full-suite failures are documentation-governance / architecture-boundary
  / taxonomy / contract guard tests** that still encode pre-S1 documentation
  locations moved to `docs/history/`. None are in the S1 acceptance gate,
  observability verification, or core-runtime tests → **no S1 runtime regression**.
  This is exactly **TD-006 (P1)**.
- **ruff 451 errors are pre-existing full-suite historical debt** (import
  organization etc.), not an S1 regression.
- **Real provider smoke** is satisfied per S1 G-03 (3 passed, key-safe opt-in) and
  was **not** re-run in this audit (no new real-provider authorization; safety
  boundary). Network-dependent real tests
  (`test_provider_real_smoke.py`, `test_real_cli_regressions.py`,
  `test_real_mcp_flight.py`) are excluded from the full-suite health number.

Known stale guards: TD-006 (full-suite guards tied to pre-S1 doc locations) — the
only thing that keeps full-suite non-green; resolving it is an S2-baseline cleanup
candidate, not a runtime fix.

## 6. Documentation baseline

- `README.md` / `S_ROADMAP.md` — stable S-series framing; not rewritten this audit;
  no obvious error found.
- S2 docs (`S2_BASELINE_STATUS.md`, `S2_GOAL.md`, `S2_GOAL_GAP.md`, `WORK_LOG.md`)
  — `S2_BASELINE_STATUS.md` is now the audited baseline; `S2_GOAL.md` /
  `S2_GOAL_GAP.md` remain skeletons as required.
- S1 history — fully archived under `docs/history/S1_BASELINE_USABLE_PRODUCT/` and
  usable as evidence.
- Current doc conflict / gap: none within `docs/current`. The full-suite guard
  failures (§5) reflect guard tests pointing at pre-S1 doc paths, not a conflict
  inside current authoritative docs.

## 7. Technical debt baseline

From `docs/current/TECH_DEBT.md` (unresolved items only; long resolved/result text
is not duplicated here):

| ID | Priority | Scope | Debt | Affects S2 startup? | Notes |
|---|---|---|---|---|---|
| TD-006 | P1 | Tests + Docs governance | Pre-S1 documentation-governance guard tests are stale (point at docs moved to history) | Indirectly — keeps full-suite non-green, not a runtime blocker | Confirmed by §5: all 36 full-suite failures are this class. Cleanup candidate for S2 baseline or a separate Sn pass. |
| TD-001 | P2 | L3 Evidence | Evidence does not persist full model request/response body | No | G-11; S2/Sn when full-fidelity audit is required. |
| TD-003 | P3 | L2 Context | Secondary `agent/context.py compress_history` is unreachable dead code (confirmed this audit) | No | Reachability confirmed: zero imports in src; active path is `agent/memory.py:220`. Dead-code cleanup target. |
| TD-004 | P3 | L3 Evidence | Pending-tool `events.jsonl` tool_output preview may be empty | No | S2/Sn event-log fidelity. |
| TD-002 | P3 | L1 Runtime Spine | Planning/compress still use legacy `ProviderBackedClient` facade | No | G-06; same provider underneath. |

Debt classification:

- **Affects S2 startup**: none is a hard blocker. TD-006 is the only P1 and only
  makes full-suite status non-green; it does not block starting S2 work.
- **S2 baseline cleanup candidates**: TD-006 (and optionally TD-003 dead-code
  removal).
- **S2/Sn functional depth**: TD-001, TD-002, TD-004 are depth/fidelity debts,
  relevant only if the S2 goal touches those areas.

These debts are **not** converted into S2 gaps here. S2 gaps are generated only
after `S2_GOAL.md` is confirmed.

## 8. Risks and unknowns

- **S2 goal is not confirmed.** `S2_GOAL.md` is a skeleton; nothing here should be
  read as a goal decision.
- **S2 gap is not generated.** `S2_GOAL_GAP.md` is a skeleton.
- **Full-suite status is red**, but only due to TD-006 guard tests; relying on the
  targeted acceptance + observability set is safe for S2-entry verification until
  TD-006 is cleaned up.
- **Real provider coverage** is not freshly re-verified this audit; it remains at
  the S1 G-03 satisfied state.
- Whether TD-006 cleanup and any L5 activation belong in S2 vs a later Sn is a goal
  decision, not decided by this baseline.

## 9. Recommended next step

- Discuss and confirm `S2_GOAL.md` with the user (scope, non-goals, target
  capabilities, acceptance criteria, boundaries).
- Then generate `S2_GOAL_GAP.md` from this baseline vs the confirmed goal.
- This audit does **not** authorize implementation; it only establishes the S2
  starting facts.
