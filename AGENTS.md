# AGENTS.md

This file is repo-specific guidance for coding agents working on
`my-first-agent` at `/Users/jinkun.wang/work_space/my-first-agent`.
It captures the project rules that repeatedly appear in evidence packets so
future work can stay scoped without relying on a giant prompt each time.

## Project identity

- The project is `my-first-agent`; it is not the coding agent's identity.
- Work on branch `main` unless the user explicitly says otherwise.
- The expected remote is `https://github.com/yaoziyaoguai/my-first-agent.git`.
- `v0.8.0` is the Memory architecture foundation release. Do not create,
  delete, retarget, or push tags without explicit user authorization.

## Stage Development Governance (S1-S5 + S_FINAL closed; roadmap mainline closed)

This project uses a staged development governance model. Stages close one at a
time: a closed stage is archived under `docs/history/`, and `docs/current/`
keeps only the live working set.

- S1 (Baseline Usable Product) is complete and archived under
  `docs/history/S1_BASELINE_USABLE_PRODUCT/`.
- S2 (Governed Task Agent) is complete and archived under
  `docs/history/S2_GOVERNED_TASK_AGENT/`; its release record is
  `docs/history/S2_GOVERNED_TASK_AGENT/S2_RELEASE_SUMMARY.md`.
- S3 (Extensible Governed Agent Runtime) is complete and archived under
  `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/`; its release record is
  `docs/history/S3_EXTENSIBLE_GOVERNED_AGENT_RUNTIME/S3_RELEASE_SUMMARY.md`
  (G01-G13 satisfied; full pytest green; two independent audits' findings fixed).
- S4 (Auditable Governed Agent Runtime) is complete and archived under
  `docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/`; its release record is
  `docs/history/S4_AUDITABLE_GOVERNED_AGENT_RUNTIME/S4_RELEASE_SUMMARY.md`
  (G01-G12 satisfied; independent close-out audit passed; full pytest green in
  the S4 audit record).
- S5 (Durable Governed Task Recovery) is complete and archived under
  `docs/history/S5_DURABLE_GOVERNED_TASK_RECOVERY/`; its release record is
  `docs/history/S5_DURABLE_GOVERNED_TASK_RECOVERY/S5_RELEASE_SUMMARY.md`
  (G01-G11 satisfied; G12 deferred/non-goal guardrail; full pytest green;
  independent audit passed with all findings fixed).
- **S_FINAL (Roadmap Mainline Closure) is complete and archived** under
  `docs/history/S_FINAL_ROADMAP_MAINLINE_CLOSURE/`; its release record is
  `docs/history/S_FINAL_ROADMAP_MAINLINE_CLOSURE/S_FINAL_RELEASE_SUMMARY.md`
  (FINAL-G01..G05 done; G06 deferred carry-forward; G07 guardrail verified;
  full-suite ruff green; full pytest green). **The S-series roadmap mainline is
  closed.** There is no active stage; any next work is a new, separately-authorized
  direction (no S6).

Historical documents are evidence, not routing authority. Do not use historical
docs (including archived S1/S2 stage docs) to override current work unless the
user explicitly promotes them back into `docs/current/`.

### Current Documents

The S-series roadmap mainline is closed (S1-S5 + S_FINAL archived under
`docs/history/`). `docs/current/` now holds the productization working set
only. The closed `S_ROADMAP.md` lives at
`docs/archive/s-series-runtime-kernel/S_ROADMAP.md` (history, not current
authority).

- `docs/current/PRODUCT_CAPABILITY_AUDIT.md`
  - Baseline module maturity audit (L0-L6). Source of truth for maturity
    ratings; later work must not override ratings without new evidence.
- `docs/current/PRODUCTIZATION_ROADMAP.md`
  - Phased productization roadmap (Phase 0-6) derived from the audit.
- `docs/current/PRODUCTIZATION_GAP_LEDGER.md`
  - Single intake for all productization work. New tasks enter here as gaps.
- `docs/current/TECH_DEBT.md`
  - Carry-forward / deferred debt only. Gaps enter the ledger first; only
    genuinely blocked items move here.

Stage scratch evidence (`_tmp_*`) is archived to the relevant stage's
`_review_artifacts/` at close-out (mirrors the S2/S3/S4/S5 archive layout).

### Goal and Gap Rules

These rules apply to whichever stage/goal is active. **The S-series roadmap
mainline is closed** (S1-S5 + S_FINAL all archived under `docs/history/`); there is
no active stage or live gap register under `docs/current/`. Any new stage work
requires a new, explicitly-authorized goal before `docs/current/` stage docs are
recreated.

1. The active stage `*_GOAL.md` is frozen after user approval.
   - Do not change the goal because implementation is hard.
   - Do not narrow the goal silently.
   - Do not expand the goal because a module exists.
   - Only the user can approve goal changes.
2. The active stage `*_GOAL_GAP.md` is a tracked gap / to-do list.
   - Completed gaps must be checked off with evidence.
   - Evidence can be a commit hash, test result, log, trace, audit section, or
     source reference.
   - Do not delete unfinished gaps.
   - Do not rewrite gaps just to make the stage look complete.
3. Gaps may be struck through only when:
   - the user explicitly changes the stage goal;
   - the gap is proven invalid;
   - the gap is merged into another tracked gap;
   - the user explicitly approves cancellation.
4. If an important gap is confirmed out of stage scope, move it to
   `TECH_DEBT.md`.
   - Mark the original gap in the stage `*_GOAL_GAP.md` as moved to debt.
   - Include the technical debt ID.

Example:

```
- [>] Gap: prove X path under real provider. Moved to TECH_DEBT.md: TD-004. Reason: out of stage scope after review.
```

### Technical Debt Rules

`TECH_DEBT.md` is not a dumping ground for unfinished work.

Productization work enters `docs/current/PRODUCTIZATION_GAP_LEDGER.md` first.
An item moves to `TECH_DEBT.md` only when it is genuinely blocked (concrete
code/architecture/external dependency), has a clear future trigger, does not
block the current phase exit, and the debt entry records blocker + impact +
trigger + verification idea. "Large scope", "later", or "future work" are not
valid debt reasons.

Do not add an item to technical debt merely because a task is incomplete today.

Add technical debt only when the project deliberately:

- defers an important issue beyond the current stage;
- uses a workaround;
- leaves a temporary fake/manual path;
- keeps a capability dormant;
- postpones a known architecture gap;
- decides an important gap cannot be completed within S1.

Each debt item must include:

- ID
- Date
- Stage introduced
- Area
- Debt
- Why deferred
- Current impact
- Risk level
- Trigger to revisit
- Status
- Evidence

### Work Log Rules

When a stage is active, every coding-agent run appends an entry to that stage's
`WORK_LOG.md` (created under `docs/current/` for the active stage).

The entry must include:

- date/time
- task name
- files changed
- what was done
- verification commands and results
- stage `*_GOAL_GAP.md` items updated
- `TECH_DEBT.md` items added or updated
- commit hash, if committed
- next step only if authorized by current docs

### Recommendation Rules

Do not freely recommend new directions.

Next-step recommendations are allowed only if they are directly grounded in:

- `docs/current/PRODUCT_CAPABILITY_AUDIT.md`
- `docs/current/PRODUCTIZATION_ROADMAP.md`
- `docs/current/PRODUCTIZATION_GAP_LEDGER.md`
- `docs/current/TECH_DEBT.md`
- the current docs above; the S-series roadmap mainline is closed and there is
  no active stage. The closed `S_ROADMAP.md` is at
  `docs/archive/s-series-runtime-kernel/S_ROADMAP.md` (history, not authority).
  Archived stage docs under `docs/history/` are evidence, not routing authority.
- the user's current explicit instruction

Do not invent:

- new goals
- new phases
- new architecture documents
- new modules
- new roadmaps
- new cleanup plans

If no authorized next step exists in current docs, say:

`No authorized next step found in current docs.`

### Stage Closing Review

Before closing a stage, run a Stage Closing Review:

1. Review all open items in the stage `*_GOAL_GAP.md`.
2. Complete any remaining item that is still feasible within the stage.
3. Move important but unfinished out-of-stage items to `TECH_DEBT.md`.
4. Mark moved items in the stage `*_GOAL_GAP.md` with the referenced debt ID.
5. Append a stage closing entry to the stage `WORK_LOG.md`.
6. Archive the stage docs under `docs/history/<STAGE>/` and reset
   `docs/current/` to the roadmap + tech-debt working set.
7. Do not silently delete unfinished gaps.

### Provider Rules

FakeProvider and RealProvider must not become two separate agents.

FakeProvider:

- is for deterministic tests, CI, and runtime contract verification;
- is not the product capability ceiling;
- must not have its own independent Agent Loop.

RealProvider:

- is for real model execution, manual smoke, and integration validation;
- must not bypass the runtime spine.

After entering the core runtime, FakeProvider and RealProvider should share the
same:

- action parsing;
- dispatcher / tool mediator;
- policy / approval;
- tool execution path;
- checkpoint / state path;
- evidence / log / trace path.

If a task risks splitting fake and real paths, record it in the active stage
`*_GOAL_GAP.md` or `TECH_DEBT.md`.

## Safety boundaries

- no .env
- no agent_log.jsonl contents
- no real sessions/runs
- no real MCP config
- no real skill dirs
- no real subagent dirs
- no private data
- no secret output, secret logging, or env secret expansion
- no real LLM/provider/MCP calls
- no real MCP endpoint connection or server reachability check
- no real server command execution
- no writing real home config or sensitive paths
- public documentation research is allowed only when it does not upload repo
  content, private data, logs, config, or secrets.

## Architecture rules

- Preserve existing architecture.
- no broad refactor
- no framework migration
- no LangGraph conversion
- no memory activation unless explicitly authorized.
- Do not rewrite stable runtime/memory/tool executor paths for elegance.
- Keep CLI adapters thin; service/use-case layers own semantics; presenters own
  output.
- Tool, MCP config, Skill, and Subagent work must not bypass runtime/tool
  policy.
- Skill/Subagent work must be fake-first, local-only, and fixture/sample based.
- parent runtime remains in control for child capability/delegation boundaries.

## Post-Architecture-Repair Navigation

> Note (S1 governance): The documents referenced below were moved under
> `docs/history/` (e.g. `docs/history/06-audit/...`,
> `docs/history/CAPABILITY_BOUNDARIES.md`,
> `docs/history/architecture/ARCHITECTURE_NORTH_STAR.zh.md`). Per **S1
> Development Governance** above, they are historical evidence, not current
> routing authority. Read them for background only; current work is governed by
> the documents under `docs/current/`.

Architecture Repair Mainline is closed:

**ACCEPT_WITH_TRACKED_DEBT — ARCHITECTURE REPAIR MAINLINE CLOSED**

- Do not start Window 4 unless the user explicitly opens a new, documented repair
  mainline.
- Do not treat docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md as an
  active repair queue. It is now a closed historical repair record.
- For module-level hardening or Module Maturity work, read in this order:
  1. docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_RETROSPECTIVE.zh.md
  2. docs/06-audit/ARCHITECTURE_REPAIR_MAINLINE_CLOSURE_AUDIT.zh.md
  3. docs/CAPABILITY_BOUNDARIES.md
  4. docs/06-audit/CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md only as a closed
     historical record
  5. docs/architecture/ARCHITECTURE_NORTH_STAR.zh.md as target/principle
     authority, not as current runtime fact
- Historical Window plans, Window closure audits, and inventories are evidence
  files. Do not execute them as current plans unless a new user request names
  that historical artifact explicitly.

## TDD and quality gates

- For behavior changes, write Red tests first and confirm they fail for the
  intended reason.
- Keep changes surgical and tied to the selected user-approved scope or plan.
- Run targeted tests for touched areas.
- Run `git diff --check`.
- Run `.venv/bin/ruff check .`.
- Run `.venv/bin/python -m pytest -q -rx`; pytest exit code must be 0.
- Known xfails should remain explicit and must not be hidden by skipping,
  deleting, or weakening tests.

## Git and publishing

- Commit only scoped, explainable files.
- Use controlled push only: `git push origin main`.
- no push --tags
- no push --all
- no force push
- no `git push origin v0.8.0` unless explicitly authorized.
- Do not modify remotes.

## Evidence packet standard

Every large pack should end with an evidence packet containing:

- repo status and ahead/behind
- files changed and why they are in scope
- Red/Green evidence
- quality gates and exit codes
- commit hash and push verification
- safety checklist
- P0/P1/P2/P3 risk review
- final verdict and recommended next pack

Stop and ask the user only for P0/P1/P2 blockers, unknown dirty diffs,
out-of-scope production changes, sensitive/private data risk, tag/release
requests, real external integration, or broad refactor pressure.

## Code comments and docs

Add Chinese learning comments/docstrings in key production code, tests, and docs
when they explain architecture boundaries, policy decisions, state transitions,
or why a fake/local-only seam exists.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
