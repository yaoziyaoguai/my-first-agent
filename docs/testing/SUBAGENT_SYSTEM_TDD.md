# SubAgent System TDD Plan

Status: Test-Driven Development plan for the formal SubAgent System.

Every phase starts by reading:
- `docs/rfc/SUBAGENT_CANONICAL_RFC.md`
- `docs/design/SUBAGENT_SYSTEM_SDD.md`
- This TDD document

The implementation loop writes or extends tests first, verifies red where
appropriate, then implements the smallest behavior change.

## Phase 0: Existing Safe Local MVP Characterization

- **Tests to add**: characterize existing `agent/subagents/local.py` contracts:
  `SubagentProfile`, `DelegationRequest`, `DelegationResult`, path policy,
  frontmatter validation, secret redaction.
- **Expected behavior**: Safe Local MVP loads `SUBAGENT.md` from fixture
  paths, rejects `model != fake`, blocks external process references, redacts
  secret-like values.
- **Forbidden behavior**: real LLM call, external process spawn, tool
  execution, direct Memory write.
- **Selected command**: `python -m pytest tests/test_subagent_local_mvp_contract.py -q`
- **Exit criteria**: all existing MVP tests green; MVP boundaries confirmed.

## Phase 1: Descriptor / SUBAGENT.md Schema

- **Tests to add**: valid descriptor parse, missing name, invalid name format,
  invalid status, invalid model (must be fake/fixture/none), invalid risk,
  duplicate names fail-closed, secret-like values in frontmatter redacted.
- **Expected behavior**: valid `SUBAGENT.md` frontmatter → `SubAgentDescriptor`.
  Invalid → `SubAgentLoadError`.
- **Forbidden behavior**: partial invalid descriptors becoming visible,
  `model=real` accepted, descriptors with no `name` registered.
- **Selected command**: `python -m pytest tests/test_subagent_descriptor.py -q`
- **Exit criteria**: invalid descriptors fail-closed with typed errors.
  `SubAgentDescriptor` is frozen.

## Phase 2: Filesystem Registry

- **Tests to add**: deterministic scan of explicit roots, descriptors in
  stable order, duplicate names fail-closed, disabled/hidden not visible,
  runtime/session scoped construction (no module-level global), reload
  behavior.
- **Expected behavior**: `SubAgentRegistry(roots=[...])` returns visible
  descriptors only.
- **Forbidden behavior**: module-level global singleton as formal registry,
  network/DB-based discovery, descriptors from non-root paths.
- **Selected command**: `python -m pytest tests/test_subagent_registry.py -q`
- **Exit criteria**: registry isolates per test/session.

## Phase 3: Delegation Request/Result Contract

- **Tests to add**: `SubAgentRequest` creation and validation,
  `SubAgentResult` with all status values (`ok`, `error`,
  `needs_confirmation`, `max_iterations_exceeded`), `SubAgentError` structure,
  `SubAgentAuditRecord` completeness, `SubAgentContext` assembly.
- **Expected behavior**: request → context → execution → result → audit flow
  is well-typed. All dataclasses are frozen.
- **Forbidden behavior**: mutable request/result objects, missing required
  fields silently accepted, audit record missing correlation IDs.
- **Selected command**: `python -m pytest tests/test_subagent_contract.py -q`
- **Exit criteria**: contract types are frozen, validated, and auditable.

## Phase 4: Tool Permission Boundary

- **Tests to add**: `SubAgentToolBoundary.check()` allows tool in both
  descriptor and request `allowed_tools`, blocks tool outside upper bound,
  blocks unknown tool, preserves ToolRegistry risk level, preserves
  confirmation requirement, blocks hidden/internal tools.
- **Expected behavior**: SubAgent can request tools within bounds; all
  execution still flows through ToolRegistry.
- **Forbidden behavior**: tool risk downgrade, confirmation bypass, tool
  execution from SubAgent, hidden tool exposure.
- **Selected command**: `python -m pytest tests/test_subagent_tool_boundary.py tests/test_tool_exposure.py -q`
- **Exit criteria**: tool boundary is a pure check — no execution path.

## Phase 5: Skill Boundary

- **Tests to add**: `SubAgentSkillBoundary.check()` allows Skill in
  `allowed_skills`, blocks Skill outside list, passes through Skill System for
  loading, respects Skill's own `allowed_tools` and `memory_scope`.
- **Expected behavior**: SubAgent receives L1 metadata only for allowed
  Skills; full loading follows Skill System progressive disclosure.
- **Forbidden behavior**: Skill body pre-loading, Skill tool bypass, Skill
  memory scope override.
- **Selected command**: `python -m pytest tests/test_subagent_skill_boundary.py -q`
- **Exit criteria**: Skill boundary delegates to Skill System — no duplicate
  loading logic.

