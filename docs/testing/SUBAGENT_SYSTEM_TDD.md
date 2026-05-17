# SubAgent System TDD Plan

Status: Test-Driven Development plan for the production-grade formal SubAgent
System. Every phase starts by reading `docs/rfc/SUBAGENT_CANONICAL_RFC.md`,
`docs/design/SUBAGENT_SYSTEM_SDD.md`, and this document.

The implementation loop writes or extends tests first, verifies red where
appropriate, then implements the smallest behavior change.

Tests are categorized:
- **Required for v1**: must pass before v1 is considered complete.
- **Gated but designed**: tests exist but execution requires config gate.
- **Future but documented**: test stubs / contracts defined for future phases.

## Phase 0: Existing Safe Local MVP Characterization

- **Category**: Required for v1.
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

- **Category**: Required for v1.
- **Tests to add**: valid descriptor parse, missing name, invalid name format,
  invalid status, invalid model (must be fake/fixture/none in v1), invalid risk,
  duplicate names fail-closed, secret-like values in frontmatter redacted,
  `supported_modes` validation, `max_iterations_default` range check.
- **Expected behavior**: valid `SUBAGENT.md` frontmatter → `SubAgentDescriptor`.
  Invalid → `SubAgentLoadError`. `supported_modes` must be subset of known
  `SubAgentExecutionMode` values.
- **Forbidden behavior**: partial invalid descriptors becoming visible,
  `model=real` accepted in v1 without config gate, descriptors with no `name`
  registered, unsupported modes silently accepted.
- **Selected command**: `python -m pytest tests/test_subagent_descriptor.py -q`
- **Exit criteria**: invalid descriptors fail-closed with typed errors.
  `SubAgentDescriptor` is frozen. `supported_modes` validation operational.

## Phase 2: Filesystem Registry

- **Category**: Required for v1.
- **Tests to add**: deterministic scan of explicit roots, descriptors in
  stable order, duplicate names fail-closed, disabled/hidden not visible,
  runtime/session scoped construction (no module-level global), reload
  behavior, `find_by_role` filtering, `supported_modes` filtering.
- **Expected behavior**: `SubAgentRegistry(roots=[...])` returns visible
  descriptors only. `find_by_role` returns matching active descriptors.
- **Forbidden behavior**: module-level global singleton as formal registry,
  network/DB-based discovery, descriptors from non-root paths.
- **Selected command**: `python -m pytest tests/test_subagent_registry.py -q`
- **Exit criteria**: registry isolates per test/session.

## Phase 3: Delegation Request/Result Contract

- **Category**: Required for v1.
- **Tests to add**: `SubAgentRequest` creation and validation (including
  `execution_mode`, `max_revisions`, `relevant_files`, `output_schema`),
  `SubAgentResult` with all status and stop_reason values,
  `SubAgentError` structure, `SubAgentAuditRecord` completeness,
  `SubAgentRun` state machine, `ToolRequest` structure, `ParentAdjudicationResult`
  structure.
- **Expected behavior**: request → context → execution → result → audit →
  adjudication flow is well-typed. All dataclasses are frozen.
- **Forbidden behavior**: mutable request/result objects, missing required
  fields silently accepted, audit record missing correlation IDs.
- **Selected command**: `python -m pytest tests/test_subagent_contract.py -q`
- **Exit criteria**: contract types are frozen, validated, and auditable.

## Phase 4: Context Packaging

- **Category**: Required for v1.
- **Tests to add**: `SubAgentContextPackage` assembly from request + descriptor
  + memory + skill + tool snapshots; `FileSummary` generation (summary not full
  content); context budget enforcement (`max_context_chars`); budget overflow
  trimming; `forbidden_actions` populated correctly; `stop_conditions` derived
  from mode; `role_prompt` generation; `goal` derivation from task.
- **Expected behavior**: context package is assembled deterministically;
  budget enforced; summaries not full files; memory context included only when
  scope permits.
- **Forbidden behavior**: full file content in context package; secrets in
  context package; budget exceeded without warning; memory context included when
  `memory_scope=none`.
- **Selected command**: `python -m pytest tests/test_subagent_context_packaging.py -q`
- **Exit criteria**: context package is complete, budgeted, and sanitized.

## Phase 5: Execution Modes

