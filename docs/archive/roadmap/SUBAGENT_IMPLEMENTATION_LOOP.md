# SubAgent System Implementation Loop

This document is the execution loop for a future Coding Agent. Do not implement
SubAgent System code without reading the RFC, SDD, and TDD first.

## 1. Loop Rules

Every phase must:

1. Read `docs/rfc/SUBAGENT_CANONICAL_RFC.md`.
2. Read `docs/design/SUBAGENT_SYSTEM_SDD.md`.
3. Read `docs/testing/SUBAGENT_SYSTEM_TDD.md`.
4. Write or extend tests first.
5. Confirm the new test fails for the intended reason when practical.
6. Implement minimum code.
7. Run selected tests.
8. Run full pytest when code touches Runtime, ToolRegistry, Memory,
   checkpoint, core loop, CLI/TUI.
9. Update docs if behavior or phase status changes.
10. Commit a scoped change.
11. Stop for audit at defined gates.

Do not modify real `.env`, read real `agent_log.jsonl`, read real `sessions/` or
`runs/`, call real LLMs for delegation unless config gate is explicitly opened
for a gated phase, spawn external processes, or install dependencies.

Formal SubAgent implementation must not import or modify the Safe Local MVP
(`agent/subagents/local.py`) unless a dedicated migration phase is explicitly
approved. The Safe Local MVP is a test baseline and reference only.

The formal namespace is `agent/subagent_system/`. Implementation phases should
create or modify `agent/subagent_system/*`, and tests should target
`agent/subagent_system/*`.

Naming convention:

- **Capability Level = L0-L5**.
- **Dogfood Tier = T1-T6**.
- **Implementation Phase = Phase 0-N**.
- **Audit Priority = P0-P3**.

## 2. Target Architecture

The SubAgent System is designed as a production-grade architecture. Phases build
toward this target, not toward a minimal local-only wrapper.

Production-grade target architecture starts from day one; implementation starts
at the L0 safe-local baseline. L1/L2 are gated capabilities. L3/L4/L5 are
contract/future capabilities unless explicit approval opens a later phase.

```
Capability pyramid (implementation order):

L0: Safe Local SubAgent           ← Phase 0-13, 17-19(T1/audit) (v1 required)
L1: Real LLM Read-Only            ← Phase 14 (gated dogfood)
L2: Real LLM Tool-Requesting      ← Phase 15 (gated)
L3: Sandboxed Tool-Capable        ← Phase 16 (contract, then gated)
L4: Worktree-Capable              ← Future (explicit phase)
L5: Parallel Multi-SubAgent       ← Future (explicit phase)
```

### 2.1 Phase Mapping

| Phase | Canonical Name | Capability / Tier | Status |
|-------|----------------|-------------------|--------|
| 0 | Safe Local MVP Characterization | L0 | Required |
| 1 | Descriptor Schema | L0 | Required |
| 2 | Filesystem Registry | L0 | Required |
| 3 | Delegation Contract Types | L0 | Required |
| 4 | Context Packaging | L0 | Required |
| 5 | Execution Mode Policy | L0 contract; L1/L2/L3 gates | Required/gated |
| 6 | Tool Permission Boundary | L0; L2 parent-mediated requests | Required/gated |
| 7 | Skill Boundary | L0 | Required |
| 8 | Memory Boundary | L0 | Required |
| 9 | Checkpoint / Resume Boundary | L0 | Required |
| 10 | Bounded Local Execution | L0 | Required |
| 11 | Parent Adjudication / Result Merge | L0 minimum; L1+ full target | Required/extended |
| 12 | Runtime / Parent Adapter | L0 | Required |
| 13 | Trace / Observability | L0 minimum; L1+ full target | Required/extended |
| 14 | Real LLM Read-Only Gated Dogfood | L1 / T2 | Gated |
| 15 | Real LLM Tool-Requesting Gated Dogfood | L2 / T3 | Gated |
| 16 | Sandbox Contract and Gated Execution | L3 / T4 | Contract/gated |
| 17 | CLI/TUI Visibility | L0 | Required |
| 18 | Dogfood Harness | T1-T6 | Required/gated/future |
| 19 | Audit Readiness Packet | Target capability | Required gate |

