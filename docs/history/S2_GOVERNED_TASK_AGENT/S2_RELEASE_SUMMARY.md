# S2 Release Summary — Governed Task Agent

> Archive summary for S2. This is an evidence/record document, not routing
> authority. S2 is complete; the next step is a fresh S3 baseline audit when the
> user authorizes it. See `docs/current/S_ROADMAP.md` and
> `docs/current/TECH_DEBT.md` for the post-S2 context.

- **Release name**: S2 — Governed Task Agent
- **Verdict**: **completed / release-ready**
- **Stage window**: S1 archive → S2 closeout (2026-06-17 baseline audit →
  2026-06-19 release hardening pass → S2 closeout)
- **Commit range**: `origin/main..HEAD` = 23 commits (`6ed21c5` archive S1 &
  bootstrap S2 docs → closeout commit)

## 1. Core capabilities delivered

S2 upgraded FirstAgent from S1's "baseline usable product" to a **governed
multi-step task agent** on the same runtime spine:

- **L4 task orchestration** — formal governed task state model
  (`GovernedTaskLifecycle`/`GovernedStepStatus`/`GovernedTaskProgress`) +
  orchestration skeleton (receive→plan→execute→advance→checkpoint→resume→done).
- **L2 task context** — `TaskContextPackage`, task-scoped memory boundary,
  provider-callable context validation, resume-does-not-lose-content contract.
- **L3 governed tool contract** — task-level governed tool report + safe evidence
  summary over `tool_execution_log` (allowed/rejected/failed/control + bypass
  detection).
- **L4 progress + human review** — `TaskProgressReview` (progress %, current
  step, blocking reason) + side-effect-free `HumanTakeoverDecision` seam.
- **L3 task evidence depth** — `TaskEvidenceReport` (structured replay metadata,
  not byte-for-byte; TD-001/TD-004 surfaced as explicit debt).
- **L1 acceptance classification** — `acceptance_gate.py` separates
  runtime_regression / doc_governance_debt / quality_debt / unknown_failure.
- **L5 Skill selectively-active** — first L5 capability under a governed gate
  (`MY_FIRST_AGENT_S2_SKILL_ENABLE`, default-off).

## 2. Final acceptance results

All S2 gaps (S2-G01..S2-G13) satisfied (13/13). Final acceptance gate:

| Check | Command | Result |
|---|---|---|
| S2 targeted acceptance | `pytest tests/test_s2_reference_task_acceptance.py` | 1 passed, 1 skipped (real opt-in) |
| S2 skill gate | `pytest tests/test_s2_skill_controlled_integration.py` | 6 passed |
| S2 acceptance gate | `pytest tests/test_s2_acceptance_gate.py` | 5 passed |
| S1 must-not-regress | golden_e2e + smoke + wiring | 22 passed |
| S1 observability | evidence_lifecycle + b7_event_log | 91 passed |
| All S2 gap tests | 9 S2 test modules | 32 passed, 1 skipped |

## 3. Real provider evidence (AC-7)

**Passed**. `MY_FIRST_AGENT_RUN_S2_REAL_PROVIDER_SMOKE=1 pytest ...::test_s2_
reference_task_real_provider_key_safe_context_smoke` → 1 passed (real non-fake
provider). The smoke resolves the provider via the **production path**
(`build_model_provider_from_env()`, reads `config/config.yaml`), enters the S2
governed task path, and records evidence through the **same memory/tool/task
seam** as the fake E2E — proving real provider enters the governed task path
and aligns key-event chains with fake/local. Key-safe: no secret read/printed/
copied/moved/staged.

## 4. S2-G09 Skill default-off final contract

- **Semantics**: discovery allowed, activation default-off, execution gated.
- `build_skill_registry()` keeps S1 behavior (always scans `skills/`).
- default-off gate acts only at activation/execution: SKILL_SELECT registration,
  `SkillRuntimeActionHandler.handle`, `core.py` body injection, checkpoint
  restore.
- **Test contract**: discovery/metadata tests stay opt-out; activation/
  execution tests opt in via `monkeypatch.setenv("MY_FIRST_AGENT_S2_SKILL_ENABLE","1")`.
