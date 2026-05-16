# Skill System Implementation Loop

This document is the execution loop for a future Coding Agent. Do not implement
Skill System code without reading the RFC, SDD, and TDD first.

## 1. Loop Rules

Every phase must:

1. Read `docs/rfc/SKILL_CANONICAL_RFC.md`.
2. Read `docs/design/SKILL_SYSTEM_SDD.md`.
3. Read `docs/testing/SKILL_SYSTEM_TDD.md`.
4. Write or extend tests first.
5. Confirm the new test fails for the intended reason when practical.
6. Implement minimum code.
7. Run selected tests.
8. Run full pytest when code touches runtime/tool/memory/core/checkpoint/CLI/TUI.
9. Update docs if behavior or phase status changes.
10. Commit a scoped change.
11. Stop for audit at defined gates.

Do not modify real `.env`, read real `agent_log.jsonl`, read real `sessions/` or
`runs/`, call real LLMs, clone remote Skills, or install dependencies.

## 2. Phases

### Phase 0: Legacy Prototype Freeze Verification

Goal: prove `agent/skills/` remains legacy/experimental and inactive by default.

Work:

- Verify `agent.skills.__all__ == []`.
- Verify default `agent.tools` import excludes Skill lifecycle tools.
- Verify install/update tools remain explicit opt-in.

Stop gate: audit confirms no legacy prototype contamination.

### Phase 1: Descriptor Schema

Goal: define parser/schema for `SKILL.md` frontmatter.

Work:

- Add `SkillManifest`, `SkillDescriptor`, typed errors.
- Fail closed on invalid names/status/risk/resources.
- Redact secret-like values.

Stop gate: schema tests green.

### Phase 2: Filesystem Registry

Goal: runtime/session-scoped deterministic registry.

Work:

- Explicit roots only.
- No module-level global singleton.
- Duplicate names fail closed.
- Disabled/hidden Skills not visible.

Stop gate: independent review of registry scope.

### Phase 3: Loader + Progressive Disclosure

Goal: Level 1/2/3 loading contracts.

Work:

- Metadata prompt section.
- Selected body loading.
- On-demand resource loading.
- Audit loaded levels.

Stop gate: prompt inspection confirms no all-body injection.

### Phase 4: Selector

Goal: deterministic Skill selection.

Work:

- Explicit selection support.
- Metadata-only matching.
- Ambiguous match asks user.
- Disabled/deprecated policy.

Stop gate: selector never reads bodies or calls LLM.

### Phase 5: Tool Binding

Goal: connect Skill allowed tools to ToolRegistry without bypass.

Work:

- Treat `allowed_tools` as upper-bound.
- Preserve ToolRegistry risk/capability filtering.
- Preserve confirmation.
- Block unknown/out-of-scope tool requests.

Stop gate: tool boundary audit.

### Phase 6: Runtime Invocation Adapter

Goal: request/result invocation flow under parent Runtime.

Work:

- Add SkillInvocationRequest/Result.
- Add SkillContext assembly.
- Add audit record.
- Ensure no Skill-owned loop.

Stop gate: full pytest with temp HOME.

### Phase 7: Memory Context Boundary

Goal: approved memory read/proposal boundary.

Work:

- Implement `memory_scope` handling.
- Provide context through adapter.
- Route memory proposals through governance.

Stop gate: Memory governance audit.

### Phase 8: CLI/TUI Visibility

Goal: presentation only.

Work:

- Show available descriptors.
- Show selected Skill/reason.
- Show result/audit id.

Stop gate: TUI dependency boundary tests.

### Phase 9: Dogfood Harness

Goal: synthetic local dogfood scenarios.

Work:

- Add fixtures for scenarios in dogfood plan.
- Produce redacted audit packets.
- No network, real LLM, `.env`, sessions/runs.

Stop gate: dogfood packet review.

### Phase 10: Independent Audit And Hardening

Goal: close P0/P1/P2 and decide readiness.

Work:

- Run audit checklist.
- Fix scoped findings.
- Run full pytest.
- Prepare push/PR only after user approval.

Stop gate: user decides next action.

## 3. Stop Conditions

Stop and ask the user if any phase:

- wants network install
- wants a real Skill from GitHub
- touches `.env`
- reads real `agent_log.jsonl`
- reads real `sessions/` or `runs/`
- changes Memory governance
- introduces SubAgent
- introduces backend abstraction, DB, graph, embedding, or vector store
- has unclear tool risk boundary
- needs to weaken/skip tests
- full pytest fails
- requires push or tag

## 4. Commit Shape

Use scoped commits per phase. Include:

- phase id
- behavior protected
- tests run
- explicit statement that Skill remains parent-runtime controlled