Dogfood tiers map to capability levels as follows:

| Dogfood Tier | Scenario Set | Capability Level | Status |
|--------------|--------------|------------------|--------|
| T1 | Synthetic Deterministic | L0 | Required |
| T2 | Real LLM Read-Only | L1 | Gated |
| T3 | Real LLM Tool-Requesting | L2 | Gated |
| T4 | Sandboxed Tool-Capable | L3 | Future / gated contract |
| T5 | Worktree Coding | L4 | Future |
| T6 | Parallel Multi-SubAgent | L5 | Future placeholder |

### 2.2 Entry Criteria Model

Every phase must evaluate concrete entry criteria before writing tests or code:

- Previous phase exit criteria are satisfied, or Phase 0 characterization is
  complete for Phase 1.
- Required docs for the phase have been read: RFC, SDD, TDD, and dogfood/audit
  docs where the phase references them.
- Tests for the previous phase passed, or a documented blocker stops the loop.
- Working tree is clean, or the current phase explicitly owns every dirty file.
- No stop condition from §5 has triggered.
- Allowed and forbidden files for the phase are understood before edits.

Gated phases additionally require the config gate, audit gate, and applicable
dogfood gate to exist and remain closed by default. Future/contract phases must
not implement execution by default; they may define contracts, docs, and tests
only unless the user gives explicit approval.

## 3. Phases

### Phase 0: Safe Local MVP Characterization

Goal: confirm Safe Local MVP boundaries and establish test baseline.

Entry criteria:

- Required SubAgent docs are read for context.
- Working tree is clean.
- No stop condition is active.
- Allowed work is characterization only; formal SubAgent modules are not
  created in this phase.

Work:

- Run `tests/test_subagent_local_mvp_contract.py` and verify all pass.
- Document MVP contracts: `SubagentProfile`, `DelegationRequest`,
  `DelegationResult`, path policy, frontmatter validation, secret redaction.
- Verify MVP never calls real LLM, never spawns external processes.

Stop gate: MVP characterization complete; tests green.

### Phase 1: Descriptor Schema

Goal: define parser/schema for `SUBAGENT.md` frontmatter.

Entry criteria:

- Phase 0 exit gate is satisfied.
- `tests/test_subagent_local_mvp_contract.py` is green.
- RFC/SDD/TDD descriptor sections are read.
- Working tree is clean or owns only Phase 1 descriptor docs/tests/files.
- Allowed/forbidden files below are understood; do not create non-descriptor
  modules.

Allowed files: `agent/subagent_system/descriptor.py`,
`agent/subagent_system/errors.py`, and focused tests/docs.

Forbidden files: ToolRegistry, Memory, Runtime loop, CLI/TUI, executor,
real LLM path.

Work:

- Add `SubAgentDescriptor` (frozen dataclass), typed errors.
- Parse `SUBAGENT.md` YAML frontmatter.
- Fail closed on invalid name/status/model/risk.
- Redact secret-like values.
- `model` must be `fake`/`fixture`/`none` in v1.
- `supported_modes` must be subset of `SubAgentExecutionMode` values.

Stop gate: descriptor tests green.

### Phase 2: Filesystem Registry

Goal: runtime/session-scoped deterministic registry.

Entry criteria:

- Phase 1 descriptor tests are green.
- Registry section in SDD and TDD Phase 2 are read.
- Working tree is clean or owns only Phase 2 registry files.
- No stop condition is active.
- Registry scope is runtime/session scoped before implementation starts.

Allowed files: `agent/subagent_system/registry.py`,
`agent/subagent_system/descriptor.py`, fixtures, and focused tests/docs.

Forbidden files: executor, ToolRegistry, Memory governance, real LLM path.

Work:

