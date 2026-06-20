# S5 Baseline Status

> Status: S5 planning baseline. This document records the repo state after S4
> close-out. It does not freeze the S5 goal and does not authorize an S5 gap
> loop by itself.

## 1. Baseline Verdict

S4 is independently audited, closed, and archived under
`docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/`. `docs/current/` is now the
S5 planning working set plus cross-stage roadmap/debt registers.

Current S5 baseline verdict:

- S1/S2/S3/S4 are complete and archived.
- S4 delivered redacted-faithful audit/replay/verifier maturity for governed
  task evidence.
- S5 has not been implemented; no S5 gap loop has run.
- The next S5 goal should be selected from the remaining roadmap/debt surface,
  not invented outside the S-series five-layer model.

## 2. Current Repository State

- Branch: `main`.
- Remote expectation: `origin` points to the project remote configured for this
  repo; this audit did not modify remotes.
- Push status: no push was performed during S4 close-out or S5 planning.
- Current docs:
  - `docs/current/S_ROADMAP.md`
  - `docs/current/TECH_DEBT.md`
  - `docs/current/S5_BASELINE_STATUS.md`
  - `docs/current/S5_GOAL.md` once drafted
  - `docs/current/S5_GOAL_GAP.md` once generated
  - `docs/current/WORK_LOG.md`
- S4 archive:
  - `docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/S4_RELEASE_SUMMARY.md`
  - archived S4 baseline/goal/gap/fidelity contract/work log

## 3. Prior Stage Capability Summary

### S1 - Baseline Usable Product

S1 established the product baseline: local-first runtime, basic usable CLI/TUI
entry points, same-spine runtime expectations, and historical capability
boundaries for Memory, Skill, MCP, SubAgent, and Scheduler.

### S2 - Governed Task Agent

S2 added governed task semantics over the runtime: task state, approval/policy
checks, progress/review structures, regression protection, and guardrails that
prevented fake/real provider paths from splitting into separate agents.

### S3 - Extensible Governed Agent Runtime

S3 matured extension boundaries while keeping them governed:

- Skill lifecycle remained governed and local/fake-first.
- MCP became a controlled tool source routed through the same tool registry,
  mediator, policy, and evidence path.
- SubAgent stayed parent-mediated and read-only/audit-first.
- Scheduler remained boundary-clear and dormant, not default runtime behavior.
- Full pytest returned to green with explicit xfails.

### S4 - Auditable Governed Agent Runtime

S4 matured L3 evidence fidelity:

- redacted-faithful replay chain over governed task state;
- synthetic secret redaction on the high-fidelity replay/audit surface;
- pending-tool preview/status fidelity for approval flows;
- evidence verifier for completeness, self-consistency, ordering, and
  replayability;
- fake/local reference task covering governed MCP + SubAgent audit/replay;
- opt-in key-safe real provider smoke harness with no live-key success claim;
- acceptance classification for evidence-fidelity regressions.

## 4. L1-L5 Current State

### L1 - Runtime Spine

The runtime spine remains shared across FakeProvider and RealProvider after
entering the core loop. S4 did not create a second agent path. Acceptance gates
can now classify evidence-fidelity regressions in addition to existing runtime,
extension, and debt categories.

Boundary: planner/compress still expose a legacy provider call facade
(`TD-002`), but this is a second call shape over the same provider, not a second
runtime spine.

### L2 - Context / Memory / State / Checkpoint

Checkpoint/resume exists and remains the live durability mechanism. Memory v0
contracts and evidence recording exist, but memory activation and durable
cross-session task ledger are not implemented as current product capability.

Boundary:

- `TD-003` tracks unreachable legacy context compression code.
- `TD-011` tracks the deferred durable task ledger.

### L3 - Tools / Policy / Evidence

Tool execution runs through the mediator/executor/policy/evidence path. MCP
tools use the same governed registry/mediator path. S4 added the replay chain,
redaction projection, verifier, audit observability, and fidelity acceptance
classification.

Boundary:

- S4 redaction is hard-wired to the replay/audit projection surface.
- Legacy mediator `TOOL_RESULT` preview and `record_evidence` metadata are not
  yet fully wired to the S4 redaction helpers (`TD-012`).
- The verifier does not yet detect cross-kind duplicate refs (`TD-013`).

### L4 - Task Orchestration / State Machine / Progress Tracking

The governed task state model supports steps, progress, review, pending tool
approval, delegation logs, and evidence-derived replay. S4 strengthened audit
truthfulness but did not add durable recovery, re-planning, or crash-survivable
task orchestration.

Boundary: crash recovery still relies on checkpoint files; no independent
ledger exists.

### L5 - Skill / MCP / SubAgent / Scheduler Extension Boundary

Skill, MCP, SubAgent, and Scheduler boundaries are clearer than S1:

- Skill lifecycle is governed and tested.
- MCP is default-off controlled tool-source integration.
- SubAgent is read-only/audit-first and parent-mediated.
- Scheduler is dormant unless explicitly injected.

