# S2 Baseline Status

> Current authoritative document. This is the **S2 starting-state audit** result, not
> the S2 goal and not the S2 gap, and **not the current release status**. S2 goal is
> defined and frozen in `S2_GOAL.md` (user-confirmed 2026-06-17); the S2 gap backlog
> is in `S2_GOAL_GAP.md`. Source evidence: S1 archive under
> `docs/history/S1_BASELINE_USABLE_PRODUCT/`, current code/runtime, current tests,
> and `docs/current/TECH_DEBT.md`.
>
> **Release status addendum (2026-06-19):** This file documents the S2 *entry*
> baseline as audited 2026-06-17. It does not reflect subsequent S2 work. Current
> S2 release status: all 13 gaps satisfied (see `S2_GOAL_GAP.md`); a release
> hardening pass reconciled the skill default-off test contract (S2-G09) and
> produced real-provider governed-path evidence (S2-G07/AC-7). For release judgment
> see `S2_ACCEPTANCE_GATE.md`; for the execution record see `WORK_LOG.md`.

## 0. Verdict

- **S2 baseline audit date**: 2026-06-17 CST.
- **S1 status inherited**: S1 (Baseline Usable Product) is **complete**. All P0
  release blockers (G-15, G-16, G-17, G-19), all P1 must-fix (G-07b, G-12, G-03),
  and all P2 should-fix (G-10, G-07) are satisfied per the archived
  `S1_GOAL_GAP.md`. Satisfied baselines G-01, G-02, G-04, G-05, G-08, G-09 are
  must-not-regress.
- **Overall baseline verdict**: **S2 starts from a usable S1 runtime/acceptance
  base, with stated caveats.** The targeted runtime path, deterministic S1
  acceptance gate, and observability verification are green and intact, and the
  stage switch to S2 in `docs/current/` is essentially complete. Caveats that
  prevent declaring S2 "risk-free": (a) the full-suite health check is red due to
  stale guard / documentation-governance / architecture-boundary / taxonomy /
  diagnostics guard tests (TD-006), which are guard/governance failures rather
  than runtime targeted regressions; (b) `ruff check .` is red with ~451
  historical lint errors (TD-007); (c) a few entry documents still carried stale
  `docs/current/S1_*` references at audit time (corrected this pass — see §6);
  (d) **S2 goal is not yet confirmed**, so no risk verdict for S2 can be made
  from a baseline alone.

## 1. Scope

- This file describes **only the S2 starting state** as of the audit date.
- It does **not** define the S2 goal (`S2_GOAL.md` stays a skeleton pending user
  confirmation).
- It does **not** generate the S2 gap (`S2_GOAL_GAP.md` stays a skeleton until the
  goal is confirmed).
- Numbers and commands here are the audit evidence, not a release gate for S2.

## 2. Current doc layout

`docs/current/` (active workspace):

- `README.md`, `S_ROADMAP.md` — stage/governance framing. (Correction this pass:
  both had stale `docs/current/S1_*` references at the first audit; root
  `README.md` and `S_ROADMAP.md` S1 entries now point to the S1 archive, and S2
  current entries were added. See §6.)
- `S2_BASELINE_STATUS.md` — this file.
- `S2_GOAL.md`, `S2_GOAL_GAP.md` — skeletons, pending goal confirmation.
- `TECH_DEBT.md` — cross-stage open debt (TD-001, TD-002, TD-003, TD-004, TD-006,
  TD-007).
- `WORK_LOG.md` — S2 current-stage work log.
- `_tmp_s2_baseline_audit/` — audit evidence artifacts only (this baseline's
  intermediate notes, skill log, and the authoritative full-suite failure list).
  Not an active authority; not a documentation entry point.

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
| Full-suite health | `.venv/bin/python -m pytest -q` (no exclusions; fresh re-run this pass) | **36 failed, 4747 passed, 13 skipped, 26 xfailed** (246s) |
| Full-suite lint | `.venv/bin/ruff check .` | exit 1, **~451 historical errors** (TD-007) |

Full-suite failure breakdown (authoritative, saved in
`docs/current/_tmp_s2_baseline_audit/fullsuite_failures.txt`):

| File | Failures | Class |
|---|---|---|
| `tests/test_docs_source_of_truth.py` | 23 | docs-governance / source-of-truth guard (TD-006) |
| `tests/runtime_integration/test_v6_drift_addendum_boundary.py` | 5 | architecture-boundary guard (TD-006) |
| `tests/test_architecture_boundaries.py` | 3 | architecture-boundary guard (TD-006) |
| `tests/test_evidence_taxonomy_guard.py` | 2 | taxonomy guard (TD-006) |
| `tests/test_streaming_protocol.py` | 1 | references a doc moved to history (TD-006) |
| `tests/test_provider_diagnostics.py` | 1 | diagnostics string/flag mismatch (TD-006) |
| `tests/test_capability_boundary_contract.py` | 1 | capability-boundary contract guard (TD-006) |

Findings:

- **Targeted acceptance and observability are fully green** and remain the trusted
  S2-entry verification surface for the runtime path.
- **All 36 full-suite failures are guard / documentation-governance /
  architecture-boundary / taxonomy / diagnostics / contract guard tests (TD-006)**.
  They are guard/governance failures, not targeted runtime regressions: none are in
  the S1 acceptance gate, observability verification, or core-runtime tests. Note
  the failure causes are broader than "pre-S1 doc locations" — some are
  architecture-boundary, taxonomy, or diagnostics-string assertions that need
  separate review against current governance docs.
- **ruff ~451 errors are pre-existing full-suite lint debt (TD-007)**, independent
  of TD-006 and not an S1 regression.
