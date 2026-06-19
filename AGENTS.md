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

## S2 Development Governance

This project uses a staged development governance model. S1 is complete and
archived; S2 (Governed Task Agent) is the active stage.

- Active documentation lives under `docs/current/`.
- Historical documentation lives under `docs/history/`. S1 evidence is archived
  under `docs/history/S1_BASELINE_USABLE_PRODUCT/`.

Historical documents are evidence, not routing authority. Do not use historical
docs to override current S2 documents unless the user explicitly promotes them
back into `docs/current/`.

### Current S2 Documents

The current working set is:

- `docs/current/S2_BASELINE_STATUS.md`
  - S2 starting-state audit (the S2 entry baseline, not the current release
    status). Describes what S2 inherited from S1.
  - This is not a goal document.
- `docs/current/S2_GOAL.md`
  - Confirmed/frozen S2 goal (Governed Task Agent) after user approval.
  - Defines what this stage must achieve.
  - Do not modify this file unless the user explicitly asks to redefine or
    update the S2 goal.
- `docs/current/S2_GOAL_GAP.md`
  - Gap list between the S2 baseline and the frozen S2 goal.
  - This is the active to-do list for the stage.
  - Do not remove or rewrite gaps just because they are hard.
- `docs/current/S2_ACCEPTANCE_GATE.md`
  - S2 release-judgment rules: targeted acceptance vs health/debt signals.
- `docs/current/TECH_DEBT.md`
  - Cross-stage technical debt register.
  - Important deferred work, workarounds, dormant decisions, and out-of-stage
    issues must be tracked here.
- `docs/current/WORK_LOG.md`
  - Per-agent-run execution log.
  - Every coding-agent run must append a summary here.

### Goal and Gap Rules

1. `S2_GOAL.md` is frozen after user approval.
   - Do not change the goal because implementation is hard.
   - Do not narrow the goal silently.
   - Do not expand the goal because a module exists.
   - Only the user can approve goal changes.
2. `S2_GOAL_GAP.md` is a tracked gap / to-do list.
   - Completed gaps must be checked off with evidence.
   - Evidence can be a commit hash, test result, log, trace, audit section, or
     source reference.
   - Do not delete unfinished gaps.
   - Do not rewrite gaps just to make the stage look complete.
3. Gaps may be struck through only when:
   - the user explicitly changes the S2 goal;
   - the gap is proven invalid;
   - the gap is merged into another tracked gap;
   - the user explicitly approves cancellation.
4. If an important gap is confirmed out of S2 scope, move it to `TECH_DEBT.md`.
   - Mark the original gap in `S2_GOAL_GAP.md` as moved to debt.
   - Include the technical debt ID.

Example:

```
- [>] Gap: prove X path under real provider. Moved to TECH_DEBT.md: TD-004. Reason: out of S2 scope after review.
```

### Technical Debt Rules

`TECH_DEBT.md` is not a dumping ground for unfinished work.

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

Every coding-agent run must append an entry to `docs/current/WORK_LOG.md`.

The entry must include:

- date/time
- task name
- files changed
- what was done
- verification commands and results
- `S2_GOAL_GAP.md` items updated
- `TECH_DEBT.md` items added or updated
- commit hash, if committed
- next step only if authorized by current docs

### Recommendation Rules

Do not freely recommend new directions.

Next-step recommendations are allowed only if they are directly grounded in:

- `docs/current/S2_GOAL.md`
- `docs/current/S2_GOAL_GAP.md`
- `docs/current/TECH_DEBT.md`
- `docs/current/WORK_LOG.md`
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

1. Review all open items in `S2_GOAL_GAP.md`.
2. Complete any remaining item that is still feasible within the stage.
3. Move important but unfinished out-of-stage items to `TECH_DEBT.md`.
4. Mark moved items in `S2_GOAL_GAP.md` with the referenced debt ID.
5. Append a stage closing entry to `WORK_LOG.md`.
6. Do not silently delete unfinished gaps.

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

If a task risks splitting fake and real paths, record it in `S2_GOAL_GAP.md` or
`TECH_DEBT.md`.

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