## Phase 6: Memory Boundary

- **Tests to add**: `memory_scope=none` → no context; `read_context` →
  read-only snapshot returned; `propose` → memory proposal validated;
  proposal rejection path; no auto-approve; no direct MemoryStore reference.
- **Expected behavior**: SubAgent receives memory context only through
  adapter. Proposals flow through governance.
- **Forbidden behavior**: direct Memory write, silent retain, auto-approve,
  SubAgent holding MemoryStore reference.
- **Selected command**: `python -m pytest tests/test_subagent_memory_boundary.py tests/test_memory_interaction.py -q`
- **Exit criteria**: existing Memory governance tests still pass unchanged.

## Phase 7: Checkpoint/Resume Boundary

- **Tests to add**: `SubAgentCheckpointSummary` contains only correlation
  metadata; no full prompt/transcript/secret/large artifact stored;
  `delegation_id` and `parent_trace_id` preserved; resume does not replay
  high-risk tool execution; pending confirmation state preserved.
- **Expected behavior**: checkpoint summary is small, safe, and recoverable.
- **Forbidden behavior**: raw prompt dumps, secret storage, tool re-execution
  on resume, SubAgent owning checkpoint save/load timing.
- **Selected command**: `python -m pytest tests/test_subagent_checkpoint_boundary.py tests/test_checkpoint_ownership.py -q`
- **Exit criteria**: existing checkpoint ownership tests still pass.

## Phase 8: Bounded Local Execution / max_iterations

- **Tests to add**: execution stops at `max_iterations`; status
  `max_iterations_exceeded` returned with best-effort summary; iteration
  counter accurate; fake/local execution only (no real LLM).
- **Expected behavior**: SubAgent runs bounded steps, returns result.
- **Forbidden behavior**: unbounded loop, real LLM call, external process
  spawn, exceeding `max_iterations` silently.
- **Selected command**: `python -m pytest tests/test_subagent_execution.py -q`
- **Exit criteria**: `max_iterations` is a hard bound.

## Phase 9: Parent Agent Adapter

- **Tests to add**: Parent creates `SubAgentRequest` → adapter assembles
  `SubAgentContext` → executor runs → `SubAgentResult` returned; error paths;
  tool requests forwarded (not executed); memory proposals queued; audit
  record complete.
- **Expected behavior**: request/result flow is parent-controlled.
- **Forbidden behavior**: SubAgent owning loop, SubAgent calling provider,
  adapter bypassing governance.
- **Selected command**: `python -m pytest tests/test_subagent_adapter.py tests/test_architecture_boundaries.py -q`
- **Exit criteria**: architecture tests confirm Parent owns loop.

## Phase 10: CLI/TUI Visibility

- **Tests to add**: available SubAgent list display, delegation status display,
  result/audit display, blocked action display.
- **Expected behavior**: CLI/TUI present state only.
- **Forbidden behavior**: CLI/TUI imports executor, tool boundary, or memory
  boundary. No runtime logic in presentation.
- **Selected command**: `python -m pytest tests/test_subagent_cli_tui.py tests/test_tui_dependency_boundaries.py -q`
- **Exit criteria**: presentation boundaries remain thin.

## Phase 11: Dogfood

- **Tests to add**: synthetic dogfood fixtures for each scenario in
  `docs/dogfood/SUBAGENT_DOGFOOD_PLAN.md`.
- **Expected behavior**: local-only deterministic runs; no real LLM, no
  network, no `.env`, no real sessions/runs.
- **Forbidden behavior**: network access, real LLM invocation, external
  process spawn, secret logging.
- **Selected command**: `python -m pytest tests/test_subagent_dogfood.py -q`
- **Exit criteria**: dogfood produces audit packets with no private data.

## Phase 12: Architecture Boundary Tests

- **Tests to add**: no ToolRegistry bypass, no Memory direct write, no second
  loop, no CLI/TUI runtime logic, no SubAgent imports from legacy paths, no
  nested SubAgent spawning, Skill System not bypassed, checkpoint safety.
- **Expected behavior**: high cohesion / low coupling module graph.
- **Forbidden behavior**: new SubAgent monolith, cross-layer imports, boundary
  violations.
- **Selected command**: `python -m pytest tests/test_architecture_boundaries.py tests/test_tui_dependency_boundaries.py tests/test_v0_4_transition_boundaries.py -q`
- **Exit criteria**: full suite passes and no P0/P1 audit findings.

## Full-suite Rule

Run full pytest when a phase touches Runtime, ToolRegistry, Memory,
checkpoint/resume, core loop, CLI/TUI, or architecture boundary tests:

```bash
HOME=/private/tmp/my-first-agent-subagent-system-home python -m pytest tests/ -x -q
```
