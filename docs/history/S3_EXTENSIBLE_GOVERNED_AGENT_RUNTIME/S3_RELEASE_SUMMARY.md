# S3 Release Summary — Extensible Governed Agent Runtime

> Archive summary for S3. This is an evidence/record document, not routing
> authority. S3 is complete; the next step is the S4 baseline audit + goal under
> `docs/current/`. See `docs/current/S_ROADMAP.md` and
> `docs/current/TECH_DEBT.md` for the post-S3 context.

- **Release name**: S3 — Extensible Governed Agent Runtime
- **Verdict**: **completed / release-ready** (independently audited twice; all
  audit findings fixed or debt-tracked before close-out)
- **Stage window**: S2 archive → S3 baseline audit (2026-06-19) → frozen goal →
  S3 gap loop G01-G13 (2026-06-19/20) → independent audit + fixes → S3 close-out
  (2026-06-20)
- **Commit range**: `origin/main..HEAD` S3 span = `78f27b0` (S3-G01) … through the
  independent-audit fixes (`3e41afd` / `61ea0d2` / `4c28f74`) and this close-out
  commit. Goal/baseline bootstrap: `d1fde7f` / `5186f0c` / `7dd02be` / `08049e9`.

## 1. S3 goal (frozen)

S3 = **Extensible Governed Agent Runtime**. Core = **L5 Extension Boundary
Maturation**: without overturning the S1/S2 same-spine runtime, advance the
extension boundary from boundary-clear/dormant to a more mature **governed-active**
state. Frozen scope (necessary set) = **MCP + SubAgent**:

- **MCP (must)** — controlled **MCP tool source** only (NOT a full MCP ecosystem).
- **SubAgent (must)** — **read-only / audit-first / parent-mediated** delegation
  only (NOT writable / non-mediated; NOT a full multi-agent ecosystem).
- **Skill** — held at S2 governed-active as a capability-contract reference.
- **Scheduler** — deferred to S4/Sn (boundary kept, not activated).
- **Reference task** — Extension-assisted repo governance (gap-evidence audit).
- **TD policy** — TD-006 entered the S3 release gate (AC-9); TD-007/ruff NOT a
  release blocker.

Full frozen goal: `S3_GOAL.md` (this archive). It was frozen on 2026-06-19 and not
silently widened or narrowed during implementation.

## 2. Completed gaps (S3-G01..S3-G13 — 13/13 satisfied)

| Gap | Title | Evidence (source + test) |
|---|---|---|
| S3-G01 | Define reference task precisely | `S3_REFERENCE_TASK.md` |
| S3-G02 | Unified extension capability contract | `agent/extension_capability.py`; `tests/test_extension_capability_contract.py` |
| S3-G03 | MCP governed tool source (default-off/allowlist/policy/evidence) | `agent/mcp_capability.py` + `register_mcp_tools`→TOOL_REGISTRY; `tests/test_s3_mcp_governed_tool_source.py` |
| S3-G04 | SubAgent read-only/audit-first parent-mediated | `agent/subagent_capability.py` + `subagent_system/gate.py`/`policy.py`; `tests/test_s3_subagent_parent_mediated_acceptance.py` |
| S3-G05 | Extension evidence/checkpoint/task-state integration | `agent/state.py:TaskState.delegation_log`, `agent/task_delegation_evidence.py`; `tests/test_s3_extension_evidence_checkpoint.py` |
| S3-G06 | Extension-assisted repo governance E2E reference task | `tests/test_s3_reference_task_acceptance.py` (fake/local closed loop) |
| S3-G07 | Real provider extension key-path smoke | `tests/test_s3_reference_task_acceptance.py::...real_provider_extension_key_path_smoke` (opt-in/skip) |
| S3-G08 | Acceptance gate extension-regression classification | `agent/acceptance_gate.py:EXTENSION_REGRESSION`; `tests/test_s3_acceptance_gate_extension_classification.py` |
| S3-G09 | TD-006 release-gate cleanup | full pytest green; see §3 + TD-006 resolution (below) |
| S3-G10 | docs/current+history governance for S3 | governance invariants; close-out checklist |
| S3-G11 | Skill contract remains governed-active & non-regressed | `tests/test_s3_skill_non_regression_guard.py`; `skill_system/` untouched |
| S3-G12 | Optional extension hardening (registry/report/health) | `agent/extension_registry.py`; `tests/test_s3_extension_registry.py` |
| S3-G13 | Deferred boundaries & TECH_DEBT triage (S4/Sn) | TD-008..011 in `TECH_DEBT.md` |

## 3. Final acceptance results

- **Full pytest (re-run at close-out prep, 2026-06-20):**
  **4823 passed, 15 skipped, 28 xfailed, 0 failed, exit 0.** The 28 xfailed are
  explicit, documented xfails (FakeProvider semantic shifts, config.yaml provider
  mismatch isolation, an unwritten RFC file, l3-taxonomy naming) — not hidden
  failures. Full-suite is a green release signal (AC-9 met).
- **S3 targeted acceptance (8 S3 test modules):** 32 passed, 1 skipped (real
  smoke opt-in).
- **S2 must-not-regress targeted gate:** 7 passed, 1 skipped (AC-1 holds).
- **Focused ruff** on all S3-touched files: clean. Project-wide `ruff check .`
  remains red at ~443 errors = **TD-007** (carry-forward; NOT a release blocker).

## 4. Capability boundaries at S3 close (must-not-regress for S4)

