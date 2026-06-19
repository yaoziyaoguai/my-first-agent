# S3 Baseline Status

> Current document (`docs/current/`). This records the **starting facts** for S3,
> grounded in the clean post-S2 / pre-S3 repo state. It is a **baseline**, not a
> goal and not a gap list. It does **not** define what S3 will do. `S3_GOAL.md`
> and `S3_GOAL_GAP.md` are created only after the user authorizes an S3 goal.
>
> Authority order for the next stage: `docs/current/S_ROADMAP.md`, the archived
> S2 release record, and the user's explicit instruction (see `AGENTS.md`).

## 0. Verdict

S3 has a **clean, well-governed starting point**. S2 (Governed Task Agent) is
complete, committed, and archived; the working tree is clean; the targeted S2
acceptance gate still passes on a fresh re-run (12 passed, 1 skipped). The S-series
runtime spine and the five-layer capability surface are intact in code. Two
quality debts (TD-006 full-suite guard red, TD-007 ruff red) and four
fidelity/cleanup debts (TD-001/002/003/004) carry forward. **S3's goal is not
defined and is intentionally left open** — this document only establishes where
S3 starts, not where it should go.

## 1. Scope

- **In scope:** record the post-S2 doc layout, the archived S2 release, the
  capabilities S3 inherits, the runtime/code baseline, the test/verification
  baseline, the carry-forward technical debt, and the known unknowns.
- **Out of scope (deliberately not done here):** defining the S3 goal, generating
  an S3 gap list, choosing an S3 direction (multi-agent / MCP / skill ecosystem /
  scheduler), modifying code/tests/config, or running the full pytest/ruff suites.
- **Method:** read-only audit of `docs/current/`, the S2 archive, the S1 archive,
  plus a fresh targeted-gate re-run and graphify/file confirmation of the S2 code
  surface. Full evidence: `_tmp_s3_baseline_audit/audit_evidence.md`.

## 2. Current doc layout

`docs/current/` after this audit:

- `S_ROADMAP.md` — authoritative S-series version semantics and the five-layer
  line (L1–L5). Does not encode a hard S2/S3/Sn implementation plan.
- `TECH_DEBT.md` — cross-stage carry-forward technical-debt register (open items
  only).
- `S3_BASELINE_STATUS.md` — this file.
- `WORK_LOG.md` — S3 work log (started by this audit).
- `_tmp_s3_baseline_audit/` — scratch evidence for this audit.

No `S2_*` files remain in `docs/current/` (one reference path in `TECH_DEBT.md`
points into the history archive, which is expected). No `S3_GOAL.md` /
`S3_GOAL_GAP.md` exists.

## 3. Archived S2 release

- Archive: `docs/history/S2_GOVERNED_TASK_AGENT/`.
- Release record: `S2_RELEASE_SUMMARY.md` — verdict **completed / release-ready**;
  all S2 gaps S2-G01..S2-G13 satisfied (13/13); commit range
  `origin/main..HEAD` ≈ 23 commits (`6ed21c5` → closeout).
- Stage docs archived: `S2_GOAL.md`, `S2_GOAL_GAP.md`, `S2_BASELINE_STATUS.md`,
  `S2_ACCEPTANCE_GATE.md`, `WORK_LOG.md`, plus S2 design/triage notes
  (`S2_L5_SKILL_SELECTION.md`, `S2_QUALITY_GATE_STRATEGY.md`,
  `S2_REFERENCE_TASK_ACCEPTANCE.md`, `S2_TASK_EVIDENCE_DEPTH.md`,
  `S2_TASK_STATE_MODEL.md`, `S2_TECH_DEBT_TRIAGE.md`).
- Review/tmp evidence preserved under `_review_artifacts/`
  (`_tmp_s2_baseline_audit/`, `_tmp_s2_goal_draft/`, `_tmp_s2_goal_gap/`).