- **Real provider smoke** is satisfied per S1 G-03 (3 passed, key-safe opt-in) and
  was **not** re-run in this audit (no new real-provider authorization; safety
  boundary). The opt-in/network real tests
  (`test_provider_real_smoke.py`, `test_real_cli_regressions.py`,
  `test_real_mcp_flight.py`) are collected by the full-suite number above; without
  opt-in they show as skipped/passed rather than being separately excluded.

Known stale guards: TD-006 is what keeps the full-suite health check red. It is an
S2-baseline cleanup candidate, not a runtime fix. Relying on the targeted
acceptance + observability set is the current S2-entry verification approach; it is
**not** a substitute for eventually cleaning up TD-006.

## 6. Documentation baseline

- `README.md` / `S_ROADMAP.md` — stage/governance framing. **Correction this
  pass:** the first audit wrongly stated "no obvious error found"; in fact both
  files still pointed at `docs/current/S1_GOAL.md` / `S1_GOAL_GAP.md` /
  `S1_CURRENT_CODE_ARCHITECTURE_AUDIT.zh.md`, which had moved to history. These
  stale references have been corrected: S1 entries now point to
  `docs/history/S1_BASELINE_USABLE_PRODUCT/`, and S2 current entries
  (`S2_BASELINE_STATUS.md`, `S2_GOAL.md`, `S2_GOAL_GAP.md`) were added. The
  framings were not rewritten beyond fixing stale S1 current refs.
- S2 docs (`S2_BASELINE_STATUS.md`, `S2_GOAL.md`, `S2_GOAL_GAP.md`, `WORK_LOG.md`)
  — `S2_BASELINE_STATUS.md` is now the audited baseline (refined this pass);
  `S2_GOAL.md` / `S2_GOAL_GAP.md` remain skeletons as required.
- S1 history — fully archived under `docs/history/S1_BASELINE_USABLE_PRODUCT/` and
  usable as evidence.
- Remaining doc-side caveat: the full-suite guard failures (§5) reflect guard tests
  asserting against pre-S1/pre-audit doc locations and contracts; these are tracked
  as TD-006 and are not conflicts inside the current authoritative docs themselves,
  but they do mean full-suite doc-governance coverage is stale until TD-006 is
  cleaned up.

## 7. Technical debt baseline

From `docs/current/TECH_DEBT.md` (unresolved items only; long resolved/result text
is not duplicated here):

| ID | Priority | Scope | Debt | Affects S2 startup? | Notes |
|---|---|---|---|---|---|
| TD-006 | P1 | Tests + Docs governance | Stale guard / documentation-governance / architecture-boundary / taxonomy / diagnostics / contract guard tests keep full-suite red | Indirectly — keeps full-suite non-green; not a runtime blocker | Confirmed by §5: all 36 full-suite failures are this class. Causes are broader than "pre-S1 doc locations" (some are architecture-boundary / taxonomy / diagnostics assertions). Cleanup candidate for S2 baseline or a separate Sn pass. |
| TD-007 | P3 | Cross-cutting Lint / Quality gate | `ruff check .` red with ~451 historical lint errors | No | New this pass. Independent of TD-006 (different source). Not an S2 startup blocker; tracked so lint health is not silently ignored. |
| TD-001 | P2 | L3 Evidence | Evidence does not persist full model request/response body | No | G-11; S2/Sn when full-fidelity audit is required. |
| TD-003 | P3 | L2 Context | Secondary `agent/context.py compress_history` is unreachable dead code (confirmed this audit) | No | Reachability confirmed: zero imports in src; active path is `agent/memory.py:220`. Dead-code cleanup target. |
| TD-004 | P3 | L3 Evidence | Pending-tool `events.jsonl` tool_output preview may be empty | No | S2/Sn event-log fidelity. |
| TD-002 | P3 | L1 Runtime Spine | Planning/compress still use legacy `ProviderBackedClient` facade | No | G-06; same provider underneath. |

Debt classification:

- **Affects S2 startup**: none is a hard blocker. TD-006 is the only P1 and only
  makes full-suite status non-green; it does not block starting S2 work. TD-007 is
  lint-only.
- **S2 baseline cleanup candidates**: TD-006 (and optionally TD-003 dead-code
  removal, TD-007 lint pass).
- **S2/Sn functional depth**: TD-001, TD-002, TD-004 are depth/fidelity debts,
  relevant only if the S2 goal touches those areas.

These debts are **not** converted into S2 gaps here. S2 gaps are generated only
after `S2_GOAL.md` is confirmed.

## 8. Risks and unknowns

- **S2 goal is not confirmed.** `S2_GOAL.md` is a skeleton; nothing here should be
  read as a goal decision, and no risk verdict for S2 follows from a baseline
  alone.
- **S2 gap is not generated.** `S2_GOAL_GAP.md` is a skeleton.
- **Full-suite status is red** due to TD-006 guard tests (and `ruff` is red due to
  TD-007). The targeted acceptance + observability set is the current S2-entry
  verification approach for the runtime path; this is a working reliance, not a
  claim that full-suite health is acceptable — TD-006/TD-007 remain open cleanup.
- **Real provider coverage** is not freshly re-verified this audit; it remains at
  the S1 G-03 satisfied state.
- Whether TD-006/TD-007 cleanup and any L5 activation belong in S2 vs a later Sn is
  a goal decision, not decided by this baseline.

## 9. Recommended next step

- Discuss and confirm `S2_GOAL.md` with the user (scope, non-goals, target
  capabilities, acceptance criteria, boundaries).
- Then generate `S2_GOAL_GAP.md` from this baseline vs the confirmed goal.
- This audit does **not** authorize implementation; it only establishes the S2
  starting facts.
