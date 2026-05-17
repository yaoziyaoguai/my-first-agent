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

## 2. Target Architecture

The SubAgent System is designed as a production-grade architecture. Phases build
toward this target, not toward a minimal local-only wrapper.

```
Capability pyramid (implementation order):

L0: Safe Local SubAgent           ← Phase 0-10 (v1 required)
L1: Real LLM Read-Only            ← Phase 14 (gated dogfood)
L2: Real LLM Tool-Requesting      ← Phase 15 (gated)
L3: Sandboxed Tool-Capable        ← Phase 16 (contract, then gated)
L4: Worktree-Capable              ← Future (explicit phase)
L5: Parallel Multi-SubAgent       ← Future (explicit phase)
```

## 3. Phases

### Phase 0: Safe Local MVP Characterization

Goal: confirm Safe Local MVP boundaries and establish test baseline.

Work:

- Run `tests/test_subagent_local_mvp_contract.py` and verify all pass.
- Document MVP contracts: `SubagentProfile`, `DelegationRequest`,
  `DelegationResult`, path policy, frontmatter validation, secret redaction.
- Verify MVP never calls real LLM, never spawns external processes.

Stop gate: MVP characterization complete; tests green.

### Phase 1: Descriptor Schema

Goal: define parser/schema for `SUBAGENT.md` frontmatter.

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

Allowed files: `agent/subagent_system/context.py`,
`agent/subagent_system/context_window.py`, and focused tests/docs.

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

Allowed files: `agent/subagent_system/memory_boundary.py`, memory adapter
seam tests/docs, and minimum approved Runtime adapter wiring.

Forbidden files: direct MemoryStore write, silent retain, auto-approve.

Work:

- Implement `memory_scope` handling (`none` / `read_context` / `propose`).
- Route memory proposals through governance.

Stop gate: Memory governance audit.

### Phase 9: Checkpoint/Resume Boundary

Goal: make in-flight SubAgent delegation checkpoint-aware without letting
SubAgent own the loop or replay high-risk effects.

Entry criteria:

- Phase 3 contract types exist.
- Phase 8 memory boundary tests pass.
- Existing checkpoint ownership tests are green.

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

Allowed files: `agent/subagent_system/adjudication.py`,
`agent/subagent_system/result.py`, and focused tests/docs.

Forbidden files: SubAgent owning loop, auto-merge without parent decision.

Work:

- `ParentAdjudicationResult` for each action.
- `accept_result` with summary merge.
- `reject_result` with reason.
- `request_revision` with revised `SubAgentRequest`.
- `ask_user` with user question.
- `convert_to_tool_request` routing.
- `convert_to_memory_proposal` routing.
- Revision loop with `max_revisions` bound.
- Low-confidence handling.

Stop gate: adjudication flow complete for all actions.

### Phase 12: Runtime / Parent Adapter

Goal: `SubAgentRun` lifecycle and delegation adapter under Parent Runtime.

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

Allowed files: `agent/subagent_system/trace.py`,
`agent/subagent_system/result.py`, and focused tests/docs.

Forbidden files: secrets in trace data, trace data as side channel.

Work:

- `SubAgentTraceEvent` for all 15 event types.
- Event ordering preservation.
- Event data sanitization (no secrets, no full prompts).
- Trace event count in `SubAgentAuditRecord`.
- Trace events included in `SubAgentResult`.

Stop gate: trace covers full delegation lifecycle; no secrets in trace.

### Phase 14: Real LLM Read-Only Gated Dogfood

Goal: real LLM readonly execution under config gate.

Entry criteria:

- L0 (Phases 0-13) complete and tested.
- Config system supports `subagent.real_llm_readonly.enabled`.
- Real LLM dogfood runner exists (analogue to Skill System dogfood runner).

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

Work:

- Show available SubAgent descriptors with supported modes.
- Show delegation status/reason/mode.
- Show result/audit with confidence and stop reason.
- Show adjudication decision.
- Show trace events.

Stop gate: TUI dependency boundary tests.

### Phase 18: Tiered Dogfood Harness

Goal: L1-L5 tiered dogfood harness.

Work:

- **L1 (v1 required)**: 15+ synthetic deterministic scenarios.
- **L2 (gated)**: real LLM read-only dogfood.
- **L3 (gated)**: real LLM tool-requesting dogfood.
- **L4 (future)**: sandboxed tool-capable dogfood.
- **L5 (future)**: worktree coding dogfood.
- All tiers produce redacted audit packets.
- No network, real LLM (except gated tiers), `.env`, sessions/runs.

Stop gate: L1 dogfood produces sanitized audit packets; L2+ tiers ready for
gated execution.

### Phase 19: Independent Audit And Hardening

Goal: close P0/P1/P2/P3 and decide readiness.

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
| L0: Safe Local SubAgent | 0-13, 17, 18(L1), 19 | Required for v1 |
| L1: Real LLM Read-Only | 14, 18(L2) | Gated, designed |
| L2: Real LLM Tool-Requesting | 15, 18(L3) | Gated, designed |
| L3: Sandboxed Tool-Capable | 16, 18(L4) | Contract designed, execution gated |
| L4: Worktree-Capable | Future phase | Deferred |
| L5: Parallel Multi-SubAgent | Future phase | Deferred |

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