- Explicit roots only.
- No module-level global singleton.
- Duplicate names fail closed.
- Disabled/hidden SubAgents not visible.
- `find_by_role` for role-based lookup.

Stop gate: independent review of registry scope.

### Phase 3: Delegation Contract Types

Goal: define all contract dataclasses — `SubAgentRequest`, `SubAgentContextPackage`,
`SubAgentResult`, `SubAgentError`, `SubAgentAuditRecord`, `SubAgentRun`,
`ParentAdjudicationResult`, `ToolRequest`, `SubAgentTraceEvent`,
`SubAgentCheckpointSummary`, `SubAgentExecutionMode`, `SubAgentStopReason`.

Entry criteria:

- Phase 2 registry exit gate is satisfied.
- Descriptor/registry tests pass.
- RFC delegation contract and SDD data-structure sections are read.
- Working tree is clean or owns only Phase 3 contract files.
- Contract files may define types only; no executor, provider, ToolRegistry, or
  Memory governance implementation begins here.

Allowed files: `agent/subagent_system/request.py`,
`agent/subagent_system/context.py`, `agent/subagent_system/result.py`,
`agent/subagent_system/execution_mode.py`,
`agent/subagent_system/errors.py`, and focused tests/docs.

Forbidden files: executor, ToolRegistry execution, Memory governance, real
LLM path.

Work:

- All contract types are frozen dataclasses.
- Validation: required fields, type checks, correlation IDs.
- `SubAgentExecutionMode` enum with all five modes.
- `SubAgentStopReason` enum with all ten stop reasons.

Stop gate: contract types are frozen, validated, auditable.

### Phase 4: Context Packaging

Goal: assemble `SubAgentContextPackage` from request + descriptor + boundaries.

Entry criteria:

- Phase 3 contract tests are green.
- RFC §2.4 / §5.2 and SDD §4 are read.
- Working tree is clean or owns only Phase 4 context packaging files.
- Allowed/forbidden files below are understood.
- L0 context packaging is in scope; L1+ real context-window isolation is not.

Allowed files: `agent/subagent_system/context.py`, and focused tests/docs.

Forbidden files: executor, ToolRegistry execution, real LLM path.

Work:

- `FileSummary` generation (summarized content, not full files).
- Context budget enforcement (`max_context_chars`).
- `forbidden_actions` derivation from mode policy.
- `stop_conditions` derivation from mode and constraints.
- Memory context inclusion gated by `memory_scope`.
- Skill L1 metadata inclusion gated by `allowed_skills`.

Stop gate: context package assembled deterministically; budget enforced.

### Phase 5: Execution Mode Policy

Goal: define mode policy, gating, and escalation prevention.

Entry criteria:

- Phase 4 context packaging tests are green.
- RFC §2.2 and SDD §2.5 / §2.7 are read.
- Working tree is clean or owns only Phase 5 mode/policy files.
- Config gate names are defined and closed by default.
- L1/L2/L3 execution remains gated/contract only; no real LLM or sandbox
  execution is implemented in Phase 5.

Allowed files: `agent/subagent_system/execution_mode.py`,
`agent/subagent_system/policy.py`, and focused tests/docs.

Forbidden files: real LLM invocation, tool execution, sandbox execution.

Work:

- Mode policy per `SubAgentExecutionMode` value.
- Config gate checks: `subagent.real_llm_readonly.enabled`,
  `subagent.tool_requesting.enabled`, `subagent.sandbox.enabled`.
- Mode escalation prevention: SubAgent cannot change mode.
- Mode selection bounded by `descriptor.supported_modes`.
- `SubAgentPolicy` dataclass with all gate fields.

Stop gate: mode policy enforceable; config gates testable.

### Phase 6: Tool Permission Boundary

Goal: connect SubAgent `allowed_tools` to ToolRegistry without bypass.

Entry criteria:

- Phase 5 execution mode policy tests are green.
- RFC governance/tool sections and SDD §5 are read.
- Working tree is clean or owns only Phase 6 tool-boundary files.
- ToolRegistry remains the authority before coding starts.
- This phase implements pure permission checks only; no SubAgent tool execution
  path is allowed.