- **MCP = controlled tool source only.** MCP tools register via `register_mcp_tools`
  into the same `TOOL_REGISTRY`, execute through the shared mediator, gated by
  two-layer policy + registration evidence; **default-off** (`MY_FIRST_AGENT_MCP_ENABLE`,
  proven end-to-end at `main.py:_init_mcp_bridge_if_enabled`), server allowlist
  deny-default, fake-first/dry-run (no real endpoint). NOT a full MCP ecosystem
  (TD-009 deferred).
- **SubAgent = read-only / audit-first / parent-mediated.** S3 gate
  (`MY_FIRST_AGENT_S3_SUBAGENT_ENABLE`) layers on top of the config gate;
  `forbidden_actions` block direct MemoryStore write / real LLM / shell / nested
  SubAgent; `ParentAdjudicationResult` is a pure decision. The live inline-L0
  delegation now records delegation evidence into `delegation_log` →
  checkpoint → evidence report (audit H1 fix). NOT writable / non-mediated
  (TD-010 deferred).
- **Skill = S2 governed-active, non-regressed.** `agent/skill_system/` untouched
  in S3; default-off semantics preserved.
- **Scheduler = dormant (not productionized).** `main.py` never passes
  `action_scheduler`; `chat()`/`LoopDependencies.action_scheduler` default None;
  execution gated by `if action_scheduler is not None`. NOT activated (TD-008
  deferred).
- **same-spine intact.** FakeProvider/RealProvider differ only at factory/config;
  no second main runtime introduced.

## 5. Real provider caveat (AC-6)

The S3 real-provider extension smoke
(`tests/test_s3_reference_task_acceptance.py::test_s3_reference_task_real_provider_extension_key_path_smoke`)
is **opt-in** (`MY_FIRST_AGENT_RUN_S3_REAL_PROVIDER_SMOKE=1`) and **skipped by
default**. It resolves the provider via the production path
(`build_model_provider_from_env()`, reading gitignored `config/config.yaml`) and
includes fake-key detection. **It was never executed against a real key in this
project** (key-safe boundary: opt-in + fake-key detection + default skip). AC-6 is
therefore satisfied **structurally** (the extension-assisted governed path is
reachable, key-safe, and aligned with the fake/local event chain), not by a live
real-model run. A future real-key run is the recommended deeper validation.

## 6. Independent audit findings — all fixed or debt-tracked before close-out

Two independent read-only audits were run. The second flagged one **High**:

- **H1 (High, FIXED via wiring):** the SubAgent delegation evidence seam
  (`record_delegation_run` → `delegation_log`) had **no production caller** — only
  tests invoked it; the live `execute_subagent_delegation` did not. Fixed by wiring
  `state` into `execute_subagent_delegation` and both `core.py` inline-L0 call
  sites so real delegations record evidence. New test
  `tests/test_s3_subagent_runtime_delegation_evidence.py` (3 passed). The prior
  G05/G06 "在真实循环已接入" wording was corrected (it was an overclaim).
- **M1 (Medium, FIXED):** `AGENTS.md` stage status was stale ("S3 has not
  started"); refreshed to S3-active then (this close-out) to S3-closed/S4-preparing.
- **L2 (Low, FIXED):** added end-to-end MCP default-off gate test
  `tests/test_s3_mcp_init_bridge_gate.py` (2 passed).
- **L1 (Low, handled at close-out):** S3 `_tmp_s3_*` scratch dirs archived to this
  archive's `_review_artifacts/` (mirrors S2).
- **L3 (Low, no-op):** S_ROADMAP cosmetic-drift note was itself outdated; already
  correct.

## 7. TD-006 resolution (recorded here at close-out)

TD-006 (stale guard / doc-governance / architecture-boundary / taxonomy /
diagnostics / contract guard tests keeping the full suite red) was **resolved in
S3-G09**: all 39 stale-guard failures cleared by aligning to current S-series
governance (NOT by weakening) — retire_superseded 27, update_to_current_authority
7, update_inventory 3, keep_as_xfail 2. Full pytest went green. TD-006 is removed
from the live `TECH_DEBT.md` register at close-out and recorded here per the
"resolved items live in the stage archive" rule.

## 8. Unresolved / carry-forward debt (stays in `docs/current/TECH_DEBT.md`)

- **Open / carry-forward:** TD-001 (evidence not byte-for-byte), TD-002 (legacy
  provider facade), TD-003 (unreachable `agent/context.py` dead code), TD-004
  (pending-tool event preview gap), TD-007 (ruff ~443 historical lint).
- **Deferred to S4/Sn (scope boundaries):** TD-008 (Scheduler productionization),
  TD-009 (full MCP ecosystem), TD-010 (writable/multi-agent delegation), TD-011
  (durable task ledger).

None were silently closed. Each carries an ID, status, reason, impact, recommended
stage, and verification idea.

## 9. Safety statement

- **No push** was performed for S3 (branch is ahead of origin; push is the user's
  decision).
- **No secrets** were read, printed, copied, moved, or staged. `config/config.yaml`
  and `.env` remain gitignored and untouched. The real-provider smoke only passes
  the config object through; key values were never logged.

## 10. Next stage

**S4 is not implemented.** At close-out, `docs/current/` is reset to the
roadmap + tech-debt working set, then the S4 stage docs
(`S4_BASELINE_STATUS.md` → `S4_GOAL.md` → `S4_GOAL_GAP.md` + a fresh `WORK_LOG.md`)
are created under `docs/current/`. The S4 goal is defined from
`S_ROADMAP.md` (five-layer line), this archived S3 release, and the carry-forward
`TECH_DEBT.md`. S4 must not overturn the S1/S2/S3 same-spine main line.