- Note: there is no separate `S2_GOVERNED_TASK_AGENT/TECH_DEBT.md`; S2 debt was
  consolidated into `docs/current/TECH_DEBT.md` and `S2_TECH_DEBT_TRIAGE.md`.

These are historical evidence, not routing authority (per `AGENTS.md`).

## 4. Capabilities inherited from S2

S2 upgraded FirstAgent from S1's baseline-usable product to a **governed
multi-step task agent** on the same runtime spine. S3 inherits, as a
**must-not-regress** floor:

- **Governed task path (L4)** — formal task state model + orchestration skeleton
  `receive → plan → execute → advance → checkpoint → resume → done`.
- **Task orchestration / state / progress (L4)** — task state, step status,
  progress %, current step, blocking reason; human review / takeover seam
  (side-effect-free).
- **Context / memory / checkpoint (L2)** — task-scoped context package, task
  memory boundary, resume-does-not-lose-provider-callable-content contract,
  large-result-summary resume.
- **Tool / policy / evidence (L3)** — all tool calls go through the governed
  mediator/dispatcher/policy path; task-level governed tool report with
  allowed/rejected/failed/control + bypass detection; structured task evidence
  report (replay metadata, not byte-for-byte).
- **Skill selectively-active (L5)** — Skill is the first L5 capability under a
  governed, default-off gate (`MY_FIRST_AGENT_S2_SKILL_ENABLE`): discovery
  allowed, activation default-off, execution gated; behavior equals S1 when off.
- **Real-provider governed-path smoke (AC-7)** — opt-in, key-safe; real provider
  resolves via the production path (`build_model_provider_from_env()` reading
  `config/config.yaml`), enters the governed task path, and records evidence
  through the same memory/tool/task seam as the fake E2E.
- **Acceptance gate / release governance (L1, AC-8/AC-10)** — `acceptance_gate.py`
  separates runtime_regression / doc_governance_debt / quality_debt /
  unknown_failure, so TD-006/TD-007 red does not contaminate the runtime
  acceptance signal.

## 5. Runtime / code baseline

The same-spine runtime and the five-layer surface are present in code (graphify +
file confirmation; details in the evidence packet):

- **L1:** `agent/core.py`, `agent/runtime_integration/{dispatcher,schema,tool_gate,evidence}.py`, `agent/acceptance_gate.py`.
- **L2:** `agent/task_context.py`, `agent/memory_store.py` (+ `agent/memory.py` runtime compression path).
- **L3:** `agent/task_tool_contract.py`, `agent/tool_runtime_mediator.py`, `agent/evidence_recorder.py`, `agent/task_evidence_report.py`.
- **L4:** `agent/task_state_model.py`, `agent/task_orchestration.py`, `agent/task_runtime.py`, `agent/task_review.py`.
- **L5 (active, default-off):** `agent/skill_system/*` (gate, selector, lifecycle, checkpoint_restore, task_boundary, memory_boundary, registry, …).
- **L5 (dormant / boundary-clear seams, not the S2 active capability):**
  `agent/runtime_integration/{mcp_bridge_lifecycle,mcp_tool_orchestrator,skill_lifecycle}.py`, `agent/subagent_system/*`. These exist in code but were not the S2 governed-activation target.

FakeProvider and RealProvider share one spine; the fake/real boundary stays at
the factory/config layer (per `AGENTS.md` Provider Rules).

## 6. Test and verification baseline

- **Targeted S2 acceptance gate (fresh re-run, 2026-06-19):** `12 passed,
  1 skipped` (skip = real-provider smoke, opt-in). The S2 release signal is still
  credible at the S3 starting point.
- **Full pytest (inherited from S2 release record; not re-run this audit):**
  33 failed / 4782 passed / 14 skipped / 26 xfailed. All 33 failures are the
  TD-006 known guard/governance/architecture-boundary set, classified as
  doc-governance debt, not runtime regressions.