- A release-hardening reconciliation corrected a misclassification: ~37 skill
  test failures had been wrongly counted as TD-006; they were test-contract
  gaps (activation tests needing opt-in), now fixed across 10 test files.

## 5. Full pytest remaining state

**33 failed, 4782 passed, 14 skipped, 26 xfailed**. All 33 failures are **TD-006
known guard/governance/architecture-boundary tests** (not runtime regressions,
not unknown failures):

- `test_docs_source_of_truth.py` (17), `test_architecture_boundaries.py` (6),
  `test_v6_drift_addendum_boundary.py` (5), `test_evidence_taxonomy_guard.py` (2),
  `test_provider_diagnostics.py` (1), `test_streaming_protocol.py` (1),
  `test_capability_boundary_contract.py` (1).

## 6. Ruff state

`ruff check .` = **TD-007** ~451 historical lint errors (quality debt, not a
runtime regression). Changed S2 files all pass focused ruff (S2-G12 policy).

## 7. Known carry-forward debts (→ TECH_DEBT.md)

- **TD-006** (P1) — stale guard/governance/architecture-boundary tests keep
  full-suite red (33 failures). Carry-forward: S3/Sn guard cleanup.
- **TD-007** (P3) — ruff ~451 historical lint. Carry-forward: S3/Sn lint pass.
- **TD-001** (P2) — evidence does not persist full model request/response body.
  S2 surfaced (structured replay only); full-fidelity = S3/Sn.
- **TD-002** (P3) — planning/compress legacy `ProviderBackedClient` facade.
  Carry-forward: S3/Sn adapter refactor.
- **TD-003** (P3) — `agent/context.py` unreachable dead code. Carry-forward:
  S3/Sn dead-code removal.
- **TD-004** (P3) — pending-tool events log omits tool_output preview. S2
  surfaced; S3/Sn fidelity cleanup.

## 8. Commit range (`origin/main..HEAD`, 23 commits)

```
closeout  docs: close out S2 and reset current context
4473941   chore: ignore local coding-agent tooling config (.claude/, CLAUDE.md)
3565829   docs: restore S2 release doc consistency
64baa9e   test: strengthen S2 real provider governed-path smoke (AC-7)
b931d86   test: reconcile S2 skill default-off activation test contract
a55c22a   fix: gate S2 skill activation without hiding registry
0df5cc2   docs: triage S2 technical debt into S2/S3/Sn lanes
f5f0340   docs: document S2 quality gate strategy
1c7de1f   feat: add S2 task evidence report
700b848   feat: add S2 Skill controlled integration gate
f354ffd   docs: select Skill as S2 L5 candidate
4f38fb1   test: add S2 reference task acceptance
b495766   feat: classify S2 acceptance gate signals
b72934b   feat: add S2 task progress review seam
b58b5ec   feat: add S2 governed tool contract report
0d4f23e   feat: add S2 task context package
b67b7e4   feat: add S2 task orchestration skeleton
3be7f4b   feat: define S2 governed task state model
8e706b3   docs: resolve S2 open decisions
d6d2841   docs: generate S2 goal gap backlog
9f01674   docs: draft S2 governed task agent goal
46e2efb   docs: refine S2 baseline audit findings
568317e   docs: audit S2 baseline status
6ed21c5   docs: archive S1 and bootstrap S2 docs
```

## 9. Safety statement

- **No push** was performed for S2 (branch is ahead of origin; push is the
  user's decision).
- **No secrets** were read, printed, copied, moved, or staged. `config/config.yaml`
  and `.env` remain gitignored and untouched. The real-provider smoke only
  passed the config object through; key values were never logged.

## 10. Next stage

**S3 is not started.** `docs/current/` now holds only `S_ROADMAP.md` and
`TECH_DEBT.md` — a clean post-S2 / pre-S3 entry point. No `S3_GOAL.md`,
`S3_GOAL_GAP.md`, or `S3_BASELINE_STATUS.md` exists. The next authorized task is
an **S3 baseline audit** (to be started only on explicit user authorization),
which will establish the S3 starting facts from this archived S2 state.