Deferred:

- Scheduler productionization (`TD-008`)
- full MCP ecosystem (`TD-009`)
- writable/multi-agent SubAgent ecosystem (`TD-010`)

## 5. Evidence / Audit / Replay Boundary After S4

What is true now:

- Governed task replay is redacted-faithful, ordered, and verifiable for the S4
  replay-chain surface.
- Audit observability can summarize replay/verifier outcomes without exposing raw
  payloads.
- Pending tool previews now avoid false `executed/success` status for
  failed/rejected pending tools.
- S4 reference coverage is fake/local deterministic; real provider smoke is
  opt-in and key-safe.

What is not true:

- The project does not persist raw secret payloads for byte-for-byte replay.
- The S4 redaction helper is not globally wired into every legacy evidence or
  mediator projection.
- Real provider live success is not claimed.
- The verifier is not a complete semantic proof system for every possible
  evidence collision or domain inconsistency.

## 6. Live Technical Debt

Open / carry-forward:

- `TD-002` - planner/compress use legacy provider facade.
- `TD-003` - unreachable secondary context compression path.
- `TD-007` - full-project ruff remains red due to historical lint drift.
- `TD-012` - S4 redaction is not wired into legacy mediator/evidence-recorder
  preview paths.
- `TD-013` - verifier does not detect cross-kind duplicate refs.

Deferred scope boundaries:

- `TD-008` - Scheduler productionization / main-loop activation.
- `TD-009` - full MCP ecosystem.
- `TD-010` - writable / multi-agent SubAgent ecosystem.
- `TD-011` - durable cross-session task ledger.

Resolved in S4 and no longer live:

- `TD-001` - resolved as redacted-faithful replay.
- `TD-004` - resolved pending-tool preview/status fidelity.

## 7. Verification State

Baseline audit commands already run on 2026-06-20:

- Full pytest: `.venv/bin/python -m pytest -q -rx`
  - Result: `4867 passed, 16 skipped, 28 xfailed`
- S4 targeted: `.venv/bin/python -m pytest tests/test_s4_*.py -q`
  - Result: `44 passed, 1 skipped`
- S1 targeted:
  - `tests/golden_e2e`
  - `tests/smoke/test_first_usable_task_e2e.py`
  - `tests/runtime_integration/test_phase1_real_core_loop.py::TestCoreChatWiring::test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook`
  - Result: `22 passed`
- S2 targeted: selected governed-task/runtime-policy suites
  - Result: `32 passed, 1 skipped`
- S3 targeted: selected Skill/MCP/SubAgent/Scheduler/extension-boundary suites
  - Result: `30 passed, 1 skipped`
- Focused ruff on S4-touched Python/test files:
  - Result: clean

Known caveat:

- Full-project `.venv/bin/ruff check .` is expected to remain red under `TD-007`
  until a dedicated lint cleanup stage/pack is authorized.

## 8. Docs / History Cleanliness

Expected current working set after S5 planning docs exist:

- `docs/current/S_ROADMAP.md`
- `docs/current/TECH_DEBT.md`
- `docs/current/S5_BASELINE_STATUS.md`
- `docs/current/S5_GOAL.md`
- `docs/current/S5_GOAL_GAP.md`
- `docs/current/WORK_LOG.md`

Historical routing:

- S1 archive remains under `docs/history/S1_BASELINE_USABLE_PRODUCT/`.
- S2 archive remains under `docs/history/S2_GOVERNED_TASK_AGENT/`.
- S3 archive remains under `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/`.
- S4 archive now lives under
  `docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/`.

Historical docs are evidence only, not current routing authority.

## 9. Roadmap Remaining Surface

`S_ROADMAP.md` deliberately does not prescribe a fixed S5 implementation plan.
The remaining roadmap surface must stay within the five-layer model:

- L2 durability/state/checkpoint deepening, especially `TD-011`.
- L3 evidence hardening, especially `TD-012` and `TD-013`.
- L4 governed task orchestration/recovery beyond audit replay.
- L5 selective extension activation, especially Scheduler, MCP ecosystem, and
  SubAgent boundaries, only when a future goal explicitly chooses them.
- Cross-stage quality cleanup such as `TD-007`, if explicitly prioritized.

## 10. S5 Candidate Starting Points

Viable S5 candidates from the baseline:

1. Durable governed task recovery: turn checkpoint-only recovery into a
   ledger-backed, local-safe L2/L4 durability foundation while preserving the
   same runtime spine.
2. Evidence hardening: close `TD-012`/`TD-013` and mature S4 audit fidelity
   further without expanding orchestration.
3. Selective extension activation: choose one L5 boundary, such as Scheduler,
   and activate it under governed policy/evidence controls.

Baseline recommendation pressure: durable governed task recovery is the strongest
next candidate because it consumes a clear deferred roadmap item (`TD-011`) and
creates the foundation needed before broader Scheduler or multi-extension
activation.
