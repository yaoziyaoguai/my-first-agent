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
`runs/`, call real LLMs for delegation, spawn external processes, or install
dependencies.

Formal SubAgent implementation must not import or modify the Safe Local MVP
(`agent/subagents/local.py`) unless a dedicated migration phase is explicitly
approved. The Safe Local MVP is a test baseline and reference only.

The formal namespace is `agent/subagent_system/`. Implementation phases should
create or modify `agent/subagent_system/*`, and tests should target
`agent/subagent_system/*`.

## 2. Phases

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

Stop gate: independent review of registry scope.

### Phase 3: Delegation Request/Result Contract

Goal: `SubAgentRequest` → `SubAgentContext` → `SubAgentResult` flow definition.

Allowed files: `agent/subagent_system/request.py`,
`agent/subagent_system/context.py`, `agent/subagent_system/result.py`,
`agent/subagent_system/errors.py`, and focused tests/docs.

Forbidden files: executor, ToolRegistry execution, Memory governance, real
LLM path.

Work:

- Add `SubAgentRequest`, `SubAgentContext`, `SubAgentResult`, `SubAgentError`,
  `SubAgentAuditRecord` — all frozen dataclasses.
- Validation: required fields, type checks, correlation IDs.

Stop gate: contract types are frozen, validated, and auditable.

### Phase 4: Tool Permission Boundary

Goal: connect SubAgent `allowed_tools` to ToolRegistry without bypass.

Allowed files: `agent/subagent_system/tool_boundary.py`, narrow adapter code
if required, and focused tests/docs.

Forbidden files: tool execution from SubAgent, ToolRegistry risk bypass,
confirmation skip.

Work:

- `allowed_tools` is upper bound (intersection of descriptor + request).
- ToolRegistry remains authority for risk/confirmation.
- Hidden/internal tools never exposed.
- SubAgent cannot execute tools directly.

Stop gate: tool boundary audit.

### Phase 5: Skill Boundary

Goal: connect SubAgent `allowed_skills` to Skill System without bypass.

Allowed files: `agent/subagent_system/skill_boundary.py`, and focused
tests/docs.

Forbidden files: Skill System bypass, Skill pre-loading all bodies.

Work:

- `allowed_skills` is upper bound.
- Skill System remains authority for loading/progressive disclosure.
- SubAgent receives L1 metadata only.

Stop gate: Skill boundary delegates to Skill System.

### Phase 6: Memory Boundary

Goal: read-only context and proposal-only Memory access.

Allowed files: `agent/subagent_system/memory_boundary.py`, memory adapter
seam tests/docs, and minimum approved Runtime adapter wiring.

Forbidden files: direct MemoryStore write, silent retain, auto-approve.

Work:

- Implement `memory_scope` handling (`none` / `read_context` / `propose`).
- Route memory proposals through governance.

Stop gate: Memory governance audit.

### Phase 7: Checkpoint/Resume Boundary

Goal: make in-flight SubAgent delegation checkpoint-aware without letting
SubAgent own the loop or replay high-risk effects.

Entry criteria:

- Phase 3 request/result flow exists.
- Phase 6 memory boundary tests pass.
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

Implementation scope:

- Store only bounded correlation metadata: `delegation_id`, `subagent_name`,
  `status`, `iterations_used`, `max_iterations`, `parent_trace_id`, pending
  confirmation state.
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

### Phase 8: Bounded Local Execution

Goal: fake/local execution within `max_iterations` bound.

Allowed files: `agent/subagent_system/executor.py`,
`agent/subagent_system/policy.py`, and focused tests/docs.

Forbidden files: real LLM invocation, external process spawn, real tool
execution.

Work:

- Bounded loop: `max_iterations` hard stop.
- Fake/local execution only (no real LLM).
- Status `max_iterations_exceeded` on bound hit.
- Iteration counter in audit record.

Stop gate: bounded execution proven in tests.

### Phase 9: Parent Agent Adapter

Goal: request/result delegation adapter under Parent Runtime.

Allowed files: `agent/subagent_system/delegation.py`, Runtime adapter seams
approved by tests, and focused tests/docs.

Forbidden files: SubAgent owning loop, provider direct call paths, Memory
governance changes.

Work:

- Adapter assembles `SubAgentContext` from `SubAgentRequest` + registry +
  boundaries.
- Delegates to executor.
- Returns `SubAgentResult` to Parent.
- Parent remains orchestrator.

Stop gate: architecture tests confirm Parent owns loop.

### Phase 10: CLI/TUI Visibility

Goal: presentation only.

Work:

- Show available SubAgent descriptors.
- Show delegation status/reason.
- Show result/audit.

Stop gate: TUI dependency boundary tests.

### Phase 11: Dogfood Harness

Goal: synthetic local dogfood scenarios.

Work:

- Add fixtures for scenarios in dogfood plan.
- Produce redacted audit packets.
- No network, real LLM, `.env`, sessions/runs.

Stop gate: dogfood packet review.

### Phase 12: Independent Audit And Hardening

Goal: close P0/P1/P2 and decide readiness.

Work:

- Run audit checklist.
- Fix scoped findings.
- Run full pytest.
- Prepare push/PR only after user approval.

Stop gate: user decides next action.

## 3. Stop Conditions

Stop and ask the user if any phase:

- needs real LLM delegation
- needs external process spawning
- needs shell execution
- touches `.env`
- reads real `agent_log.jsonl`
- reads real `sessions/` or `runs/`
- changes Memory governance
- changes ToolRegistry safety authority
- introduces nested SubAgent (depth > 0)
- introduces backend abstraction, DB, graph, embedding, or vector store
- checkpoint/resume would require changing existing checkpoint schema
- implementation would give SubAgent its own unbounded loop
- implementation would write full SubAgent prompts/transcripts into checkpoint
- has unclear tool risk boundary
- needs to weaken/skip tests
- full pytest fails
- requires push or tag

## 4. Commit Shape

Use scoped commits per phase. Include:

- phase id
- behavior protected
- tests run
- explicit statement that Parent Agent retains orchestration control and
  governance boundaries are preserved