- **ruff (inherited):** `ruff check .` ≈ 451 historical lint errors = TD-007
  (quality debt). Changed S2 files passed focused ruff (S2-G12 policy).
- **Acceptance gate doctrine carried into S3:** targeted gate = product signal;
  full pytest/ruff = health/debt signals; any unknown failure is release-blocking
  until classified.
- **Caveat:** full pytest/ruff were not re-executed in this audit (tree unchanged
  since `39edfdd`; token economy). A fresh full-suite re-classification is the
  recommended verification once S3 docs settle.

## 7. Technical debt baseline

Carry-forward register (`docs/current/TECH_DEBT.md`), all **open**:

- **TD-006** (P1) — stale doc-governance / architecture-boundary / taxonomy /
  diagnostics / contract guard tests keep the full suite red (33 failures).
  Trigger: before relying on full-suite status as a release signal.
- **TD-007** (P3) — `ruff check .` ≈ 451 historical lint errors. Trigger:
  dedicated batched lint pass.
- **TD-001** (P2) — evidence records structured summary + size metadata, not
  byte-for-byte model/tool payloads. Trigger: full-fidelity audit/compliance.
- **TD-002** (P3) — planner/compress still expose a second call shape via the
  legacy `ProviderBackedClient` facade. Trigger: provider-adapter refactor.
- **TD-003** (P3) — `agent/context.py` `compress_history` is confirmed-unreachable
  dead code. Trigger: L2 context cleanup touching `agent/context.py`.
- **TD-004** (P3) — pending-tool `events.jsonl` may show an empty `tool_output`
  preview. Trigger: event-log fidelity pass.

Deferred-to-S3+ architecture items (from `S2_TECH_DEBT_TRIAGE.md`): durable task
ledger; full Skill/MCP/SubAgent/Scheduler ecosystem; multiple simultaneously
active L5 capabilities; broad provider/planner facade cleanup.

## 8. Risks and unknowns

- **S3 goal is undefined.** No S3 direction is chosen. The roadmap states S2+ does
  selective deepening "by the priority decided when the stage is entered" — that
  priority is not yet set.
- **S3 gap is not generated.** It is produced from baseline-vs-goal after the goal
  is frozen, not now.
- **Direction candidates are open, not decided.** Whether S3 pursues multi-agent /
  MCP / skill ecosystem / scheduler / durable ledger / debt cleanup (TD-006/007)
  is a user decision grounded in the roadmap. The dormant MCP/SubAgent seams and
  the deferred S3+ items exist as *options*, not as a committed plan.
- **Full-suite signal is red by known debt.** Until TD-006/TD-007 are addressed,
  full pytest/ruff cannot serve as a green release gate; only the targeted gate
  can. If S3 wants full-suite as a release signal, TD-006 cleanup is a prerequisite.
- **Minor doc drift:** `S_ROADMAP.md:46` still references the old "S1 Development
  Governance" section name; `AGENTS.md` renamed it to "Stage Development
  Governance (post-S2 / pre-S3)". Cosmetic; left untouched by this audit.
- **graphify graph is stale** vs. the closeout doc moves (still points some S2 doc
  nodes at old `docs/current/` paths). Expected; no code changed this run.

## 9. Recommended next step

Grounded only in `S_ROADMAP.md`, the archived S2 release, and `AGENTS.md`:

> The next authorized step is to **define the S3 goal with the user** — decide
> which of the five layers S3 deepens and at what priority — and only then create
> `docs/current/S3_GOAL.md` (frozen on approval) followed by `S3_GOAL_GAP.md`.

This document does **not** pick that goal. No new goals, phases, architecture
docs, modules, roadmaps, or cleanup plans are proposed here (per `AGENTS.md`
Recommendation Rules). If S3 is not authorized, the standing answer remains: the
repo is at a clean post-S2 / pre-S3 baseline awaiting an S3 goal decision.