Allowed files: `agent/subagent_system/tool_boundary.py`, narrow adapter code
if required, and focused tests/docs.

Forbidden files: tool execution from SubAgent, ToolRegistry risk bypass,
confirmation skip.

Work:

- `allowed_tools` is upper bound (intersection of descriptor + request).
- ToolRegistry remains authority for risk/confirmation.
- Hidden/internal tools never exposed.
- SubAgent cannot execute tools directly (parent-mediated in L2+).
- `ToolCheckResult` returned for each tool request.

Stop gate: tool boundary audit.

### Phase 7: Skill Boundary

Goal: connect SubAgent `allowed_skills` to Skill System without bypass.

Entry criteria:

- Phase 6 tool-boundary tests are green.
- RFC Skill boundary adaptation and SDD Skill boundary sections are read.
- Working tree is clean or owns only Phase 7 skill-boundary files.
- Skill System remains the loading/progressive-disclosure authority.
- Only Skill L1 metadata exposure is in scope.

Allowed files: `agent/subagent_system/skill_boundary.py`, and focused
tests/docs.

Forbidden files: Skill System bypass, Skill pre-loading all bodies.

Work:

- `allowed_skills` is upper bound.
- Skill System remains authority for loading/progressive disclosure.
- SubAgent receives L1 metadata only.

Stop gate: Skill boundary delegates to Skill System.

### Phase 8: Memory Boundary

Goal: read-only context and proposal-only Memory access.

Entry criteria:

- Phase 7 skill-boundary tests are green.
- RFC §8 and SDD memory-boundary sections are read.
- Working tree is clean or owns only Phase 8 memory-boundary files.
- Memory governance remains the authority before coding starts.
- Direct MemoryStore writes, silent retain, and auto-approve are out of scope.

Allowed files: `agent/subagent_system/memory_boundary.py`, memory adapter
seam tests/docs, and minimum approved Runtime adapter wiring.

Forbidden files: direct MemoryStore write, silent retain, auto-approve.

Work:

- Implement `memory_scope` handling (`none` / `read_context` / `propose`).
- Route memory proposals through governance.

Stop gate: Memory governance audit.

### Phase 9: Checkpoint / Resume Boundary

Goal: make in-flight SubAgent delegation checkpoint-aware without letting
SubAgent own the loop or replay high-risk effects.

Entry criteria:

- Previous phase exit criteria are satisfied.
- Phase 3 contract types exist.
- Phase 8 memory boundary tests pass.
- Existing checkpoint ownership tests are green.
- RFC §9 and SDD checkpoint section are read.
- Working tree is clean or owns only Phase 9 checkpoint files.
- Allowed/forbidden files below are understood; checkpoint schema migration is
  a stop condition unless explicitly approved.

Allowed files:

- `agent/subagent_system/checkpoint.py`
- `agent/subagent_system/result.py`
- Focused checkpoint/resume tests
- Narrowly scoped Runtime checkpoint adapter code only if tests require it

Forbidden files:

- ToolRegistry risk/confirmation policy changes
- Memory governance changes
- Broad checkpoint schema migration without user approval

Tests first:

- Add tests for `SubAgentCheckpointSummary` containing only correlation
  metadata.
- Add tests that checkpoint does not store secrets, full prompts, or large
  artifacts.
- Add tests that resume does not bypass confirmation or re-execute high-risk
  tools.
- Add tests that `execution_mode`, `stop_reason`, and `revision_count` are
  preserved.

Implementation scope:

- Store only bounded correlation metadata.
- Do not persist full SubAgent body or transcript.
- Do not replay tool execution from SubAgent state.
- Runtime remains the only owner of loop and checkpoint save/load timing.

Selected tests:

```bash
python -m pytest tests/test_subagent_checkpoint_boundary.py tests/test_checkpoint_ownership.py -q
```

Exit criteria:

- In-flight SubAgent delegation can be recovered or explained after resume.
- Checkpoint contains no secret-like values and no full large resources.
- Interrupted delegation cannot bypass confirmation.
- Resume does not repeat high-risk tool execution.
- Full pytest passes with a temporary HOME.

### Phase 10: Bounded Local Execution

Goal: fake/local execution within `max_iterations` bound.

Entry criteria:

- Phase 9 checkpoint/resume tests are green.
- RFC loop model and TDD Phase 10 are read.
- Working tree is clean or owns only Phase 10 executor files.
- `SubAgentExecutionMode` policy exists and defaults to `local_fake`.
- No real LLM, external process, shell, repo write, or real tool execution is
  permitted in this phase.

Allowed files: `agent/subagent_system/executor.py`, and focused tests/docs.

Forbidden files: real LLM invocation, external process spawn, real tool
execution.

Work:

- Bounded loop: `max_iterations` hard stop.
- Fake/local execution only (no real LLM).
- All `SubAgentStopReason` values producible.
- Status mapped to stop reason.
- Iteration counter in audit record.

Stop gate: bounded execution proven in tests.

### Phase 11: Parent Adjudication / Result Merge

Goal: Parent can accept, reject, revise, or escalate any SubAgent result.

Entry criteria:

- Phase 10 bounded local execution tests are green.
- RFC §2.6 / §6 and SDD §6 are read.
- Working tree is clean or owns only Phase 11 adjudication files.
- L0 action subset is understood: `accept_result`, `reject_result`, `ask_user`,
  `request_revision`.
- L1+ actions are designed but do not force L0 implementation of tool/memory
  routing execution.

Allowed files: `agent/subagent_system/adjudication.py`,
`agent/subagent_system/result.py`, and focused tests/docs.

Forbidden files: SubAgent owning loop, auto-merge without parent decision.

Work:

- `ParentAdjudicationResult` for each L0 action.
- `accept_result` with summary merge.
- `reject_result` with reason.
- `request_revision` with revised `SubAgentRequest`.
- `ask_user` with user question.
- `convert_to_tool_request` routing (L1+ / later phase target).
- `convert_to_memory_proposal` routing (L1+ / later phase target).
- Revision loop with `max_revisions` bound.
- Low-confidence handling.

Stop gate: adjudication flow complete for the L0 action subset; full 8-action
model remains the production target for later phases.

### Phase 12: Runtime / Parent Adapter

Goal: `SubAgentRun` lifecycle and delegation adapter under Parent Runtime.

Entry criteria:

- Phase 11 L0 adjudication tests are green.
- Runtime ownership sections in RFC/SDD/TDD are read.
- Working tree is clean or owns only Phase 12 runtime/delegation files.
- Parent remains orchestrator; SubAgent cannot own the main loop.
- Provider direct calls, Memory governance changes, and ToolRegistry bypass are
  forbidden before implementation starts.

Allowed files: `agent/subagent_system/runtime.py`,
`agent/subagent_system/delegation.py`, Runtime adapter seams
approved by tests, and focused tests/docs.

Forbidden files: SubAgent owning loop, provider direct call paths, Memory
governance changes.

Work:

- `SubAgentRun` state machine: `pending → packaging → running →
  awaiting_confirmation → awaiting_adjudication → revising →
  completed/failed`.
- Adapter assembles `SubAgentContextPackage` from `SubAgentRequest` + registry +
  boundaries.
- Delegates to executor.
- Returns `SubAgentResult` to Parent.
- Invokes adjudication path.
- Parent remains orchestrator.

Stop gate: architecture tests confirm Parent owns loop.

### Phase 13: Trace / Observability

Goal: every delegation produces a complete, sanitized trace.

Entry criteria:

- Phase 12 runtime/adapter tests are green.
- RFC §10 and SDD trace sections are read.
- Working tree is clean or owns only Phase 13 trace/result files.
- L0 trace subset is understood:
  `delegation_started`, `context_packaged`, `result_returned`,
  `result_adjudicated`, `delegation_failed`.
- Gated/future trace events are documented targets, not L0 burden.