- **Category**: Required for v1 (mode enum + policy); Gated (real LLM execution).
- **Tests to add**: `SubAgentExecutionMode` enum values; mode policy for each
  mode (allowed tools, network, memory, checkpoint, confirmation); mode
  escalation prevention (SubAgent cannot change mode); mode selection bounded
  by `descriptor.supported_modes`; mode selection gated by config flags;
  `local_fake` and `local_deterministic` execution tests; `real_llm_readonly`
  contract tests (no actual LLM call); `real_llm_tool_requesting` contract
  tests (no actual LLM call); `sandboxed_tool_capable` contract tests (no
  actual sandbox).
- **Expected behavior**: mode policy enforces correct constraints per mode.
  Mode escalation blocked. Config gates enforced.
- **Forbidden behavior**: real LLM call in tests; mode escalation without
  config gate; unsupported mode selected.
- **Selected command**:
  ```bash
  python -m pytest tests/test_subagent_execution_modes.py -q
  ```
- **Exit criteria**: mode enum complete; mode policy enforceable; mode
  gating testable without real LLM.

## Phase 6: Tool Permission Boundary

- **Category**: Required for v1.
- **Tests to add**: `SubAgentToolBoundary.check()` allows tool in both
  descriptor and request `allowed_tools`, blocks tool outside upper bound,
  blocks unknown tool, preserves ToolRegistry risk level, preserves
  confirmation requirement, blocks hidden/internal tools, `ToolCheckResult`
  completeness, sandbox-scoped tool validation contract (no actual sandbox).
- **Expected behavior**: SubAgent can request tools within bounds; all
  execution still flows through ToolRegistry.
- **Forbidden behavior**: tool risk downgrade, confirmation bypass, tool
  execution from SubAgent, hidden tool exposure.
- **Selected command**: `python -m pytest tests/test_subagent_tool_boundary.py tests/test_tool_exposure.py -q`
- **Exit criteria**: tool boundary is a pure check — no execution path.

## Phase 7: Skill Boundary

- **Category**: Required for v1.
- **Tests to add**: `SubAgentSkillBoundary.check()` allows Skill in
  `allowed_skills`, blocks Skill outside list, passes through Skill System for
  loading, respects Skill's own `allowed_tools` and `memory_scope`,
  `SkillCheckResult` completeness.
- **Expected behavior**: SubAgent receives L1 metadata only for allowed
  Skills; full loading follows Skill System progressive disclosure.
- **Forbidden behavior**: Skill body pre-loading, Skill tool bypass, Skill
  memory scope override.
- **Selected command**: `python -m pytest tests/test_subagent_skill_boundary.py -q`
- **Exit criteria**: Skill boundary delegates to Skill System — no duplicate
  loading logic.

## Phase 8: Memory Boundary

- **Category**: Required for v1.
- **Tests to add**: `memory_scope=none` → no context; `read_context` →
  read-only snapshot returned; `propose` → memory proposal validated;
  proposal rejection path; no auto-approve; no direct MemoryStore reference;
  `source=subagent` metadata on proposals.
- **Expected behavior**: SubAgent receives memory context only through
  adapter. Proposals flow through governance.
- **Forbidden behavior**: direct Memory write, silent retain, auto-approve,
  SubAgent holding MemoryStore reference.
- **Selected command**: `python -m pytest tests/test_subagent_memory_boundary.py tests/test_memory_interaction.py -q`
- **Exit criteria**: existing Memory governance tests still pass unchanged.

## Phase 9: Checkpoint/Resume Boundary

- **Category**: Required for v1.
- **Tests to add**: `SubAgentCheckpointSummary` contains only correlation
  metadata; no full prompt/transcript/secret/large artifact stored;
  `delegation_id` and `parent_trace_id` preserved; resume does not replay
  high-risk tool execution; pending confirmation state preserved; `stop_reason`
  preserved; `execution_mode` preserved; `revision_count` preserved.
- **Expected behavior**: checkpoint summary is small, safe, and recoverable.
- **Forbidden behavior**: raw prompt dumps, secret storage, tool re-execution
  on resume, SubAgent owning checkpoint save/load timing.
- **Selected command**: `python -m pytest tests/test_subagent_checkpoint_boundary.py tests/test_checkpoint_ownership.py -q`
- **Exit criteria**: existing checkpoint ownership tests still pass.

## Phase 10: Bounded Local Execution / max_iterations