Allowed files: `agent/subagent_system/trace.py`,
`agent/subagent_system/result.py`, and focused tests/docs.

Forbidden files: secrets in trace data, trace data as side channel.

Work:

- `SubAgentTraceEvent` for the L0 minimum event subset.
- Full production trace event model remains designed for gated/future phases.
- Event ordering preservation.
- Event data sanitization (no secrets, no full prompts).
- Trace event count in `SubAgentAuditRecord`.
- Trace events included in `SubAgentResult`.

Stop gate: L0 trace covers safe-local delegation lifecycle; no secrets in trace.

### Phase 14: Real LLM Read-Only Gated Dogfood

Goal: real LLM readonly execution under config gate.

Entry criteria:

- L0 (Phases 0-13) complete and tested.
- Config system supports `subagent.real_llm_readonly.enabled`.
- Audit gate for L1 has no open P0/P1/P2 blockers.
- T2 dogfood scenarios are defined.
- Real LLM dogfood runner exists (analogue to Skill System dogfood runner).
- Explicit user approval is required before any real LLM invocation.

Allowed files: real LLM path additions to executor/runtime (gated),
dogfood fixtures, and focused tests.

Forbidden files: tool execution from SubAgent, direct provider access outside
Runtime mediation.

Work:

- Config gate: `subagent.real_llm_readonly.enabled` must be `true`.
- Provider call mediated by Runtime (not direct from SubAgent).
- Read-only tool snapshot passed to SubAgent context.
- Response parsing (TextBlock, ThinkingBlock handling).
- Confidence extraction from response.
- Stop reason derivation.
- Dogfood scenarios: code review reasoning, RFC alignment reasoning, test
  repair reasoning.

Stop gate: real LLM readonly dogfood passes; audit packet sanitized.

### Phase 15: Real LLM Tool-Requesting Gated Dogfood

Goal: real LLM with parent-mediated tool requests under config gate.

Entry criteria:

- Phase 14 complete and dogfood pass.
- Config system supports `subagent.tool_requesting.enabled`.
- Audit gate for L2 has no open P0/P1/P2 blockers.
- T3 dogfood scenarios are defined.
- Explicit user approval is required before gated execution.
- ToolRegistry and Confirmation boundaries have passing tests.

Work:

- Config gate: `subagent.tool_requesting.enabled` must be `true`.
- Tool request parsing from LLM output.
- Parent-mediated tool execution flow.
- Tool denial path.
- Confirmation gating for high-risk tools.
- Dogfood scenarios: test repair planning with tool requests, multi-file
  analysis.

Stop gate: tool-requesting dogfood passes; no direct tool execution.

### Phase 16: Sandbox Contract and Gated Execution

Goal: sandboxed tool-capable contract and (gated) execution.

Entry criteria:

- Phase 15 complete.
- Config system supports `subagent.sandbox.enabled`.
- Audit gate for L3 has no open P0/P1/P2 blockers.
- T4 dogfood scenarios are defined.
- Contract/docs/tests may be written by default; real sandbox execution needs
  explicit approval and a closed-by-default config gate.
- Sandbox must not spawn external processes or mutate repo state outside its
  scoped root.

Work:

- Sandbox contract: scoped filesystem root, tool constraints.
- Sandbox tool execution policy.
- Sandbox cleanup contract.
- Gated execution: real sandbox only when config gate open.
- Dogfood scenarios: sandboxed file read/write in tmp root, code generation in
  sandbox.

Stop gate: sandbox contract tests pass; sandbox execution gated.

### Phase 17: CLI/TUI Visibility

Goal: presentation only.

Entry criteria:

- Phase 13 L0 trace tests are green, or the current implementation loop has a
  documented reason to add visibility earlier.
- Presentation boundary docs in SDD/TDD are read.
- Working tree is clean or owns only presentation docs/tests/files.
- CLI/TUI allowed files and forbidden runtime imports are understood.

Work:

- Show available SubAgent descriptors with supported modes.
- Show delegation status/reason/mode.
- Show result/audit with confidence and stop reason.
- Show adjudication decision.
- Show trace events.

Stop gate: TUI dependency boundary tests.

### Phase 18: Dogfood Harness

Goal: T1-T6 tiered dogfood harness without conflicting with Capability L0-L5.

Entry criteria:

- Phase 13 L0 trace and Phase 17 visibility checks are green for T1.
- Dogfood plan and audit checklist are read.
- Working tree is clean or owns only Phase 18 dogfood harness files.
- No real LLM, network, external process, `.env`, sessions/runs, or repo write
  is allowed for T1.
- T2/T3 require config gate + audit gate + explicit user approval before
  execution. T4/T5/T6 are future placeholders unless explicitly approved.

Work:

- **T1 (v1 required, Capability L0)**: 15+ synthetic deterministic scenarios.
- **T2 (gated, Capability L1)**: real LLM read-only dogfood.
- **T3 (gated, Capability L2)**: real LLM tool-requesting dogfood.
- **T4 (future, Capability L3)**: sandboxed tool-capable dogfood.
- **T5 (future, Capability L4)**: worktree coding dogfood.
- **T6 (future, Capability L5)**: parallel multi-SubAgent scenarios.
- All tiers produce redacted audit packets.
- No network, real LLM (except gated tiers), `.env`, sessions/runs.

Stop gate: T1 dogfood produces sanitized audit packets; T2+ tiers are ready for
gated or future execution without being enabled by default.

### Phase 19: Audit Readiness Packet

Goal: close P0/P1/P2/P3 and decide readiness.

Entry criteria:

- Target capability phases have satisfied their exit criteria.
- Audit checklist and dogfood evidence for the target capability/tier are read.
- Working tree is clean or owns only audit-readiness files.
- Required tests for the target phase passed.
- No stop condition is active; any P0/P1/P2 finding blocks readiness.

Work:

- Run audit checklist (`docs/audit/SUBAGENT_AUDIT_CHECKLIST.md`).
- Fix scoped findings.
- Run full pytest.
- Verify all config gates functional.
- Verify all governance boundaries intact.
- Prepare push/PR only after user approval.

Stop gate: user decides next action.

## 4. Capability Level to Phase Mapping

| Capability Level | Phases | Status |
|-----------------|--------|--------|
| L0: Safe Local SubAgent | 0-13, 17, 18(T1), 19 | Required for v1 |
| L1: Real LLM Read-Only | 14, 18(T2) | Gated, designed |
| L2: Real LLM Tool-Requesting | 15, 18(T3) | Gated, designed |
| L3: Sandboxed Tool-Capable | 16, 18(T4) | Contract designed, execution gated |
| L4: Worktree-Capable | Future phase, 18(T5) placeholder | Deferred |
| L5: Parallel Multi-SubAgent | Future phase, 18(T6) placeholder | Deferred |

## 5. Stop Conditions

Stop and ask the user if any phase:

- needs real LLM delegation without config gate
- needs external process spawning without sandbox gate
- needs shell execution without sandbox gate
- touches `.env`
- reads real `agent_log.jsonl`
- reads real `sessions/` or `runs/`
- changes Memory governance
- changes ToolRegistry safety authority
- introduces nested SubAgent (depth > 0) without explicit phase
- introduces backend abstraction, DB, graph, embedding, or vector store
- checkpoint/resume would require changing existing checkpoint schema
- implementation would give SubAgent its own unbounded loop
- implementation would write full SubAgent prompts/transcripts into checkpoint
- has unclear tool risk boundary
- needs to weaken/skip tests
- full pytest fails
- requires push or tag
- config gate is bypassed or hardcoded open
- execution mode escalates without parent approval

## 6. Commit Shape

Use scoped commits per phase. Include:

- phase id
- behavior protected
- tests run
- explicit statement that Parent Agent retains orchestration control and
  governance boundaries are preserved

For gated phases, also include:
- config gate status
- dogfood tier exercised
- audit attestation