- **Category**: Required for v1.
- **Tests to add**: execution stops at `max_iterations`; status
  `max_iterations_exceeded` returned with best-effort summary; iteration
  counter accurate; fake/local execution only (no real LLM);
  `SubAgentStopReason` accuracy for each stop condition; `needs_clarification`
  stop; `needs_confirmation` stop; `tool_blocked` stop; `policy_blocked` stop.
- **Expected behavior**: SubAgent runs bounded steps, returns result with
  correct stop reason.
- **Forbidden behavior**: unbounded loop, real LLM call, external process
  spawn, exceeding `max_iterations` silently.
- **Selected command**: `python -m pytest tests/test_subagent_execution.py -q`
- **Exit criteria**: `max_iterations` is a hard bound. All stop reasons testable.

## Phase 11: Parent Adjudication / Result Merge

- **Category**: Required for v1.
- **Tests to add**: `ParentAdjudicationResult` for each action (`accept`,
  `reject`, `revise`, `ask_user`); `accept_result` with merge; `reject_result`
  with reason; `request_revision` produces new `SubAgentRequest`;
  `convert_to_tool_request` routing; `convert_to_memory_proposal` routing;
  low-confidence handling; revision loop with `max_revisions` enforcement;
  revision history preservation; conflicting result handling (future stub).
- **Expected behavior**: Parent can adjudicate all result statuses.
  Revision loop is bounded. Merge preserves traceability.
- **Forbidden behavior**: auto-merge without parent decision; revision loop
  exceeding `max_revisions`; tool execution from adjudication (routing only).
- **Selected command**: `python -m pytest tests/test_subagent_adjudication.py -q`
- **Exit criteria**: adjudication flow complete for all parent actions.

## Phase 12: Parent Agent Adapter

- **Category**: Required for v1.
- **Tests to add**: Parent creates `SubAgentRequest` → adapter assembles
  `SubAgentContextPackage` → executor runs → `SubAgentResult` returned;
  adapter invokes adjudication; error paths; tool requests forwarded (not
  executed); memory proposals queued; audit record complete; trace events
  collected; `SubAgentRun` state transitions correct.
- **Expected behavior**: request/result/adjudication flow is parent-controlled.
- **Forbidden behavior**: SubAgent owning loop, SubAgent calling provider,
  adapter bypassing governance.
- **Selected command**: `python -m pytest tests/test_subagent_adapter.py tests/test_architecture_boundaries.py -q`
- **Exit criteria**: architecture tests confirm Parent owns loop.

## Phase 13: Trace / Observability

- **Category**: Required for v1.
- **Tests to add**: `SubAgentTraceEvent` for each event type:
  `delegation_started`, `context_packaged`, `iteration_started`,
  `tool_requested`, `tool_denied`, `tool_executed`, `confirmation_required`,
  `confirmation_resolved`, `result_returned`, `result_adjudicated`,
  `revision_requested`, `delegation_failed`, `resumed_from_checkpoint`,
  `delegation_completed`; event ordering preserved; event data sanitized
  (no secrets); trace event count in audit record.
- **Expected behavior**: every delegation produces complete trace; events
  are ordered and sanitized.
- **Forbidden behavior**: secrets in trace events; missing events for key
  state transitions; events out of order.
- **Selected command**: `python -m pytest tests/test_subagent_trace.py -q`
- **Exit criteria**: trace events cover full delegation lifecycle.

## Phase 14: Real LLM Read-Only Gated Tests

- **Category**: Gated but designed (requires config + dogfood + audit).
- **Tests to add**: `real_llm_readonly` mode contract; config gate enforcement
  (`subagent.real_llm_readonly.enabled`); mode selection blocked when gate
  closed; provider call mediation (mocked); read-only tool snapshot assembly;
  real LLM response parsing; ThinkingBlock handling; confidence extraction;
  stop reason derivation from LLM output.
- **Expected behavior**: when config gate is open, real LLM is invoked via
  Runtime-mediated provider call with read-only tool snapshot. Response parsed
  into `SubAgentResult`.
- **Forbidden behavior**: real LLM call when gate closed; direct provider
  access from SubAgent; tool execution from read-only mode.
- **Selected command**: `python -m pytest tests/test_subagent_real_llm_readonly.py -q`
- **Exit criteria**: real LLM readonly path is testable with mock provider.
  Config gate prevents execution when closed.

## Phase 15: Real LLM Tool-Requesting Gated Tests

- **Category**: Gated but designed (requires L1 pass + config + audit).
- **Tests to add**: `real_llm_tool_requesting` mode contract; config gate
  enforcement; tool request parsing from LLM output; parent-mediated tool
  execution flow (mocked); tool denial flow; confirmation gating for
  high-risk tools.
- **Expected behavior**: SubAgent can request tools; parent executes on
  SubAgent's behalf; tool results fed back to SubAgent context.
- **Forbidden behavior**: direct tool execution; confirmation bypass; tool
  request outside effective bounds.
- **Selected command**: `python -m pytest tests/test_subagent_tool_requesting.py -q`
- **Exit criteria**: tool-requesting path testable with mock provider and mock
  tool registry.

## Phase 16: Sandbox Mode Contract Tests

- **Category**: Future but documented (contract tests written; execution
  requires sandbox phase).
- **Tests to add**: `sandboxed_tool_capable` mode contract; sandbox root
  scoping; tool execution within sandbox; sandbox tool requests blocked
  outside sandbox root; sandbox cleanup contract; sandbox artifact return
  contract.
- **Expected behavior**: sandbox contract defines scoped execution boundaries.
- **Forbidden behavior**: tool execution outside sandbox root; sandbox
  mutation of real repo state.
- **Selected command**: `python -m pytest tests/test_subagent_sandbox_contract.py -q`
- **Exit criteria**: sandbox contract defined in tests; no real sandbox
  execution without explicit phase.

## Phase 17: CLI/TUI Visibility

- **Category**: Required for v1.
- **Tests to add**: available SubAgent list display with modes; delegation
  status display; result/audit display; adjudication display; trace event
  display; blocked action display.
- **Expected behavior**: CLI/TUI present state only.
- **Forbidden behavior**: CLI/TUI imports executor, tool boundary, memory
  boundary, runtime. No runtime logic in presentation.
- **Selected command**: `python -m pytest tests/test_subagent_cli_tui.py tests/test_tui_dependency_boundaries.py -q`
- **Exit criteria**: presentation boundaries remain thin.

## Phase 18: Dogfood

- **Category**: Required for v1 (L1); Gated (L2-L5).
- **Tests to add**: tiered dogfood fixtures for each scenario in
  `docs/dogfood/SUBAGENT_DOGFOOD_PLAN.md`.
- **L1 (Required)**: 15 synthetic deterministic scenarios.
- **L2 (Gated)**: real LLM read-only dogfood scenarios.
- **L3 (Gated)**: real LLM tool-requesting dogfood scenarios.
- **L4 (Future)**: sandboxed tool-capable dogfood scenarios.
- **L5 (Future)**: worktree coding dogfood scenarios.
- **Expected behavior**: local-only deterministic runs for L1; gated real LLM
  runs for L2+.
- **Forbidden behavior**: network access without config; real LLM without gate;
  external process spawn; secret logging.
- **Selected command**: `python -m pytest tests/test_subagent_dogfood.py -q`
- **Exit criteria**: L1 produces audit packets with no private data. L2+
  produce sanitized results under config gate.

## Phase 19: Architecture Boundary Tests

- **Category**: Required for v1.
- **Tests to add**: no ToolRegistry bypass, no Memory direct write, no second
  loop, no CLI/TUI runtime logic, no SubAgent imports from legacy paths, no
  nested SubAgent spawning, Skill System not bypassed, checkpoint safety,
  execution mode escalation blocked, context budget enforced, mode policy
  immutable, trace events sanitized.
- **Expected behavior**: high cohesion / low coupling module graph.
- **Forbidden behavior**: new SubAgent monolith, cross-layer imports, boundary
  violations.
- **Selected command**: `python -m pytest tests/test_architecture_boundaries.py tests/test_tui_dependency_boundaries.py -q`
- **Exit criteria**: full suite passes and no P0/P1 audit findings.

## Test Category Summary

| Category | Phases | Description |
|----------|--------|-------------|
| Required for v1 | 0-13, 17, 18(L1), 19 | Must pass before v1 complete |
| Gated but designed | 14, 15, 18(L2-L3) | Tests written; execution needs config gate |
| Future but documented | 16, 18(L4-L5) | Contracts defined; execution deferred |

## Full-suite Rule

Run full pytest when a phase touches Runtime, ToolRegistry, Memory,
checkpoint/resume, core loop, CLI/TUI, or architecture boundary tests:

```bash
HOME=/private/tmp/my-first-agent-subagent-system-home python -m pytest tests/ -x -q
```
